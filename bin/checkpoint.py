#!/usr/bin/env python3
"""initialize, read, and update an assigned checkpoint; not an agent runtime."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from urllib.parse import urlsplit

MAX_BYTES = 1024 * 1024
SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
IDENTITY = ("assignment", "role", "predecessor", "working_directory")
FIELDS = {
    "version",
    "assignment",
    "role",
    "predecessor",
    "run_ids",
    "status",
    "updated_at",
    "job_summary",
    "working_directory",
    "steps",
    "checkpoint",
    "next_action",
    "blocker",
    "artifacts",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def matches(pattern, value):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def absolute(value):
    return text(value) and value.startswith("/") and "\x00" not in value


def validate(value):
    require(type(value) is dict and set(value) == FIELDS, "invalid checkpoint fields")
    require(
        type(value["version"]) is int and value["version"] == 1, "unsupported version"
    )
    require(matches(SLUG, value["assignment"]), "invalid assignment")
    require(value["role"] in ("worker", "scout", "verify", "triage"), "invalid role")
    predecessor = value["predecessor"]
    require(
        predecessor is None
        or (matches(SLUG, predecessor) and predecessor != value["assignment"]),
        "invalid predecessor",
    )
    ids = value["run_ids"]
    require(type(ids) is list and all(text(item) for item in ids), "invalid run ids")
    require(len(ids) == len(set(ids)), "duplicate run ids")
    require(
        value["status"] in ("active", "paused", "completed", "blocked", "failed"),
        "invalid status",
    )
    require(
        matches(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
            value["updated_at"],
        ),
        "invalid timestamp",
    )
    try:
        datetime.strptime(value["updated_at"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ValueError("invalid timestamp") from None
    require(
        text(value["job_summary"]) and len(value["job_summary"]) <= 500,
        "invalid job summary",
    )
    require(
        value["working_directory"] is None or absolute(value["working_directory"]),
        "invalid working directory",
    )
    require(text(value["checkpoint"]), "invalid checkpoint summary")
    require(
        value["next_action"] is None or text(value["next_action"]),
        "invalid next action",
    )
    require(value["blocker"] is None or text(value["blocker"]), "invalid blocker")
    require(
        value["status"] not in ("blocked", "failed") or text(value["blocker"]),
        "blocker required",
    )
    steps = value["steps"]
    require(type(steps) is list and bool(steps), "invalid steps")
    seen = set()
    for step in steps:
        require(
            type(step) is dict and set(step) == {"id", "title", "status"},
            "invalid step fields",
        )
        require(
            matches(SLUG, step["id"]) and step["id"] not in seen,
            "invalid or duplicate step id",
        )
        seen.add(step["id"])
        require(text(step["title"]), "invalid step title")
        require(
            step["status"]
            in ("pending", "active", "completed", "blocked", "failed", "skipped"),
            "invalid step status",
        )
    require(type(value["artifacts"]) is list, "invalid artifacts")
    for artifact in value["artifacts"]:
        require(
            type(artifact) is dict and set(artifact) == {"kind", "reference"},
            "invalid artifact fields",
        )
        kind, reference = artifact["kind"], artifact["reference"]
        require(
            kind in ("report", "log", "commit") and text(reference), "invalid artifact"
        )
        if kind == "commit":
            require(
                matches(r"[0-9a-f]{40}|[0-9a-f]{64}", reference),
                "invalid commit reference",
            )
        else:
            try:
                url = urlsplit(reference)
                valid = bool(url.scheme and (url.netloc or url.path))
            except ValueError:
                valid = False
            require(absolute(reference) or valid, "invalid artifact reference")
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate json key")
        result[key] = value
    return result


def decode(raw):
    require(len(raw) <= MAX_BYTES, "checkpoint exceeds byte limit")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=lambda _: require(False, "invalid json constant"),
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("invalid utf-8 json") from None
    return validate(value)


def encode(value):
    raw = (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
    decode(raw)
    return raw


def revision(raw):
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def parent_directory(path, create=False):
    """pin each directory without following symlinks, including ancestors."""
    path = Path(path)
    require(
        path.is_absolute() and ".." not in path.parts,
        "path must be absolute without parent traversal",
    )
    require(path.name not in ("", ".", ".."), "invalid filename")
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        yield fd, path.name
    finally:
        os.close(fd)


def read_bytes(directory, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode), "expected a regular file")
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, "checkpoint exceeds byte limit")
    return raw


def check_identity(value, expected, name):
    require(
        name == expected["assignment"] + ".json",
        "tracker filename does not match assignment",
    )
    require(
        all(value[key] == expected[key] for key in IDENTITY),
        "checkpoint identity mismatch",
    )


def read_checkpoint(path, expected):
    with parent_directory(path) as (directory, name):
        raw = read_bytes(directory, name)
        value = decode(raw)
        check_identity(value, expected, name)
    return {"checkpoint": value, "revision": revision(raw)}


def write_checkpoint(path, expected, proposed, last_revision=None, initialize=False):
    validate(proposed)
    check_identity(proposed, expected, Path(path).name)
    require(
        initialize or matches(r"[0-9a-f]{64}", last_revision),
        "last-read revision required",
    )
    value = dict(proposed)
    value["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw = encode(value)
    with parent_directory(path, create=initialize) as (directory, name):
        if initialize:
            try:
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ValueError("initialization destination already exists")
        else:
            old = read_bytes(directory, name)
            check_identity(decode(old), expected, name)
            require(revision(old) == last_revision, "stale checkpoint revision")
        temporary = name + ".tmp-" + secrets.token_hex(16)
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
            decode(read_bytes(directory, temporary))
            if initialize:
                # link is an exclusive publication, unlike check-then-replace.
                os.link(
                    temporary,
                    name,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
            else:
                # not a compare-and-swap: reconciled single-writer ownership is required.
                current = read_bytes(directory, name)
                check_identity(decode(current), expected, name)
                require(revision(current) == last_revision, "stale checkpoint revision")
                os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
    return {"checkpoint": value, "revision": revision(raw)}


def proposal(source):
    if source == "-":
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    else:
        with parent_directory(source) as (directory, name):
            raw = read_bytes(directory, name)
    return decode(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "read", "update"):
        sub = commands.add_parser(command)
        sub.add_argument("path", help="absolute assigned tracker path")
        sub.add_argument("--assignment", required=True)
        sub.add_argument(
            "--role", required=True, choices=("worker", "scout", "verify", "triage")
        )
        sub.add_argument(
            "--predecessor", default=None, help="assignment slug; omit for null"
        )
        sub.add_argument(
            "--working-directory",
            required=True,
            help="supplied absolute directory or literal null",
        )
        if command != "read":
            sub.add_argument(
                "--proposal",
                required=True,
                help="absolute complete json file path, or - for stdin",
            )
        if command == "update":
            sub.add_argument(
                "--revision",
                required=True,
                help="revision from the last successful read/write",
            )
    args = parser.parse_args()
    expected = {key: getattr(args, key) for key in IDENTITY}
    if expected["working_directory"] == "null":
        expected["working_directory"] = None
    operation, path = args.command, args.path
    try:
        if args.command == "read":
            result = read_checkpoint(args.path, expected)
        else:
            operation, path = "read-proposal", args.proposal
            proposed = proposal(args.proposal)
            operation, path = args.command, args.path
            result = write_checkpoint(
                args.path,
                expected,
                proposed,
                getattr(args, "revision", None),
                args.command == "init",
            )
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyboardInterrupt) as error:
        # do not echo malformed payloads, json snippets, or foreign identities.
        if isinstance(error, OSError):
            message = (error.strerror or "filesystem operation failed").lower()
        elif isinstance(error, KeyboardInterrupt):
            message = "interrupted; reread to confirm publication state"
        else:
            message = str(error)
        print(
            json.dumps({"operation": operation, "path": path, "error": message}),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
