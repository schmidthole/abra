# implementation handoff: ten efficiency gains

## status, scope and evidence

implementation status: the original ten-gain handoff below is retained as historical
scope, not active proposal-only guidance. the operator subsequently authorized
implementation in abra-efficiency-implementation. active contracts are in AGENTS.md
and linked docs; this document grants no publication/external-action authority.

| gain | implemented seam / evidence |
| --- | --- |
| 1 | opt-in workflow v2 implementation identity/reuse; workflow regression tests |
| 2 | embedded compact-checkpoint-v1; all seven templates and specialty; rendered negative contract tests |
| 3 | typed workflow reserve/confirm/decide/delivery and checkpoint progress; strict persistence tests |
| 4 | explicit field ownership; read-only show --compact; observation/failure tests |
| 5 | active opt-in lightweight routing and scout variant; routing/interrupt/escalation contract fixtures |
| 6 | observed capability preflight guidance and actual native worker evidence; fresh final verifier still required |
| 7 | validated existing formatter reuse; read-only checker and incompatible/partial environment tests; detached reuse gate remains |
| 8 | relevant startup including cross-repo resources/aliases/promises and global fallback; decision fixtures |
| 9 | once-only initially preauthorized v2 same-report read-only method switch; legacy/budget/owner rejection tests |
| 10 | normalized whole-rule/rendered negative checks; focused iteration and canonical final gates |

worker checks are not independent approval. task-local core/policy reports record
exact commits, commands, brief sizes, safety coverage and limits; fresh independent
whole-scope exact-candidate verification remains the delivery gate. no live github,
other-harness or model-compliance trial is claimed. original detailed proposal
language below describes the saved handoff, not unavailable commands today; consult
current helper --help and docs for actual interfaces. the original edited plan
worktree remains untouched; only this copied document's EOF is normalized.

this handoff preserves the numbering of the ten recommendations in the efficiency
review. its source baseline is commit
`5b992b60d106ff6542d61bb172da3fb208112631`. recheck these seams at dispatch; file
names and function names below are stronger anchors than historical line numbers.

review inputs, stored outside project worktrees in the coordinator's abra root:

- `data/abra-efficiency-review/report.md`: prioritized recommendations and limits;
- `data/abra-efficiency-review/coordinator-findings.md`: helper and historical
  artifact audit;
- `data/abra-efficiency-review/scout-output.md`: independent policy/template audit.

historical observations below are attributed to those reports, not claimed as
newly reproduced timings or live trials. the reports cite repeated verification,
large briefs/manifests and failed profile launches; they establish opportunities,
not measured speedups. implementation details here are grounded in current source.
when historical task artifacts are unavailable to a later worker, retain that
limitation rather than treating the citations as fresh measurements.

## invariants for every package

- substantive changes still receive fresh independent review and meaningful tests
  at the exact candidate commit, in a detached verifier worktree. the worker's
  summary is supporting context, never the acceptance authority.
- explicit action authority and specialty delivery ceilings remain separate from
  recipe selection, review approval and requested delivery. required unavailable,
  pending or failed checks block a pass; no checks does not mean ci passed.
- tasks-axi remains the lifecycle authority. the coordinator alone writes workflow
  manifests; each assignment alone writes its checkpoint. no new task database,
  scheduler, watcher, process runner, generic dag or agent framework is needed.
- persist dispatch/publication intent before acting and confirmed outcome after.
  an interrupted intent may have executed. inspect native ownership and actual
  artifacts before resuming, replacing or repeating; unknown ownership blocks.
- retain saved requests, acceptance, authority, briefs, decisions, reports and
  attempt history. stable assignment ids survive same-assignment resumes;
  replacements require reconciled stopped ownership, new ids and predecessors.
- preserve bounded repairs: implementation has initial verification plus at most
  two repair rounds; planning has its own stricter validation-budget semantics.
  switching methods, changing acceptance or replacing an agent cannot quietly
  reset a budget or bypass an unresolved blocked verdict.
- reuse `bin/durable_files.py` and the validated helper write paths. retain strict
  bounded json, identity checks, no-follow path handling, exclusive initialization,
  atomic complete replacement and last-read revision checks. these are not locks,
  compare-and-swap, exactly-once execution, permission enforcement or fsync-based
  power-loss durability. preserve malformed/foreign/stale evidence and leftover
  temporaries; never auto-repair or promote them.

all new interfaces, fields and routing permissions described below are proposed,
not available commands or approved exceptions. use current `--help` before real
cli use; do not transcribe proposed operation names into a live dispatch command.

## 1. reuse verification when only delivery changes

### current problem and evidence

`docs/workflows.md` defines one `acceptance_revision` over acceptance, requested
delivery and authority. `bin/workflow.py` functions `current_acceptance`, `progress`,
`validate`, `transition` and `show` use that revision for implementation approval.
changing local-commit delivery to pr therefore reopens verify even with identical
code. the review cites `data/abra-plan/task-body.md:40-46`: another independent
review and a repeated 354-test run for an unchanged commit. the existing tests
`test_changed_delivery_scope_reopens_approval_and_keeps_prior_scope` and
`test_acceptance_and_candidate_changes_invalidate_approval` encode today's rule.

### proposed changes and seams

