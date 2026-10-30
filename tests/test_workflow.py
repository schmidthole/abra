"""fixed recipe persistence and disposable simulated interruption trials, not native trials."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "bin/workflow.py"
spec = importlib.util.spec_from_file_location("workflow", HELPER)
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)
checkpoint = workflow.checkpoint


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        # all trial files, including simulated external effects, stay in this worktree.
        directory = ROOT / ".cache/workflow-trials"
        directory.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=directory)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / "data/example/workflow.json"
        self.path.parent.mkdir(parents=True)
        self.brief = self.path.parent / "brief.md"
        self.brief.write_text("full request, acceptance and local delivery authority\n")
        self.report = self.path.parent / "report.md"
        self.report.write_text("independent verdict and test evidence\n")
        self.value = dict(
            version=1,
            task_id="example",
            updated_at="2026-06-01T12:00:00Z",
            briefs=[
                dict(
                    reference=str(self.brief),
                    acceptance_revision="a" * 64,
                    requested_delivery="local-commit",
                    decision="select",
                )
            ],
            selections=[self.selection("implement", "selection-01", "select")],
            decisions=[
                dict(
                    id="select",
                    kind="operator",
                    summary="operator selected implement; local commit delivery authorized",
                    evidence=[str(self.brief)],
                )
            ],
            status="active",
            current_stage="worker",
            checkpoint="operator selected recipe",
            next_action="reserve worker",
            blocker=None,
            delivery_refs=[],
        )
        self.revision = None

    def selection(self, recipe, id, decision):
        return dict(
            id=id,
            recipe=recipe,
            version=1,
            rationale="operator selected bounded recipe",
            decision=decision,
            stages=[dict(id=s, attempts=[]) for s in workflow.RECIPES[recipe]],
        )

    def save(self, initialize=False):
        result = workflow.write_workflow(
            self.path, "example", self.value, self.revision, initialize
        )
        self.value, self.revision = result["workflow"], result["revision"]
        return result

    def stage(self, name):
        return next(
            s for s in self.value["selections"][-1]["stages"] if s["id"] == name
        )

    def last(self):
        return workflow.ordered(self.value["selections"][-1])[-1][1]

    def reserve(self, stage, candidate=None):
        number = len(workflow.ordered(self.value["selections"][-1])) + 1
        id = stage + "-" + str(number)
        links = []
        if stage in workflow.AGENT_STAGES:
            links = [
                dict(
                    assignment=id,
                    role=stage,
                    predecessor=None,
                    tracker=str(self.path.parent / "agents" / (id + ".json")),
                    brief=str(self.brief),
                    working_directory=str(self.root),
                    dispatch="intent",
                    reconciliation=None,
                )
            ]
        attempt = dict(
            id=id,
            order=number,
            status="active",
            intent="authorized " + stage + " action; reconcile before repeating",
            assignments=links,
            acceptance_revision=workflow.current_acceptance(self.value),
            candidate_commit=candidate,
            verdict=None,
            report=None,
            outcome=None,
            evidence=[],
            decision=None,
        )
        self.stage(stage)["attempts"].append(attempt)
        self.value["current_stage"] = stage
        self.value["status"] = "active"
        self.value["next_action"] = "perform authorized " + stage
        self.save()
        return self.last()

    def finish(self, status="passed", commit=None, verdict=None, evidence=None):
        stage, attempt = workflow.ordered(self.value["selections"][-1])[-1]
        for link in attempt["assignments"]:
            link["dispatch"] = "confirmed"
        if evidence is None:
            evidence = [str(self.report)]
            if stage == "deliver":
                evidence += [attempt["candidate_commit"], *self.value["delivery_refs"]]
                if workflow.current_delivery(self.value) in ("pr", "merge"):
                    evidence.append("https://example.test/pr/1")
            evidence = list(dict.fromkeys(evidence))
        attempt.update(
            status=status,
            candidate_commit=commit or attempt["candidate_commit"],
            verdict=verdict,
            report=(
                str(self.report)
                if stage in ("verify", "triage", "scout", "report")
                else None
            ),
            outcome="coordinator reviewed actual evidence",
            evidence=evidence,
            decision="decision-" + attempt["id"],
        )
        self.value["decisions"].append(
            dict(
                id=attempt["decision"],
                kind="coordinator",
                summary="reviewed actual outcome independently of agent status",
                evidence=[str(self.report)],
            )
        )
        self.value["current_stage"] = workflow.progress(
            self.value["selections"][-1], workflow.current_acceptance(self.value)
        )
        if self.value["current_stage"] is None:
            self.value.update(
                status="paused",
                next_action="review requested delivery or repair exhaustion",
            )
        self.save()

    def worker(self, commit="b" * 40):
        self.reserve("worker")
        self.finish(commit=commit)

    def verify(self, commit="b" * 40, verdict="pass"):
        self.reserve("verify", commit)
        self.finish(status="passed" if verdict == "pass" else "failed", verdict=verdict)

    def complete(self):
        stage, attempt = workflow.ordered(self.value["selections"][-1])[-1]
        refs = [str(self.report)]
        if stage == "deliver":
            refs = (
                [attempt["candidate_commit"]]
                if workflow.current_delivery(self.value) == "local-commit"
                else ["https://example.test/pr/1"]
            )
        self.value.update(
            status="completed",
            next_action=None,
            delivery_refs=list(dict.fromkeys([*self.value["delivery_refs"], *refs])),
        )
        self.save()

    def agent(self, link=None, status="active", commits=(), run_ids=None):
        link = link or self.last()["assignments"][-1]
        obj = dict(
            version=1,
            assignment=link["assignment"],
            role=link["role"],
            predecessor=link["predecessor"],
            run_ids=[] if run_ids is None else run_ids,
            status=status,
            updated_at="2026-06-01T12:00:00Z",
            job_summary="bounded fixture assignment",
            working_directory=link["working_directory"],
            steps=[
                dict(
                    id="work",
                    title="bounded work",
                    status="completed" if status == "completed" else "active",
                )
            ],
            checkpoint="fixture confirmed progress",
            next_action=None,
            blocker=None,
            artifacts=[dict(kind="commit", reference=c) for c in commits],
        )
        expected = {key: link[key] for key in checkpoint.IDENTITY}
        return checkpoint.write_checkpoint(
            link["tracker"], expected, obj, initialize=True
        )

    def reconcile(self, link, id="reconcile"):
        self.value["decisions"].append(
            dict(
                id=id,
                kind="reconciliation",
                summary="native owner stopped; actual worktree and reports inspected; replacement authorized",
                evidence=[str(self.report)],
            )
        )
        link["reconciliation"] = id

    def test_happy_implement_verify_deliver(self):
        self.save(True)
        self.worker()
        self.verify()
        self.reserve("deliver", "b" * 40)
        self.finish()
        self.complete()
        read = workflow.read_workflow(self.path, "example")
        self.assertEqual(read["workflow"]["status"], "completed")
        self.assertEqual(
            [s for s, _ in workflow.ordered(self.value["selections"][-1])],
            ["worker", "verify", "deliver"],
        )
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.path.parent.glob("*.tmp-*")), [])

    def test_failed_verify_repairs_fresh_verifiers_history_and_limit(self):
        self.save(True)
        for round in range(3):
            self.worker(str(round + 1) * 40)
            self.verify(str(round + 1) * 40, "fail")
        history = copy.deepcopy(self.value)
        self.assertIsNone(self.value["current_stage"])
        with self.assertRaisesRegex(ValueError, "repair rounds"):
            self.reserve("worker")
        self.assertEqual(
            workflow.read_workflow(self.path, "example")["workflow"], history
        )
        verifiers = [
            a["assignments"][0]["assignment"]
            for s, a in workflow.ordered(history["selections"][-1])
            if s == "verify"
        ]
        self.assertEqual(len(set(verifiers)), 3)

    def test_repair_then_fresh_verify_can_pass_without_losing_failure(self):
        self.save(True)
        self.worker()
        self.verify(verdict="fail")
        failed = copy.deepcopy(self.last())
        self.worker("c" * 40)
        self.verify("c" * 40)
        self.assertEqual(self.stage("verify")["attempts"][0], failed)
        self.assertEqual(self.value["current_stage"], "deliver")
        with self.assertRaises(ValueError):
            self.reserve("deliver", "b" * 40)

    def test_interrupted_dispatch_missing_native_id_cannot_authorize_duplicate(self):
        self.save(True)
        self.reserve("worker")
        self.agent()
        prior = self.path.read_bytes()
        shown = workflow.show(self.path, "example")
        self.assertTrue(
            any("native id not recorded" in x["issue"] for x in shown["issues"])
        )
        self.assertTrue(
            any("outcome unresolved" in x["issue"] for x in shown["issues"])
        )
        replacement = copy.deepcopy(self.last()["assignments"][-1])
        replacement.update(
            assignment="worker-replacement",
            tracker=str(self.path.parent / "agents/worker-replacement.json"),
            predecessor="worker-1",
        )
        self.last()["assignments"].append(replacement)
        with self.assertRaisesRegex(ValueError, "reconciled predecessor"):
            self.save()
        self.assertEqual(self.path.read_bytes(), prior)

    def test_same_assignment_resume_and_reconciled_replacement(self):
        self.save(True)
        self.reserve("worker")
        initial = self.agent(run_ids=["run-one"])
        link = self.last()["assignments"][0]
        expected = {k: link[k] for k in checkpoint.IDENTITY}
        resumed = dict(initial["checkpoint"], run_ids=["run-one", "run-two"])
        checkpoint.write_checkpoint(
            link["tracker"], expected, resumed, initial["revision"]
        )
        self.reconcile(link)
        self.save()
        self.assertEqual(len(self.stage("worker")["attempts"]), 1)
        old = Path(link["tracker"]).read_bytes()
        replacement = dict(
            link,
            assignment="worker-replacement",
            predecessor=link["assignment"],
            tracker=str(self.path.parent / "agents/worker-replacement.json"),
            dispatch="intent",
            reconciliation=None,
        )
        self.last()["assignments"].append(replacement)
        self.save()
        self.agent(replacement)
        self.assertEqual(Path(link["tracker"]).read_bytes(), old)
        self.assertEqual(len(self.last()["assignments"]), 2)

    def test_completed_verifier_with_failed_verdict_is_not_approval(self):
        self.save(True)
        self.worker()
        self.reserve("verify", "b" * 40)
        self.agent(status="completed", commits=["b" * 40])
        shown = workflow.show(self.path, "example")
        self.assertEqual(self.value["current_stage"], "verify")
        self.assertEqual(
            shown["stages"][1]["attempts"][0]["coordinator_status"], "active"
        )
        self.finish(status="failed", verdict="fail")
        self.assertEqual(self.value["current_stage"], "worker")
        with self.assertRaises(ValueError):
            self.reserve("deliver", "b" * 40)

    def test_acceptance_and_candidate_changes_invalidate_approval(self):
        self.save(True)
        self.worker()
        self.verify()
        self.value["decisions"].append(
            dict(
                id="criteria",
                kind="operator",
                summary="changed acceptance",
                evidence=[str(self.brief)],
            )
        )
        self.value["briefs"].append(
            dict(
                reference=str(self.brief),
                acceptance_revision="d" * 64,
                requested_delivery="local-commit",
                decision="criteria",
            )
        )
        self.value["current_stage"] = "verify"
        self.save()
        prior = copy.deepcopy(self.value)
        with self.assertRaises(ValueError):
            self.reserve("deliver", "b" * 40)
        self.value = prior
        self.verify()
        self.worker("c" * 40)
        self.assertEqual(self.value["current_stage"], "verify")
        self.verify("c" * 40)
        self.assertEqual(self.value["current_stage"], "deliver")
        with self.assertRaisesRegex(ValueError, "terminal attempts"):
            self.stage("verify")["attempts"][0]["report"] = str(self.brief)
            self.save()

    def test_changed_acceptance_reopens_completed_delivery(self):
        self.test_happy_implement_verify_deliver()
        self.value["decisions"].append(
            dict(
                id="criteria",
                kind="operator",
                summary="changed acceptance",
                evidence=[str(self.brief)],
            )
        )
        self.value["briefs"].append(
            dict(
                reference=str(self.brief),
                acceptance_revision="d" * 64,
                requested_delivery="local-commit",
                decision="criteria",
            )
        )
        with self.assertRaises(ValueError):
            self.save()
        self.value.update(
            current_stage="verify", status="active", next_action="fresh verification"
        )
        self.save()
        self.verify()
        self.reserve("deliver", "b" * 40)
        self.finish()
        self.complete()

    def test_simulated_commit_before_outcome_is_reconciled_not_repeated(self):
        self.save(True)
        self.reserve("worker")
        repo = self.root / "project"
        repo.mkdir()

        def git(*args):
            return subprocess.check_output(
                ["git", "-C", str(repo), *args], text=True
            ).strip()

        git("init", "-q")
        (repo / "code.txt").write_text("bounded change\n")
        git("add", "code.txt")
        git(
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "-qm",
            "fixture change",
        )
        candidate = git("rev-parse", "HEAD")
        # simulated harness stops after git commit but before any outcome record.
        reread = workflow.read_workflow(self.path, "example")
        self.assertIsNone(
            workflow.ordered(reread["workflow"]["selections"][-1])[-1][1]["outcome"]
        )
        before = git("rev-list", "--count", "HEAD")
        self.reconcile(self.last()["assignments"][0])
        self.finish(commit=candidate)
        self.assertEqual(git("rev-list", "--count", "HEAD"), before)
        self.assertEqual(self.last()["candidate_commit"], candidate)

    def test_simulated_pr_action_before_outcome_does_not_repeat_action(self):
        self.value["briefs"][-1]["requested_delivery"] = "pr"
        self.save(True)
        self.worker()
        self.verify()
        self.reserve("deliver", "b" * 40)
        # a local receipt substitutes for an external pr api; no network or native agent.
        receipt = self.root / "pr-receipt.json"
        receipt.write_text(
            json.dumps(
                dict(
                    url="https://example.test/pr/1",
                    head="b" * 40,
                    required_checks="passed",
                )
            )
        )
        before = receipt.read_bytes()
        shown = workflow.show(self.path, "example")
        self.assertEqual(shown["workflow"]["current_stage"], "deliver")
        self.assertIsNone(self.last()["outcome"])
        actual = json.loads(receipt.read_text())
        self.assertEqual(actual["head"], "b" * 40)
        self.finish(evidence=[str(self.report), str(receipt), actual["url"]])
        self.value.update(
            checkpoint="reconciled existing pr receipt; no repeat publication",
            status="completed",
            next_action=None,
            delivery_refs=[actual["url"]],
        )
        self.save()
        self.assertEqual(receipt.read_bytes(), before)

    def test_research_and_investigation_report_are_not_code_delivery(self):
        for recipe in ("research", "investigate"):
            with self.subTest(recipe=recipe):
                self.path = self.root / recipe / "example/workflow.json"
                self.value["selections"] = [
                    self.selection(recipe, "selection-01", "select")
                ]
                self.value.update(
                    current_stage=workflow.RECIPES[recipe][0],
                    status="active",
                    next_action="reserve",
                    delivery_refs=[],
                )
                self.save(True)
                for stage in workflow.RECIPES[recipe]:
                    self.reserve(stage)
                    self.finish()
                with self.assertRaisesRegex(ValueError, "report is not code delivery"):
                    self.complete()
                self.value["briefs"][-1]["requested_delivery"] = "report"
                with self.assertRaisesRegex(ValueError, "immutable"):
                    self.save()
                self.value["briefs"][-1]["requested_delivery"] = "local-commit"
                self.value.update(
                    status="paused",
                    next_action="ask operator to select implement recipe",
                    delivery_refs=[],
                )
                self.save()

    def test_report_delivery_and_explicit_recipe_change(self):
        self.value.update(current_stage="scout")
        self.value["briefs"][-1]["requested_delivery"] = "report"
        self.value["selections"] = [
            self.selection("research", "selection-01", "select")
        ]
        self.save(True)
        self.reserve("scout")
        with self.assertRaises(ValueError):
            self.value["selections"].append(
                self.selection("investigate", "selection-02", "select")
            )
            self.value["current_stage"] = "triage"
            self.save()
        self.value = workflow.read_workflow(self.path, "example")["workflow"]
        self.finish()
        self.reserve("report")
        self.finish()
        self.complete()
        old = copy.deepcopy(self.value["selections"][0])
        self.value["decisions"].append(
            dict(
                id="change",
                kind="operator",
                summary="operator requests triage recipe",
                evidence=[str(self.brief)],
            )
        )
        self.value["selections"].append(
            self.selection("investigate", "selection-02", "change")
        )
        self.value.update(
            status="active", current_stage="triage", next_action="reserve triage"
        )
        self.save()
        self.assertEqual(self.value["selections"][0], old)
        for stage in workflow.RECIPES["investigate"]:
            self.reserve(stage)
            self.finish()
        self.complete()

    def test_changed_delivery_scope_reopens_approval_and_keeps_prior_scope(self):
        self.test_happy_implement_verify_deliver()
        old = copy.deepcopy(self.value["briefs"][-1])
        self.value["decisions"].append(
            dict(
                id="pr-scope",
                kind="operator",
                summary="operator now authorizes pr delivery",
                evidence=[str(self.brief)],
            )
        )
        self.value["briefs"].append(
            dict(
                reference=str(self.brief),
                acceptance_revision="e" * 64,
                requested_delivery="pr",
                decision="pr-scope",
            )
        )
        with self.assertRaises(ValueError):
            self.save()
        self.value.update(
            status="active",
            current_stage="verify",
            next_action="fresh verification under current delivery scope",
        )
        self.save()
        prior = copy.deepcopy(self.value)
        with self.assertRaises(ValueError):
            self.reserve("deliver", "b" * 40)
        self.value = prior
        self.verify()
        self.reserve("deliver", "b" * 40)
        self.finish()
        self.complete()
        self.assertEqual(self.value["briefs"][0], old)
        self.assertEqual(workflow.current_delivery(self.value), "pr")
        self.assertEqual(len(self.stage("deliver")["attempts"]), 2)

    def test_report_to_code_scope_change_requires_explicit_implement_selection(self):
        self.value["briefs"][0]["requested_delivery"] = "report"
        self.value["selections"] = [
            self.selection("research", "selection-01", "select")
        ]
        self.value["current_stage"] = "scout"
        self.save(True)
        self.reserve("scout")
        self.finish()
        self.reserve("report")
        self.finish()
        self.complete()
        self.value["decisions"].append(
            dict(
                id="code-scope",
                kind="operator",
                summary="operator requests implementation and local delivery",
                evidence=[str(self.brief)],
            )
        )
        self.value["briefs"].append(
            dict(
                reference=str(self.brief),
                acceptance_revision="e" * 64,
                requested_delivery="local-commit",
                decision="code-scope",
            )
        )
        self.value.update(
            current_stage="report",
            status="active",
            next_action="obtain operator recipe selection",
        )
        self.save()
        self.reserve("report")
        self.finish()
        with self.assertRaisesRegex(ValueError, "report is not code delivery"):
            self.complete()
        self.value = workflow.read_workflow(self.path, "example")["workflow"]
        self.value["decisions"].append(
            dict(
                id="implement-selection",
                kind="operator",
                summary="operator selects implement",
                evidence=[str(self.brief)],
            )
        )
        self.value["selections"].append(
            self.selection("implement", "selection-02", "implement-selection")
        )
        self.value.update(
            current_stage="worker",
            status="active",
            next_action="reserve implementation",
        )
        self.save()
        self.worker()
        self.verify()
        self.reserve("deliver", "b" * 40)
        self.finish()
        self.complete()
        self.assertEqual(self.value["selections"][0]["recipe"], "research")
        self.assertEqual(self.value["briefs"][0]["requested_delivery"], "report")

    def test_schema_strict_types_unknown_keys_duplicates_and_order(self):
        workflow.validate(self.value)
        for field in self.value:
            bad = copy.deepcopy(self.value)
            del bad[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                workflow.validate(bad)
        for raw in (
            b'{"version":1,"version":1}',
            b"[]",
            b"null",
            b"NaN",
            b"\xff",
            b"[" * 2000,
            b" " * (workflow.MAX_BYTES + 1),
        ):
            with self.subTest(raw=raw[:20]), self.assertRaises(ValueError):
                workflow.decode(raw)
        invalid = {
            "version": [True, 2, 1.0],
            "task_id": [None, "Upper", []],
            "updated_at": [1, "2026-02-30T12:00:00Z"],
            "decisions": [None, [{}]],
            "briefs": [None, [], [{}]],
            "selections": [None, [], [{}]],
            "status": [[], "done"],
            "next_action": [1, ""],
            "delivery_refs": [None, ["relative"], [None]],
            "blocker": [1, ""],
        }
        for field, values in invalid.items():
            for val in values:
                with self.subTest(field=field, val=val), self.assertRaises(ValueError):
                    workflow.validate(dict(self.value, **{field: val}))
        self.save(True)
        self.reserve("worker")
        good = copy.deepcopy(self.value)
        for key, val in (
            ("order", True),
            ("order", 2),
            ("status", "completed"),
            ("run_ids", []),
            ("acceptance_revision", "short"),
            ("candidate_commit", "abc"),
        ):
            self.value = copy.deepcopy(good)
            self.last()[key] = val
            with self.subTest(key=key), self.assertRaises(ValueError):
                workflow.validate(self.value)

    def test_missing_malformed_foreign_stale_files_preserved(self):
        with self.assertRaises(FileNotFoundError):
            workflow.read_workflow(self.path, "example")
        self.save(True)
        raw = self.path.read_bytes()
        old_revision = self.revision
        self.value["checkpoint"] = "new confirmed progress"
        self.save()
        with self.assertRaisesRegex(ValueError, "stale"):
            workflow.write_workflow(self.path, "example", self.value, old_revision)
        for content in (
            b'{"secret":',
            raw.replace(b'"version": 1', b'"version": 2'),
            raw.replace(b'"task_id": "example"', b'"task_id": "foreign"'),
        ):
            self.path.write_bytes(content)
            for operation in (
                lambda: workflow.read_workflow(self.path, "example"),
                lambda: self.save(),
                lambda: self.save(True),
            ):
                with self.assertRaises(ValueError):
                    operation()
                self.assertEqual(self.path.read_bytes(), content)

    def test_unsafe_paths_symlinks_and_types(self):
        for path in (
            Path("example/workflow.json"),
            self.root / "example/../example/workflow.json",
            self.root / "foreign/workflow.json",
            self.root / "example/wrong.json",
        ):
            with self.subTest(path=str(path)), self.assertRaises((ValueError, OSError)):
                workflow.write_workflow(path, "example", self.value, initialize=True)
        target = self.root / "target"
        target.write_text("preserve\n")
        self.path.symlink_to(target)
        for operation in (
            lambda: self.save(True),
            lambda: workflow.read_workflow(self.path, "example"),
            lambda: self.save(),
        ):
            with self.assertRaises((ValueError, OSError)):
                operation()
        self.path.unlink()
        for kind in ("fifo", "directory"):
            if kind == "fifo":
                os.mkfifo(self.path)
            else:
                self.path.mkdir()
            for operation in (
                lambda: self.save(True),
                lambda: workflow.read_workflow(self.path, "example"),
                lambda: self.save(),
            ):
                with self.assertRaises((ValueError, OSError)):
                    operation()
            self.path.unlink() if kind == "fifo" else self.path.rmdir()
        alias = self.root / "alias"
        alias.symlink_to(self.path.parent.parent)
        with self.assertRaises(OSError):
            workflow.write_workflow(
                alias / "example/workflow.json", "example", self.value, initialize=True
            )
        self.assertEqual(target.read_text(), "preserve\n")

    def test_show_missing_malformed_foreign_stale_discrepancies_read_only(self):
        self.save(True)
        self.worker()
        self.reserve("verify", "b" * 40)
        link = self.last()["assignments"][0]
        before = self.path.read_bytes()
        shown = workflow.show(self.path, "example")
        self.assertTrue(any("checkpoint" in x["issue"] for x in shown["issues"]))
        self.agent(status="completed", commits=["c" * 40])
        path = Path(link["tracker"])
        valid = path.read_bytes()
        (self.brief).unlink()
        shown = workflow.show(self.path, "example")
        self.assertTrue(
            any("differs from candidate" in x["issue"] for x in shown["issues"])
        )
        self.assertTrue(
            any("not stage approval" in x["issue"] for x in shown["issues"])
        )
        self.assertTrue(any(x["reference"] == str(self.brief) for x in shown["issues"]))
        for raw in (b"{", valid.replace(b'"role": "verify"', b'"role": "worker"')):
            path.write_bytes(raw)
            workflow.show(self.path, "example")
            self.assertEqual(path.read_bytes(), raw)
        path.unlink()
        path.symlink_to(self.report)
        workflow.show(self.path, "example")
        self.assertTrue(path.is_symlink())
        self.assertEqual(self.path.read_bytes(), before)

    def test_publication_interruption_stale_recheck_and_owned_temp_cleanup(self):
        self.save(True)
        before = self.path.read_bytes()
        self.value["checkpoint"] = "new progress"
        for error in (OSError("replace failed"), KeyboardInterrupt()):
            with patch.object(
                workflow.os, "replace", side_effect=error
            ), self.assertRaises(type(error)):
                self.save()
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(list(self.path.parent.glob("*.tmp-*")), [])
        real_read = workflow.read_bytes

        def race(directory, name):
            if ".tmp-" in name:
                self.path.write_bytes(before + b" ")
            return real_read(directory, name)

        with patch.object(
            workflow, "read_bytes", side_effect=race
        ), self.assertRaisesRegex(ValueError, "stale"):
            self.save()
        self.assertEqual(self.path.read_bytes(), before + b" ")

    def test_docs_example_and_all_nested_fields_are_strict(self):
        docs = (ROOT / "docs/workflows.md").read_text()
        workflow.validate(json.loads(docs.split("```json\n", 1)[1].split("```", 1)[0]))
        self.save(True)
        self.reserve("worker")
        good = copy.deepcopy(self.value)
        getters = [
            lambda v: v["briefs"][0],
            lambda v: v["decisions"][0],
            lambda v: v["selections"][0],
            lambda v: v["selections"][0]["stages"][0],
            lambda v: v["selections"][0]["stages"][0]["attempts"][0],
            lambda v: v["selections"][0]["stages"][0]["attempts"][0]["assignments"][0],
        ]
        for getter in getters:
            for key in [*getter(good), "unknown"]:
                bad = copy.deepcopy(good)
                obj = getter(bad)
                if key == "unknown":
                    obj[key] = "unexpected"
                else:
                    del obj[key]
                with self.subTest(field=key), self.assertRaises(ValueError):
                    workflow.validate(bad)
        encoded = workflow.encode(good)
        with self.assertRaisesRegex(ValueError, "duplicate json key"):
            workflow.decode(
                encoded.replace(
                    b'"dispatch": "intent"',
                    b'"dispatch": "intent", "dispatch": "intent"',
                )
            )

    def test_init_exclusive_publication_preserves_intervening_file(self):
        real_link = os.link

        def race(*args, **kwargs):
            self.path.write_text("foreign intervening file")
            return real_link(*args, **kwargs)

        with patch.object(workflow.os, "link", side_effect=race), self.assertRaises(
            FileExistsError
        ):
            self.save(True)
        self.assertEqual(self.path.read_text(), "foreign intervening file")
        self.assertEqual(list(self.path.parent.glob("*.tmp-*")), [])

    def test_attempt_intent_required_before_action_and_terminal_approval(self):
        self.save(True)
        prior = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "intent before"):
            # a terminal result cannot be smuggled into a reservation update.
            with patch.object(self, "save"):
                self.reserve("worker")
                self.finish(commit="b" * 40)
            self.save()
        self.assertEqual(self.path.read_bytes(), prior)
        self.value = workflow.read_workflow(self.path, "example")["workflow"]
        self.reserve("worker")
        saved = copy.deepcopy(self.value)
        self.last().update(
            status="passed",
            candidate_commit="b" * 40,
            outcome="agent completed",
            evidence=[str(self.report)],
            decision="select",
        )
        self.value["current_stage"] = "verify"
        with self.assertRaisesRegex(ValueError, "coordinator decision"):
            self.save()
        self.value = saved
        self.last()["status"] = "blocked"
        with self.assertRaisesRegex(ValueError, "workflow blocker"):
            self.save()
        self.value.update(status="blocked", blocker="missing required dependency")
        self.save()
        self.assertEqual(self.value["current_stage"], "worker")

    def test_delivery_needs_kind_specific_reference(self):
        self.save(True)
        self.worker()
        self.verify()
        self.reserve("deliver", "b" * 40)
        self.finish()
        good = copy.deepcopy(self.value)
        self.value.update(
            status="completed", next_action=None, delivery_refs=[str(self.report)]
        )
        with self.assertRaisesRegex(ValueError, "exact candidate reference"):
            self.save()
        self.value = good
        self.complete()

    def test_unresolved_coordinator_intent_cannot_be_archived_by_recipe_change(self):
        self.save(True)
        self.worker()
        self.verify()
        self.reserve("deliver", "b" * 40)
        self.value["decisions"].append(
            dict(
                id="change",
                kind="operator",
                summary="operator selects investigate",
                evidence=[str(self.brief)],
            )
        )
        self.value["selections"].append(
            self.selection("investigate", "selection-02", "change")
        )
        self.value["current_stage"] = "triage"
        with self.assertRaisesRegex(ValueError, "unresolved ownership"):
            self.save()

    def cli(self, command, *extra, raw=None):
        return subprocess.run(
            [
                sys.executable,
                str(HELPER),
                command,
                str(self.path),
                "--task-id",
                "example",
                *extra,
            ],
            cwd=ROOT,
            input=raw,
            capture_output=True,
            timeout=10,
        )

    def test_cli_round_trip_errors_and_no_external_mutations_or_launch(self):
        backlog = self.root / "data/backlog.md"
        backlog.write_text("tasks-axi authority\n")
        result = self.cli("init", "--proposal", "-", raw=workflow.encode(self.value))
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.cli("read")
        envelope = json.loads(result.stdout)
        self.assertEqual(envelope["workflow"]["task_id"], "example")
        self.value["checkpoint"] = "read completed"
        result = self.cli(
            "update",
            "--proposal",
            "-",
            "--revision",
            envelope["revision"],
            raw=workflow.encode(self.value),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        before = self.path.read_bytes()
        result = self.cli("show")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(backlog.read_text(), "tasks-axi authority\n")
        result = self.cli(
            "update",
            "--proposal",
            "-",
            "--revision",
            "0" * 64,
            raw=b'{"secret-sensitive":',
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(b"secret-sensitive", result.stderr)
        self.assertEqual(json.loads(result.stderr)["operation"], "read-proposal")
        for command in ("launch", "resume", "reset", "run"):
            self.assertEqual(self.cli(command).returncode, 2)
        source = HELPER.read_text()
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("bin/tasks", source)

    def test_portable_and_specialty_workflow_contracts(self):
        for role in ("worker", "verify", "scout", "triage"):
            template = (ROOT / "templates" / (role + ".md")).read_text()
            for field in (
                "workflow_path",
                "workflow_recipe",
                "workflow_stage",
                "workflow_attempt",
            ):
                self.assertIn("{{" + field + "}}", template)
            self.assertIn("coordinator alone writes the workflow manifest", template)
        for path in (
            "AGENTS.md",
            "README.md",
            "docs/specialty.md",
            "docs/modes/specialty.md",
        ):
            self.assertIn("workflow", (ROOT / path).read_text())


if __name__ == "__main__":
    unittest.main()
