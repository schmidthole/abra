#!/usr/bin/env python3
"""container entrypoint: seed the instance root, run sshd, and optionally one trigger listener.

runs as the abra user under tini. it never restarts anything: when sshd or the
listener exits on its own, the container exits non-zero so the orchestrator can
restart it. sigterm and sigint are forwarded to both children.
"""

import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile

HOME = Path("/home/abra")
SOURCE = Path("/opt/abra")
RUN = Path("/run/abra")
SSHD = "/usr/sbin/sshd"
SSHD_CONFIG = SOURCE / "docker/sshd_config"
SLACK_PYTHON = "/opt/venvs/slack/bin/python"
PYTHON = "/usr/bin/python3"
KEYGEN = "ssh-keygen"
DEFAULT_KEYS = "/etc/abra/ssh/authorized_keys"
DEFAULT_ROOT = "/home/abra/abra"
HOST_KEY = ".abra-sshd/ssh_host_ed25519_key"
MAX_KEYS_BYTES = 64 * 1024
TRIGGERS = ("", "none", "slack", "linear")
KEY_TYPE = re.compile(
    r"(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)"
    r"|sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com)"
)
KEY_DATA = re.compile(r"[A-Za-z0-9+/]{16,16384}={0,3}")
# variables ssh sessions need to run abra by hand; slack tokens and the linear key
# and client secret are not put in the ssh session env.
SHARED = (
    "ABRA_ROOT",
    "ABRA_NAME",
    "ABRA_TRIGGER",
    "ABRA_SPECIALTY_DIR",
    "ABRA_AGENT_MODE",
    "ABRA_MAX_CONCURRENCY",
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "GH_TOKEN",
    "DISABLE_AUTOUPDATER",
    "npm_config_cache",
    "npm_config_prefer_offline",
    "npm_config_update_notifier",
)
SECRETS = (
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "GH_TOKEN",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "LINEAR_API_KEY",
    "LINEAR_CLIENT_SECRET",
)
# printable ascii without quotes or backslashes, so sshd_config quoting stays exact.
SAFE_VALUE = re.compile(r"[\x20\x21\x23-\x5b\x5d-\x7e]{0,8192}")


class SetupError(Exception):
    pass


def log(message):
    print("entrypoint: " + message, file=sys.stderr, flush=True)


def trigger(env):
    """the selected trigger, or none; unknown values fail closed."""
    value = env.get("ABRA_TRIGGER", "")
    if value not in TRIGGERS:
        raise SetupError("unknown abra_trigger; expected one of: none, slack, linear")
    return value or "none"


def instance_root(env):
    value = env.get("ABRA_ROOT", "") or DEFAULT_ROOT
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise SetupError("abra_root must be an absolute path without '..'")
    return path


def read_keys(path):
    """return validated authorized_keys text; anything missing or malformed fails closed."""
    try:
        if not Path(path).is_file():
            raise SetupError("authorized keys file missing: " + str(path))
        if Path(path).stat().st_size > MAX_KEYS_BYTES:
            raise SetupError("authorized keys file is larger than 64 kib")
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise SetupError("authorized keys file unreadable: " + str(path)) from None
    count = 0
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not valid_key(line):
            raise SetupError("authorized keys line " + str(number) + " is not a key")
        count += 1
    if not count:
        raise SetupError("authorized keys file has no keys: " + str(path))
    return text, count


def valid_key(line):
    """a key line: optional options, then a known key type and base64 key data."""
    fields = line.split()
    for index, field in enumerate(fields[:-1]):
        if KEY_TYPE.fullmatch(field):
            return bool(KEY_DATA.fullmatch(fields[index + 1]))
    return False


def write_private(path, text):
    """write text atomically with mode 0600."""
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def prepare_run(run):
    if run.is_symlink() or not run.is_dir():
        raise SetupError("runtime directory missing: " + str(run))
    os.chmod(run, 0o700)


def seed_root(source, root):
    """copy the image's abra into a missing root; an existing root is never touched."""
    if root.exists() or root.is_symlink():
        if not (root / "bin/abra").is_file():
            log("warning: instance root has no bin/abra: " + str(root))
        log("using existing instance root " + str(root))
        return False
    if not root.parent.is_dir():
        raise SetupError("instance root parent missing: " + str(root.parent))
    staging = Path(tempfile.mkdtemp(dir=root.parent, prefix=".abra-seed-"))
    try:
        shutil.copytree(source, staging / "root", symlinks=True)
        os.rename(staging / "root", root)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    log("seeded instance root " + str(root) + " from " + str(source))
    return True


def seed_home(home):
    """create shell dotfiles a fresh volume lacks; existing files are kept."""
    for name in (".bashrc", ".profile"):
        skeleton = Path("/etc/skel") / name
        target = home / name
        if skeleton.is_file() and not target.exists() and not target.is_symlink():
            shutil.copyfile(skeleton, target)