- separate implementation acceptance identity from the full request/delivery
  revision. retain the full `acceptance_revision` and append-only saved briefs;
  it still changes for delivery or authority changes. add a separately asserted
  implementation identity for implement briefs: exact review base commit and a
  sha256 of a saved substantive contract containing original problem, acceptance,
  constraints, required local checks and review assumptions. include relevant
  environment/dependency/security assumptions, not just a hash of code bytes.
  a proposed v2 brief extension could hold `implementation_identity` with `base`
  and `revision`; non-implement briefs use null. the saved brief must retain the
  exact contract bytes used for the digest and explain exclusions. these fields
  and schema version are proposals requiring implementation approval.
- update replay to resolve each attempt's existing `acceptance_revision` to its
  immutable brief. a passing verify approves its exact candidate plus substantive
  identity, not every future delivery request. a delivery-only revision may reuse
  that approval only after an explicit coordinator reuse decision with evidence
  comparing the old/new saved contracts, unchanged base and relevant assumptions.
  hashes identify asserted bytes; they do not prove semantic equivalence.
- keep deliver attempts bound to the current full request revision. a changed
  delivery request reopens deliver, never silently treats an old local delivery
  as a new pr delivery. preserve the historical local receipt. add explicit reuse
  decision linkage rather than manufacturing another passed verifier attempt.
- in `progress`/`validate`/`transition`, reject reuse after a new worker attempt,
  candidate change, substantive acceptance/required-check change or missing review
  identity/evidence. `show` should distinguish reusable code review from stale
  publication readiness; it must not announce that reuse itself authorizes action.
- update `docs/workflows.md`, `AGENTS.md`, `README.md`, `templates/verify.md` and
  `templates/worker.md` to separate fresh code review from publication checks.
  keep `docs/planning.md`'s exact document-package approval and byte checks intact;
  this optimization is for implement delivery, not plan-package mutation.

### safeguards, compatibility and recovery

before publication, recheck explicit authority, specialty ceiling, clean worker
status and exact verified head, intended target repository/branch/base and review
assumptions. inspect existing prs before creating one, confirm remote/pr head is
the reviewed candidate after push, and check required ci for that head. ci is
fresh publication evidence, not replaced by an old local test report. a target-base
advance, changed runtime assumptions or newly required local check requires review
of applicability; if equivalence cannot be established, obtain fresh independent
verification. rebasing, merging a base or repairing ci creates a new candidate and
requires the normal worker/fresh-verifier cycle. no automatic merge authority.

use an explicit versioned manifest change rather than silently adding fields to
strict v1. retain v1 read/validation and its conservative re-verification semantics.
new v2 tasks can record the split from the start. an optional separately authorized
migration must preserve a v1 byte snapshot, all history and old approvals as
historical evidence; an old approval with no recorded substantive identity is not
reusable by inference. do not backfill equivalence from commit equality alone.
old binaries must refuse v2 rather than guess. no downgrade that discards history.

if publication may have happened before recording outcome, reconcile the actual
remote/pr/check state before any retry. failed/pending ci leaves delivery blocked;
reuse never converts it to passed. if reuse evidence is incomplete or invalid,
fall back to fresh review, not a best-effort publication. the two-repair-round
limit remains effective across delivery revisions.

### acceptance and validation

extend `tests/test_workflow.py` with table-driven cases: unchanged local-to-pr
revision reuses one actual review but requires a new deliver intent and decision;
changed candidate/base/acceptance/assumptions/checks or a new worker invalidates;
missing reuse evidence rejects; stale local completion cannot complete pr delivery;
old briefs/decisions remain immutable; legacy v1 still behaves conservatively.
exercise pr-before-outcome reconciliation using existing local receipt fixtures.
retain `tests/test_plan_workflow.py` rejection of stale document/repository identities
and all repair-budget cases. manual disposable-repo trials must demonstrate
clean-head, duplicate-pr, exact remote-head and pending/failing/absent-check handling;
live github trials require separate authority. success means one code review for
an eligible unchanged candidate, with no fewer publication safety checks. measure
avoided review launches/test reruns, not a presumed percentage speedup.

## 2. shorten and deduplicate mandatory instructions

### current problem and evidence

`docs/agent-tracking.md` requires embedding the entire specification in every
brief. all seven files in `templates/` repeat workflow/checkpoint instructions;
`AGENTS.md`, `README.md`, `docs/workflows.md` and specialty documents repeat detailed
policy. the review reports roughly 22-45 kb filled briefs and a 264-line tracking
manual. tutorials and filesystem internals occupy context even on routine work.
`tests/test_agent_tracking.py` also binds many rules to exact prose/newlines.

### proposed changes and seams

- divide `docs/agent-tracking.md` into a short, complete operational contract and
  a detailed versioned schema/help/recovery reference. keep one canonical compact
  section for expansion into each brief, not a bare link. add a contract version
  marker. save the exact reference snapshot or immutable revision with each filled
  brief; an absolute path to a mutable current manual is not enough on recovery.
- the embedded contract must contain actual request/acceptance/authority and role
  boundary, absolute working/report/tracker/helper paths, assignment/role/predecessor/
  run ids, sole-writer ownership and allowed write exceptions. include the full
  checkpoint field list/types or a minimal valid complete proposal, helper init/
  read/update usage, complete stdin proposals, last-read revisions and timestamp
  ownership. an agent must be able to initialize safely without rediscovering the
  schema in another repository. load the detailed reference for nonroutine schema
  questions, helper errors or recovery; if required reference bytes cannot be
  accessed/validated, stop, not invent the format.
