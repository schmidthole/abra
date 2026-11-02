"""validate reuse without installing packages or executing fixture interpreters."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "check_formatter", ROOT / "bin/check_formatter.py"
)
formatter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(formatter)


class CheckFormatterTests(unittest.TestCase):
    def setUp(self):
        cache = ROOT / ".cache"
        cache.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "formatter/bin"
        self.bin.mkdir(parents=True)
        for name in ("python", "black"):
            path = self.bin / name
            path.write_text("#!" + str(self.bin / "python") + "\n")
            path.chmod(0o700)
        self.requirements = self.root / "requirements-dev.txt"
        self.requirements.write_bytes((ROOT / "requirements-dev.txt").read_bytes())
        self.digest = hashlib.sha256(self.requirements.read_bytes()).hexdigest()
        self.pins = formatter.requirement_pins(self.requirements.read_bytes())
        self.observed = dict(
            version=[3, 14, 2],
            prefix=str(self.bin.parent),
            packages=self.pins.copy(),
            executable=str(self.bin / "python"),
            implementation="CPython",
            platform="fixture-platform",
            machine="fixture-architecture",
        )

    def inspect(self):
        with patch.object(
            formatter.subprocess,
            "run",
            return_value=SimpleNamespace(stdout=json.dumps(self.observed)),
        ) as run:
            result = formatter.inspect_formatter(
                str(self.bin), self.requirements, self.digest
            )
        return result, run

    def test_candidate_pins_and_interpreter_receipt_without_mutation(self):
        before = {
            path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()
        }
        result, run = self.inspect()
        self.assertEqual(result["pins"], self.pins)
        self.assertEqual(result["requirements_sha256"], self.digest)
        self.assertEqual(result["platform"], "fixture-platform")
        command = run.call_args.args[0]
        self.assertEqual(command[:4], [str(self.bin / "python"), "-I", "-B", "-c"])
        self.assertEqual(run.call_args.kwargs["env"]["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertNotIn("PYTHONPATH", run.call_args.kwargs["env"])
        self.assertEqual(
            before,
            {
                path: path.read_bytes()
                for path in self.root.rglob("*")
                if path.is_file()
            },
        )

    def test_missing_and_wrong_pins_each_block(self):
        for name in self.pins:
            with self.subTest(name=name):
                original = self.observed["packages"].pop(name)
                with self.assertRaisesRegex(ValueError, "incomplete or has wrong pins"):
                    self.inspect()
                self.observed["packages"][name] = "0.0"
                with self.assertRaisesRegex(ValueError, "incomplete or has wrong pins"):
                    self.inspect()
                self.observed["packages"][name] = original

    def test_changed_candidate_requirements_block_before_execution(self):
        self.requirements.write_text(self.requirements.read_text() + "\n")
        with patch.object(formatter.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "digest changed"):
                formatter.inspect_formatter(
                    str(self.bin), self.requirements, self.digest
                )
            run.assert_not_called()

    def test_interpreter_version_or_environment_mismatch_blocks(self):
        self.observed["version"] = [3, 9, 6]
        with self.assertRaisesRegex(ValueError, "python 3.11"):
            self.inspect()
        self.observed["version"] = [3, 14, 2]
        self.observed["prefix"] = str(self.root / "another-environment")
        with self.assertRaisesRegex(ValueError, "another environment"):
            self.inspect()

    def test_partial_or_untrusted_environment_blocks_before_execution(self):
        for change in (
            "black-missing",
            "interpreter-changed",
            "writable-directory",
            "writable-package",
        ):
            with self.subTest(change=change), patch.object(
                formatter.subprocess, "run"
            ) as run:
                black = self.bin / "black"
                if change == "black-missing":
                    black.unlink()
                elif change == "interpreter-changed":
                    black.write_text("#!/other/python\n")
                elif change == "writable-directory":
                    self.bin.chmod(0o777)
                else:
                    package = self.bin.parent / "package.py"
                    package.write_text("untrusted content")
                    package.chmod(0o666)
                with self.assertRaises((ValueError, OSError)):
                    formatter.inspect_formatter(
                        str(self.bin), self.requirements, self.digest
                    )
                run.assert_not_called()
                self.bin.chmod(0o755)
                black.write_text("#!" + str(self.bin / "python") + "\n")
                black.chmod(0o700)
                package = self.bin.parent / "package.py"
                if package.exists():
                    package.unlink()

    def test_reject_unsupported_unhashed_duplicate_requirements(self):
        for value in (
            b"black>=1",
            b"-e project",
            b"black==1",
            b"--index-url https://example.test",
            b"click==1 --hash=sha256:" + b"a" * 64,
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                formatter.requirement_pins(value)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            formatter.requirement_pins(self.requirements.read_bytes() * 2)


if __name__ == "__main__":
    unittest.main()
