"""static decision/outcome contracts; these do not execute a routing runtime."""

import json
from pathlib import Path
import re
import textwrap
import unittest

from test_agent_tracking import rules, normalize_rule_paragraphs

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = json.loads((ROOT / "tests/fixtures/operating-contracts.json").read_text())
ROUTING = (ROOT / "docs/routing.md").read_text()
CAPABILITIES = (ROOT / "docs/capabilities.md").read_text()


def table(text, heading):
    rows = text.split(heading + "\n", 1)[1].split("\n\n", 1)[0].splitlines()[1:]
    return [[value.strip() for value in row.strip("|").split("|")] for row in rows]


def routing_order(text):
    section = text.split("## routing decision order\n\n", 1)[1].split(
        "\nnormative decision cases", 1
    )[0]
    return [
        " ".join(part.split()) for part in re.split(r"\n(?=[1-8]\. )", section.strip())
    ]


def normalize_routing(text):
    text = normalize_rule_paragraphs(text)
    start = text.index("## routing decision order\n\n") + len(
        "## routing decision order\n\n"
    )
    end = text.index("\nnormative decision cases", start)
    return text[:start] + "\n".join(routing_order(text)) + "\n" + text[end:]


def review_routing(text):
    actual = dict(
        routing_rules=rules(text),
        routing_order=routing_order(text),
        routing_cases=table(
            text, "| case | supplied facts | route | required outcome |"
        ),
        startup_cases=table(text, "| case | discovery facts | inspection |"),
    )
    if actual != {key: EXPECTED[key] for key in actual}:
        raise ValueError("routing authority, decision or recovery contract changed")


def review_capabilities(text):
    if (
        rules(text) != EXPECTED["capability_rules"]
        or table(text, "| role | required observed facilities | forbidden expansion |")
        != EXPECTED["capability_roles"]
    ):
        raise ValueError("capability role or failure boundary changed")


class OperatingContractsTests(unittest.TestCase):
    def test_routing_decisions_have_full_inputs_routes_and_obligations(self):
        review_routing(ROUTING)
        cases = {row[0]: row[1:] for row in EXPECTED["routing_cases"]}
        for excluded in (
            "policy-line",
            "security-doc",
            "code",
            "probe",
            "external",
            "explicit-full",
            "specialty-full",
            "no-opt-in",
            "unknown-owner",
            "uncertain-scope",
        ):
            with self.subTest(case=excluded):
                self.assertNotIn(
                    cases[excluded][1],
                    ("lightweight-direct", "lightweight-scout", "lightweight-docs"),
                )
        self.assertEqual(cases["brainstorm"][1], "lightweight-direct")
        self.assertEqual(cases["certified-package"][1], "plan")
        self.assertEqual(cases["one-scout"][1], "lightweight-scout")
        self.assertEqual(cases["unknown-owner"][1], "blocked")

    def test_weakened_exclusions_or_startup_outcomes_reject(self):
        for old, new in (
            ("| implement |", "| lightweight-docs |"),
            ("| blocked |", "| lightweight-scout |"),
            ("| full-relevant |", "| summary-sufficient |"),
            ("| broaden-full |", "| summary-sufficient |"),
            ("| full-unfinished |", "| summary-sufficient |"),
            (
                "explicit full recipe or specialty requirement",
                "optional full recipe or specialty suggestion",
            ),
        ):
            with self.subTest(mutation=old):
                normalized = normalize_routing(ROUTING)
                self.assertIn(old, normalized)
                with self.assertRaises(ValueError):
                    review_routing(normalized.replace(old, new))

    def test_lightweight_and_cross_repo_recovery_cannot_drop_evidence_or_repeat(self):
        for key in (
            "lightweight-record",
            "interrupted-intent",
            "report-before-outcome",
            "escalation",
            "startup-broadening",
        ):
            value = rules(ROUTING)[key]
            # delete a complete operational rule; all saved-record and stop rules count.
            weakened = ROUTING.replace("- [" + key + "] " + value, "")
            if weakened == ROUTING:
                paragraphs = re.split(r"\n\s*\n", ROUTING)
                weakened = "\n\n".join(
                    p for p in paragraphs if not p.startswith("- [" + key + "]")
                )
            with self.subTest(rule=key), self.assertRaises(ValueError):
                review_routing(weakened)
        for old, new in (
            ("never duplicate-dispatch", "always duplicate-dispatch"),
            ("without retroactive stage", "with retroactive stage"),
            (
                "read the **full body before every update**",
                "skip the full body before every update",
            ),
        ):
            with self.subTest(mutation=old):
                normalized = normalize_routing(ROUTING)
                self.assertIn(old, normalized)
                with self.assertRaises(ValueError):
                    review_routing(normalized.replace(old, new))

    def test_reflow_of_whole_rules_not_incidental_line_identity(self):
        # table syntax is structural; only paragraph line wrapping is incidental.
        paragraphs = ROUTING.split("\n\n")
        reflowed = "\n\n".join(
            (
                textwrap.fill(
                    p, width=71, break_long_words=False, break_on_hyphens=False
                )
                if p.startswith("- [")
                else p
            )
            for p in paragraphs
        )
        review_routing(reflowed)

    def test_capability_roles_and_failure_boundary(self):
        review_capabilities(CAPABILITIES)
        for key in rules(CAPABILITIES):
            changed = "\n\n".join(
                p
                for p in CAPABILITIES.split("\n\n")
                if not p.startswith("- [" + key + "]")
            )
            with self.subTest(rule=key), self.assertRaises(ValueError):
                review_capabilities(changed)
        with self.assertRaises(ValueError):
            review_capabilities(
                normalize_rule_paragraphs(CAPABILITIES).replace(
                    "blocks required work", "permits continued work"
                )
            )
        with self.assertRaises(ValueError):
            review_capabilities(
                CAPABILITIES.replace("no product repair", "product repair permitted")
            )
        for path in (
            "AGENTS.md",
            "README.md",
            "docs/workflows.md",
            "docs/specialty.md",
        ):
            with self.subTest(path=path):
                text = (ROOT / path).read_text()
                self.assertRegex(text, r"capabilit(?:y|ies)")


if __name__ == "__main__":
    unittest.main()