- retain update triggers (before substantive work, meaningful progress, before
  consequential actions and before return), stop-on-helper-failure/conflict rules,
  missing-on-resume/foreign/malformed preservation, uncertain publication handling,
  no extra scratch-file exception, and status-not-liveness/not-approval semantics.
  retain identity and stable-step rules, reconciliation before resume/replacement,
  redaction and no claims of permission or power-loss safety. concise does not
  mean omitting operational invariants.
- remove surrounding duplicate paragraphs from `templates/worker.md`,
  `templates/scout.md`, `templates/verify.md`, `templates/triage.md` and all three
  planning templates only after the compact block covers them. keep role-specific
  constraints and full acceptance evidence. make `AGENTS.md` a routing/safety index
  with essential always-visible authority/worktree/review/ownership rules; put
  transition detail in workflows, plan detail in planning and recovery detail in
  tracking. make `README.md` an overview with links. update `docs/specialty.md` and
  `docs/modes/specialty.md` to require the same expanded portable contract even
  when an override omits it. do not add a templating framework to accomplish this.

### safeguards, compatibility and recovery

existing saved briefs remain authoritative for their assignments; do not replace
or shorten them in place. apply the new contract to new assignments only, and
include its version/reference snapshot so a different checkout cannot silently
supply a newer contract. checkpoint json v1 and helper filesystem mechanics need
not change. no instruction can grant commands outside the supplied working
directory, or override a stricter specialty. if an override/reference is incomplete,
supply the full existing contract or block; never launch with missing safeguards.

### acceptance and validation

update `tests/test_agent_tracking.py`, template checks in `tests/test_workflow.py`
and `tests/test_plan_workflow.py`, and relevant `tests/test_triage.py` contracts.
check all seven rendered briefs and a specialty override fixture: supplied fields
appear once, no placeholders remain, embedded contract is complete and referenced
bytes/version are available. add negative fixtures removing revision/identity/write
boundaries or stop rules and require failure; mere keyword presence is insufficient.
use real `checkpoint.decode`/`validate` for the compact example and disposable
helper round trips. retain `tests/test_checkpoint.py` behavior tests. independently
review a coverage table mapping every old operational invariant to its new home.
a later authorized cross-repository trial must initialize, update and stop on a
conflict using only the portable brief/reference. compare filled bytes and reading
burden with equivalent old briefs; reject savings that lose safe recoverability.

## 3. generate routine state transitions instead of hand-building json

### current problem and evidence

`bin/workflow.py` and `bin/checkpoint.py` expose init/read/complete update, with
manual full proposals required by their docs. the review reports manifests around
8-20 kb. the model repeatedly reconstructs ids, ordering, unchanged history and
nested records just to reserve or finish a stage. strict validation is useful;
manual repetition is not the useful part.

### proposed changes and seams

add a small set of typed builders/convenience operations to the existing helpers,
not a patch language or a workflow executor. proposed operation names below are
not current cli subcommands:

| proposed operation | caller supplies semantic input | helper supplies mechanics |
| --- | --- | --- |
| reserve attempt/assignment | stage, intent, full saved brief, identity/paths, predecessor, candidate or plan input where required | next collision-free id/order, active attempt, dispatch intent and null outcome fields |
| confirm dispatch | attempt/assignment and observed launch evidence | one-way dispatch confirmation, retaining identity/history |
| record stage decision | explicit coordinator decision, verdict, report, candidate/result package, outcome and evidence | linked decision/terminal fields and replay-derived current stage |
| reserve/record delivery | current authorized target/candidate, recovery lookup, then actual receipt/check evidence and decision | separate intent/outcome records and append-only delivery refs |
| record checkpoint progress | agent's complete coherent steps/progress/next action/blocker/artifacts, optional observed run ids | retain immutable identity, append distinct run ids, helper timestamp and validated replacement |

implement workflow builders near `ordered`, `progress`, `validate`, `transition`
and cli parsing in `bin/workflow.py`. checkpoint convenience belongs near
`validate`/`write_checkpoint` in `bin/checkpoint.py`. begin with reserve and dispatch
confirmation; add the other operations as separate bounded packages, not a giant
all-purpose mutation interface. required semantic fields must not be guessed.
reuse the current full validation, transition and identity checks and existing
`write_workflow`/`write_checkpoint` publication paths for every operation. derive
ids deterministically from occupied ids and reject supplied collisions. helper
success means a valid persisted assertion, not observed harness success.

keep full-proposal init/update for compatibility and unusual reconciled edits.
typed requests may be small strict stdin objects with exact per-operation keys,
bounds and duplicate-key rejection, plus the normal absolute path, supplied
identity and caller's last-read revision. cli syntax and request schemas must be
designed/documented as part of the later implementation, not assumed available.
update workflow/tracking docs, examples, `README.md` and portable helper guidance only
after those commands actually exist. no tasks-axi writes, harness calls, git actions,
report hashing or verdict inference inside the helpers.

### safeguards, compatibility and recovery

the caller remains responsible for semantic approval and a coherent next action.
no `passed` result from a completed checkpoint, no automatic retry, idempotence
claim, ownership takeover, generic nested patch, force option or scheduler. retain
single-writer ownership and revision checks both before staging and just before
publication. an interrupted operation may have published: read and reconcile;
do not blindly repeat reserve and create another assignment. stale revision errors
preserve bytes and require reconciliation rather than automatic token refresh.

