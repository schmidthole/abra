"""exercise worktree behavior against real temporary repositories."""

import importlib.util
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "worktree", Path(__file__).resolve().parents[1] / "bin/worktree.py"
)
worktree = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worktree)


class WorktreeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "home"
        self.source = Path(self.temporary.name) / "source with spaces"
        self.source.mkdir()
        worktree.git(self.source, "init", "-b", "main")
        worktree.git(self.source, "config", "user.email", "test@example.invalid")
        worktree.git(self.source, "config", "user.name", "test")
        (self.source / "file.txt").write_text("original\n")
        worktree.git(self.source, "add", ".")
        worktree.git(self.source, "commit", "-m", "initial")
        worktree.register(
            self.root, "demo", self.source, "main", ["sample"], "test repo"
        )

    def test_registry_alias_and_duplicate(self):
        name, repo = worktree.resolve(worktree.read_registry(self.root), "sample")
        self.assertEqual(name, "demo")
        self.assertEqual(repo["path"], str(self.source.resolve()))
        with self.assertRaises(ValueError):
            worktree.register(self.root, "other", self.source, "main", ["sample"], "")
        with self.assertRaises(ValueError):
            worktree.resolve(worktree.read_registry(self.root), "missing")

    def test_worker_isolation_and_duplicate_refusal(self):
        (self.source / "file.txt").write_text("uncommitted\n")
        result = worktree.create(self.root, "sample", "fix-one")
        path = Path(result["path"])
        self.assertEqual((path / "file.txt").read_text(), "original\n")
        self.assertEqual(worktree.git(path, "branch", "--show-current"), "abra/fix-one")
        (path / "file.txt").write_text("worker change\n")
        with self.assertRaises(ValueError):
            worktree.create(self.root, "demo", "fix-one")
        self.assertEqual((path / "file.txt").read_text(), "worker change\n")
        self.assertEqual((self.source / "file.txt").read_text(), "uncommitted\n")

    def test_verification_is_detached_at_exact_worker_commit(self):
        worker = Path(worktree.create(self.root, "demo", "fix-one")["path"])
        (worker / "file.txt").write_text("implemented\n")
        worktree.git(worker, "commit", "-am", "implement")
        head = worktree.git(worker, "rev-parse", "HEAD")
        result = worktree.create(self.root, "demo", "fix-one", head)
        verify = Path(result["path"])
        self.assertEqual(worktree.git(verify, "rev-parse", "HEAD"), head)
        self.assertEqual(worktree.git(verify, "branch", "--show-current"), "")
        self.assertEqual((verify / "file.txt").read_text(), "implemented\n")
        (verify / "file.txt").write_text("test mutation\n")
        self.assertEqual((worker / "file.txt").read_text(), "implemented\n")

    def test_verification_rejects_annotated_tag_object(self):
        worktree.git(self.source, "tag", "-a", "release", "-m", "release")
        tag = worktree.git(self.source, "rev-parse", "release")
        with self.assertRaises(ValueError):
            worktree.create(self.root, "demo", "tag-check", tag)
        self.assertFalse((self.root / ".worktrees/demo").exists())

    def test_invalid_input_and_branch_collision(self):
        for task in ("../escape", "--force", "has space", "UPPER"):
            with self.assertRaises(ValueError):
                worktree.create(self.root, "demo", task)
        with self.assertRaises(ValueError):
            worktree.create(self.root, "demo", "valid", "main")
        worktree.git(self.source, "branch", "abra/collision")
        with self.assertRaises(ValueError):
            worktree.create(self.root, "demo", "collision")
        self.assertFalse((self.root / ".worktrees/demo/collision").exists())


if __name__ == "__main__":
    unittest.main()
