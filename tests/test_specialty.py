"""exercise specialty manifest loading and the startup check."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "bin/specialty.py"
SPEC = importlib.util.spec_from_file_location("specialty", SCRIPT)
specialty = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(specialty)


class SpecialtyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        environment = mock.patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop(specialty.ENV, None)
        base = Path(self.temporary.name).resolve()
        self.root = base / "home"
        self.root.mkdir()
        self.repo = base / "repo"
        self.repo.mkdir()
        for args in (
            ("init", "-b", "main"),
            ("config", "user.email", "test@example.invalid"),
            ("config", "user.name", "test"),
            ("commit", "--allow-empty", "-m", "initial"),
        ):
            subprocess.run(
                ["git", "-C", str(self.repo), *args], check=True, capture_output=True
            )
        self.pack = self.root / "specialty"
        (self.pack / "jobs").mkdir(parents=True)
        (self.pack / "templates").mkdir()
        (self.pack / "SPECIALTY.md").write_text("# example\n")
        (self.pack / "jobs/nightly.md").write_text("run the nightly check\n")
        (self.pack / "templates/worker.md").write_text("# worker\n")
        (self.pack / "mcp.json").write_text('{"mcpServers": {}}\n')
        self.manifest = {
            "name": "example",
            "description": "an example specialty",
            "repos": {
                "demo": {
                    "path": str(self.repo),
                    "origin": "https://example.com/demo.git",
                    "base": "main",
                    "aliases": ["sample"],
                    "description": "demo repo",
                }
            },
            "secrets": ["EXAMPLE_TOKEN"],
            "egress": ["api.example.com"],
            "mcp_config": "mcp.json",
            "jobs": {"nightly": {"prompt": "jobs/nightly.md", "schedule": "0 3 * * *"}},
            "delivery": "local-commit",
        }
        self.write()

    def write(self, manifest=None):
        (self.pack / "specialty.json").write_text(json.dumps(manifest or self.manifest))

    def rejects(self, pattern, change):
        manifest = json.loads(json.dumps(self.manifest))
        change(manifest)
        self.write(manifest)
        with self.assertRaisesRegex(ValueError, pattern):
            specialty.load(self.root)

    def test_absent_specialty_is_base_abra(self):
        empty = Path(self.temporary.name) / "empty"
        empty.mkdir()
        self.assertIsNone(specialty.load(empty))
        self.assertEqual(specialty.check(empty), (None, []))

    def test_valid_manifest_and_defaults(self):
        pack = specialty.load(self.root)
        self.assertEqual(pack["name"], "example")
        self.assertEqual(pack["delivery"], "local-commit")
        self.assertEqual(pack["repos"]["demo"]["aliases"], ["sample"])
        minimal = {
            "name": "example",
            "description": "",
            "repos": {"demo": {"path": str(self.repo), "base": "main"}},
        }
        self.write(minimal)
        pack = specialty.load(self.root)
        self.assertEqual(pack["delivery"], "draft-pr")
        self.assertEqual(
            pack["repos"]["demo"],
            dict(
                path=str(self.repo), origin="", base="main", aliases=[], description=""
            ),
        )
        self.assertEqual((pack["secrets"], pack["egress"], pack["jobs"]), ([], [], {}))

    def test_env_override(self):
        other = Path(self.temporary.name) / "other"
        other.mkdir()
        os.environ[specialty.ENV] = str(self.pack)
        self.assertEqual(specialty.load(other)["name"], "example")
        os.environ[specialty.ENV] = "relative/path"
        with self.assertRaisesRegex(ValueError, "absolute"):
            specialty.load(other)
        os.environ[specialty.ENV] = str(other / "missing")
        with self.assertRaisesRegex(ValueError, "not a directory"):
            specialty.load(other)

    def test_rejects_invalid_manifest_fields(self):
        cases = {
            "unknown keys": lambda m: m.update(extra=1),
            "missing keys": lambda m: m.pop("repos"),
            "name": lambda m: m.update(name="Not A Slug"),
            "description": lambda m: m.update(description=7),
            "non-empty object": lambda m: m.update(repos={}),
            "repo .* name": lambda m: m.update(repos={"Bad": m["repos"]["demo"]}),
            "repo .*unknown keys": lambda m: m["repos"]["demo"].update(token="x"),
            "repo .*missing keys": lambda m: m["repos"]["demo"].pop("base"),
            "must be absolute": lambda m: m["repos"]["demo"].update(path="repo"),
            "hyphen": lambda m: m["repos"]["demo"].update(base="--force"),
            "aliases": lambda m: m["repos"]["demo"].update(aliases=["UPPER"]),
            "ambiguous": lambda m: m["repos"].update(
                other=dict(path=str(self.repo), base="main", aliases=["sample"])
            ),
            "secrets": lambda m: m.update(secrets=["bad-name"]),
            "egress": lambda m: m.update(egress=["https://example.com/path"]),
            "delivery": lambda m: m.update(delivery="merge"),
            "jobs must": lambda m: m.update(jobs=[]),
            "job .*name": lambda m: m.update(jobs={"Bad": m["jobs"]["nightly"]}),
            "job .*missing keys": lambda m: m["jobs"]["nightly"].pop("schedule"),
            "job .*prompt is missing": lambda m: m["jobs"]["nightly"].update(
                prompt="jobs/missing.md"
            ),
            "mcp_config is missing": lambda m: m.update(mcp_config="nope.json"),
        }
        for pattern, change in cases.items():
            with self.subTest(pattern=pattern):
                self.rejects(pattern, change)

    def test_rejects_path_escapes(self):
        outside = Path(self.temporary.name) / "outside.md"
        outside.write_text("secret\n")
        for prompt in ("../outside.md", str(outside), "jobs/../../outside.md"):
            with self.subTest(prompt=prompt):
                self.rejects(
                    "inside the specialty dir",
                    lambda m: m["jobs"]["nightly"].update(prompt=prompt),
                )
        (self.pack / "jobs/link.md").symlink_to(outside)
        self.rejects(
            "escapes", lambda m: m["jobs"]["nightly"].update(prompt="jobs/link.md")
        )
        self.write()
        (self.pack / "templates/scout.md").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "templates/scout.md escapes"):
            specialty.load(self.root)

    def test_rejects_nested_template_escape(self):
        outside = Path(self.temporary.name) / "outside.md"
        outside.write_text("secret\n")
        (self.pack / "templates/sub/deeper").mkdir(parents=True)
        (self.pack / "templates/sub/deeper/ok.md").write_text("# ok\n")
        self.assertEqual(specialty.load(self.root)["name"], "example")
        (self.pack / "templates/sub/deeper/big.md").write_text(
            "x" * (specialty.MAX_FILE + 1)
        )
        with self.assertRaisesRegex(ValueError, "templates/sub/deeper/big.md exceeds"):
            specialty.load(self.root)
        (self.pack / "templates/sub/deeper/big.md").unlink()
        (self.pack / "templates/sub/leak.md").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "templates/sub/leak.md escapes"):
            specialty.load(self.root)
        (self.pack / "templates/sub/leak.md").unlink()
        (self.pack / "templates/sub/loop").symlink_to(
            self.pack / "templates", target_is_directory=True
        )
        with self.assertRaisesRegex(ValueError, "looping symlink|more than|unreadable"):
            specialty.load(self.root)

    def test_rejects_deeply_nested_json(self):
        nested = "[" * 20000 + "]" * 20000
        (self.pack / "mcp.json").write_text(nested)
        with self.assertRaisesRegex(ValueError, "mcp_config is not valid json"):
            specialty.load(self.root)
        (self.pack / "specialty.json").write_text(nested)
        with self.assertRaisesRegex(ValueError, "specialty.json is not valid json"):
            specialty.load(self.root)
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "error: specialty.json is not valid json\n")

    def test_rejects_bad_files(self):
        (self.pack / "SPECIALTY.md").unlink()
        with self.assertRaisesRegex(ValueError, "specialty.md is missing"):
            specialty.load(self.root)
        (self.pack / "SPECIALTY.md").write_text("x" * (specialty.MAX_FILE + 1))
        with self.assertRaisesRegex(ValueError, "exceeds"):
            specialty.load(self.root)
        (self.pack / "SPECIALTY.md").write_text("# example\n")
        (self.pack / "specialty.json").write_text("{not json")
        with self.assertRaisesRegex(ValueError, "not valid json"):
            specialty.load(self.root)
        (self.pack / "specialty.json").write_text('{"name": "a", "name": "b"}')
        with self.assertRaisesRegex(ValueError, "duplicate json key"):
            specialty.load(self.root)
        self.write()
        (self.pack / "mcp.json").write_text("[]")
        with self.assertRaisesRegex(ValueError, "json object"):
            specialty.load(self.root)

    def test_check_secrets_and_repos(self):
        _, problems = specialty.check(self.root)
        self.assertEqual(
            problems, ["required secret env var is not set: EXAMPLE_TOKEN"]
        )
        os.environ["EXAMPLE_TOKEN"] = "do-not-print"
        self.assertEqual(specialty.check(self.root)[1], [])
        self.manifest["repos"]["demo"]["base"] = "missing-branch"
        self.manifest["repos"]["other"] = dict(
            path=str(Path(self.temporary.name) / "nowhere"), base="main"
        )
        self.write()
        self.assertEqual(
            specialty.check(self.root)[1],
            [
                "repo demo base does not resolve to a commit",
                "repo other path is not a git checkout root",
            ],
        )

    def run_cli(self):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "check"],
            capture_output=True,
            text=True,
            env=dict(os.environ, ABRA_SPECIALTY_DIR=str(self.pack)),
        )

    def test_cli_exit_codes_never_print_secret_values(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn("EXAMPLE_TOKEN", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        os.environ["EXAMPLE_TOKEN"] = "do-not-print"
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("specialty ok: example", result.stdout)
        self.assertNotIn("do-not-print", result.stdout + result.stderr)
        (self.pack / "specialty.json").write_text("{")
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "error: specialty.json is not valid json\n")


if __name__ == "__main__":
    unittest.main()