where builders do not change on-disk schema, support current v1 unchanged. where
#1 or #9 requires a version change, builders must dispatch through that version's
validator and reject unsupported versions. do not make schema migration a side
effect of a convenience operation. paused/blocked and old immutable history survive
both manual and typed paths. errors remain redacted and do not echo foreign data.

### acceptance and validation

in `tests/test_workflow.py` and `tests/test_checkpoint.py`, compare builder results
with equivalent valid manual proposals (excluding actual timestamps). test wrong
role/stage, missing evidence/decision, stale revision, collision, foreign identity,
unknown/duplicate request keys, oversized input, replacement without reconciliation,
terminal mutation, multiple reservations and exhausted repair budget. exercise
failure before publication and after publication/before output using existing
fault-injection patterns; confirm old or new complete bytes, no truncation, and
only owned temporary cleanup. retain symlink/nonregular-target tests and
`tests/test_plan_workflow.py` package constraints. acceptance is less caller-written
json with identical validator protection, not fewer validation checks. measure
proposal bytes/manual edits and validation-repair events for comparable transitions.

## 4. stop maintaining the same progress in several places

### current problem and evidence

`AGENTS.md`'s context-continuity section requires a broadly standalone task body;
`docs/workflows.md` separately records checkpoint/next action/blocker/stage decisions;
agents record progress in their checkpoints. the audit found overlapping summaries
and references, creating extra read-modify-write cycles and disagreement risks.
`workflow.py show` already joins manifests with validated checkpoints and issues;
it is a suitable observation seam, not a second source of lifecycle truth.

### proposed changes and seams

adopt an explicit ownership table in `AGENTS.md`, `docs/workflows.md`,
`docs/agent-tracking.md` and `README.md`:

| record | authoritative content | update trigger |
| --- | --- | --- |
| tasks-axi body/lifecycle | saved original request/authority links, current acceptance/steering summary, repo/worktree/manifest references, material blockers, human handoff, delivery expectation/outcome | material steering, hold/unhold, ownership handoff, changed next safe action, delivery and explicit lifecycle changes |
| coordinator manifest | selection, attempts, dispatch/delivery intents and outcomes, evidence-backed stage decisions, current coordinator next action/blocker | before consequential coordinator actions and after confirmed outcomes |
| agent checkpoint | assignment identity/run ids, detailed coarse steps, confirmed agent progress, next action, agent blocker/artifacts | existing agent update triggers |
| immutable briefs/reports | full request/constraints/authority, exact assignment and check evidence | save new revision/report, preserve old bytes |

stop copying every agent step or routine manifest transition into task notes.
retain enough task summary to discover scope/conflicts and resume via explicit
absolute links; a link-only task is insufficient. material steering must be saved
before action. unresolved dispatch or publication intent remains durable in the
manifest and a concise task warning, not hidden in agent progress.

extend `show` if needed with a compact read-only current selection/stage/attempt,
manifest next action/blocker, latest assignment observation and issue summary.
label coordinator decision separately from agent status. do not make `show` write
back to tasks-axi or overwrite checkpoints, or add a cached combined database.
use the task's existing lifecycle/dashboard alongside it rather than claiming it
consults tasks-axi. today `show` does not inspect native state, git/pr state or all
report bytes for semantic validity; retain those limitations. package identity
checks for planning remain mandatory outside ordinary reference existence checks.

### safeguards, compatibility and recovery

no schema change is necessary just to stop mirroring prose. leave existing notes
and history intact; use the new division on the next material update, preserving
original intent rather than destructively compacting unresolved evidence. maintain
inspect-full-body-before-update. disagreement between task, manifest, checkpoint
and artifacts is an issue to reconcile, not a latest-timestamp-wins merge. missing
links/reference access or uncertain ownership blocks resumption. during recovery,
read the full relevant task, saved current/original briefs, manifest, checkpoints
and actual evidence before any new action, even if the combined view looks complete.

### acceptance and validation

extend `tests/test_workflow.py` read-only show cases for missing/malformed/foreign
checkpoints, stale candidate/report refs, agent completed with failed verdict,
unresolved dispatch and coordinator blocker. assert every source byte is unchanged
by show and no external commands/mutations occur. review docs/templates for the
ownership table, not duplicated new progress fields. simulate interruption after
commit or pr receipt with task notes not yet refreshed: recovery must find the
manifest intent, inspect evidence and record outcome without repeating the action.
a fresh coordinator should identify original request, authority, candidate, owner,
blocker and next safe action by following the compact handoff. measure eliminated
mirroring writes and contradictions, not merely shorter task bodies.

## 5. create an explicit lightweight path

### current problem and evidence

`AGENTS.md` and `docs/workflows.md` already exempt small direct answers, but all
delegated research uses stage/attempt/decision/report-delivery machinery.
`docs/planning.md` routes product direction through refine/ground/validate. the
scout audit identifies avoidable ceremony for short read-only research and
brainstorming; it does not prove all product questions currently require a plan.
this gain requires explicit operator policy approval before use.

### proposed changes and seams

clarify the existing exemption rather than add a fifth recipe. propose these
routing boundaries for later approval in `AGENTS.md`, `docs/workflows.md`,
`docs/planning.md`, `README.md` and `templates/scout.md`:

