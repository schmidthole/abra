#!/usr/bin/env python3
"""load and check an optional abra specialty pack."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
ENV = "ABRA_SPECIALTY_DIR"
DELIVERY = ("report", "local-commit", "draft-pr", "pr")
MAX_MANIFEST = 64 * 1024
MAX_FILE = 256 * 1024
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
HOST = re.compile(r"(?=.{1,253}\Z)" + LABEL + r"(?:\." + LABEL + r")*")
TOP_KEYS = {
    "name",
    "description",
    "repos",
    "secrets",
    "egress",
    "mcp_config",
    "jobs",
    "delivery",
}
REPO_KEYS = {"path", "origin", "base", "aliases", "description"}
JOB_KEYS = {"prompt", "schedule"}


def locate(root):
    """return the resolved specialty directory, or none for base abra."""
    value = os.environ.get(ENV, "")
    if value:
        path = Path(value)
        if not path.is_absolute():
            raise ValueError("specialty dir override must be an absolute path")
        if not path.is_dir():
            raise ValueError("specialty dir override is not a directory")
        return path.resolve()
    path = Path(root) / "specialty"
    if not path.exists() and not path.is_symlink():
        return None
    if not path.is_dir():
        raise ValueError("specialty path exists but is not a directory")
    return path.resolve()


def text(value, field, empty=True):
    if not isinstance(value, str) or (not empty and not value) or "\0" in value:
        raise ValueError(
            field + " must be a" + ("" if empty else " non-empty") + " string"
        )
    return value


def strings(value, field, pattern):
    if not isinstance(value, list):
        raise ValueError(field + " must be a list")
    for item in value:
        if not isinstance(item, str) or not pattern.fullmatch(item):
            raise ValueError(field + " has an invalid entry: " + json.dumps(item))
    return value


def slug(value, field):
    return strings([value], field, SLUG)[0]


def keys(value, allowed, required, field):
    if not isinstance(value, dict):
        raise ValueError(field + " must be an object")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(field + " has unknown keys: " + json.dumps(unknown))
    missing = sorted(set(required) - set(value))
    if missing:
        raise ValueError(field + " is missing keys: " + json.dumps(missing))
    return value


def inside(directory, relative, field):
    """resolve a relative path and refuse anything outside the specialty dir."""
    text(relative, field, empty=False)
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(field + " must be a relative path inside the specialty dir")
    resolved = (directory / path).resolve()
    if not resolved.is_relative_to(directory):
        raise ValueError(field + " escapes the specialty dir")
    return resolved


def bounded(path, field, limit=MAX_FILE):
    if not path.is_file():
        raise ValueError(field + " is missing or not a file")
    if path.stat().st_size > limit:
        raise ValueError(field + " exceeds " + str(limit) + " bytes")
    return path


def unique(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("duplicate json key: " + json.dumps(key))
        data[key] = value
    return data


def read_json(path, field, limit=MAX_FILE):
    try:
        return json.loads(
            bounded(path, field, limit).read_text(encoding="utf-8"),
            object_pairs_hook=unique,
        )
    except UnicodeDecodeError:
        raise ValueError(field + " is not valid utf-8") from None
    except json.JSONDecodeError:
        raise ValueError(field + " is not valid json") from None


def repos(value):
    if not isinstance(value, dict) or not value:
        raise ValueError("repos must be a non-empty object")
    seen = set()
    result = {}
    for name, entry in value.items():
        field = "repo " + json.dumps(name)
        slug(name, field + " name")
        keys(entry, REPO_KEYS, {"path", "base"}, field)
        path = text(entry["path"], field + " path", empty=False)
        if not Path(path).is_absolute():
            raise ValueError(field + " path must be absolute")
        base = text(entry["base"], field + " base", empty=False)
        if base.startswith("-"):
            raise ValueError(field + " base must not start with a hyphen")
        aliases = strings(entry.get("aliases", []), field + " aliases", SLUG)
        for alias in [name, *aliases]:
            if alias in seen:
                raise ValueError("repo name or alias is ambiguous: " + alias)
            seen.add(alias)
        result[name] = dict(
            path=path,
            origin=text(entry.get("origin", ""), field + " origin"),
            base=base,
            aliases=aliases,
            description=text(entry.get("description", ""), field + " description"),
        )
    return result


def load(root):
    """return the validated specialty manifest, or none when absent."""
    directory = locate(root)
    if directory is None:
        return None
    bounded(inside(directory, "SPECIALTY.md", "specialty.md"), "specialty.md")
    manifest = read_json(
        inside(directory, "specialty.json", "specialty.json"),
        "specialty.json",
        MAX_MANIFEST,
    )
    keys(manifest, TOP_KEYS, {"name", "description", "repos"}, "specialty.json")
    jobs = manifest.get("jobs", {})
    if not isinstance(jobs, dict):
        raise ValueError("jobs must be an object")
    for name, job in jobs.items():
        field = "job " + json.dumps(name)
        slug(name, field + " name")
        keys(job, JOB_KEYS, JOB_KEYS, field)
        prompt = inside(directory, job["prompt"], field + " prompt")
        bounded(prompt, field + " prompt")
        text(job["schedule"], field + " schedule", empty=False)
    mcp_config = manifest.get("mcp_config")
    if mcp_config is not None:
        path = inside(directory, mcp_config, "mcp_config")
        if not isinstance(read_json(path, "mcp_config"), dict):
            raise ValueError("mcp_config must contain a json object")
    templates = directory / "templates"
    if templates.exists() or templates.is_symlink():
        if not inside(directory, "templates", "templates").is_dir():
            raise ValueError("templates must be a directory")
        for entry in templates.iterdir():
            field = "templates/" + entry.name
            resolved = inside(directory, "templates/" + entry.name, field)
            if resolved.is_file():
                bounded(resolved, field)
    delivery = manifest.get("delivery", "draft-pr")
    if delivery not in DELIVERY:
        raise ValueError("delivery must be one of: " + ", ".join(DELIVERY))
    return dict(
        dir=str(directory),
        name=slug(manifest["name"], "name"),
        description=text(manifest["description"], "description"),
        repos=repos(manifest["repos"]),
        secrets=strings(manifest.get("secrets", []), "secrets", ENV_NAME),
        egress=strings(manifest.get("egress", []), "egress", HOST),
        mcp_config=mcp_config,
        jobs=jobs,
        delivery=delivery,
    )


def git(path, *args):
    result = subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True
    )
    return None if result.returncode else result.stdout.strip()


def check(root):
    """validate the manifest and environment; return the pack and any problems."""
    pack = load(root)
    if pack is None:
        return None, []
    problems = []
    for name in pack["secrets"]:
        if not os.environ.get(name):
            problems.append("required secret env var is not set: " + name)
    for name, repo in pack["repos"].items():
        path = Path(repo["path"])
        top = git(path, "rev-parse", "--show-toplevel") if path.is_dir() else None
        if top is None or Path(top).resolve() != path.resolve():
            problems.append("repo " + name + " path is not a git checkout root")
        elif not git(
            path,
            "rev-parse",
            "--verify",
            "--quiet",
            "--end-of-options",
            repo["base"] + "^{commit}",
        ):
            problems.append("repo " + name + " base does not resolve to a commit")
    return pack, problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="lint the specialty pack and environment")
    parser.parse_args()
    try:
        pack, problems = check(ROOT)
    except (ValueError, OSError) as error:
        print("error: " + str(error), file=sys.stderr)
        return 1
    if pack is None:
        print("no specialty configured; running as base abra")
        return 0
    for problem in problems:
        print("error: " + problem, file=sys.stderr)
    if problems:
        return 1
    print(
        "specialty ok: "
        + pack["name"]
        + " ("
        + str(len(pack["repos"]))
        + " repos, delivery ceiling "
        + pack["delivery"]
        + ")"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
