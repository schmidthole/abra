# product planning

use the operator-selected `plan` v1 recipe for product direction, not code delivery:
`refine -> ground -> validate -> deliver`. it uses the existing coordinator workflow,
tasks-axi and native subagents; there is no new runtime, database, scheduler or dag.
see [workflow schema and recovery](workflows.md). no issue creation, scheduling,
publication or automatic implementation is authorized. report delivery is not product
approval. readiness is not customer desirability or scheduling approval either.
engineering decomposition and ticket-level work follow human product approval in a
separately authorized implementation task.

## briefs and report package

all three agent stages use the existing `scout` checkpoint role, with distinct stage
ids and fresh assignment trackers; validation requires fresh independent context.
replacement predecessors must be from the same stage, despite scout role reuse.
this does not change `verify`, the exact-code-candidate implementation role. fill
these portable briefs, including the full shared checkpoint instructions and workflow
context, even with specialty overrides:

- [refinement](../templates/plan-refine.md): `spec.md` covers users/problem, outcomes,
  success measures, scope/non-goals, journeys (including failures and permissions),
  numbered requirements, testable acceptance, assumptions, decisions and dependencies.
  `slices.md` defines outcome-oriented phases: what and why, not how; link outcomes,
  requirements, scope, dependencies/sequence and observable acceptance. no technical
  designs, implementation file/task lists, estimates, assignment commitments or tickets.
- [engineering grounding](../templates/plan-ground.md): add constraints and evidence
  to `review.md`, not implementation design. classify claims supported / contradicted /
  proposed / unknown, with exact repository commits and file/line or versioned contract
  evidence. source inspection is not production evidence. without a codebase, inspect
  constraints/contracts and mark source checks not applicable. unavailable evidence
  remains unknown; no fake commits, inferred production facts or invented certainty.
- [independent validation](../templates/plan-validate.md): append findings/readiness to
  `review.md`, preserving grounding. check bidirectional outcome -> requirement -> slice
  -> acceptance coverage, consistency, gaps, dependencies, rollout/migration,
  observability, security/privacy, accessibility where relevant, and open decisions.
  each finding includes severity, evidence and feedback destination (refine, ground,
  operator); verdict is ready / needs revision / blocked. explicitly list nonblocking
  unknowns; missing critical evidence/authority blocks readiness, not a guessed pass.

agents write only authorized task-local reports and their checkpoints, never product
code or coordinator state. use read-only worktrees pinned to each inspected repository
commit for grounding; no codebase may use a null working directory. the coordinator
supplies exact package inputs, approved feedback and output paths. material product,
scope or authority decisions return to the operator. technical evidence-only corrections
may be coordinator decisions; they never silently revise product acceptance.

## plan-only identity schema

existing manifest v1 fields and all older recipe attempts remain unchanged. only plan
attempts add required `package` (input) and `result_package` (confirmed output). each
is null or an object with exactly:

```json
{
  "spec": {"reference": "/srv/abra/data/example/spec.md", "revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
  "slices": {"reference": "/srv/abra/data/example/slices.md", "revision": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
  "review": null,
  "repositories": [{"reference": "/srv/repos/example", "commit": "cccccccccccccccccccccccccccccccccccccccc"}],
  "source_checks": "applicable"
}
```

`revision` is sha256 of exact document bytes, never a git commit. document references
are absolute `data/<task-id>/spec.md`, `slices.md`, `review.md` in the manifest's task
directory. each document may be null when genuinely absent; the initial refine input
may be null. do not manufacture hashes for absent artifacts. `candidate_commit` is
always null for plan. `repositories` contains distinct path/url identities and exact
40/64-hex commits of inspected code. source_checks is `applicable` (needs pinned
repositories), `not-applicable` (no codebase, empty repositories), or `unavailable`
(record access gaps in review; it is not a verified source check). versioned contracts
and production evidence belong in review with immutable refs, not fake repo commits.

a passed refine needs spec/slices; ground/validate/deliver outputs need all three.
unfinished attempts and failed non-validation stages have null result_package. a
terminal failed validate may record a full result_package solely to preserve appended
validation findings in review.md. its product/repository/source-check identities must
match input, with confirmed report/evidence and a coordinator decision; it is never
approval. record this result when review bytes changed. null remains valid for
historical failures or unchanged artifacts. neither form bypasses failure/blocked
routing or resets the repair count. reserve input identity before
dispatch and never rewrite it. a terminal result and report require confirmed refs in
attempt evidence and an explicit coordinator decision. each passed stage needs report;
validate alone uses `verdict`: ready for passed, needs revision or blocked for failed;
a blocked unresolved validation may carry blocked. other plan stages have null verdict.