- direct small answer or brainstorming/critique: answer within the requested scope
  and label assumptions and limitations. keep the existing small-answer exemption;
  for newly covered lightweight work save a concise request/authority/outcome record
  under the existing task-local reports, linked from its task handoff. no claim of
  grounded readiness or independent validation. explicit plan v1 or reviewed spec/
  slice-package requests still use all three planning stages and exact delivery.
- bounded one-scout read-only research: keep a tasks-axi item/handoff with saved
  request, acceptance, authority, assignment reservation, absolute brief/tracker
  links and dispatch intent/observed launch outcome. agent still owns a checkpoint
  and authorized report. propose omitting workflow.json and separate coordinator
  report-delivery attempt for this narrow case; the coordinator reviews/delivers
  the actual report and explicitly records outcome/lifecycle in tasks-axi.
- trivial local documentation: only mechanical or unambiguous non-policy prose,
  no code/config/dependency/interface/security/authority or operating-rule change.
  save request, diff/check evidence and exact local commit/outcome. required final
  project gates still apply. independent review requirements for substantive
  documentation and any code stay on the full path; ambiguity uses the full path.

exclude publication/merge/production, sensitive data/security work, diagnostic
execution, multiple stages/agents/repos with unclear scope, uncertain prior
ownership and any substantial implementation. a short diff is not a risk test;
changing verification policy in one sentence is substantive. honor stricter
specialties and explicit operator recipe choices. this handoff itself does not
qualify as a trivial mechanical doc edit.

no helper/api currently implements a lightweight workflow. if templates need an
explicit context discriminator, propose a small documented full/lightweight brief
variant with task/assignment/authority links, not fabricated stage ids or nullable
v1 fields that today's validator rejects. maintain the complete compact tracking
contract from #2 for any delegated assignment.

### safeguards, compatibility and recovery

approve examples/counterexamples and the saved-record minimum before deployment.
existing full workflows continue under their selected recipe; do not remove
manifests mid-task. if lightweight research discovers implementation or scope
expands, stop at the report boundary, save findings and obtain separately authorized
full work. initialize a normal workflow linking earlier evidence only after
reconciling ownership; do not retroactively invent stage passes. use the saved
lightweight dispatch intent for interrupted-launch recovery; missing checkpoint
or native id never proves no scout ran. there is no duplicate-launch shortcut.

### acceptance and validation

add routing contract fixtures alongside `tests/test_workflow.py`,
`tests/test_plan_workflow.py` and `tests/test_agent_tracking.py`: small answer,
brainstorm vs certified package, bounded scout, trivial typo, policy doc change,
security doc, external action, explicit full recipe and unknown ownership. assert
excluded cases route full or ask, not merely that the word lightweight exists.
walk through interrupted lightweight scout intent, report-before-outcome and
escalation to implementation without lost evidence or inferred authority. live
routing compliance remains a separately authorized harness trial. success means
less ceremony for eligible requests with discoverable ownership/outcomes, never
calling an unreviewed idea a ready plan. measure unnecessary stage launches avoided
and misrouting/escalation incidents; keep this opt-in until boundaries are proven.

## 6. match agent capabilities before dispatch

### current problem and evidence

the review cites `data/abra-plan/verify-01-blocker.md:3-5` and
`data/autonomous-recipes/verify-result.md:15-28`: chosen verifier profiles could not
invoke the checkpoint helper or run checks. `templates/verify.md` requires shell
execution, exact-head inspection, tests and canonical format/lint. read-only product
intent does not mean tool-less verification. `CLAUDE.md` already records harness-
specific fresh-context and background-agent constraints.

### proposed changes and seams

add a short role-capability checklist to dispatch guidance in `AGENTS.md`, `README.md`,
`templates/verify.md`, `templates/worker.md`, `templates/scout.md` and
`templates/triage.md`; plan templates keep their scout/report write needs. record
observed harness/profile/configuration and check limitations in the filled brief:

- worker: supplied worktree access, shell/git/python/check tools and authorized
  task file/commit writes, plus tracker/report writes;
- verify: fresh independent context, detached worktree read/shell/test execution,
  local disposable probe/build-output permission and canonical tooling, supplied
  helper execution plus tracker/report writes, no product repair/publication;
- scout/plan: required source/reference reads and authorized reports/checkpoint
  helper writes; null working directory grants no other project commands;
- triage: same tracking/report baseline and only explicitly authorized diagnostic
  probes in the supplied worktree; do not broaden access to fit a profile.

before reserving an expensive attempt, inspect available harness configuration and
known profile tool allowlists. use existing documented native facilities only;
there is no portable introspection or preflight api in abra today. if inspection
cannot establish capability, use a separately authorized minimal disposable native
trial or report blocked. do not invent a `capabilities` cli, probing service or
agent runtime. preparation checks may read helper `--help`, interpreter/tool
versions and authorized path accessibility; the coordinator must not initialize
an agent-owned tracker as its probe. successful help execution is not proof of
future write permission, fresh context or complete test availability.

keep harness-specific selection guidance in `CLAUDE.md` and equivalent available
harness instructions, not hardcoded vendor tool names in portable role contracts.
pass exact absolute helper/report/worktree paths and the known pinned formatter
path from #7. permission policy and availability can differ per profile/session;
a previous success is evidence, not a permanent guarantee.

