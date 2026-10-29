"""exercise deterministic checkpoint files and cli, not agent compliance."""

from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "bin/checkpoint.py"
SPEC = (ROOT / "docs/agent-tracking.md").read_text()
spec = importlib.util.spec_from_file_location("checkpoint", HELPER)
checkpoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checkpoint)


def example():
    return json.loads(SPEC.split("```json\n", 1)[1].split("```", 1)[0])


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / "agents/scout-01.json"
        self.value = example()
        self.identity = {key: self.value[key] for key in checkpoint.IDENTITY}

    def initialize(self):
        return checkpoint.write_checkpoint(
            self.path, self.identity, self.value, initialize=True
        )

    def update(self, revision, value=None):
        return checkpoint.write_checkpoint(
            self.path, self.identity, value or self.value, revision
        )

    def assert_no_temporaries(self):
        self.assertEqual(list(self.path.parent.glob("*.tmp-*")), [])

    def cli(self, command, *extra, raw=None):
        return subprocess.run(
            [
                sys.executable,
                str(HELPER),
                command,
                str(self.path),
                "--assignment",
                "scout-01",
                "--role",
                "scout",
                "--working-directory",
                "null",
                *extra,
            ],
            input=raw,
            capture_output=True,
            cwd=self.root,
            timeout=10,
        )

    def test_init_scaffolds_parents_and_read_returns_revision(self):
        before = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = self.initialize()
        after = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        raw = self.path.read_bytes()
        self.assertEqual(checkpoint.read_checkpoint(self.path, self.identity), result)
        self.assertEqual(result["revision"], checkpoint.revision(raw))
        self.assertLessEqual(before, result["checkpoint"]["updated_at"])
        self.assertLessEqual(result["checkpoint"]["updated_at"], after)
        self.assertEqual(
            raw, (json.dumps(result["checkpoint"], indent=2) + "\n").encode()
        )
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.value, example())
        self.assert_no_temporaries()

    def test_init_never_clobbers_existing_regular_malformed_or_foreign(self):
        self.path.parent.mkdir()
        foreign = dict(self.value, role="worker")
        for raw in (
            checkpoint.encode(self.value),
            b'{"secret":',
            checkpoint.encode(foreign),
        ):
            with self.subTest(raw_kind=raw[:10]):
                self.path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    self.initialize()
                self.assertEqual(self.path.read_bytes(), raw)
                self.assert_no_temporaries()

    def test_init_exclusive_publication_rejects_new_destination(self):
        real_link = os.link

        def racing_link(*args, **kwargs):
            self.path.write_bytes(b"unexpected writer")
            return real_link(*args, **kwargs)

        with patch.object(checkpoint.os, "link", side_effect=racing_link):
            with self.assertRaises(FileExistsError):
                self.initialize()
        self.assertEqual(self.path.read_bytes(), b"unexpected writer")
        self.assert_no_temporaries()

    def test_symlink_targets_and_ancestor_paths_are_preserved(self):
        self.path.parent.mkdir()
        target = self.root / "target"
        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    target.write_bytes(checkpoint.encode(self.value))
                self.path.symlink_to(target)
                for operation in (
                    self.initialize,
                    lambda: checkpoint.read_checkpoint(self.path, self.identity),
                    lambda: self.update("0" * 64),
                ):
                    with self.assertRaises((ValueError, OSError)):
                        operation()
                self.assertTrue(self.path.is_symlink())
                self.path.unlink()
        alias = self.root / "alias"
        alias.symlink_to(self.path.parent, target_is_directory=True)
        with self.assertRaises(OSError):
            checkpoint.write_checkpoint(
                alias / self.path.name, self.identity, self.value, initialize=True
            )
        self.assertFalse(self.path.exists())
        self.assertEqual(target.read_bytes(), checkpoint.encode(self.value))

    def test_non_regular_targets_do_not_block_or_change(self):
        self.path.parent.mkdir()
        for kind in ("directory", "fifo"):
            with self.subTest(kind=kind):
                if kind == "directory":
                    self.path.mkdir()
                else:
                    os.mkfifo(self.path)
                for operation in (
                    self.initialize,
                    lambda: checkpoint.read_checkpoint(self.path, self.identity),
                    lambda: self.update("0" * 64),
                ):
                    with self.assertRaises((ValueError, OSError)):
                        operation()
                if kind == "directory":
                    self.path.rmdir()
                else:
                    self.path.unlink()

    def test_relative_parent_traversal_and_wrong_filename_are_rejected(self):
        for path in (
            Path("scout-01.json"),
            self.root / ".." / self.root.name / "scout-01.json",
            self.root / "worker-01.json",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                checkpoint.write_checkpoint(
                    path, self.identity, self.value, initialize=True
                )
        self.assertEqual(list(self.root.iterdir()), [])

    def test_strict_json_duplicate_keys_types_and_byte_limit(self):
        valid = checkpoint.encode(self.value)
        for raw in (
            b"{",
            b"\xff",
            b"[]",
            b"null",
            b"true",
            b"\xef\xbb\xbf" + valid,
            valid.replace(b'"version": 1', b'"version": 1, "version": 1'),
            valid.replace(
                b'"title": "trace supplied sources"', b'"title": "x", "title": "y"'
            ),
            valid.replace(b'"version": 1', b'"version": NaN'),
            valid.replace(b'"version": 1', b'"version": Infinity'),
            b"[" * 2000 + b"]" * 2000,
            b" " * (checkpoint.MAX_BYTES + 1),
        ):
            with self.subTest(prefix=raw[:30]), self.assertRaises(ValueError):
                checkpoint.decode(raw)

    def test_every_field_is_required_and_extra_fields_rejected(self):
        for field in self.value:
            value = dict(self.value)
            del value[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                checkpoint.validate(value)
        with self.assertRaises(ValueError):
            checkpoint.validate(dict(self.value, extra="unexpected"))

    def test_invalid_schema_values_and_types(self):
        invalid = {
            "version": [True, 1.0, 2, "1", None],
            "assignment": ["", "Upper", "bad--id", None, 7],
            "role": [None, "coordinator", [], 2],
            "predecessor": ["scout-01", "", 1, []],
            "run_ids": [None, "id", ["a", "a"], [""], [1], [None]],
            "status": [None, "done", [], 1],
            "updated_at": [
                None,
                1,
                "2026-02-30T12:00:00Z",
                "2026-6-01T12:00:00Z",
                "2026-06-01T12:00:00+00:00",
            ],
            "job_summary": [None, "", " ", "a" * 501, 1],
            "working_directory": ["relative", "", 1, "/bad\x00path"],
            "checkpoint": [None, "", " ", {}],
            "next_action": ["", " ", 1, []],
            "blocker": ["", " ", 1, []],
            "steps": [
                None,
                [],
                {},
                [None],
                [{"id": "a", "title": "x"}],
                [{"id": "a", "title": "x", "status": "active", "extra": 1}],
                [{"id": "A", "title": "x", "status": "active"}],
                [{"id": "a", "title": " ", "status": "active"}],
                [{"id": "a", "title": "x", "status": "unknown"}],
            ],
            "artifacts": [
                None,
                {},
                [None],
                [{"kind": "report"}],
                [{"kind": "unknown", "reference": "/x"}],
                [{"kind": "report", "reference": "relative"}],
                [{"kind": "report", "reference": "https://["}],
                [{"kind": "commit", "reference": "abcd"}],
            ],
        }
        for field, values in invalid.items():
            for item in values:
                with self.subTest(field=field, item=item), self.assertRaises(
                    ValueError
                ):
                    checkpoint.validate(dict(self.value, **{field: item}))
        duplicate = copy.deepcopy(self.value)
        duplicate["steps"].append(duplicate["steps"][0])
        with self.assertRaises(ValueError):
            checkpoint.validate(duplicate)
        for status in ("blocked", "failed"):
            with self.assertRaises(ValueError):
                checkpoint.validate(dict(self.value, status=status))

    def test_valid_statuses_nulls_predecessor_and_artifacts(self):
        for status in ("active", "paused", "completed", "blocked", "failed"):
            value = dict(
                self.value,
                status=status,
                blocker="obstacle" if status in ("blocked", "failed") else None,
                next_action=None,
                predecessor="scout-00",
                run_ids=["one", "two"],
                working_directory="/project",
                artifacts=[
                    {"kind": "commit", "reference": "a" * 40},
                    {"kind": "commit", "reference": "b" * 64},
                    {"kind": "log", "reference": "/log"},
                    {"kind": "report", "reference": "https://example.org/report"},
                    {"kind": "report", "reference": "file:///project/report.md"},
                ],
            )
            self.assertEqual(checkpoint.decode(checkpoint.encode(value)), value)
        for status in (
            "pending",
            "active",
            "completed",
            "blocked",
            "failed",
            "skipped",
        ):
            value = copy.deepcopy(self.value)
            value["steps"][0]["status"] = status
            checkpoint.validate(value)

    def test_update_replaces_whole_file_and_owns_timestamp(self):
        result = self.initialize()
        old = self.path.read_bytes()
        with self.path.open("rb") as prior_reader:
            value = dict(
                self.value,
                checkpoint="confirmed test result",
                next_action=None,
                status="completed",
            )
            result = self.update(result["revision"], value)
            self.assertEqual(prior_reader.read(), old)
        self.assertEqual(
            checkpoint.decode(self.path.read_bytes()), result["checkpoint"]
        )
        self.assertEqual(result["checkpoint"]["checkpoint"], "confirmed test result")
        self.assertNotEqual(result["checkpoint"]["updated_at"], value["updated_at"])
        self.assert_no_temporaries()

    def test_all_immutable_identity_fields_are_enforced(self):
        result = self.initialize()
        old = self.path.read_bytes()
        for key, item in (
            ("assignment", "worker-01"),
            ("role", "worker"),
            ("predecessor", "scout-00"),
            ("working_directory", "/different"),
        ):
            with self.subTest(field=key):
                with self.assertRaises(ValueError):
                    self.update(result["revision"], dict(self.value, **{key: item}))
                expected = dict(self.identity, **{key: item})
                proposed = dict(self.value, **{key: item})
                with self.assertRaises(ValueError):
                    checkpoint.write_checkpoint(
                        self.path, expected, proposed, result["revision"]
                    )
                with self.assertRaises(ValueError):
                    checkpoint.read_checkpoint(self.path, expected)
                self.assertEqual(self.path.read_bytes(), old)

    def test_missing_revision_and_stale_content_never_overwrite(self):
        result = self.initialize()
        for token in (None, "", "short", "0" * 64):
            with self.subTest(token=token), self.assertRaises(ValueError):
                self.update(token)
        newer = self.update(
            result["revision"], dict(self.value, checkpoint="new confirmed progress")
        )
        with self.assertRaisesRegex(ValueError, "stale"):
            self.update(result["revision"])
        self.assertEqual(checkpoint.read_checkpoint(self.path, self.identity), newer)
        self.assert_no_temporaries()

    def test_second_revision_check_preserves_intervening_writer(self):
        result = self.initialize()
        replacement = checkpoint.encode(
            dict(self.value, checkpoint="intervening progress")
        )
        real_read = checkpoint.read_bytes

        def racing_read(directory, name):
            if ".tmp-" in name:
                self.path.write_bytes(replacement)
            return real_read(directory, name)

        with patch.object(checkpoint, "read_bytes", side_effect=racing_read):
            with self.assertRaisesRegex(ValueError, "stale"):
                self.update(result["revision"])
        self.assertEqual(self.path.read_bytes(), replacement)
        self.assert_no_temporaries()

    def test_second_check_rejects_symlink_destination(self):
        result = self.initialize()
        sibling = self.root / "sibling.json"
        sibling.write_bytes(self.path.read_bytes())
        real_read = checkpoint.read_bytes

        def racing_read(directory, name):
            if ".tmp-" in name:
                self.path.unlink()
                self.path.symlink_to(sibling)
            return real_read(directory, name)

        with patch.object(checkpoint, "read_bytes", side_effect=racing_read):
            with self.assertRaises(OSError):
                self.update(result["revision"])
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(checkpoint.revision(sibling.read_bytes()), result["revision"])
        self.assert_no_temporaries()

    def test_replace_failure_and_interruption_preserve_prior_and_cleanup_owned_temp(
        self,
    ):
        result = self.initialize()
        raw = self.path.read_bytes()
        unrelated = self.path.parent / "other.json.tmp-unowned"
        unrelated.write_bytes(b"leave alone")
        for error in (OSError("replace failed"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                with patch.object(checkpoint.os, "replace", side_effect=error):
                    with self.assertRaises(type(error)):
                        self.update(result["revision"])
                self.assertEqual(self.path.read_bytes(), raw)
                self.assertEqual(list(self.path.parent.glob("*.tmp-*")), [unrelated])
                self.assertEqual(unrelated.read_bytes(), b"leave alone")
                checkpoint.read_checkpoint(self.path, self.identity)

    def test_staging_validation_failure_preserves_prior_and_cleans_temp(self):
        result = self.initialize()
        raw = self.path.read_bytes()
        real_read = checkpoint.read_bytes

        def broken_staging(directory, name):
            return b"invalid" if ".tmp-" in name else real_read(directory, name)

        with patch.object(checkpoint, "read_bytes", side_effect=broken_staging):
            with self.assertRaises(ValueError):
                self.update(result["revision"])
        self.assertEqual(self.path.read_bytes(), raw)
        self.assert_no_temporaries()

    def test_partial_staging_write_failure_preserves_prior_and_cleans_temp(self):
        result = self.initialize()
        raw = self.path.read_bytes()
        real_fdopen = checkpoint.os.fdopen

        @contextmanager
        def broken_writer(fd, mode):
            with real_fdopen(fd, mode) as stream:
                if mode == "wb":

                    def fail_write(data):
                        stream.write(data[:12])
                        stream.flush()
                        raise OSError("staging write failed")

                    yield SimpleNamespace(write=fail_write)
                else:
                    yield stream

        with patch.object(checkpoint.os, "fdopen", side_effect=broken_writer):
            with self.assertRaises(OSError):
                self.update(result["revision"])
        self.assertEqual(self.path.read_bytes(), raw)
        self.assert_no_temporaries()

    def test_invalid_existing_checkpoint_is_never_repaired_by_read_or_update(self):
        self.path.parent.mkdir()
        values = (
            b"malformed",
            checkpoint.encode(self.value).replace(b'"version": 1', b'"version": 2'),
            b" " * (checkpoint.MAX_BYTES + 1),
        )
        for raw in values:
            with self.subTest(prefix=raw[:20]):
                self.path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    checkpoint.read_checkpoint(self.path, self.identity)
                with self.assertRaises(ValueError):
                    self.update(checkpoint.revision(raw))
                self.assertEqual(self.path.read_bytes(), raw)
                self.assert_no_temporaries()

    def test_missing_read_or_update_does_not_initialize(self):
        for operation in (
            lambda: checkpoint.read_checkpoint(self.path, self.identity),
            lambda: self.update("0" * 64),
        ):
            with self.assertRaises(FileNotFoundError):
                operation()
        self.assertFalse(self.path.parent.exists())

    def test_temp_creation_never_clobbers_collision(self):
        result = self.initialize()
        collision = self.path.parent / (self.path.name + ".tmp-collision")
        collision.symlink_to(self.path)
        with patch.object(checkpoint.secrets, "token_hex", return_value="collision"):
            with self.assertRaises(FileExistsError):
                self.update(result["revision"])
        self.assertTrue(collision.is_symlink())
        self.assertEqual(
            checkpoint.revision(self.path.read_bytes()), result["revision"]
        )

    def test_init_link_failure_cleans_temp_without_publication(self):
        with patch.object(checkpoint.os, "link", side_effect=OSError("link failed")):
            with self.assertRaises(OSError):
                self.initialize()
        self.assertFalse(self.path.exists())
        self.assert_no_temporaries()

    def test_cli_file_and_stdin_complete_proposal_and_read(self):
        proposal = self.root / "proposal.json"
        proposal.write_bytes(checkpoint.encode(self.value))
        result = self.cli("init", "--proposal", str(proposal))
        self.assertEqual(result.returncode, 0, result.stderr)
        initial = json.loads(result.stdout)
        result = self.cli("read")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), initial)
        value = dict(
            self.value, checkpoint="cli confirmed", status="completed", next_action=None
        )
        result = self.cli(
            "update",
            "--revision",
            initial["revision"],
            "--proposal",
            "-",
            raw=checkpoint.encode(value),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["checkpoint"]["checkpoint"], "cli confirmed"
        )
        self.assert_no_temporaries()

    def test_cli_stdin_init_file_update_and_non_null_identity(self):
        self.value["predecessor"] = "scout-00"
        self.value["working_directory"] = str(self.root)
        identity = ("--predecessor", "scout-00", "--working-directory", str(self.root))
        result = self.cli(
            "init", *identity, "--proposal", "-", raw=checkpoint.encode(self.value)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        proposal = self.root / "proposal.json"
        proposal.write_bytes(
            checkpoint.encode(dict(self.value, checkpoint="file update"))
        )
        result = self.cli(
            "update",
            *identity,
            "--revision",
            json.loads(result.stdout)["revision"],
            "--proposal",
            str(proposal)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["checkpoint"]["checkpoint"], "file update"
        )

    def test_cli_errors_do_not_leak_payloads_or_foreign_contents(self):
        result = self.cli(
            "init", "--proposal", "-", raw=b'{"secret-sensitive-payload":'
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(b"secret-sensitive-payload", result.stderr)
        self.assertEqual(json.loads(result.stderr)["operation"], "read-proposal")
        self.assertEqual(json.loads(result.stderr)["path"], "-")
        self.initialize()
        self.path.write_bytes(
            checkpoint.encode(
                dict(self.value, role="worker", checkpoint="secret-sensitive-payload")
            )
        )
        for command, extra in (
            ("read", ()),
            ("init", ("--proposal", "-")),
            ("update", ("--proposal", "-", "--revision", "0" * 64)),
        ):
            result = self.cli(command, *extra, raw=checkpoint.encode(self.value))
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")
            self.assertNotIn(b"secret-sensitive-payload", result.stderr)
            json.loads(result.stderr)

    def test_cli_unsafe_proposal_paths_and_oversized_stdin(self):
        target = self.root / "proposal.json"
        target.write_bytes(checkpoint.encode(self.value))
        link = self.root / "proposal-link.json"
        link.symlink_to(target)
        for source in (str(link), "relative.json", str(self.root / "missing")):
            result = self.cli("init", "--proposal", source)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(self.path.exists())
        result = self.cli(
            "init", "--proposal", "-", raw=b" " * (checkpoint.MAX_BYTES + 1)
        )
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.path.exists())

    def test_cli_requires_identity_revision_and_has_no_patch_or_dashboard(self):
        for extra in (
            ("--proposal", "-"),
            ("--revision", "0" * 64, "--proposal", "-", "--status", "failed"),
        ):
            result = self.cli("update", *extra, raw=checkpoint.encode(self.value))
            self.assertEqual(result.returncode, 2)
        result = self.cli("list")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