## coordinator protocol and bounded feedback

1. save full request/authority, get explicit operator recipe selection, initialize as
   documented in workflows. report is the only requested delivery supported by plan.
2. save immutable snapshots of current document bytes and evidence before replacements
   under `data/<task-id>/` (include snapshot refs in attempt/decision evidence). preserve
   earlier findings and supersession notes in review. hashes identify history but do
   not preserve old bytes by themselves. reserve attempt/dispatch intent before acting;
   confirm actual launch/outcomes afterwards. agent completion never approves a stage.
3. refine may replace product direction only within operator authority; its input
   must preserve the latest recorded review and grounding identity, including failed
   validation findings and any initially supplied package. null bootstrap is allowed
   only before a package is recorded, never to erase prior evidence. its result also
   preserves those identities (initial absent review remains null). ground cannot
   change spec/slices; validate cannot change spec/slices or repository/source-check
   identity, and may only append validation content to review. the coordinator checks
   review diffs to prevent hidden grounding/scope changes. input/result identities
   avoid circular hashing as review acquires stage findings. never embed review's own
   final byte hash inside review; the manifest records it after the report is complete.
4. coordinator routes feedback to refine for product changes or ground for evidence-only
   changes, then fresh validation. a new refine invalidates grounding and validation;
   a new ground invalidates validation/delivery. direct changed inputs to validate or
   deliver are rejected. changed acceptance/authority requires a new saved brief and
   operator decision, then refinement. only passed refinement establishes successful
   refinement for that acceptance; any failed refine must be retried successfully
   before grounding, even with unchanged acceptance. initial validation plus at most
   two repair rounds per selection, including successful validations later invalidated: pass/restart or
   revision changes never reset this budget. after exhaustion stop for the operator;
   a third ready result can still be delivered. terminal blocked verdict also stops
   that selection for operator intervention. unresolved blocked attempts must be
   reconciled/resolved before progress, never bypassed by another dispatch.
5. deliver the exact current validated result_package, without modifying it, through a
   coordinator attempt with persisted intent and explicit outcome/decision. before any
   delivery rehash all three current files and compare to the approved package, confirm
   repository evidence is still the intended pinned set, inspect review's grounding and
   validation content, and reconcile ownership/any uncertain delivery outcome. if any
   bytes/evidence changed, record a new refine/ground attempt and revalidate; do not
   quietly relabel or reuse approval. completed requires all three confirmed document
   refs in delivery_refs and delivery evidence, plus the delivery report ref. link the
   delivered package to tasks-axi and explicitly complete report delivery, not product
   approval or implementation. completion always requires current acceptance, even
   after repair exhaustion. if acceptance changes during delivery, reconcile that
   intent and retain its actual outcome as historical evidence, not current delivery.
   an already-completed old delivery must likewise become non-completed on acceptance
   change; keep old attempts/refs intact and pause/block for further direction rather
   than certify stale scope. new implementation needs separate approval and recipe.

existing reconciliation, same-assignment resume, replacement ownership and immutable
history rules apply. a new operator-selected recipe/selection is explicit authority,
not a coordinator escape from the repair limit. preserve any unresolved dispatch or
delivery intent; `show` never authorizes repeat action.

## enforcement and limits

the helper validates fixed order, package structure/hash syntax and equality, pinned
repository syntax, stage-to-role mapping, stage-authorized document identities,
approval invalidation, repair budget, immutable history and report-only completion.
it does not read/hash document bytes on writes, prove claim classifications or inspect
review sections, validate production behavior, verify snapshot preservation, guarantee
fresh native context, or establish operator authority. these are coordinator review
obligations; hashes/references are assertions, not a security boundary. source checks
and unknowns need reasoned review, not automatic readiness. ordinary `show` reference
checks cannot detect document-byte drift. a manifest can be internally consistent yet
refer to edited bytes: the coordinator byte checks above are required for delivery.

`tests/test_plan_workflow.py` covers normal/no-codebase paths, stale identities,
blocked/unknown evidence, repair routing/limit, roles/history and prompt contracts.
these are simulated checks, not live agent trials; no claim of agent compliance,
customer desirability, live production verification or unattended recovery is made.