def host_key(path):
    """generate the ed25519 host key once into the volume; reuse it afterwards."""
    directory = path.parent
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise SetupError("host key directory is not a directory: " + str(directory))
    os.chmod(directory, 0o700)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise SetupError("host key is not a regular file: " + str(path))
    if path.exists():
        os.chmod(path, 0o600)
        log("reusing ssh host key")
        return False
    temporary = directory / (".new-" + path.name)
    for stale in (temporary, Path(str(temporary) + ".pub")):
        if stale.exists() or stale.is_symlink():
            stale.unlink()
    result = subprocess.run(
        [
            KEYGEN,
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            "abra-host",
            "-f",
            str(temporary),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )
    if result.returncode:
        raise SetupError("ssh-keygen failed with code " + str(result.returncode))
    os.chmod(temporary, 0o600)
    os.replace(Path(str(temporary) + ".pub"), Path(str(path) + ".pub"))
    os.replace(temporary, path)
    log("generated ssh host key")
    return True


def sshd_env(env):
    """an sshd setenv line with the variables ssh sessions see; values are never logged."""
    pairs = []
    for name in SHARED:
        value = env.get(name)
        if value is None:
            continue
        if not SAFE_VALUE.fullmatch(value):
            log(
                "not sharing "
                + name.lower()
                + " with ssh sessions: unsupported characters"
            )
            continue
        pairs.append('"' + name + "=" + value + '"')
    lines = ["# written by the container entrypoint at start; do not edit."]
    if pairs:
        lines.append("SetEnv " + " ".join(pairs))
    return "\n".join(lines) + "\n"


def without_secrets(env):
    return {name: value for name, value in env.items() if name not in SECRETS}


def commands(env, root, selected):
    """the child processes to run: sshd always, plus the selected listener."""
    sshd = ([SSHD, "-D", "-e", "-f", str(SSHD_CONFIG)], without_secrets(env), "sshd")
    children = [sshd]
    if selected == "slack":
        name = env.get("ABRA_NAME", "") or "abra"
        argv = [SLACK_PYTHON, str(root / "triggers/slack.py"), "--root", str(root)]
        children.append((argv + ["--name", name], dict(env), "slack listener"))
    elif selected == "linear":
        name = env.get("ABRA_NAME", "") or "abra"
        argv = [PYTHON, str(root / "triggers/linear.py"), "--root", str(root)]
        children.append((argv + ["--name", name], dict(env), "linear listener"))
    return children


def setup(env):
    selected = trigger(env)
    root = instance_root(env)
    keys, count = read_keys(env.get("ABRA_AUTHORIZED_KEYS", "") or DEFAULT_KEYS)
    if not os.access(HOME, os.W_OK):
        raise SetupError("home is not writable by the abra user: " + str(HOME))
    prepare_run(RUN)
    write_private(RUN / "authorized_keys", keys)
    log("loaded " + str(count) + " authorized keys")
    env = dict(env)
    env["ABRA_ROOT"] = str(root)
    seed_home(HOME)
    seed_root(SOURCE, root)
    host_key(HOME / HOST_KEY)
    write_private(RUN / "sshd_env", sshd_env(env))
    log("trigger: " + selected)
    return commands(env, root, selected)


def supervise(children):
    """start children; stop all when one exits or on sigterm. no restarts."""
    state = {"stopping": False}
    live = {}

    def stop_all(signum):
        for pid in list(live):
            try:
                os.kill(pid, signum)
            except ProcessLookupError:
                pass

    def handle(signum, frame):
        if not state["stopping"]:
            log("received signal " + str(signum) + ", stopping")
        state["stopping"] = True
        stop_all(signum)

    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)
    code = 0
    for argv, child_env, name in children:
        if state["stopping"]:
            break
        try:
            process = subprocess.Popen(argv, env=child_env, stdin=subprocess.DEVNULL)
        except OSError:
            log("could not start " + name)
            state["stopping"] = True
            stop_all(signal.SIGTERM)
            code = 1
            break
        live[process.pid] = (name, process)
        log("started " + name)
    if state["stopping"]:
        stop_all(signal.SIGTERM)
    while live:
        try:
            pid, status = os.wait()
        except ChildProcessError:
            break
        if pid not in live:
            continue
        name, process = live.pop(pid)
        result = os.waitstatus_to_exitcode(status)
        process.returncode = result
        if state["stopping"]:
            log(name + " stopped with code " + str(result))
            continue
        log(name + " exited with code " + str(result) + "; stopping the container")
        code = result if result > 0 else 1
        state["stopping"] = True
        stop_all(signal.SIGTERM)
    return code


def main(env=None):
    env = os.environ if env is None else env
    try:
        children = setup(env)
    except SetupError as error:
        log("error: " + str(error))
        return 1
    except OSError as error:
        log("error: setup failed (" + type(error).__name__ + ")")
        return 1
    return supervise(children)


if __name__ == "__main__":
    sys.exit(main())