### safeguards, compatibility and recovery

no workflow/checkpoint schema migration is needed. save capability evidence in
existing brief/evidence references without a new capability registry. agents still
initialize their own trackers and stop if unavailable. a post-launch failure must
remain blocked, with actual ownership reconciled before replacing the profile;
never suppress required tracking/tests or launch again because no tracker exists.
if no compliant verifier exists, report blocked rather than coordinator self-
approval. no preflight authorizes network, production or publication operations.

### acceptance and validation

add portable dispatch contract checks in `tests/test_agent_tracking.py` and
`tests/test_workflow.py` for execution/tracking/report needs and unknown-capability
blocking. retain `tests/test_plan_workflow.py` independent-context requirements.
manual trials for each supported harness must use disposable projects and record
profile, allowed tools, helper round trip owned by the trial agent, exact-head
check, test/formatter availability and report write. include a deliberately
restricted profile and require a blocked result without duplicate dispatch.
static tests cannot certify native tool availability. success means unsupported
profiles are rejected before substantial work more often, without weakening a
required gate; count failed launches and setup restarts rather than infer latency.

## 7. reuse pinned tooling across worktrees

### current problem and evidence

`README.md`'s development section already recommends a separate formatter venv.
`Makefile` invokes `black` from path over python sources/tests; `requirements-dev.txt`
hash-pins black and dependencies and needs python 3.11+, whereas `make test` supports
python 3.9. the review cites repeated environment installation in
`data/autonomous-recipes/verify-02-result.md:44-47` and
`data/abra-plan/verify-03-output.md:66-68`. repeated setup, not formatting itself,
is the avoidable cost.

### proposed changes and seams

first consistently reuse the existing `README.md` approach. inspect installed formatter
environments before installing anything; validate executable/interpreter and all
installed pins against the candidate's requirements, then pass its absolute bin
path in worker/verifier briefs. document `PATH` setup in `README.md`, `AGENTS.md` and
`templates/worker.md`/`templates/verify.md`, with capability guidance from #6.
keep `make format` and `make test` as canonical final commands. adding a dependency
manager or changing pins is not needed for this gain.

if multiple versions actually need reuse, propose a simple manually prepared
tooling cache keyed by python implementation/major-minor, platform/architecture
and sha256 of exact `requirements-dev.txt` bytes. include actual resolved
interpreter identity/version in its receipt. create each environment exclusively,
install using existing hash-checked requirements, record key/pins and publish for
reuse only after a complete validation. do not mutate a shared ready environment
to satisfy another candidate; a different key gets a different directory. cache
lifecycle/setup must be separately authorized and need not be a new abra helper.
never treat a matching path name alone as proof of a valid installation.

### safeguards, compatibility and recovery

only trusted formatter executables/dependencies are shared; candidate project
imports, test outputs, probes, caches and mutable runtime environments stay in
isolated worktrees. do not expose credentials or run project install hooks in the
shared tool environment. candidates with changed requirement hashes or incompatible
python/platform do not reuse it. first implementation can retain manual `README.md`
setup when no validated cache exists. do not repoint system python for tests just
to use a newer formatter interpreter; record which python `make test` actually used.

a partial installation is unavailable, not ready; preserve/inspect it and create
another authorized location rather than overwrite a potentially used environment.
concurrent preparers must not write one directory. stale/missing tools block
required formatting until an authorized compatible setup is available; network
failure is not a pass. worktree cleanup must not remove the reusable tool path.
no blind shared writable project venv and no install on every verifier launch.

### acceptance and validation

update `tests/test_repository_contracts.py` for documented canonical targets if
needed, without pinning host-specific paths. later tooling setup tests should
exercise key changes for python/platform/requirements, reject incomplete/wrong-pin
environments and keep project output isolated; use temporary fixtures, not global
installs in unit tests. manually run two disposable worktree checks with one
validated tool environment: `make format` must use the pinned black, `make test`
must use the intended supported python, and the second run must not install.
record actual pin verification, environment path/key, commands and unchanged
candidate diff. measure install count and setup failures; do not claim a test-speed
improvement from sharing a formatter.

## 8. read relevant unfinished tasks at startup, not every task

### current problem and evidence

`AGENTS.md` startup requires full notes for all unfinished tasks, including held
items, before new work. the review notes only three other unfinished tasks at the
time, but cost grows with the whole portfolio. dashboard and registry/worktree
inventory already provide a useful discovery layer; task status alone is not
ownership evidence.

### proposed changes and seams

change startup guidance in `AGENTS.md` and `README.md`, and align recovery guidance in
`docs/workflows.md`/`docs/agent-tracking.md` without reducing full recovery:

- read the dashboard and worktree inventory, resolve the requested project through
  current `worktree.py resolve`, and honor specialty registry constraints;
- read full bodies for the target/resumed task, likely duplicates, dependencies,
  tasks sharing repository/worktree/branch/assignment resources and material
  promises. inspect held items whose blockers or ownership can affect the request;
- include cross-repository conflicts: shared libraries/services, multi-repo tasks,
  common publication targets, shared tooling or operator inputs and aliases.
  repository-name equality alone cannot establish irrelevance;
- broaden to full notes when summaries are ambiguous, links are missing, index
  information is insufficient to rule out overlap, ownership is uncertain, or a
  genuine global/session recovery requires it. use full read-before-update for
  every task being changed. fully reconcile any reused assignment/worktree and
  its manifest/briefs/checkpoints/artifacts regardless of dashboard status.

