"""guard checkpoint prompt contracts, not live compliance or filesystem behavior."""

from datetime import datetime
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("worker", "scout", "verify", "triage")
SPEC = (ROOT / "docs/agent-tracking.md").read_text()


class AgentTrackingTests(unittest.TestCase):
    def test_example_matches_versioned_field_contract(self):
        example = json.loads(SPEC.split("```json\n", 1)[1].split("```", 1)[0])
        fields = set(re.findall(r"^\| `([a-z_]+)` \|", SPEC, re.M))
        self.assertEqual(
            fields,
            {
                "version",
                "assignment",
                "role",
                "predecessor",
                "run_ids",
                "status",
                "updated_at",
                "job_summary",
                "working_directory",
                "steps",
                "checkpoint",
                "next_action",
                "blocker",
                "artifacts",
            },
        )
        self.assertEqual(set(example), fields)
        self.assertIs(type(example["version"]), int)
        self.assertEqual(example["version"], 1)
        self.assertRegex(example["assignment"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertIn(example["role"], ROLES)
        self.assertIn(
            example["status"], ("active", "paused", "completed", "blocked", "failed")
        )
        datetime.strptime(example["updated_at"], "%Y-%m-%dT%H:%M:%SZ")
        self.assertIsNone(example["predecessor"])
        self.assertIsNone(example["working_directory"])
        self.assertIsNone(example["blocker"])
        self.assertEqual(example["run_ids"], [])
        self.assertEqual(example["artifacts"], [])
        for key in ("job_summary", "checkpoint", "next_action"):
            self.assertIsInstance(example[key], str)
            self.assertTrue(example[key].strip())
        self.assertLessEqual(len(example["job_summary"]), 500)
        self.assertTrue(example["steps"])
        ids = []
        for step in example["steps"]:
            self.assertEqual(set(step), {"id", "title", "status"})
            self.assertRegex(step["id"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
            self.assertIsInstance(step["title"], str)
            self.assertTrue(step["title"].strip())
            self.assertIn(
                step["status"],
                ("pending", "active", "completed", "blocked", "failed", "skipped"),
            )
            ids.append(step["id"])
        self.assertEqual(len(ids), len(set(ids)))

    def test_all_roles_have_equal_fillable_tracking_integration(self):
        blocks = []
        for role in ROLES:
            with self.subTest(role=role):
                template = (ROOT / "templates" / (role + ".md")).read_text()
                block = template.split("## shared checkpoint\n", 1)[1].split(
                    "## assignment\n", 1
                )[0]
                blocks.append(block)
                fields = re.findall(r"\{\{([a-z_]+)\}\}", block)
                self.assertEqual(
                    set(fields),
                    {
                        "assignment",
                        "tracker_path",
                        "predecessor",
                        "run_ids",
                        "tracking_instructions",
                    },
                )
                self.assertEqual(len(fields), len(set(fields)))
                for field in re.findall(r"\{\{([a-z_]+)\}\}", template):
                    template = template.replace(
                        "{{" + field + "}}", "supplied " + field
                    )
                self.assertNotIn("{{", template)
                self.assertNotIn("}}", template)
        self.assertTrue(all(block == blocks[0] for block in blocks))
        for instruction in (
            "before substantive work",
            "before consequential actions",
            "before pause/return",
            "pause and report",
            "assigned tracker and its same-directory atomic",
            "outside the project\nworktree",
            "does not grant other write or execution authority",
            "preserve\nmalformed or foreign checkpoints",
            "not liveness",
        ):
            self.assertIn(instruction, blocks[0])

    def test_original_role_boundaries_remain_explicit(self):
        boundaries = {
            "worker": (
                "change project files only there",
                "commit only task-owned files",
            ),
            "scout": ("do not modify project files", "supplied report path"),
            "verify": (
                "never edit the worker\ncheckout, fix product code",
                "candidate commit:",
            ),
            "triage": ("shared checkpoint exception above", "do not mutate production"),
        }
        for role, phrases in boundaries.items():
            template = (ROOT / "templates" / (role + ".md")).read_text()
            for phrase in phrases:
                with self.subTest(role=role, phrase=phrase):
                    self.assertIn(phrase, template)

    def test_safe_write_and_failure_instructions_are_present(self):
        for instruction in (
            "all fields below\nare required",
            "no unknown fields or duplicate keys",
            "never copy secrets",
            "exclusively created temporary regular file",
            "parse/check the new json before replacing",
            "never truncate the destination in place",
            "if it changed unexpectedly, stop",
            "clean up only the temporary file you created",
            "pause substantive\n   work until resolved",
            "final state was not persisted",
            "power-loss durability or model compliance",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, SPEC)

    def test_recovery_walkthroughs_cover_reconciliation_not_liveness(self):
        scenarios = {
            "interruption and same-assignment resume": (
                "reconciles actual files, git history",
                "without blindly repeating the commit",
                "preserve stable assignment and step ids",
            ),
            "replacement assignment": (
                "stop/reconcile the old\nwriter",
                "predecessor `worker-01`",
                "leave `worker-01.json` intact",
            ),
            "malformed or foreign checkpoint": (
                "unsupported version",
                "preserve it unchanged",
                "do not delete old\ndata",
            ),
            "missing or stale checkpoint": (
                "absent\nfile on resume is not evidence that nothing ran",
                "not proof of liveness, approval, or current truth",
                "do not invent success",
            ),
        }
        for heading, phrases in scenarios.items():
            section = SPEC.split("### " + heading + "\n", 1)[1].split("\n### ", 1)[0]
            for phrase in phrases:
                with self.subTest(scenario=heading, phrase=phrase):
                    self.assertIn(phrase, section)
        self.assertIn("static contract walkthroughs, not live harness trials", SPEC)

    def test_coordinator_and_specialty_dispatch_share_contract(self):
        agents = (ROOT / "AGENTS.md").read_text()
        self.assertIn("`docs/agent-tracking.md`", agents)
        self.assertIn("`data/<task-id>/agents/<assignment>.json`", agents)
        self.assertIn("agent alone writes", agents)
        self.assertIn("including\n  specialty overrides", agents)
        self.assertIn("reconcile native ownership", agents)
        specialty = (ROOT / "docs/specialty.md").read_text()
        self.assertIn("[shared checkpoint contract](agent-tracking.md)", specialty)
        self.assertIn("even when an override omits them", specialty)
        readme = (ROOT / "README.md").read_text()
        self.assertIn("](docs/agent-tracking.md)", readme)
        self.assertIn("not liveness, verified\nsuccess", readme)


if __name__ == "__main__":
    unittest.main()
