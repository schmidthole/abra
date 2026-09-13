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

    def test_cleanup_preview_removal_and_branch_preservation(self):
        result = worktree.create(self.root, "demo", "finished")
        path = Path(result["path"])
        with self.assertRaisesRegex(ValueError, "--idle"):
            worktree.cleanup(self.root, "demo", "finished", yes=True)
        preview = worktree.cleanup(self.root, "sample", "finished", idle=True)
        self.assertFalse(preview["removed"])
        self.assertTrue(path.exists())
        removed = worktree.cleanup(self.root, "demo", "finished", idle=True, yes=True)
        self.assertTrue(removed["removed"])
        self.assertFalse(path.exists())
        self.assertEqual(
            worktree.git(self.source, "rev-parse", "abra/finished"), result["commit"]
        )
        self.assertTrue(self.source.exists())

    def test_cleanup_refuses_dirty_and_hidden_untracked_files(self):
        path = Path(worktree.create(self.root, "demo", "dirty")["path"])
        worktree.git(path, "config", "status.showUntrackedFiles", "no")
        for filename in ("file.txt", "untracked.txt"):
            with self.subTest(filename=filename):
                (path / filename).write_text("unsaved\n")
                with self.assertRaisesRegex(ValueError, "uncommitted or untracked"):
                    worktree.cleanup(self.root, "demo", "dirty", idle=True, yes=True)
                self.assertTrue(path.exists())
                if filename == "file.txt":
                    worktree.git(path, "checkout", "--", filename)

    def test_cleanup_detached_commit_requires_preserving_ref(self):
        head = worktree.git(self.source, "rev-parse", "HEAD")
        path = Path(worktree.create(self.root, "demo", "review", head)["path"])
        (path / "file.txt").write_text("unique\n")
        worktree.git(path, "commit", "-am", "unique")
        with self.assertRaisesRegex(ValueError, "not preserved"):
            worktree.cleanup(self.root, "demo", "review", head, idle=True, yes=True)
        worktree.git(path, "tag", "saved-review")
        worktree.cleanup(self.root, "demo", "review", head, idle=True, yes=True)
        self.assertFalse(path.exists())
        self.assertTrue(worktree.git(self.source, "rev-parse", "saved-review"))

    def test_cleanup_refuses_locked_worktree(self):
        path = Path(worktree.create(self.root, "demo", "locked")["path"])
        worktree.git(self.source, "worktree", "lock", str(path))
        with self.assertRaisesRegex(ValueError, "locked"):
            worktree.cleanup(self.root, "demo", "locked", idle=True, yes=True)
        self.assertTrue(path.exists())

    def test_cleanup_rejects_invalid_paths_and_symlinks(self):
        for task, verify in (("../escape", None), ("valid", "main")):
            with self.assertRaises(ValueError):
                worktree.cleanup(self.root, "demo", task, verify, idle=True, yes=True)
        for relative in (".worktrees", ".worktrees/demo", ".worktrees/demo/main"):
            with self.subTest(path=relative):
                managed = self.root / relative
                managed.parent.mkdir(parents=True, exist_ok=True)
                managed.symlink_to(self.source, target_is_directory=True)
                with self.assertRaisesRegex(ValueError, "symlinks"):
                    worktree.cleanup(self.root, "demo", "main", idle=True, yes=True)
                managed.unlink()
        self.assertTrue(self.source.exists())

    def test_cleanup_refuses_registered_source_checkout(self):
        path = Path(worktree.create(self.root, "demo", "source")["path"])
        registry = worktree.read_registry(self.root)
        registry["demo"]["path"] = str(path)
        (self.root / "data/repos.json").write_text(worktree.json.dumps(registry))
        with self.assertRaisesRegex(ValueError, "source checkout"):
            worktree.cleanup(self.root, "demo", "source", idle=True, yes=True)
        self.assertTrue(path.exists())

    def test_cleanup_refuses_foreign_worktree(self):
        foreign = self.root / "foreign"
        foreign.mkdir()
        worktree.git(foreign, "init", "-b", "main")
        worktree.git(foreign, "fetch", str(self.source), "main")
        path = self.root / ".worktrees/demo/foreign"
        worktree.git(foreign, "worktree", "add", "--detach", str(path), "FETCH_HEAD")
        with self.assertRaisesRegex(ValueError, "not a registered worktree"):
            worktree.cleanup(self.root, "demo", "foreign", idle=True, yes=True)
        self.assertTrue(path.exists())

    def test_cleanup_removes_ignored_output(self):
        path = Path(worktree.create(self.root, "demo", "ignored")["path"])
        worktree.git(path, "config", "core.excludesFile", str(self.root / "ignore"))
        (self.root / "ignore").write_text("cache\n")
        (path / "cache").write_text("disposable\n")
        worktree.cleanup(self.root, "demo", "ignored", idle=True, yes=True)
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
