#!/usr/bin/env python3
"""register repositories and create isolated git worktrees."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent


def git(path, *args):
    result = subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True
    )
    if result.returncode:
        raise ValueError(result.stderr.strip().lower())
    return result.stdout.strip()


def slug(value):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise ValueError(
            "names must contain lowercase letters, digits, and single hyphens"
        )
    return value


def read_registry(root):
    path = root / "data/repos.json"
    return json.loads(path.read_text()) if path.exists() else {}


def resolve(registry, name):
    matches = [
        (key, value)
        for key, value in registry.items()
        if name == key or name in value.get("aliases", [])
    ]
    if len(matches) != 1:
        raise ValueError("repo name is unknown or ambiguous; inspect the registry")
    return matches[0]


def register(root, name, path, base, aliases, description):
    slug(name)
    for alias in aliases:
        slug(alias)
    if len(set([name, *aliases])) != len([name, *aliases]):
        raise ValueError("duplicate repo alias")
    registry = read_registry(root)
    for key, value in registry.items():
        if key != name and set([key, *value.get("aliases", [])]) & set(
            [name, *aliases]
        ):
            raise ValueError("repo name or alias already registered")
    path = Path(path).expanduser().resolve()
    path = Path(git(path, "rev-parse", "--show-toplevel"))
    git(path, "rev-parse", "--verify", "--end-of-options", base + "^{commit}")
    origin = subprocess.run(
        ["git", "-C", str(path), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    entry = dict(
        path=str(path),
        origin=origin,
        base=base,
        aliases=aliases,
        description=description,
    )
    if name in registry and registry[name] != entry:
        raise ValueError(
            "repo already registered differently; edit data/repos.json deliberately"
        )
    registry[name] = entry
    directory = root / "data"
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / "repos.json.tmp"
    temporary.write_text(json.dumps(registry, indent=2) + "\n")
    os.replace(temporary, directory / "repos.json")
    return entry


def create(root, name, task, verify=None):
    slug(task)
    name, repo = resolve(read_registry(root), name)
    slug(name)
    source = Path(repo["path"]).resolve()
    ref = verify if verify else repo["base"]
    if verify and not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", verify):
        raise ValueError("verification requires a full commit hash")
    commit = git(source, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}")
    if verify and commit != verify:
        raise ValueError("verification hash must identify a commit directly")
    suffix = task + ("-verify-" + commit if verify else "")
    parent = root / ".worktrees" / name
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / suffix
    if target.exists() or target.is_symlink():
        raise ValueError(
            "worktree path already exists; inspect it instead of replacing it"
        )
    if not target.resolve().is_relative_to((root / ".worktrees").resolve()):
        raise ValueError("worktree path escapes the managed directory")
    branch = None if verify else "abra/" + task
    options = ["--detach"] if verify else ["-b", branch]
    git(source, "worktree", "add", *options, str(target), commit)
    return dict(repo=name, path=str(target), branch=branch, commit=commit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("register")
    add.add_argument("name")
    add.add_argument("path")
    add.add_argument("--base", required=True)
    add.add_argument("--alias", action="append", default=[])
    add.add_argument("--description", default="")
    commands.add_parser("list")
    lookup = commands.add_parser("resolve")
    lookup.add_argument("name")
    worktree = commands.add_parser("create")
    worktree.add_argument("repo")
    worktree.add_argument("task")
    worktree.add_argument("--verify", metavar="commit")
    args = parser.parse_args()
    try:
        if args.command == "register":
            result = register(
                ROOT, args.name, args.path, args.base, args.alias, args.description
            )
        elif args.command == "list":
            result = read_registry(ROOT)
        elif args.command == "resolve":
            name, repo = resolve(read_registry(ROOT), args.name)
            result = dict(name=name, **repo)
        else:
            result = create(ROOT, args.repo, args.task, args.verify)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError) as error:
        print("error: " + str(error).lower(), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
