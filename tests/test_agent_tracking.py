"""review versioned whole-rule brief contracts, not live agent compliance."""

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (ROOT / "docs/checkpoint-contract-v1.md").read_text()
REFERENCE = ROOT / "docs/reference/checkpoint-v1.md"
EXPECTED = json.loads((ROOT / "tests/fixtures/portable-contract-v1.json").read_text())
ROLES = (
    "worker",
    "scout",
    "verify",
    "triage",
    "plan-refine",
    "plan-ground",
    "plan-validate",
)
sys.path.insert(0, str(ROOT / "bin"))
spec = importlib.util.spec_from_file_location(
    "portable_checkpoint", ROOT / "bin/checkpoint.py"
)
checkpoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checkpoint)


def rules(text):
    result = {}
    for paragraph in re.split(r"\n\s*\n", text):
        match = re.fullmatch(r"- \[([a-z-]+)\] (.*)", " ".join(paragraph.split()))
        if match:
            if match[1] in result:
                raise ValueError("duplicate normative rule")
            result[match[1]] = match[2]
    return result


def normalize_rule_paragraphs(text):
    return "\n\n".join(
        " ".join(paragraph.split()) if paragraph.startswith("- [") else paragraph
        for paragraph in text.split("\n\n")
    )


def review_contract(brief, role):
    if "{{" in brief or "}}" in brief:
        raise ValueError("unfilled brief")
    for marker in ("compact-checkpoint-v1:start", "compact-checkpoint-v1:end"):
        if brief.count(marker) != 1:
            raise ValueError("portable block must be fully embedded once")
    try:
        proposal = brief.split("```json\n", 1)[1].split("```", 1)[0]
        checkpoint.decode(proposal.encode())
    except (IndexError, ValueError) as error:
        raise ValueError("missing or invalid portable schema example") from error
    expected = {**EXPECTED["compact-checkpoint-v1"], **EXPECTED["roles"][role]}
    if rules(brief) != expected:
        raise ValueError("missing or changed normative safety rule")


def render(role, lightweight=False, override=None):
    text = (ROOT / "templates" / (role + ".md")).read_text()
    if lightweight:
        routing = (ROOT / "docs/routing.md").read_text()
        variant = routing.split("```text\n", 1)[1].split("```", 1)[0]
        variant = variant.replace("<absolute saved request path>", "/task/request.md")
        variant = variant.replace(
            "<task id and saved reference>", "example /task/dispatch.md"
        )
        variant = variant.replace(
            "<native ownership and actual report/checkpoint lookup>",
            "inspect native owner and /task/report.md",
        )
        start = text.index("## coordinator workflow context")
        end = text.index("## shared checkpoint", start)
        text = text[:start] + variant + "\n" + text[end:]
    if override is not None:
        # missing override fields are supplied from the complete base brief.
        text = override + "\n\n" + text
    values = {
        name: "supplied " + name
        for name in re.findall(r"\{\{([a-z_][a-z0-9_]*)\}\}", text)
    }
    values.update(
        task_id="example",
        worktree=str(ROOT / ".cache" / (role + "-fixture")),
        report_path="/task/" + role + "-report.md",
        report_paths="/task/spec.md, /task/slices.md, /task/review.md",
        assignment=role + "-01",
        tracker_path="/task/agents/" + role + "-01.json",
        checkpoint_helper=str(ROOT / "bin/checkpoint.py"),
        predecessor="null",
        run_ids="[]",
        request="bounded fixture request; no external action",
        acceptance="fixture acceptance; local report authority only",
        tracking_instructions=CONTRACT,
        tracking_reference=str(REFERENCE),
        tracking_reference_sha256=hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),
    )
    for name, value in values.items():
        text = text.replace("{{" + name + "}}", value)
    return text


