#!/usr/bin/env python3
"""read-only validation of an explicitly trusted existing formatter environment."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


def requirement_pins(data):
    text = data.decode("utf-8")
    pins = {}
    for requirement in text.replace("\\\n", " ").splitlines():
        requirement = requirement.strip()
        if not requirement or requirement.startswith("#"):
            continue
        match = re.fullmatch(
            r"([a-zA-Z0-9_-]+)==([0-9][a-zA-Z0-9.]*)(\s+--hash=sha256:[0-9a-f]{64})+",
            requirement,
        )
        if not match:
            raise ValueError("unsupported or unhashed formatter requirement")
        name = match[1].lower().replace("_", "-")
        if name in pins:
            raise ValueError("duplicate formatter requirement")
        pins[name] = match[2]
    if "black" not in pins:
        raise ValueError("formatter requirements must pin black")
    return pins


def trusted_path(path):
    info = path.stat()
    if info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022:
        raise ValueError("formatter path has untrusted owner or write permissions")
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise ValueError("formatter path must be regular file or directory")


def check_observation(observed, pins, environment):
    if observed["version"][:2] < [3, 11]:
        raise ValueError("formatter interpreter requires python 3.11+")
    if Path(observed["prefix"]).resolve() != environment:
        raise ValueError("formatter interpreter belongs to another environment")
    installed = observed["packages"]
    if any(installed.get(name) != version for name, version in pins.items()):
        raise ValueError("formatter environment is incomplete or has wrong pins")
    return observed


def inspect_formatter(bin_path, requirements, expected_digest):
    bin_path = Path(bin_path)
    if not bin_path.is_absolute() or ".." in bin_path.parts:
        raise ValueError("formatter bin must be absolute without parent traversal")
    environment = bin_path.parent.resolve()
    data = Path(requirements).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_digest:
        raise ValueError("candidate requirements digest changed")
    pins = requirement_pins(data)
    # inspect before executing: callers still establish provenance and trusted parents.
    for parent in (bin_path, *bin_path.parents):
        trusted_path(parent)

    def walk_error(error):
        raise error

    for root, directories, files in os.walk(environment, onerror=walk_error):
        trusted_path(Path(root))
        for name in directories + files:
            trusted_path(Path(root) / name)
    python = bin_path / "python"
    black = bin_path / "black"
    if not os.access(python, os.X_OK) or not os.access(black, os.X_OK):
        raise ValueError("formatter python/black executable missing")
    if black.read_text().splitlines()[0] != "#!" + str(python):
        raise ValueError("formatter executable has unexpected interpreter")
    script = """
import importlib.metadata as m, json, platform, sys
print(json.dumps(dict(version=list(sys.version_info[:3]), executable=sys.executable,
    implementation=platform.python_implementation(), platform=platform.platform(),
    machine=platform.machine(), prefix=sys.prefix,
    packages={d.metadata['Name'].lower().replace('_', '-'):d.version for d in m.distributions()})))
"""
    result = subprocess.run(
        [str(python), "-I", "-B", "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    observed = check_observation(json.loads(result.stdout), pins, environment)
    return {
        "bin": str(bin_path),
        "requirements_sha256": digest,
        "pins": pins,
        **observed,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bin", required=True, help="absolute trusted existing formatter bin"
    )
    parser.add_argument(
        "--requirements", required=True, help="candidate requirements file"
    )
    parser.add_argument(
        "--requirements-sha256",
        required=True,
        help="expected requirements digest from trusted environment evidence",
    )
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                inspect_formatter(
                    args.bin, args.requirements, args.requirements_sha256
                ),
                indent=2,
            )
        )
    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        subprocess.SubprocessError,
    ) as error:
        print("error: formatter validation failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
