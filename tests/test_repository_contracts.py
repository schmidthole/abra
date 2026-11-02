"""guard the native coordination repository's remaining file contracts."""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RepositoryContractsTests(unittest.TestCase):
    def test_retired_runtime_and_deployment_paths_are_absent(self):
        for name in (
            "bin/abra",
            "triggers",
            "Dockerfile",
            ".dockerignore",
            "docker",
            "docs/container.md",
            "docs/triggers.md",
            "docs/slack.md",
            "docs/linear.md",
            "docs/modes/headless.md",
            "docs/modes/resident.md",
            "docs/modes/linear.md",
            "tests/test_abra.py",
            "tests/test_acp.py",
            "tests/test_bridge.py",
            "tests/test_container.py",
            "tests/test_linear.py",
            "tests/test_resident.py",
            "tests/test_slack.py",
            "tests/test_triggers.py",
            "tests/fake_acp_agent.py",
            "tests/fake_linear_axi.py",
            "tests/fake_resident_agent.py",
        ):
            with self.subTest(path=name):
                self.assertFalse((ROOT / name).exists())

    def test_formatter_inputs_exist(self):
        makefile = (ROOT / "Makefile").read_text()
        command = makefile.split("format:\n\t", 1)[1].splitlines()[0].split()
        self.assertEqual(command[0], "black")
        for name in command[1:]:
            with self.subTest(path=name):
                self.assertTrue((ROOT / name).exists())

    def test_readme_local_heading_references_resolve(self):
        readme = (ROOT / "README.md").read_text()
        references = re.findall(r"\]\(([^)#]*)#([^)]*)\)", readme)
        self.assertTrue(references)
        for reference, fragment in references:
            if "://" in reference:
                continue
            target = ROOT / (reference or "README.md")
            with self.subTest(reference=reference, fragment=fragment):
                self.assertTrue(target.is_file())
                headings = re.findall(
                    r"^#{1,6} (.+)$", target.read_text(), re.MULTILINE
                )
                anchors = {
                    re.sub(r"[^\w -]", "", heading.lower()).replace(" ", "-")
                    for heading in headings
                }
                self.assertIn(fragment, anchors)

    def test_documentation_file_references_resolve(self):
        documents = [
            *ROOT.glob("*.md"),
            *ROOT.glob("docs/**/*.md"),
            *ROOT.glob("templates/*.md"),
        ]
        for document in documents:
            text = document.read_text()
            references = re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", text)
            references += re.findall(r"`((?:docs|templates)/[^`\s]+\.md)`", text)
            for reference in references:
                if "://" in reference:
                    continue
                base = (
                    ROOT
                    if reference.startswith(("docs/", "templates/"))
                    else document.parent
                )
                with self.subTest(
                    document=document.relative_to(ROOT), reference=reference
                ):
                    self.assertTrue((base / reference).is_file())


if __name__ == "__main__":
    unittest.main()
