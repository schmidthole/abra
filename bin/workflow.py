#!/usr/bin/env python3
"""persist coordinator-selected workflows; never launch agents or mutate tasks-axi."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checkpoint
from durable_files import MAX_BYTES, parent_directory, read_bytes, revision, require

RECIPES = {
    "implement": ("worker", "verify", "deliver"),
    "investigate": ("triage", "review", "report"),
    "research": ("scout", "report"),
}
AGENT_STAGES = {"worker", "verify", "triage", "scout"}
COMMIT = r"[0-9a-f]{40}|[0-9a-f]{64}"
HASH = r"[0-9a-f]{64}"
FIELDS = {
    "version",
    "task_id",
    "updated_at",
    "briefs",
    "selections",
    "decisions",
    "status",
    "current_stage",
    "checkpoint",
    "next_action",
    "blocker",
    "delivery_refs",
}
ATTEMPT_FIELDS = {
    "id",
    "order",
    "status",
    "intent",
    "assignments",
    "acceptance_revision",
    "candidate_commit",
    "verdict",
    "report",
    "outcome",
    "evidence",
    "decision",
}
LINK_FIELDS = {
    "assignment",
    "role",
    "predecessor",
    "tracker",
    "brief",
    "working_directory",
    "dispatch",
    "reconciliation",
}


def fields(value, expected, name):
    require(
        type(value) is dict and set(value) == set(expected),
        "invalid " + name + " fields",
    )


def path_string(value):
    return checkpoint.absolute(value) and ".." not in Path(value).parts


def reference(value):
    if not checkpoint.text(value):
        return False
    if checkpoint.matches(COMMIT, value):
        return True
    if value.startswith("/"):
        return path_string(value)
    try:
        url = urlsplit(value)
        return bool(url.scheme and (url.netloc or url.path))
    except ValueError:
        return False


def references(value):
    require(
        type(value) is list and all(reference(x) for x in value), "invalid references"
    )
    require(len(value) == len(set(value)), "duplicate references")


def decision_ref(value, decisions, kinds):
    require(
        checkpoint.text(value)
        and value in decisions
        and decisions[value]["kind"] in kinds,
        "missing or inappropriate coordinator decision",
    )


def current_acceptance(value):
    return value["briefs"][-1]["acceptance_revision"]


def current_delivery(value):
    return value["briefs"][-1]["requested_delivery"]


def ordered(selection):
    return sorted(
        (
            (stage["id"], attempt)
            for stage in selection["stages"]
            for attempt in stage["attempts"]
        ),
        key=lambda item: item[1]["order"],
    )


def progress(selection, acceptance):
    """replay the fixed recipe only; assignments never determine success."""
    name = selection["recipe"]
    stages = RECIPES[name]
    expected, candidate, approval, failures = stages[0], None, None, 0
    report_revision = None
    entries = ordered(selection)
    for index, (stage, attempt) in enumerate(entries):
        # a new worker may deliberately invalidate a prior candidate/approval.
        restart = (
            name == "implement"
            and stage == "worker"
            and expected in ("verify", "deliver", None)
            and candidate is not None
        )
        reverify = (
            name == "implement"
            and stage == "verify"
            and expected in ("deliver", None)
            and approval != attempt["acceptance_revision"]
        )
        require(
            stage == expected
            or restart
            or reverify
            or (
                name != "implement"
                and stage == "report"
                and expected is None
                and report_revision != attempt["acceptance_revision"]
            ),
            "attempt violates recipe order",
        )
        require(failures < 3, "two repair rounds exhausted")
        if stage == "worker":
            approval = None
        if stage in ("verify", "deliver"):
            require(
                candidate is not None and attempt["candidate_commit"] == candidate,
                "candidate must match the latest passed worker",
            )
        if stage == "deliver":
            require(
                approval == attempt["acceptance_revision"],
                "verification approval invalidated",
            )
        if attempt["status"] in ("active", "blocked"):
            require(index == len(entries) - 1, "unresolved attempt must be last")
            return stage
        if attempt["status"] == "failed":
            if stage == "verify":
                failures += 1
                expected = "worker" if failures < 3 else None
            else:
                expected = stage
            continue
        if stage == "worker":
            candidate = attempt["candidate_commit"]
        if stage == "verify":
            approval = attempt["acceptance_revision"]
        if stage == "report":
            report_revision = attempt["acceptance_revision"]
        expected = stages[stages.index(stage) + 1] if stage != stages[-1] else None
    if (
        name == "implement"
        and expected in ("deliver", None)
        and approval is not None
        and approval != acceptance
    ):
        return "verify"
    if name != "implement" and expected is None and report_revision != acceptance:
        return "report"
    return expected


def validate(value):
    fields(value, FIELDS, "workflow")
    require(
        type(value["version"]) is int and value["version"] == 1, "unsupported version"
    )
    require(checkpoint.matches(checkpoint.SLUG, value["task_id"]), "invalid task id")
    require(
        checkpoint.matches(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
            value["updated_at"],
        ),
        "invalid timestamp",
    )
    try:
        datetime.strptime(value["updated_at"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ValueError("invalid timestamp") from None
    decisions = {}
    require(type(value["decisions"]) is list, "invalid decisions")
    for decision in value["decisions"]:
        fields(decision, ("id", "kind", "summary", "evidence"), "decision")
        require(
            checkpoint.matches(checkpoint.SLUG, decision["id"])
            and decision["id"] not in decisions,
            "invalid or duplicate decision id",
        )
        require(
            decision["kind"] in ("operator", "coordinator", "reconciliation"),
            "invalid decision kind",
        )
        require(checkpoint.text(decision["summary"]), "invalid decision summary")
        references(decision["evidence"])
        require(bool(decision["evidence"]), "decision evidence required")
        decisions[decision["id"]] = decision
    require(
        type(value["briefs"]) is list and bool(value["briefs"]),
        "saved full brief required",
    )
    for brief in value["briefs"]:
        fields(
            brief,
            ("reference", "acceptance_revision", "requested_delivery", "decision"),
            "brief",
        )
        require(
            path_string(brief["reference"]),
            "brief must be an absolute path without traversal",
        )
        require(
            checkpoint.matches(HASH, brief["acceptance_revision"]),
            "invalid acceptance revision",
        )
        decision_ref(brief["decision"], decisions, ("operator",))
    acceptance = current_acceptance(value)
    revisions = [b["acceptance_revision"] for b in value["briefs"]]
    require(len(revisions) == len(set(revisions)), "brief revisions must be unique")
    for brief in value["briefs"]:
        require(
            brief["requested_delivery"] in ("report", "local-commit", "pr", "merge"),
            "invalid requested delivery",
        )
    selections = value["selections"]
    require(type(selections) is list and bool(selections), "recipe selection required")
    selection_ids, attempt_ids, assignments = set(), set(), {}
    terminal_decisions = set()
    for selection in selections:
        fields(
            selection,
            ("id", "recipe", "version", "rationale", "decision", "stages"),
            "selection",
        )
        require(
            checkpoint.matches(checkpoint.SLUG, selection["id"])
            and selection["id"] not in selection_ids,
            "invalid or duplicate selection id",
        )
        selection_ids.add(selection["id"])
        require(
            type(selection["recipe"]) is str and selection["recipe"] in RECIPES,
            "unknown recipe",
        )
        require(
            type(selection["version"]) is int and selection["version"] == 1,
            "unsupported recipe version",
        )
        require(checkpoint.text(selection["rationale"]), "selection rationale required")
        decision_ref(selection["decision"], decisions, ("operator",))
        require(type(selection["stages"]) is list, "invalid stages")
        stages = selection["stages"]
        require(
            all(type(s) is dict and set(s) == {"id", "attempts"} for s in stages),
            "invalid stage fields",
        )
        require(
            tuple(s["id"] for s in stages) == RECIPES[selection["recipe"]],
            "stages must match fixed recipe",
        )
        for stage in stages:
            require(type(stage["attempts"]) is list, "invalid attempts")
            orders = []
            for attempt in stage["attempts"]:
                fields(attempt, ATTEMPT_FIELDS, "attempt")
                require(
                    checkpoint.matches(checkpoint.SLUG, attempt["id"])
                    and attempt["id"] not in attempt_ids,
                    "invalid or duplicate attempt id",
                )
                attempt_ids.add(attempt["id"])
                require(
                    type(attempt["order"]) is int and attempt["order"] > 0,
                    "invalid attempt order",
                )
                orders.append(attempt["order"])
                require(
                    attempt["status"] in ("active", "blocked", "passed", "failed"),
                    "invalid attempt status",
                )
                require(checkpoint.text(attempt["intent"]), "attempt intent required")
                require(
                    checkpoint.matches(HASH, attempt["acceptance_revision"])
                    and any(
                        b["acceptance_revision"] == attempt["acceptance_revision"]
                        for b in value["briefs"]
                    ),
                    "unknown acceptance revision",
                )
                require(
                    attempt["candidate_commit"] is None
                    or checkpoint.matches(COMMIT, attempt["candidate_commit"]),
                    "invalid candidate commit",
                )
                require(
                    attempt["verdict"] is None
                    or attempt["verdict"] in ("pass", "fail", "blocked"),
                    "invalid verdict",
                )
                require(
                    attempt["report"] is None
                    or (
                        reference(attempt["report"])
                        and not checkpoint.matches(COMMIT, attempt["report"])
                    ),
                    "invalid report",
                )
                require(
                    attempt["outcome"] is None or checkpoint.text(attempt["outcome"]),
                    "invalid outcome",
                )
                references(attempt["evidence"])
                require(type(attempt["assignments"]) is list, "invalid assignments")
                links = attempt["assignments"]
                require(
                    bool(links) == (stage["id"] in AGENT_STAGES),
                    "assignment role does not match stage",
                )
                previous = None
                for link in links:
                    fields(link, LINK_FIELDS, "assignment link")
                    assignment = link["assignment"]
                    require(
                        checkpoint.matches(checkpoint.SLUG, assignment)
                        and assignment not in assignments,
                        "invalid or reused assignment",
                    )
                    require(link["role"] == stage["id"], "assignment role mismatch")
                    require(
                        path_string(link["tracker"])
                        and Path(link["tracker"]).name == assignment + ".json",
                        "invalid tracker path",
                    )
                    require(path_string(link["brief"]), "invalid assignment brief path")
                    require(
                        link["working_directory"] is None
                        or path_string(link["working_directory"]),
                        "invalid working directory",
                    )
                    predecessor = link["predecessor"]
                    require(
                        predecessor is None
                        or (
                            checkpoint.matches(checkpoint.SLUG, predecessor)
                            and predecessor in assignments
                            and assignments[predecessor]["role"] == link["role"]
                        ),
                        "invalid predecessor link",
                    )
                    require(
                        link["dispatch"] in ("intent", "confirmed"),
                        "invalid dispatch state",
                    )
                    if link["reconciliation"] is not None:
                        decision_ref(
                            link["reconciliation"], decisions, ("reconciliation",)
                        )
                    if previous:
                        require(
                            predecessor == previous["assignment"]
                            and previous["reconciliation"] is not None,
                            "replacement requires reconciled predecessor",
                        )
                    if predecessor:
                        require(
                            assignments[predecessor]["reconciliation"] is not None,
                            "predecessor ownership unresolved",
                        )
                    assignments[assignment] = link
                    previous = link
                if attempt["status"] in ("passed", "failed"):
                    decision_ref(attempt["decision"], decisions, ("coordinator",))
                    require(
                        attempt["decision"] not in terminal_decisions,
                        "terminal attempts need distinct decisions",
                    )
                    terminal_decisions.add(attempt["decision"])
                    require(
                        checkpoint.text(attempt["outcome"])
                        and bool(attempt["evidence"]),
                        "terminal attempt requires outcome and evidence",
                    )
                    require(
                        all(
                            l["dispatch"] == "confirmed"
                            or l["reconciliation"] is not None
                            for l in links
                        ),
                        "unresolved dispatch cannot finish",
                    )
                    if stage["id"] == "verify":
                        require(
                            attempt["report"] is not None
                            and attempt["verdict"]
                            == ("pass" if attempt["status"] == "passed" else "fail"),
                            "verification needs exact verdict and report",
                        )
                    if stage["id"] == "worker" and attempt["status"] == "passed":
                        require(
                            attempt["candidate_commit"] is not None,
                            "passed worker requires candidate commit",
                        )
                    if (
                        stage["id"] in ("report", "scout", "triage")
                        and attempt["status"] == "passed"
                    ):
                        require(attempt["report"] is not None, "report required")
                else:
                    require(
                        attempt["decision"] is None,
                        "unfinished attempt cannot claim stage decision",
                    )
                if stage["id"] != "verify":
                    require(
                        attempt["verdict"] is None,
                        "verdict belongs only to verification",
                    )
            require(orders == sorted(set(orders)), "attempts must be uniquely ordered")
        entries = ordered(selection)
        require(
            [a["order"] for _, a in entries] == list(range(1, len(entries) + 1)),
            "attempt order must be contiguous",
        )
        progress(selection, acceptance)
    expected = progress(selections[-1], acceptance)
    require(
        value["current_stage"] == expected,
        "current stage does not match recipe progress",
    )
    require(
        value["status"] in ("active", "paused", "blocked", "completed"),
        "invalid workflow status",
    )
    require(checkpoint.text(value["checkpoint"]), "checkpoint summary required")
    require(
        value["blocker"] is None or checkpoint.text(value["blocker"]), "invalid blocker"
    )
    require(
        value["status"] != "blocked" or checkpoint.text(value["blocker"]),
        "blocked workflow needs blocker",
    )
    require(
        value["next_action"] is None or checkpoint.text(value["next_action"]),
        "invalid next action",
    )
    require(
        value["status"] != "active" or checkpoint.text(value["next_action"]),
        "active workflow needs next action",
    )
    latest_entries = ordered(selections[-1])
    if latest_entries and latest_entries[-1][1]["status"] == "blocked":
        require(
            value["status"] == "blocked" and checkpoint.text(value["blocker"]),
            "blocked attempt needs workflow blocker",
        )
    references(value["delivery_refs"])
    if value["status"] == "completed":
        require(
            expected is None
            and value["next_action"] is None
            and bool(value["delivery_refs"]),
            "completion requires confirmed requested delivery",
        )
        last = ordered(selections[-1])[-1] if ordered(selections[-1]) else None
        require(
            last is not None
            and last[0] in ("deliver", "report")
            and last[1]["status"] == "passed",
            "delivery stage must pass",
        )
        require(
            (selections[-1]["recipe"] == "implement")
            == (current_delivery(value) != "report"),
            "report is not code delivery",
        )
        require(
            set(value["delivery_refs"]).issubset(last[1]["evidence"]),
            "delivery references need confirmed evidence",
        )
        delivery = current_delivery(value)
        if delivery == "local-commit":
            require(
                last[1]["candidate_commit"] in value["delivery_refs"],
                "local delivery needs the exact candidate reference",
            )
        elif delivery in ("pr", "merge"):
            require(
                any(
                    urlsplit(ref).scheme in ("https", "http") and urlsplit(ref).netloc
                    for ref in value["delivery_refs"]
                ),
                "pr or merge delivery needs a confirmed url",
            )
        else:
            require(
                last[1]["report"] in value["delivery_refs"],
                "report delivery needs its report reference",
            )
    return value


def prefix(old, new, name):
    require(
        len(new) >= len(old) and new[: len(old)] == old, name + " history is immutable"
    )


def transition(old, new):
    require(old["task_id"] == new["task_id"], "task identity is immutable")
    new_decisions = {d["id"] for d in new["decisions"][len(old["decisions"]) :]}
    prefix(old["decisions"], new["decisions"], "decision")
    prefix(old["briefs"], new["briefs"], "brief")
    prefix(old["delivery_refs"], new["delivery_refs"], "delivery")
    require(
        len(new["selections"]) >= len(old["selections"]),
        "recipe history cannot be removed",
    )
    for index, prior in enumerate(old["selections"]):
        proposed = new["selections"][index]
        if index < len(new["selections"]) - 1:
            require(prior == proposed, "old recipe selections are immutable")
            continue
        require(
            all(prior[k] == proposed[k] for k in prior if k != "stages"),
            "recipe changes require a new selection",
        )
        for previous_stage, next_stage in zip(prior["stages"], proposed["stages"]):
            before, after = previous_stage["attempts"], next_stage["attempts"]
            require(len(after) >= len(before), "attempt history cannot be removed")
            for previous, following in zip(before, after):
                if previous["status"] not in ("passed", "failed") and following[
                    "status"
                ] in ("passed", "failed"):
                    require(
                        following["decision"] in new_decisions,
                        "terminal outcome needs a new coordinator decision",
                    )
                if previous["status"] in ("passed", "failed"):
                    require(
                        all(
                            previous[k] == following[k]
                            for k in previous
                            if k != "assignments"
                        ),
                        "terminal attempts are immutable",
                    )
                    require(
                        len(previous["assignments"]) == len(following["assignments"]),
                        "terminal assignments are immutable",
                    )
                for key in ("id", "order", "intent", "acceptance_revision"):
                    require(
                        previous[key] == following[key], "attempt identity is immutable"
                    )
                if previous["candidate_commit"] is not None:
                    require(
                        previous["candidate_commit"] == following["candidate_commit"],
                        "attempt candidate is immutable",
                    )
                links = previous["assignments"]
                require(
                    len(following["assignments"]) >= len(links),
                    "assignment history cannot be removed",
                )
                for a, b in zip(links, following["assignments"]):
                    require(
                        all(
                            a[k] == b[k]
                            for k in a
                            if k not in ("dispatch", "reconciliation")
                        ),
                        "assignment identity is immutable",
                    )
                    require(
                        a["dispatch"] != "confirmed" or b["dispatch"] == "confirmed",
                        "dispatch cannot be unconfirmed",
                    )
                    require(
                        a["reconciliation"] is None
                        or a["reconciliation"] == b["reconciliation"],
                        "reconciliation is immutable",
                    )
    for brief in new["briefs"][len(old["briefs"]) :]:
        require(
            brief["decision"] in new_decisions,
            "changed acceptance needs a new operator decision",
        )
    for selection in new["selections"][len(old["selections"]) :]:
        require(
            selection["decision"] in new_decisions,
            "recipe change needs a new operator decision",
        )
        for _, attempt in ordered(old["selections"][-1]):
            require(
                attempt["status"] in ("passed", "failed")
                or (
                    bool(attempt["assignments"])
                    and all(
                        l["reconciliation"] is not None for l in attempt["assignments"]
                    )
                ),
                "recipe change has unresolved ownership",
            )
    old_ids = {a["id"] for s in old["selections"] for _, a in ordered(s)}
    new_attempts = [
        a for s in new["selections"] for _, a in ordered(s) if a["id"] not in old_ids
    ]
    require(len(new_attempts) <= 1, "reserve one attempt before acting")
    for attempt in new_attempts:
        require(
            attempt["status"] == "active"
            and attempt["outcome"] is None
            and attempt["decision"] is None
            and not attempt["evidence"],
            "persist attempt intent before outcome",
        )
        require(
            attempt["acceptance_revision"] == current_acceptance(new),
            "new attempt requires current acceptance",
        )
        require(
            all(
                l["dispatch"] == "intent" and l["reconciliation"] is None
                for l in attempt["assignments"]
            ),
            "reserve dispatch intent before spawning",
        )
    old_links = {
        l["assignment"]
        for s in old["selections"]
        for _, a in ordered(s)
        for l in a["assignments"]
    }
    for s in new["selections"]:
        for _, a in ordered(s):
            for link in a["assignments"]:
                if link["assignment"] not in old_links:
                    require(
                        link["dispatch"] == "intent" and link["reconciliation"] is None,
                        "new assignment requires dispatch intent",
                    )


def decode(raw):
    require(len(raw) <= MAX_BYTES, "workflow exceeds byte limit")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=checkpoint.unique_object,
            parse_constant=lambda _: require(False, "invalid json constant"),
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("invalid utf-8 json") from None
    return validate(value)


def encode(value):
    raw = (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
    decode(raw)
    return raw


def identity(value, task_id, path):
    require(
        Path(path).name == "workflow.json" and Path(path).parent.name == task_id,
        "expected task-local workflow.json",
    )
    require(value["task_id"] == task_id, "workflow identity mismatch")
    # assignment links are confined to this task, never arbitrary checkpoint files.
    for selection in value["selections"]:
        for _, attempt in ordered(selection):
            for link in attempt["assignments"]:
                require(
                    Path(link["tracker"])
                    == Path(path).parent / "agents" / (link["assignment"] + ".json"),
                    "tracker must belong to this task",
                )


def read_workflow(path, task_id):
    with parent_directory(path) as (directory, name):
        raw = read_bytes(directory, name)
        value = decode(raw)
        identity(value, task_id, path)
    return {"workflow": value, "revision": revision(raw)}


def write_workflow(path, task_id, proposed, last_revision=None, initialize=False):
    validate(proposed)
    identity(proposed, task_id, path)
    require(
        initialize or checkpoint.matches(HASH, last_revision),
        "last-read revision required",
    )
    if initialize:
        require(
            all(
                not stage["attempts"]
                for s in proposed["selections"]
                for stage in s["stages"]
            )
            and len(proposed["selections"]) == 1
            and proposed["status"] != "completed"
            and not proposed["delivery_refs"],
            "initialize selection before reserving attempts",
        )
    value = dict(
        proposed, updated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    raw = encode(value)
    with parent_directory(path, create=initialize) as (directory, name):

        def check_old():
            previous = read_bytes(directory, name)
            old = decode(previous)
            identity(old, task_id, path)
            require(revision(previous) == last_revision, "stale workflow revision")
            transition(old, value)

        if initialize:
            try:
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ValueError("initialization destination already exists")
        else:
            check_old()
        temporary = name + ".tmp-" + secrets.token_hex(16)
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
            decode(read_bytes(directory, temporary))
            if initialize:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
            else:
                # not a compare-and-swap: reconciled coordinator ownership is required.
                check_old()
                os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
    return {"workflow": value, "revision": revision(raw)}


def inspect_reference(ref):
    if checkpoint.matches(COMMIT, ref):
        return "commit reference not checked"
    if not ref.startswith("/"):
        return "external reference not checked"
    try:
        with parent_directory(ref) as (directory, name):
            read_bytes(directory, name)
        return None
    except (OSError, ValueError):
        return "missing, unsafe, oversized or unreadable reference"


def show(path, task_id):
    result = read_workflow(path, task_id)
    value, issues, stages = result["workflow"], [], []
    checked_refs = set()

    def check_ref(ref):
        if ref not in checked_refs:
            checked_refs.add(ref)
            issue = inspect_reference(ref)
            if issue:
                issues.append({"reference": ref, "issue": issue})

    for brief in value["briefs"]:
        check_ref(brief["reference"])
    for decision in value["decisions"]:
        for ref in decision["evidence"]:
            check_ref(ref)
    for ref in value["delivery_refs"]:
        check_ref(ref)
    for selection in value["selections"]:
        for stage in selection["stages"]:
            attempts = []
            for attempt in stage["attempts"]:
                joined = {
                    "id": attempt["id"],
                    "coordinator_status": attempt["status"],
                    "verdict": attempt["verdict"],
                    "assignments": [],
                }
                refs = [
                    *attempt["evidence"],
                    *([attempt["report"]] if attempt["report"] else []),
                ]
                for ref in refs:
                    check_ref(ref)
                if (
                    stage["id"] == "verify"
                    and attempt["status"] == "passed"
                    and attempt["acceptance_revision"] != current_acceptance(value)
                ):
                    issues.append(
                        {
                            "reference": attempt["report"],
                            "issue": "historical approval does not cover current acceptance or delivery scope",
                        }
                    )
                for link in attempt["assignments"]:
                    item = {
                        "assignment": link["assignment"],
                        "dispatch": link["dispatch"],
                        "checkpoint": None,
                    }
                    check_ref(link["brief"])
                    if link["dispatch"] == "intent":
                        issues.append(
                            {
                                "reference": link["tracker"],
                                "issue": "dispatch outcome unresolved; do not repeat automatically",
                            }
                        )
                    expected = {k: link[k] for k in checkpoint.IDENTITY}
                    try:
                        agent = checkpoint.read_checkpoint(link["tracker"], expected)[
                            "checkpoint"
                        ]
                        item["checkpoint"] = agent
                        if not agent["run_ids"]:
                            issues.append(
                                {
                                    "reference": link["tracker"],
                                    "issue": "native id not recorded; reconcile ownership before any dispatch",
                                }
                            )
                        for artifact in agent["artifacts"]:
                            if artifact["kind"] != "commit":
                                check_ref(artifact["reference"])
                        if attempt["candidate_commit"] and any(
                            a["kind"] == "commit"
                            and a["reference"] != attempt["candidate_commit"]
                            for a in agent["artifacts"]
                        ):
                            issues.append(
                                {
                                    "reference": link["tracker"],
                                    "issue": "checkpoint commit differs from candidate; reconcile evidence",
                                }
                            )
                        if agent["status"] == "completed":
                            issues.append(
                                {
                                    "reference": link["tracker"],
                                    "issue": "agent completed is not stage approval; consult verdict and report",
                                }
                            )
                    except (OSError, ValueError):
                        issues.append(
                            {
                                "reference": link["tracker"],
                                "issue": "missing, malformed, unsafe or foreign checkpoint; preserve and reconcile",
                            }
                        )
                    joined["assignments"].append(item)
                attempts.append(joined)
            stages.append(
                {
                    "selection": selection["id"],
                    "stage": stage["id"],
                    "attempts": attempts,
                }
            )
    result["stages"] = stages
    result["issues"] = issues
    result["notice"] = (
        "read-only observations, not liveness, approval, or authorization to repeat actions"
    )
    return result


def proposal(source):
    if source == "-":
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    else:
        with parent_directory(source) as (directory, name):
            raw = read_bytes(directory, name)
    return decode(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "read", "update", "show"):
        sub = commands.add_parser(command)
        sub.add_argument("path", help="absolute data/<task-id>/workflow.json path")
        sub.add_argument("--task-id", required=True)
        if command in ("init", "update"):
            sub.add_argument(
                "--proposal",
                required=True,
                help="complete json on stdin (-) or absolute authorized file",
            )
        if command == "update":
            sub.add_argument("--revision", required=True)
    args = parser.parse_args()
    operation, path = args.command, args.path
    try:
        if args.command == "read":
            result = read_workflow(args.path, args.task_id)
        elif args.command == "show":
            result = show(args.path, args.task_id)
        else:
            operation, path = "read-proposal", args.proposal
            proposed = proposal(args.proposal)
            operation, path = args.command, args.path
            result = write_workflow(
                args.path,
                args.task_id,
                proposed,
                getattr(args, "revision", None),
                args.command == "init",
            )
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyboardInterrupt) as error:
        if isinstance(error, OSError):
            message = (error.strerror or "filesystem operation failed").lower()
        elif isinstance(error, KeyboardInterrupt):
            message = "interrupted; reread to confirm publication state"
        else:
            message = str(error)
        print(
            json.dumps({"operation": operation, "path": path, "error": message}),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