make #4's compact task summary carry discoverable scope/resource/dependency links
in the existing task body; do not add an indexed task database or assume tasks-axi
provides a new query api. inspect its actual `--help` before using any available
filter. `worktree.py list` lists registered repos, not native agent liveness;
combine existing inventory and recorded task/worktree evidence honestly.

### safeguards, compatibility and recovery

this is a policy change requiring approval, not a permission to skip unrelated
looking recovery evidence today. existing tasks with poor summaries trigger broader
reads until their next material handoff improves discoverability. preserve notes;
no bulk rewrite/backfill is necessary. uncertain ownership, missing native ids,
malformed trackers and interrupted intents remain blockers even across repos.
if a supposedly unrelated conflict appears during work, pause affected actions,
read/reconcile the task and record the conflict before continuing.

### acceptance and validation

add startup decision fixtures to contract tests in `tests/test_workflow.py` or
`tests/test_repository_contracts.py`: unrelated held item may remain summarized;
same-repo duplicate, multi-repo dependency, shared resource, alias ambiguity,
missing summary and global recovery require full inspection. review fixtures for
actual decision outcomes rather than phrase presence. perform a disposable recovery
walkthrough with one cross-repo task and an unknown old writer; new dispatch must
block. retain `tests/test_worktree.py` alias/collision/isolation checks. acceptance
is bounded startup reading without missing relevant blockers, not zero reading.
measure bodies opened and missed-conflict incidents at comparable portfolio sizes.

## 9. permit narrow method changes without another approval round

### current problem and evidence

`docs/workflows.md` requires operator approval for every later recipe selection;
`workflow.py validate` accepts coordinator selection only initially and `transition`
requires a new operator decision for subsequent selections. the review suggests
read-only research/triage method adjustment may not change the requested outcome,
but rates confidence moderate. this must not become general autonomous branching.

### proposed changes and seams

seek explicit operator approval for a narrow standing policy: coordinator may
switch between `research` and read-only `investigate` only if the original question,
scope, substantive acceptance, report deliverable, authority and delivery ceiling
are unchanged. no new diagnostic execution or access. preauthorization must be
saved with the original brief/policy revision and referenced by the coordinator
change decision; initial recipe-selection autonomy is not such preauthorization.
plan-package stages and implement are excluded, as are publication and lightweight
escape routes. if intent/deliverable is ambiguous, ask instead of classifying it
as method-only.

add a bounded eligibility check and selection-authority linkage in a proposed
versioned schema update to `bin/workflow.py` near selection validation and
`transition`. preserve fixed recipe shapes and append a selection with rationale,
unchanged-contract comparison and prior-selection/authorization evidence. a
proposed explicit `change_authorization` reference can distinguish preauthorized
coordinator method changes from operator recipe changes; exact fields must be
settled in that implementation brief. never simply allow any coordinator decision
for all later selections. retain full-proposal validation and typed builders from
#3 if available. update `docs/workflows.md`, `AGENTS.md`, `README.md`,
`docs/triage.md`, `docs/planning.md`, `docs/specialty.md` and
`docs/modes/specialty.md` to state permitted and excluded transitions consistently.

### safeguards, compatibility and recovery

before a switch, reconcile all old assignments as stopped and resolve any
outstanding coordinator action intent. retain old selection/attempt/checkpoint
history and the reason existing evidence is insufficient. repeated method changes
must not create an unbounded loop: propose at most one coordinator method switch
per task under the standing permission, then return to the operator. this is a
limit to approve with the policy, not a currently available allowance. do not reset
implementation or planning repair counts through selections, acceptance changes,
replacements or a detour into report-only work. budget exhaustion and blocked
validation still require operator intervention.

legacy v1 continues to require explicit operator approval for later selections.
use a versioned extension only on explicitly eligible new/migrated workflows;
do not infer preauthorization for old tasks. no migration discards decisions or
unresolved outcomes. if identity/authority comparison is uncertain or action may
have executed, block and reconcile rather than switch. revert policy for new
switches if ambiguity emerges; keep already recorded selections as history.

### acceptance and validation

extend `tests/test_workflow.py` around
`test_later_recipe_selection_still_requires_operator` and
`test_unresolved_coordinator_intent_cannot_be_archived_by_recipe_change`:
preauthorized unchanged research/read-only triage may switch once; absent permission,
changed question/acceptance/delivery, new probe permission, implementation/plan
transition, unresolved ownership/intent and second automatic switch reject.
legacy v1 tests stay intact. retain `tests/test_plan_workflow.py` pass/restart and
revision-do-not-reset-budget cases, and add attempted method-detour rejection.
a manual same-question investigation walkthrough must save rationale/authority and
produce only the requested report. measure avoided approval interruptions alongside
scope-confusion incidents; if safe eligibility is hard to explain, do not enable.

## 10. reduce maintenance ritual, not final evidence

### current problem and evidence

`tests/test_agent_tracking.py` asserts literal prose with embedded newlines for
safety and recovery rules. template assertions also appear in
`tests/test_workflow.py` and `tests/test_plan_workflow.py`. line reflow or safe
contract factoring causes failures unrelated to behavior. `AGENTS.md` requires
unit tests and formatting after each block, without distinguishing focused
iteration from canonical candidate gates.