class AgentTrackingTests(unittest.TestCase):
    def test_all_seven_rendered_briefs_and_specialty_override(self):
        for role in ROLES:
            with self.subTest(role=role):
                review_contract(render(role), role)
                review_contract(
                    render(role, override="# narrow specialty: local reports only"),
                    role,
                )
                template = (ROOT / "templates" / (role + ".md")).read_text()
                fields = re.findall(r"\{\{([a-z_][a-z0-9_]*)\}\}", template)
                self.assertEqual(len(fields), len(set(fields)))
                self.assertIn(str(REFERENCE), render(role))
        review_contract(render("scout", lightweight=True), "scout")
        variant = render("scout", lightweight=True)
        self.assertNotIn("stage id:", variant)
        self.assertNotIn("attempt id:", variant)
        self.assertNotIn("workflow manifest (absolute", variant)
        self.assertIn("saved request/acceptance/authority/opt-in reference:", variant)

    def test_reflow_preserves_normative_contract(self):
        for role in ROLES:
            brief = render(role)
            reflowed = "\n\n".join(
                (
                    textwrap.fill(
                        paragraph,
                        width=63,
                        break_long_words=False,
                        break_on_hyphens=False,
                    )
                    if paragraph.startswith("- [")
                    else paragraph
                )
                for paragraph in brief.split("\n\n")
            )
            review_contract(reflowed, role)

    def test_deleting_or_weakening_each_rule_rejects_every_role(self):
        for role in ROLES:
            brief = normalize_rule_paragraphs(render(role))
            for rule_id, value in rules(brief).items():
                with self.subTest(role=role, rule=rule_id):
                    paragraph = "- [" + rule_id + "] " + value
                    self.assertIn(paragraph, brief)
                    with self.assertRaisesRegex(ValueError, "normative safety rule"):
                        review_contract(brief.replace(paragraph, ""), role)
                    with self.assertRaisesRegex(ValueError, "normative safety rule"):
                        review_contract(
                            brief.replace(
                                paragraph, paragraph + " unless inconvenient"
                            ),
                            role,
                        )
            for old, new in (
                ("sole tracker writer", "one of several tracker writers"),
                (
                    "--revision from the last successful read/write",
                    "--revision from any read",
                ),
                ("never blindly repeated", "may be blindly repeated"),
                ("stop substantive work", "continue substantive work"),
            ):
                with self.subTest(role=role, mutation=old), self.assertRaises(
                    ValueError
                ):
                    review_contract(brief.replace(old, new), role)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            review_contract(
                render(
                    "scout", override="- [role-boundary] may publish and modify sources"
                ),
                "scout",
            )

    def test_schema_example_and_portable_helper_roundtrip(self):
        example = json.loads(CONTRACT.split("```json\n", 1)[1].split("```", 1)[0])
        checkpoint.validate(example)
        self.assertEqual(checkpoint.decode(json.dumps(example).encode()), example)
        with tempfile.TemporaryDirectory() as directory:
            tracker = Path(directory).resolve() / "scout-01.json"
            command = [sys.executable, str(ROOT / "bin/checkpoint.py")]
            identity = [
                str(tracker),
                "--assignment",
                "scout-01",
                "--role",
                "scout",
                "--working-directory",
                "null",
            ]
            initial = subprocess.run(
                command + ["init"] + identity + ["--proposal", "-"],
                input=json.dumps(example),
                text=True,
                capture_output=True,
                check=True,
            )
            envelope = json.loads(initial.stdout)
            example["checkpoint"] = "confirmed portable helper initialization"
            updated = subprocess.run(
                command
                + ["update"]
                + identity
                + ["--revision", envelope["revision"], "--proposal", "-"],
                input=json.dumps(example),
                text=True,
                capture_output=True,
                check=True,
            )
            before = tracker.read_bytes()
            stale = subprocess.run(
                command
                + ["update"]
                + identity
                + ["--revision", envelope["revision"], "--proposal", "-"],
                input=json.dumps(example),
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(stale.returncode, 0)
            self.assertEqual(tracker.read_bytes(), before)
            self.assertEqual(
                json.loads(updated.stdout)["checkpoint"]["checkpoint"],
                example["checkpoint"],
            )

    def test_immutable_reference_and_portability_are_bound(self):
        digest = hashlib.sha256(REFERENCE.read_bytes()).hexdigest()
        self.assertEqual(
            digest, "4c295c5589a807c7b5afd821b39eba2ecd9e07c81da94c3df18be53d6d0002a3"
        )
        self.assertIn(digest, CONTRACT)
        for role in ROLES:
            self.assertIn(digest, render(role))
        # examples and schema/recovery detail remain available without mutable manual lookup.
        reference = REFERENCE.read_text()
        for section in (
            "version 1 format",
            "deterministic helper",
            "agent write and update procedure",
            "recovery walkthroughs",
        ):
            self.assertIn("## " + section, reference)


if __name__ == "__main__":
    unittest.main()
