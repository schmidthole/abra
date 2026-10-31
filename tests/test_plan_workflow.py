"""fixed planning replay and portable prompt contracts, not live agent trials."""

import copy
import hashlib
import re
import unittest

import test_workflow as fixtures

workflow = fixtures.workflow
ROOT = fixtures.ROOT


class PlanWorkflowTests(unittest.TestCase):
    setUp = fixtures.WorkflowTests.setUp
    selection = fixtures.WorkflowTests.selection
    save = fixtures.WorkflowTests.save
    stage = fixtures.WorkflowTests.stage
    last = fixtures.WorkflowTests.last
    agent = fixtures.WorkflowTests.agent
    reconcile = fixtures.WorkflowTests.reconcile

    def start(self, source_checks="applicable"):
        self.value["selections"] = [self.selection("plan", "selection-01", "select")]
        self.value["briefs"][0]["requested_delivery"] = "report"
        self.value["current_stage"] = "refine"
        self.source_checks = source_checks
        self.save(True)

    def package(self, review=True):
        package = dict(
            repositories=(
                [dict(reference=str(self.root), commit="b" * 40)]
                if self.source_checks == "applicable"
                else []
            ),
            source_checks=self.source_checks,
        )
        for name in workflow.DOCUMENTS:
            path = self.path.parent / (name + ".md")
            if not path.exists():
                path.write_text(name + " initial content\n")
            package[name] = (
                dict(
                    reference=str(path),
                    revision=hashlib.sha256(path.read_bytes()).hexdigest(),
                )
                if name != "review" or review
                else None
            )
        return package

    def reserve(self, stage, package=None):
        entries = workflow.ordered(self.value["selections"][-1])
        if package is None and entries:
            package = copy.deepcopy(entries[-1][1]["result_package"])
        number = len(entries) + 1
        id = stage + "-" + str(number)
        links = []
        if stage != "deliver":
            links = [
                dict(
                    assignment=id,
                    role="scout",
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
            intent="authorized " + stage,
            assignments=links,
            acceptance_revision=workflow.current_acceptance(self.value),
            candidate_commit=None,
            verdict=None,
            report=None,
            outcome=None,
            evidence=[],
            decision=None,
            package=package,
            result_package=None,
        )
        self.stage(stage)["attempts"].append(attempt)
        self.value.update(
            current_stage=stage, status="active", next_action="perform " + stage
        )
        self.save()
        return self.last()

    def finish(self, result=None, verdict=None, status="passed"):
        stage, attempt = workflow.ordered(self.value["selections"][-1])[-1]
        for link in attempt["assignments"]:
            link["dispatch"] = "confirmed"
        if result is None and status == "passed":
            result = self.package(review=stage != "refine")
            if stage == "refine" and attempt["package"] is not None:
                for name in ("review", "repositories", "source_checks"):
                    result[name] = copy.deepcopy(attempt["package"][name])
        attempt.update(
            status=status,
            result_package=result,
            verdict=verdict,
            report=str(self.report),
            outcome="coordinator checked report and exact bytes",
            evidence=[str(self.report)]
            + (
                [result[n]["reference"] for n in workflow.DOCUMENTS if result[n]]
                if result
                else []
            ),
            decision="decision-" + attempt["id"],
        )
        self.value["decisions"].append(
            dict(
                id=attempt["decision"],
                kind="coordinator",
                summary="confirmed actual planning outcome",
                evidence=[str(self.report)],
            )
        )
        self.value["current_stage"] = workflow.progress(
            self.value["selections"][-1], workflow.current_acceptance(self.value)
        )
        if self.value["current_stage"] is None:
            self.value.update(
                status="paused", next_action="operator review or confirmed delivery"
            )
        self.save()

    def grounded(self):
        self.reserve("refine")
        self.finish()
        self.reserve("ground")
        self.finish()

    def ready(self):
        self.grounded()
        self.reserve("validate")
        self.finish(verdict="ready")

    def test_report_flow_and_no_codebase(self):
        for mode in ("applicable", "not-applicable"):
            with self.subTest(mode=mode):
                if self.revision is not None:
                    self.setUp()
                self.start(mode)
                self.ready()
                self.reserve("deliver")
                self.finish(result=copy.deepcopy(self.last()["package"]))
                self.value.update(
                    status="completed",
                    next_action=None,
                    delivery_refs=[
                        str(self.report),
                        *[
                            self.last()["result_package"][n]["reference"]
                            for n in workflow.DOCUMENTS
                        ],
                    ],
                )
                self.save()
                self.assertEqual(
                    workflow.read_workflow(self.path, "example")["workflow"]["status"],
                    "completed",
                )
                self.assertIsNone(self.last()["candidate_commit"])

    def test_review_gains_findings_without_circular_input_identity(self):
        self.start()
        self.grounded()
        grounded = copy.deepcopy(self.last()["result_package"])
        self.reserve("validate")
        review = self.path.parent / "review.md"
        review.write_text(review.read_text() + "validation: ready; no blocking gaps\n")
        self.finish(verdict="ready")
        self.assertEqual(self.last()["package"], grounded)
        self.assertNotEqual(self.last()["result_package"]["review"], grounded["review"])
        self.reserve("deliver")
        self.finish(result=copy.deepcopy(self.last()["package"]))

    def test_legacy_attempts_remain_unchanged_and_reject_plan_fields(self):
        trial = fixtures.WorkflowTests()
        trial.setUp()
        self.addCleanup(trial.doCleanups)
        trial.save(True)
        trial.worker()
        self.assertEqual(set(trial.last()), workflow.ATTEMPT_FIELDS)
        self.assertEqual(workflow.decode(workflow.encode(trial.value)), trial.value)
        trial.last().update(package=None, result_package=None)
        with self.assertRaisesRegex(ValueError, "invalid attempt fields"):
            trial.save()

    def test_input_package_is_immutable_even_on_grounding_restart(self):
        self.start()
        self.grounded()
        self.reserve("ground", self.package())
        self.last()["package"]["repositories"][0]["commit"] = "e" * 40
        with self.assertRaisesRegex(ValueError, "attempt identity is immutable"):
            self.save()

    def test_changed_product_input_must_return_to_refinement(self):
        self.start()
        self.grounded()
        changed = self.package()
        changed["slices"]["revision"] = "e" * 64
        with self.assertRaisesRegex(ValueError, "require refinement"):
            self.reserve("ground", changed)

    def test_third_ready_validation_can_deliver_but_changed_acceptance_cannot_restart(
        self,
    ):
        self.start()
        self.grounded()
        for number in range(3):
            self.reserve("validate")
            self.finish(
                verdict="ready" if number == 2 else "needs revision",
                status="passed" if number == 2 else "failed",
            )
            if number < 2:
                self.reserve("ground", self.package())
                self.finish()
        before = copy.deepcopy(self.value)
        self.reserve("deliver")
        self.finish(result=copy.deepcopy(self.last()["package"]))
        self.value = before
        self.value["briefs"].append(
            {
                **self.value["briefs"][0],
                "acceptance_revision": "e" * 64,
                "decision": "change",
            }
        )
        self.value["decisions"].append(
            dict(
                id="change",
                kind="operator",
                summary="changed acceptance",
                evidence=[str(self.brief)],
            )
        )
        self.assertIsNone(workflow.progress(self.value["selections"][-1], "e" * 64))
        with self.assertRaisesRegex(ValueError, "two repair rounds"):
            self.reserve("refine", self.package())

    def test_task_local_document_paths_and_complete_evidence_are_required(self):
        self.start()
        self.reserve("refine")
        wrong = self.package(review=False)
        wrong["spec"]["reference"] = str(self.root / "spec.md")
        with self.assertRaisesRegex(ValueError, "belong to this task"):
            self.finish(result=wrong)
        self.value = workflow.read_workflow(self.path, "example")["workflow"]
        self.finish()
        self.reserve("ground")
        self.finish()
        self.last()["evidence"].remove(str(self.path.parent / "review.md"))
        with self.assertRaisesRegex(ValueError, "confirmed evidence"):
            self.save()

    def test_stale_delivery_rejected_for_each_document_and_repository(self):
        self.start()
        self.ready()
        original = copy.deepcopy(self.value)
        for name in (*workflow.DOCUMENTS, "repositories", "source_checks"):
            with self.subTest(name=name):
                self.value = copy.deepcopy(original)
                stale = copy.deepcopy(self.last()["result_package"])
                if name in workflow.DOCUMENTS:
                    stale[name]["revision"] = "e" * 64
                elif name == "repositories":
                    stale[name][0]["commit"] = "e" * 40
                else:
                    stale[name] = "unavailable"
                with self.assertRaisesRegex(ValueError, "stale"):
                    self.reserve("deliver", stale)

    def test_repairs_route_to_refine_or_ground_with_fresh_validation(self):
        self.start()
        self.grounded()
        self.reserve("validate")
        old_assignment = self.last()["assignments"][0]["assignment"]
        self.finish(status="failed", verdict="needs revision")
        self.assertEqual(self.value["current_stage"], "refine")
        self.reserve("ground", self.package())
        self.finish()
        self.reserve("validate")
        self.assertNotEqual(self.last()["assignments"][0]["assignment"], old_assignment)
        self.finish(status="failed", verdict="needs revision")
        self.reserve("refine", self.package())
        changed = self.package()
        changed["spec"]["revision"] = "e" * 64
        self.finish(result=changed)
        self.reserve("ground")
        self.finish(result={**changed, "review": self.package()["review"]})
        self.reserve("validate")
        self.finish(status="failed", verdict="needs revision")
        self.assertIsNone(self.value["current_stage"])
        with self.assertRaisesRegex(ValueError, "two repair rounds"):
            self.reserve("refine", self.package())

    def test_success_and_revision_do_not_reset_validation_budget(self):
        self.start()
        self.ready()
        for _ in range(2):
            self.reserve("ground", self.package())
            self.finish()
            self.reserve("validate")
            self.finish(verdict="ready")
        self.assertEqual(self.value["current_stage"], "deliver")
        with self.assertRaisesRegex(ValueError, "two repair rounds"):
            self.reserve("ground", self.package())

    def test_acceptance_change_invalidates_and_requires_refinement(self):
        self.start()
        self.ready()
        self.value["briefs"].append(
            {
                **self.value["briefs"][0],
                "acceptance_revision": "c" * 64,
                "decision": "change",
            }
        )
        self.value["decisions"].append(
            dict(
                id="change",
                kind="operator",
                summary="changed product acceptance",
                evidence=[str(self.brief)],
            )
        )
        self.value["current_stage"] = "refine"
        self.save()
        with self.assertRaisesRegex(ValueError, "planning approval invalidated"):
            self.reserve("deliver")
        self.value["selections"][-1]["stages"][-1]["attempts"].pop()
        with self.assertRaisesRegex(ValueError, "changed acceptance"):
            self.reserve("ground", self.package())

    def test_unknown_evidence_and_blocked_verdict_never_approve(self):
        self.start("unavailable")
        self.grounded()
        self.reserve("validate")
        self.agent(status="completed")
        self.last().update(status="blocked", verdict="blocked", report=str(self.report))
        self.value.update(status="blocked", blocker="source access unavailable")
        self.save()
        self.assertEqual(self.value["current_stage"], "validate")
        self.assertIn(
            "agent completed is not stage approval",
            str(workflow.show(self.path, "example")),
        )
        self.finish(status="failed", verdict="blocked")
        with self.assertRaisesRegex(ValueError, "operator intervention"):
            self.reserve("refine", self.package())

    def test_changed_grounding_requires_revalidation(self):
        self.start()
        self.ready()
        changed = self.package()
        changed["repositories"][0]["commit"] = "c" * 40
        self.reserve("ground", changed)
        self.finish(result=changed)
        self.assertEqual(self.value["current_stage"], "validate")
        with self.assertRaisesRegex(ValueError, "recipe order"):
            self.reserve("deliver", changed)

    def test_ground_and_validate_cannot_change_scope_or_pins(self):
        self.start()
        self.grounded()
        self.reserve("validate")
        original = copy.deepcopy(self.value)
        for name in ("spec", "repositories"):
            self.value = copy.deepcopy(original)
            changed = self.package()
            if name == "spec":
                changed[name]["revision"] = "c" * 64
            else:
                changed[name][0]["commit"] = "c" * 40
            with self.assertRaisesRegex(ValueError, "cannot change"):
                self.finish(result=changed, verdict="ready")

    def test_input_identity_and_terminal_history_are_immutable(self):
        self.start()
        self.grounded()
        self.reserve("validate")
        self.last()["package"]["review"]["revision"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "stale"):
            self.save()
        self.value = workflow.read_workflow(self.path, "example")["workflow"]
        self.finish(verdict="ready")
        self.last()["result_package"]["review"]["revision"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "terminal attempts"):
            self.save()

    def test_refinement_preserves_review_and_grounding_identity(self):
        self.start()
        self.grounded()
        self.reserve("refine", self.package())
        original = copy.deepcopy(self.value)
        for name in ("review", "repositories"):
            self.value = copy.deepcopy(original)
            changed = self.package()
            if name == "review":
                changed[name]["revision"] = "e" * 64
            else:
                changed[name][0]["commit"] = "e" * 40
            with self.assertRaisesRegex(ValueError, "refinement cannot change"):
                self.finish(result=changed)

    def test_scout_role_reuse_does_not_merge_stage_assignment_boundaries(self):
        self.start()
        self.grounded()
        self.reserve("validate")
        predecessor = self.stage("refine")["attempts"][0]["assignments"][0]
        self.reconcile(predecessor)
        self.last()["assignments"][0]["predecessor"] = predecessor["assignment"]
        with self.assertRaisesRegex(ValueError, "invalid predecessor link"):
            self.save()

    def test_stage_roles_and_strict_package_fields(self):
        self.start()
        self.reserve("refine")
        self.last()["assignments"][0]["role"] = "worker"
        with self.assertRaisesRegex(ValueError, "role mismatch"):
            self.save()
        self.last()["assignments"][0]["role"] = "scout"
        self.last()["candidate_commit"] = "b" * 40
        with self.assertRaisesRegex(ValueError, "not candidate commits"):
            self.save()
        for mutate in (
            lambda p: p.update(extra="field"),
            lambda p: p["spec"].update(revision="not-a-hash"),
            lambda p: p.update(source_checks="not-applicable"),
            lambda p: p["repositories"][0].update(commit=None),
        ):
            package = self.package()
            mutate(package)
            with self.assertRaises(ValueError):
                workflow.validate_package(package)

    def test_delivery_requires_all_reports_and_no_publication(self):
        self.start()
        self.ready()
        self.reserve("deliver")
        self.finish(result=copy.deepcopy(self.last()["package"]))
        self.value.update(
            status="completed", next_action=None, delivery_refs=[str(self.report)]
        )
        with self.assertRaisesRegex(ValueError, "all three"):
            self.save()
        self.value["briefs"][0]["requested_delivery"] = "pr"
        with self.assertRaisesRegex(ValueError, "report delivery only"):
            self.save()


class PlanTemplateTests(unittest.TestCase):
    def test_portable_briefs_share_tracking_and_workflow_contract(self):
        scout = (ROOT / "templates/scout.md").read_text()
        shared = scout.split("## coordinator workflow context\n")[1].split(
            "## assignment\n"
        )[0]
        for stage in ("refine", "ground", "validate"):
            text = (ROOT / "templates" / ("plan-" + stage + ".md")).read_text()
            self.assertIn(shared, text)
            self.assertIn("checkpoint role: scout", text)
            self.assertNotIn("{{candidate_commit}}", text)
            fields = re.findall(r"\{\{([a-z_]+)\}\}", text)
            self.assertEqual(
                set(fields),
                {
                    "task_id",
                    "request",
                    "acceptance",
                    "constraints",
                    "worktree",
                    "package",
                    "feedback",
                    "report_paths",
                    "workflow_path",
                    "workflow_recipe",
                    "workflow_stage",
                    "workflow_attempt",
                    "assignment",
                    "tracker_path",
                    "checkpoint_helper",
                    "predecessor",
                    "run_ids",
                    "tracking_instructions",
                },
            )
            self.assertEqual(len(fields), len(set(fields)))
            for name in fields:
                text = text.replace("{{" + name + "}}", "supplied " + name)
            self.assertNotIn("{{", text)
            self.assertIn("do not modify project files", " ".join(text.split()))
            self.assertIn("material product or scope decisions", text)

    def test_docs_and_stage_specific_contracts(self):
        docs = (ROOT / "docs/planning.md").read_text()
        for phrase in (
            "spec.md",
            "slices.md",
            "review.md",
            "not how",
            "two repair rounds",
            "not live agent trials",
            "candidate_commit",
            "byte",
            "operator",
            "not product approval",
        ):
            self.assertIn(phrase, " ".join(docs.split()))
        ground = (ROOT / "templates/plan-ground.md").read_text()
        for phrase in (
            "supported / contradicted / proposed / unknown",
            "exact repository commits",
            "production",
            "not applicable",
        ):
            self.assertIn(phrase, ground)
        validate = (ROOT / "templates/plan-validate.md").read_text()
        for phrase in (
            "fresh",
            "bidirectional",
            "ready / needs revision / blocked",
            "security/privacy",
            "accessibility",
            "feedback destination",
        ):
            self.assertIn(phrase, validate)
        linear = (ROOT / "docs/modes/linear.md").read_text()
        self.assertIn("does not inherit pr", linear)
        self.assertIn("blocked-status reporting is not publication", linear)
        for path in (
            "AGENTS.md",
            "README.md",
            "docs/workflows.md",
            "docs/specialty.md",
        ):
            self.assertIn("plan", (ROOT / path).read_text())


if __name__ == "__main__":
    unittest.main()