### proposed changes and seams

- inventory each wording assertion: keep exact normative schema keys, placeholders,
  role names, version markers, stage order and command syntax; replace incidental
  line-wrap/prose identity assertions with structured contract extraction and
  targeted role/authority checks. use the compact contract boundaries/version
  from #2 as a stable seam. do not add a generic natural-language policy parser.
- use `checkpoint.validate`/`decode`, `workflow.validate`/`transition` and disposable
  cli trials for behavior. preserve tests that malformed/foreign/stale files are
  unchanged, replacement requires reconciliation, intents precede actions, required
  evidence/verdicts exist, histories are immutable and budgets are enforced.
- for rules enforced only by prompts, retain explicit invariant-to-location review
  and negative rendered-brief fixtures. removing a stop rule or reversing a role
  boundary must fail a meaningful contract check. normalizing whitespace can fix
  line-wrap brittleness; checking for a few safety keywords cannot establish that
  negation, ownership and authority are correct. state residual manual/live-review
  obligations rather than pretend unit tests enforce model compliance.
- clarify in `AGENTS.md`, `README.md`, `templates/worker.md` and `templates/verify.md`:
  during iteration run focused tests appropriate to each changed block and format
  changed python as needed; before committing a candidate run canonical
  `make format` and `make test` plus any task-specific required checks. independent
  verification reruns required gates at the exact candidate. doc-only work needs
  no artificial new unit test, but existing required final gates still apply.

### safeguards, compatibility and recovery

no runtime or schema migration is needed. change assertions alongside the contract
they cover and maintain a before/after coverage map. do not delete behavior tests
merely to shorten prompts or speed a suite. temporary probes stay in the verifier
worktree and must be distinguished from candidate changes. if formatter rewrites
candidate files during verification, report failure rather than silently repair.
unavailable dependencies/checks remain blocked; focused iteration is not a final
pass. a failing final check returns to the worker and fresh verification under
the existing bounded repair policy.

### acceptance and validation

update `tests/test_agent_tracking.py`, the template portions of
`tests/test_workflow.py`/`tests/test_plan_workflow.py`, `tests/test_triage.py` and
`tests/test_repository_contracts.py` only where contracts change. prove harmless
line reflow passes while deleting revision checks, weakening single-writer/role
boundaries or allowing repeat of an uncertain action fails. retain and run
`tests/test_checkpoint.py`, workflow/plan behavioral suites and worktree/specialty
coverage unchanged unless a separately approved behavior change requires updates.
run canonical final gates and an independent exact-candidate review for each code
package. compare safe prose-edit churn and iteration runs, not weaker final evidence.

## priority, dependencies and bounded later dispatch

these are proposed work packages, not scheduled tasks or authority to start work.
create later implementation briefs with the original request, explicit approved
policy/schema decisions, baseline/candidate, exact scope, checks and delivery
ceiling. each package gets normal worker -> independent verify -> authorized
local delivery; no push/pr/merge is implied. split further if acceptance is not
bounded. do not bundle all ten into one refactor.

| package | gain and bounded output | dependency / exit gate |
| --- | --- | --- |
| a | #6 capability checklist and harness-specific documented selection/trial evidence; no introspection service | first; demonstrate a usable verifier without bypasses |
| b | #7 existing formatter reuse instructions and validated path handoff; cache only if presently needed | independent of schema work; two-worktree reuse check |
| c | #1 split review/publication identity, conservative versioned compatibility, replay/tests/docs | approve identity/migration contract first; all invalidation/authority/ci cases pass |
| d | #2 compact portable contract and policy index, with the relevant wording-test work from #10 | approve invariant coverage map first; all roles and specialty overrides retain safety |
| e | #3 reserve/confirm typed workflow operations only | after c's chosen schema; identical validator and persistence behavior |
| f | #3 explicit verdict/delivery builders and narrowly typed agent-progress convenience | after e; preserve plan identities/repair limits and agent ownership |
| g | #4 state ownership division and compact read-only show | after e/f where helpful, but no hard dependency for doc-only ownership clarification; recovery works without mirrored progress |
| h | #5 lightweight routing and brainstorming boundary | operator approves eligibility/record minimum; after d/g so briefs/handoffs remain complete |
| i | #8 scoped startup | after g supplies discoverable summaries; operator approves cross-repo/broadening rules |
| j | #9 one preauthorized report-only method switch | last policy change; operator approves boundary/budget/versioning, after c/e; no unresolved-action escape |
| k | remaining #10 assertion cleanup and focused-vs-final cadence | can accompany d and relevant packages; behavioral coverage and final gates must stay intact |

first batch is a/b/c/d: observed failed launches, repeated tool installation,
publication-only re-review and large briefs have direct evidence. a/b enable
reliable verification of c/d. use e/f/g next to reduce recurring bookkeeping
without another coordination layer. h/i/j are separate policy decisions, not
optimizations workers may enable unilaterally. k should reduce incidental churn
as contracts evolve, not precede them with mass test deletion.

before c/j, settle the proposed versioned schema shape, saved identity bytes,
legacy-read behavior and explicit migration authority. before d, settle compact
contract/reference versioning. before h/i/j, approve their concrete allowed and
excluded cases. these are deliberate future decision gates; the current task
asks for a detailed plan, not authorization to make them active.
