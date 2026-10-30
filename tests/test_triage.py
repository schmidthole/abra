"""guard the portable triage brief interface, not live agent behavior."""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates/triage.md"


class TriageTemplateTests(unittest.TestCase):
    def test_triage_inputs_are_explicit_and_fillable(self):
        template = TEMPLATE.read_text()
        inputs = {
            "task_id",
            "repo",
            "worktree",
            "request",
            "evidence",
            "constraints",
            "authorized_probes",
            "report_path",
            "assignment",
            "tracker_path",
            "checkpoint_helper",
            "predecessor",
            "run_ids",
            "tracking_instructions",
            "workflow_path",
            "workflow_recipe",
            "workflow_stage",
            "workflow_attempt",
        }
        fields = re.findall(r"\{\{([a-z_]+)\}\}", template)
        self.assertEqual(set(fields), inputs)
        self.assertEqual(len(fields), len(inputs))
        for field in inputs:
            template = template.replace("{{" + field + "}}", "supplied " + field)
        self.assertNotIn("{{", template)
        self.assertNotIn("}}", template)

    def test_triage_report_keeps_reproduction_and_cause_separate(self):
        template = TEMPLATE.read_text()
        report = template.split("## report and completion\n", 1)[1]
        fields = dict(re.findall(r"^- ([a-z ,]+): ([^\n]+)", report, re.M))
        self.assertEqual(
            set(fields),
            {
                "behavior summary",
                "affected system and evidence",
                "reproduction status",
                "hypotheses, checks, and outcomes",
                "cause confidence",
                "remaining questions and access",
                "diagnostic artifacts",
                "recommended next action",
                "worker handoff",
            },
        )
        self.assertEqual(
            fields["reproduction status"],
            "reproduced / not reproduced / blocked / not attempted.",
        )
        self.assertTrue(
            fields["cause confidence"].startswith(
                "confirmed / suspected / undetermined."
            )
        )

    def test_triage_docs_are_discoverable(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("`templates/triage.md`", (ROOT / "AGENTS.md").read_text())
        for path in ("templates/triage.md", "docs/triage.md"):
            with self.subTest(path=path):
                self.assertIn("](" + path + ")", readme)
                self.assertTrue((ROOT / path).is_file())


if __name__ == "__main__":
    unittest.main()
