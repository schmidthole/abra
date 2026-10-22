"""exercise the container entrypoint with stub children, and check image config files."""

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "docker/entrypoint.py"
SPEC = importlib.util.spec_from_file_location("entrypoint", SCRIPT)
entrypoint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(entrypoint)

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"


def executable(path, body):
    path.write_text("#!" + sys.executable + "\n" + textwrap.dedent(body))
    path.chmod(0o755)


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name).resolve()
        self.base = base
        self.home = base / "home"
        self.home.mkdir()
        self.run_dir = base / "run"
        self.run_dir.mkdir()
        self.source = base / "source"
        (self.source / "bin").mkdir(parents=True)
        (self.source / "triggers").mkdir()
        (self.source / "bin/abra").write_text("# stub\n")
        self.keys = base / "authorized_keys"
        self.keys.write_text("# operator keys\n" + KEY + " operator@example\n")
        self.calls = base / "calls.log"
        self.sshd = base / "sshd"
        executable(
            self.sshd,
            """\
            import os, sys, time
            with open(os.environ["STUB_LOG"], "a") as handle:
                handle.write("sshd " + " ".join(sys.argv[1:]) + "\\n")
            time.sleep(60)
            """,
        )
        self.root = self.home / "abra"
        self.env = {
            "ABRA_ROOT": str(self.root),
            "ABRA_AUTHORIZED_KEYS": str(self.keys),
            "STUB_LOG": str(self.calls),
            "PATH": os.environ.get("PATH", ""),
        }
        for name, value in (
            ("HOME", self.home),
            ("RUN", self.run_dir),
            ("SOURCE", self.source),
            ("SSHD", str(self.sshd)),
            ("SLACK_PYTHON", sys.executable),
        ):
            patcher = mock.patch.object(entrypoint, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for number in (signal.SIGTERM, signal.SIGINT):
            self.addCleanup(signal.signal, number, signal.getsignal(number))

    def listener(self, code):
        executable(
            self.source / "triggers/slack.py",
            """\
            import os, sys, time
            with open(os.environ["STUB_LOG"], "a") as handle:
                handle.write("slack " + " ".join(sys.argv[1:]) + "\\n")
            time.sleep(0.5)
            sys.exit(%d)
            """ % code,
        )

    def main(self, env=None):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = entrypoint.main(env or self.env)
        return code, stderr.getvalue()

    def test_trigger_selection(self):
        self.assertEqual(entrypoint.trigger({}), "none")
        self.assertEqual(entrypoint.trigger({"ABRA_TRIGGER": "none"}), "none")
        self.assertEqual(entrypoint.trigger({"ABRA_TRIGGER": "slack"}), "slack")
        for value in ("SLACK", "linear", "slack ", "none;rm"):
            with self.assertRaisesRegex(entrypoint.SetupError, "unknown abra_trigger"):
                entrypoint.trigger({"ABRA_TRIGGER": value})

    def test_instance_root_must_be_absolute(self):
        self.assertEqual(entrypoint.instance_root({}), Path(entrypoint.DEFAULT_ROOT))
        for value in ("relative/root", "/home/abra/../etc"):
            with self.assertRaises(entrypoint.SetupError):
                entrypoint.instance_root({"ABRA_ROOT": value})

    def test_keys_fail_closed(self):
        missing = self.base / "missing"
        with self.assertRaisesRegex(entrypoint.SetupError, "missing"):
            entrypoint.read_keys(missing)
        with self.assertRaisesRegex(entrypoint.SetupError, "missing"):
            entrypoint.read_keys(self.base)
        for text in ("", "\n\n", "# only a comment\n"):
            self.keys.write_text(text)
            with self.assertRaisesRegex(entrypoint.SetupError, "no keys"):
                entrypoint.read_keys(self.keys)
        self.keys.write_text(KEY + "\nsecret-looking garbage\n")
        with self.assertRaises(entrypoint.SetupError) as caught:
            entrypoint.read_keys(self.keys)
        self.assertIn("line 2", str(caught.exception))
        self.assertNotIn("garbage", str(caught.exception))
        self.keys.write_text("ssh-ed25519 not*base64\n")
        with self.assertRaises(entrypoint.SetupError):
            entrypoint.read_keys(self.keys)
        self.keys.write_text(KEY + "\n" + "#" * (64 * 1024))
        with self.assertRaisesRegex(entrypoint.SetupError, "larger"):
            entrypoint.read_keys(self.keys)
        self.keys.write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(entrypoint.SetupError, "unreadable"):
            entrypoint.read_keys(self.keys)

    def test_keys_accept_options_and_comments(self):
        text = (
            "# team\n\n" + KEY + "\n" + 'from="10.0.0.0/8",no-pty ' + KEY + " ops key\n"
        )
        self.keys.write_text(text)
        self.assertEqual(entrypoint.read_keys(self.keys), (text, 2))

    def test_seed_copies_once_and_never_overwrites(self):
        (self.source / "README.md").write_text("image copy\n")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertTrue(entrypoint.seed_root(self.source, self.root))
        self.assertEqual((self.root / "README.md").read_text(), "image copy\n")
        self.assertEqual(
            [path.name for path in self.home.iterdir() if path.name.startswith(".")],
            [],
        )
        (self.root / "README.md").write_text("operator edit\n")
        (self.root / "data").mkdir()
        (self.source / "NEW.md").write_text("new in image\n")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertFalse(entrypoint.seed_root(self.source, self.root))
        self.assertEqual((self.root / "README.md").read_text(), "operator edit\n")
        self.assertFalse((self.root / "NEW.md").exists())

    def test_seed_requires_parent(self):
        with self.assertRaisesRegex(entrypoint.SetupError, "parent missing"):
            entrypoint.seed_root(self.source, self.base / "nope/abra")

    @unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen not installed")
    def test_host_key_generated_once(self):
        path = self.home / entrypoint.HOST_KEY
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertTrue(entrypoint.host_key(path))
            first = path.read_bytes()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertTrue(Path(str(path) + ".pub").is_file())
            path.chmod(0o644)
            self.assertFalse(entrypoint.host_key(path))
        self.assertEqual(path.read_bytes(), first)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_host_key_symlink_rejected(self):
        path = self.home / entrypoint.HOST_KEY
        path.parent.mkdir()
        path.symlink_to(self.keys)
        with self.assertRaisesRegex(entrypoint.SetupError, "regular file"):
            entrypoint.host_key(path)

    def test_sshd_env_shares_allowlist_only(self):
        env = {
            "ABRA_ROOT": "/home/abra/abra",
            "GH_TOKEN": "gh tok'en $x #y",
            "ANTHROPIC_API_KEY": 'bad"quote',
            "CLAUDE_CODE_OAUTH_TOKEN": "bad\\slash",
            "SLACK_BOT_TOKEN": "xoxb-secret",
            "SLACK_APP_TOKEN": "xapp-secret",
            "OTHER": "value",
        }
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            text = entrypoint.sshd_env(env)
        self.assertIn(
            'SetEnv "ABRA_ROOT=/home/abra/abra" "GH_TOKEN=gh tok\'en $x #y"', text
        )
        for hidden in ("xoxb", "xapp", "OTHER", "bad", "ANTHROPIC", "CLAUDE"):
            self.assertNotIn(hidden, text)
        self.assertIn("not sharing anthropic_api_key", stderr.getvalue())
        self.assertNotIn("quote", stderr.getvalue())
        self.assertNotIn("SetEnv", entrypoint.sshd_env({}))

    def test_commands(self):
        env = dict(self.env, SLACK_BOT_TOKEN="xoxb-1", GH_TOKEN="gh-1")
        children = entrypoint.commands(env, self.root, "none")
        self.assertEqual([name for _, _, name in children], ["sshd"])
        argv, sshd_env, _ = children[0]
        self.assertEqual(argv[1:], ["-D", "-e", "-f", str(entrypoint.SSHD_CONFIG)])
        self.assertNotIn("SLACK_BOT_TOKEN", sshd_env)
        self.assertNotIn("GH_TOKEN", sshd_env)
        env["ABRA_NAME"] = "helper"
        children = entrypoint.commands(env, self.root, "slack")
        argv, listener_env, name = children[1]
        self.assertEqual(name, "slack listener")
        self.assertEqual(
            argv,
            [
                sys.executable,
                str(self.root / "triggers/slack.py"),
                "--root",
                str(self.root),
                "--name",
                "helper",
            ],
        )
        self.assertEqual(listener_env["SLACK_BOT_TOKEN"], "xoxb-1")

    def test_missing_keys_exit_before_any_change(self):
        self.keys.unlink()
        code, stderr = self.main()
        self.assertEqual(code, 1)
        self.assertIn("authorized keys file missing", stderr)
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(list(self.run_dir.iterdir()), [])
        self.assertFalse(self.calls.exists())

    def test_unknown_trigger_exits(self):
        code, stderr = self.main(dict(self.env, ABRA_TRIGGER="bogus"))
        self.assertEqual(code, 1)
        self.assertIn("unknown abra_trigger", stderr)
        self.assertFalse(self.root.exists())

    @unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen not installed")
    def test_listener_exit_stops_container_non_zero(self):
        self.listener(3)
        env = dict(self.env, ABRA_TRIGGER="slack", GH_TOKEN="gh-secret-value")
        code, stderr = self.main(env)
        self.assertEqual(code, 3)
        self.assertIn("slack listener exited with code 3", stderr)
        self.assertIn("sshd stopped", stderr)
        self.assertNotIn("gh-secret-value", stderr)
        calls = sorted(self.calls.read_text().splitlines())
        self.assertEqual(
            calls,
            [
                "slack --root " + str(self.root) + " --name abra",
                "sshd -D -e -f " + str(entrypoint.SSHD_CONFIG),
            ],
        )
        self.assertEqual(
            (self.run_dir / "authorized_keys").stat().st_mode & 0o777, 0o600
        )
        self.assertEqual((self.run_dir / "sshd_env").stat().st_mode & 0o777, 0o600)
        self.assertIn(
            "GH_TOKEN=gh-secret-value", (self.run_dir / "sshd_env").read_text()
        )
        self.assertTrue((self.root / "bin/abra").is_file())

    @unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen not installed")
    def test_clean_listener_exit_is_still_a_failure(self):
        self.listener(0)
        code, stderr = self.main(dict(self.env, ABRA_TRIGGER="slack"))
        self.assertEqual(code, 1)
        self.assertIn("slack listener exited with code 0", stderr)

    @unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen not installed")
    def test_restart_reuses_host_key_and_root(self):
        self.listener(2)
        env = dict(self.env, ABRA_TRIGGER="slack")
        self.assertEqual(self.main(env)[0], 2)
        key = (self.home / entrypoint.HOST_KEY).read_bytes()
        (self.root / "bin/abra").write_text("# operator upgraded\n")
        code, stderr = self.main(env)
        self.assertEqual(code, 2)
        self.assertIn("reusing ssh host key", stderr)
        self.assertIn("using existing instance root", stderr)
        self.assertEqual((self.home / entrypoint.HOST_KEY).read_bytes(), key)
        self.assertEqual((self.root / "bin/abra").read_text(), "# operator upgraded\n")

    @unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen not installed")
    def test_sigterm_stops_children_cleanly(self):
        wrapper = self.base / "wrapper.py"
        wrapper.write_text(textwrap.dedent("""\
                import importlib.util, sys
                from pathlib import Path
                spec = importlib.util.spec_from_file_location("entrypoint", sys.argv[1])
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.HOME = Path(sys.argv[2])
                module.RUN = Path(sys.argv[3])
                module.SOURCE = Path(sys.argv[4])
                module.SSHD = sys.argv[5]
                sys.exit(module.main())
                """))
        process = subprocess.Popen(
            [
                sys.executable,
                str(wrapper),
                str(SCRIPT),
                str(self.home),
                str(self.run_dir),
                str(self.source),
                str(self.sshd),
            ],
            env=self.env,
            stderr=subprocess.PIPE,
            encoding="utf-8",
        )
        deadline = time.time() + 10
        while time.time() < deadline and not self.calls.exists():
            time.sleep(0.05)
        self.assertTrue(self.calls.exists(), "sshd stub never started")
        process.send_signal(signal.SIGTERM)
        _, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertIn("received signal 15, stopping", stderr)
        self.assertIn("sshd stopped with code -15", stderr)


def dockerignored(path, patterns):
    """approximate docker's .dockerignore matching: a pattern or a parent matches."""
    parts = path.split("/")
    for pattern in patterns:
        pattern = pattern.rstrip("/")
        for end in range(1, len(parts) + 1):
            candidate = "/".join(parts[:end])
            regex = (
                re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*", "[^/]*")
            )
            if re.fullmatch(regex, candidate):
                return True
    return False


class ImageConfigTests(unittest.TestCase):
    def setUp(self):
        self.dockerfile = (REPO / "Dockerfile").read_text()

    def arg(self, name):
        match = re.search(r"^ARG " + name + r"=(\S+)$", self.dockerfile, re.M)
        self.assertIsNotNone(match, name)
        return match.group(1)

    def test_sshd_config_is_key_only(self):
        lines = (REPO / "docker/sshd_config").read_text().splitlines()
        settings = {}
        for line in lines:
            if line.strip() and not line.startswith("#"):
                key, _, value = line.partition(" ")
                self.assertNotIn(key, settings, "duplicate " + key)
                settings[key] = value
        expected = {
            "Port": "2222",
            "AllowUsers": "abra",
            "PermitRootLogin": "no",
            "AuthenticationMethods": "publickey",
            "PasswordAuthentication": "no",
            "KbdInteractiveAuthentication": "no",
            "PermitEmptyPasswords": "no",
            "X11Forwarding": "no",
            "AllowAgentForwarding": "no",
            "AllowTcpForwarding": "no",
            "DisableForwarding": "yes",
            "PermitUserEnvironment": "no",
            "StrictModes": "yes",
            "AuthorizedKeysFile": str(entrypoint.RUN / "authorized_keys"),
            "HostKey": str(entrypoint.HOME / entrypoint.HOST_KEY),
            "Include": str(entrypoint.RUN / "sshd_env"),
        }
        for key, value in expected.items():
            self.assertEqual(settings.get(key), value, key)

    def test_dockerignore_excludes_local_state_and_secrets(self):
        patterns = [
            line
            for line in (REPO / ".dockerignore").read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        for path in (
            ".git",
            ".git/config",
            "data/backlog.md",
            "operator/draft.md",
            "specialty/specialty.json",
            ".worktrees/abra/x/file",
            ".sources/repo",
            ".env",
            ".env.local",
            ".envrc",
            ".env-prod",
            "docker/.envrc",
            "docker/.env",
            "config.prod.json",
            "deploy/app.prod.yaml",
            "production.txt",
            "deploy/my-production-values.yaml",
            "prod-secrets.yaml",
            "deploy/prod-values.yaml",
            "NOTES.md",
            ".claude/settings.local.json",
            ".cache/x",
            "bin/__pycache__/x.pyc",
            "triggers/x.pyc",
        ):
            self.assertTrue(dockerignored(path, patterns), path)
        for path in (
            "bin/abra",
            "docker/entrypoint.py",
            "triggers/slack.py",
            "AGENTS.md",
            ".gitignore",
            "templates/worker.md",
        ):
            self.assertFalse(dockerignored(path, patterns), path)

    def test_base_image_is_pinned_full_debian(self):
        base = re.search(r"^FROM (\S+)$", self.dockerfile, re.M).group(1)
        self.assertRegex(base, r"^debian:[a-z]+-[0-9]{8}@sha256:[0-9a-f]{64}$")
        self.assertNotRegex(base, "slim|alpine")

    def test_npx_prefetch_matches_wrapper_pins(self):
        tasks = (REPO / "bin/tasks").read_text()
        github = (REPO / "bin/github").read_text()
        self.assertIn("tasks-axi@" + self.arg("TASKS_AXI_VERSION") + " ", tasks)
        self.assertIn("gh-axi@" + self.arg("GH_AXI_VERSION") + " ", github)
        self.assertIn("npm_config_prefer_offline=true", self.dockerfile)
        self.assertIn("npm_config_prefer_offline", entrypoint.SHARED)

    def test_versions_and_checksums_pinned(self):
        self.assertRegex(self.arg("NODE_VERSION"), r"^[0-9]+\.[0-9]+\.[0-9]+$")
        self.assertRegex(self.arg("GH_VERSION"), r"^[0-9]+\.[0-9]+\.[0-9]+$")
        self.assertRegex(self.arg("CLAUDE_CODE_VERSION"), r"^[0-9]+\.[0-9]+\.[0-9]+$")
        for name in ("NODE_SHA256_AMD64", "NODE_SHA256_ARM64", "GH_KEYRING_SHA256"):
            self.assertRegex(self.arg(name), r"^[0-9a-f]{64}$")
        self.assertEqual(self.dockerfile.count("sha256sum -c -"), 2)

    def test_slack_requirements_match_and_are_hashed(self):
        def pins(path):
            text = path.read_text()
            return dict(re.findall(r"^([A-Za-z0-9_.-]+)==(\S+)", text, re.M))

        image = REPO / "docker/requirements-slack.txt"
        self.assertEqual(pins(image), pins(REPO / "triggers/requirements-slack.txt"))
        for path in (image, REPO / "requirements-dev.txt"):
            entries = re.split(r"\n(?=[A-Za-z])", path.read_text().split("\n", 1)[1])
            entries = [entry for entry in entries if not entry.startswith("#")]
            self.assertTrue(entries, path)
            for entry in entries:
                self.assertRegex(entry, r"==[^\s]+ \\\n    --hash=sha256:[0-9a-f]{64}")
        self.assertIn("black==", (REPO / "requirements-dev.txt").read_text())
        self.assertIn("requirements-dev.txt", self.dockerfile)
        self.assertGreaterEqual(self.dockerfile.count("--require-hashes"), 2)

    def test_runs_as_abra_under_tini_without_baked_secrets(self):
        users = re.findall(r"^USER (\S+)$", self.dockerfile, re.M)
        self.assertEqual(users[-1], "abra")
        self.assertIn('ENTRYPOINT ["/usr/bin/tini", "--"', self.dockerfile)
        self.assertIn("rm -f /etc/ssh/ssh_host_*", self.dockerfile)
        for name in entrypoint.SECRETS:
            self.assertNotIn(name, self.dockerfile)
        self.assertNotRegex(
            self.dockerfile, r"(?i)\b(golang|dotnet|openjdk|yarn|pnpm)\b"
        )


if __name__ == "__main__":
    unittest.main()
