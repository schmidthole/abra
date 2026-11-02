# durable coordinator workflows

one coordinator owns `data/<task-id>/workflow.json` in abra's root, outside project
worktrees. tasks-axi still owns the task lifecycle, holds and completion; link the
manifest's absolute path in the existing task body. the helper never calls tasks-axi,
launches agents, polls native state, or performs delivery. small direct answers need
no workflow; newly opted-in eligible lightweight work follows [routing](routing.md)
with durable task-local ownership/intent/outcome instead, not fabricated stages.
for a clear initial full delegated request, the coordinator selects the
smallest suitable fixed versioned recipe, records the choice and rationale, and
proceeds without asking the operator to choose a workflow. explicit operator
selections prevail; ask only when intent, scope, acceptance or authority is
materially ambiguous. save the full original request, acceptance criteria,
authority, constraints and requested delivery in a brief under `data/<task-id>/`
before initialization. reference the actual operator request/authority separately
from the recipe decision; never invent approval. recipe selection does not grant
publication, merge, production or other external-action authority. separate action
authority and delivery ceilings still apply.

## operational invariants

- [initial-selection] for clear initial full work choose the smallest suitable fixed recipe and save rationale; explicit operator choices and stricter specialties win. ask only for material intent, scope, acceptance or authority ambiguity. selection grants no publication, merge, production or other external-action authority.

- [method-switch] v1 later selections require operator approval. only new opted-in v2 report tasks may switch once between research and read-only investigate with initial saved operator preauthorization and unchanged full question, scope, acceptance, access, authority and report contract. reconcile every prior owner stopped and resolve every active, blocked or uncertain intent first. no probes, implement, plan, publication, lightweight detour or repair-budget reset.

- [review-reuse] v1 request/delivery revision changes require fresh verification. v2 reuse requires the latest actual passed verifier for the exact candidate, unchanged saved substantive implementation identity/base/check assumptions, no intervening worker and an explicit current comparison-evidence decision. current delivery authority, clean head, target/base, duplicate-pr, remote-head and required-ci gates remain; an old local receipt is not pr completion.

- [state-ownership] tasks-axi owns lifecycle and concise discoverable material handoff; coordinator alone owns manifest decisions/intents/next action; each agent alone owns checkpoint progress. immutable briefs/reports retain exact request/authority/evidence. no routine step mirroring, link-only handoffs or timestamp-wins conflict resolution; full relevant recovery and full-body-before-update remain mandatory.

- [final-gates] focused iteration never replaces canonical worker candidate make format and make test plus required task checks, or fresh independent exact-candidate gates. unavailable checks block. verifiers never repair product code; changed candidate requires fresh review. initial verification plus at most two repair rounds, with no method/replacement/acceptance detour reset.

## fixed version 1 recipes

| recipe | stable ordered stage ids | completion meaning |
| --- | --- | --- |
| `implement` | `worker`, `verify`, `deliver` | requested verified local commit, pr, or merge, within explicit authority |
| `investigate` | `triage`, `review`, `report` | coordinator reviews findings, then delivers the requested investigation report |
| `research` | `scout`, `report` | delivers the requested research report |
| `plan` | `refine`, `ground`, `validate`, `deliver` | report-only product direction and outcome-oriented slices; not product approval |

choose `implement` for clear code-change requests, `investigate` for unclear
reported behavior needing identification or reproduction, `research` for information
gathering, and `plan` for product direction/specification. use a direct answer for
small questions; do not add stages or ask a workflow-choice question for a clear
request. this autonomous choice applies to initial selection only: later recipe changes
require explicit operator approval in v1, not automatic branching. only new opted-in
v2 report tasks may use the once-only initially preauthorized same-contract read-only
method switch below; never an implementation/plan/lightweight or budget escape.

[planning](planning.md) defines its three portable briefs, plan-only package identity
fields, feedback/repair budget and exact report delivery protocol. refine/ground/validate
map to scout checkpoints, not the implementation verify role. existing v1 artifacts
remain valid unchanged.

`review`, `deliver` and `report` are coordinator stages, not new agent roles. there
is no generic dag, plugin, scheduler, runner or automatic branching. if research or
triage reveals implementation work, record the recommendation, obtain an explicit
operator recipe change (or create a separately authorized task), and append a new
selection. do not treat a report as code delivery. delivery/acceptance steering on
the same task appends a saved brief revision and explicit operator decision. retain prior scope, approvals and attempts; never
automatically branch or infer new authority.

## ownership and action protocol

| record | authoritative content | update trigger |
| --- | --- | --- |
| tasks-axi | lifecycle, discoverable original request/authority/steering, resource/dependency/promise links, material blocker and handoff/outcome | material steering, ownership, next safe action, delivery/lifecycle |
| coordinator manifest | selection/attempts/intents/outcomes/evidence-backed decisions and coordinator next action/blocker | before coordinator actions, after confirmed outcomes |
| agent checkpoint | assignment/native ids/coarse steps/confirmed progress/agent next action/blocker/artifacts | portable contract triggers |
| immutable briefs/reports | full request/authority/constraints/assignment and exact evidence | new immutable revision/report |

stop copying routine agent steps/manifest transitions into task notes. maintain
absolute links and enough summary to discover conflicts; no link-only handoffs.
save material steering before action; unresolved intents retain a concise task
warning. disagreement is reconciled, never timestamp-merged. [scoped startup](routing.md#scoped-startup)
includes cross-repo dependencies/resources/aliases/promises and broadens on ambiguity
or global recovery. full-body-before-update and complete ownership recovery apply
regardless of scope or status. inspect [capabilities](capabilities.md) before dispatch.


- the coordinator alone writes the manifest. the assigned agent alone writes its
  existing [checkpoint](agent-tracking.md); that ownership contract is unchanged.
  native run ids and detailed steps stay there (and native ids in task notes), not
  in the manifest. an attempt is a bounded stage try, not a native harness run.
- save the full filled portable assignment brief first. before spawning, persist
  an active attempt with intent, assignment reservation, absolute tracker path,
  role, predecessor, working directory and brief reference. reserve only one new
  attempt per update. every new assignment starts with `dispatch: "intent"`.
  supply workflow path, selection/recipe, stage and attempt in all role briefs,
  including specialty overrides. agents read this context but never write it.
- then act through the native harness. afterwards mark dispatch `confirmed` only
  for an observed launch/resume outcome; record actual progress/evidence. do not
  store native ids here. an interrupted intent may already have executed.
- before publication or delivery, reserve the coordinator attempt and its intent:
  identify the authorized action, target, candidate, checks and recovery lookup.
  inspect existing commits/prs/checks before acting. afterwards record the actual
  outcome, evidence and coordinator decision; never equate intention with success.
- terminal attempt decisions are explicit `coordinator` decisions, not translations
  of agent status. a completed verifier can have a failing verdict. all terminal
  attempts require outcome and evidence. references and decisions are assertions
  made by the coordinator: the helper cannot prove authority, truth, clean trees,
  test results, independent ownership, or external delivery.

## strict manifest version 1

all fields are required, with no unknown fields or duplicate json keys at any
level. json is utf-8, limited to 1 mib; booleans are not integer versions/orders.
all ids use lowercase slugs. timestamps are utc `YYYY-MM-DDTHH:MM:SSZ`; the helper
owns actual write time. no empty strings in place of null. keep summaries concise,
redacted and coarse; reference reports rather than copying their payloads.

| field | meaning |
| --- | --- |
| `version` | integer `1` |
| `task_id` | immutable tasks-axi identity; parent directory name |
| `updated_at` | actual helper write time, never a heartbeat |
| `briefs` | ordered immutable saved brief revisions; latest is current acceptance |
| `selections` | ordered recipe selections, latest is current; old selections retained |
| `decisions` | ordered immutable durable operator/coordinator/reconciliation decisions |
| `status` | `active`, `paused`, `blocked`, `completed`; never liveness |
| `current_stage` | current recipe stage id, or null when stages ended/repairs exhausted |
| `checkpoint` | confirmed coarse progress |
| `next_action` | intended next action, null only when no action remains; required for active |
| `blocker` | obstacle or null; required for blocked |
| `delivery_refs` | append-only confirmed delivery commits/paths/urls, initially empty |

nested objects have exactly these fields:

- decision: `id`, `kind` (`operator`, `coordinator`, `reconciliation`), `summary`,
  `evidence` (nonempty distinct reference array). record recipe selection and
  changes, revised acceptance, authority and consequential coordinator choices.
- brief: `reference` (absolute saved full brief path), `acceptance_revision`
  (64 lowercase hex characters, unique across briefs), `requested_delivery`
  (`report`, `local-commit`, `pr`, or `merge`; not authority by itself), `decision`
  (operator decision id). compute a sha256 of the saved acceptance, requested
  delivery and authority text; change it whenever any of those changes,
  even at the same candidate. preserve prior saved briefs; do not edit them in
  place. the helper validates syntax/linkage, not the hash's asserted meaning.
- selection: `id`, `recipe`, `version` (integer `1`), `rationale`, `decision`
  (operator or coordinator decision id for the initial selection; operator decision
  id for every later selection), `stages`. a coordinator selection decision records
  suitability, not operator approval or action authority. brief decisions remain
  operator-only. changing recipe requires appending a selection and a new operator
  decision; never rewrite the selected recipe in place.
- stage: `id`, `attempts`. stages exactly match the fixed recipe in order. no
  separate stage status: the coordinator's attempt outcomes determine progress.
- attempt (existing recipes; plan adds `package` and `result_package` as defined in
  [planning](planning.md)): `id`, `order`, `status`, `intent`, `assignments`,
  `acceptance_revision`,
  `candidate_commit`, `verdict`, `report`, `outcome`, `evidence`, `decision`.
  `order` is contiguous from 1 across the current selection, regardless of stage;
  per-stage arrays retain that order. ids are unique across the whole workflow.
  status is `active`, `blocked`, `passed`, or `failed`. intent is nonempty;
  outcome/decision are null until resolved. evidence is a distinct reference
  array, initially empty. a terminal attempt needs nonempty outcome/evidence and
  a new distinct coordinator decision id. `candidate_commit` is null or a full lowercase
  40/64-hex commit; passed worker and every implement verify/deliver attempt need
  the exact candidate. `verdict` is null except verify (`pass`, `fail`, `blocked`)
  and plan validate (`ready`, `needs revision`, `blocked`). terminal
  verification requires matching passed/pass or failed/fail and a report path/url.
  `report` is otherwise null or a path/url; successful scout, triage and report
  attempts require it. coordinator stages have `assignments: []`.
- assignment link: `assignment`, `role`, `predecessor`, `tracker`, `brief`,
  `working_directory`, `dispatch`, `reconciliation`. identity matches the existing
  checkpoint contract; predecessor and working directory may be null. tracker is
  exactly this task's `agents/<assignment>.json`. brief is an absolute full filled
  brief path. dispatch is `intent` or `confirmed`; reconciliation is null or a
  reconciliation decision id documenting checked native ownership and artifacts.

paths are absolute without `..`; evidence/delivery references may also be full
lowercase 40/64-hex commits or urls with a scheme and location. report fields use
paths/urls. references do not grant access. the helper does not dereference
references during writes. `show` checks local regular references
with a 1 mib bound and reports missing/unsafe/oversized references; external urls
(including file urls) and commit references are explicitly unchecked. checkpoint
references are read with supplied link identity, no-follow traversal and strict checkpoint v1 validation.

### transitions and verification

history cannot be removed or rewritten: decisions/briefs append; selections retain
stable ids/stages, attempts retain identity/order/intent/acceptance and any known
candidate. passed/failed attempts are immutable except a later reconciliation
annotation on an assignment. assignment identity is immutable, dispatch cannot be
unconfirmed and a recorded reconciliation cannot be replaced. only the final
attempt may remain active/blocked. a new attempt must be persisted active, without
outcome/evidence/approval, before action. initialization has one selection and no
attempts or delivery references. a blocked attempt requires the workflow blocker.
resolve an outstanding coordinator delivery intent before switching recipes; an
operator recipe change is not permission to forget an uncertain delivery action.

implement advances worker -> verify -> deliver. a verifier must examine the latest
passed worker's exact candidate, with the current acceptance revision. no passed
agent status substitutes for report, explicit verdict and coordinator decision.
changing candidate requires a new worker attempt, then a fresh verify assignment;
in v1, changing acceptance or delivery scope requires a new saved brief and operator
decision and fresh verification even if code is unchanged. opt-in v2 reuse below
requires explicit substantive comparison evidence, not inferred commit equality. a changed report scope
reopens the report stage; the coordinator decides whether a new recipe selection
or upstream work is needed. old approvals remain evidence, not current permission. a new worker deliberately invalidates prior approval. delivery must
match the approved exact candidate/acceptance, and the coordinator still checks the
worker tree is clean and head unchanged. required ci pending/failing prevents a
successful pr delivery; no checks is not 'ci passed'.

failed verification returns to a new worker attempt, then a fresh verifier. initial
verification plus at most two repair rounds are allowed within a selection; after
the third failing verdict, no further attempts can be appended. block/pause and
summarize to the operator, not an automatic retry. changing recipes is an explicit
operator choice, never a way for the coordinator to silently bypass this limit.
non-verification failed stages may be explicitly retried, preserving history.

same-assignment resume keeps attempt/assignment and stable tracker steps; native
run changes alone do not create attempts. replacement appends a fresh assignment
with predecessor and a new tracker/brief, after a reconciliation decision on the
old assignment records confirmed stopped ownership. replacements for the same bounded goal
can stay in that attempt; repairs need a new worker attempt. a fresh verify never
reuses another attempt's assignment. unresolved dispatch blocks replacement or
progress; missing native id is not permission to launch again.

completed requires the final deliver/report attempt to pass, confirmed outcome and
evidence, and nonempty delivery refs contained in that evidence. local-commit
completion needs the exact candidate commit reference; pr/merge needs a confirmed http(s) url;
report delivery needs the report reference. implement delivers code, other recipes
reports; the requested delivery must match. tasks-axi completion
is a separate explicit coordinator action only after requested delivery is achieved.

## cli and example

```sh
python3 bin/workflow.py --help
python3 bin/workflow.py init --help
python3 bin/workflow.py read --help
python3 bin/workflow.py update --help
python3 bin/workflow.py show --help
```

all operations require absolute task-local `workflow.json` and `--task-id`. `init`
and `update` require a complete manifest via `--proposal -` (stdin preferred) or an
absolute already-authorized json file. there is no patch command. `read`, `init`
and `update` return `{"workflow": <validated manifest>, "revision": "<sha256>"}`.
`update --revision <last-read-revision>` checks exact prior bytes, not timestamps;
reread and reconcile a conflict, never blindly retry using a fresh token. `show`
returns that envelope plus stages/attempts joined to checkpoint objects, issues and
a notice: observations are not liveness, approval or repeat-action authorization.
it does not alter files, consult tasks-axi, git, prs or native harness state.

this initial example assumes the full brief already exists at the supplied path:

```json
{
  "version": 1,
  "task_id": "example",
  "updated_at": "2026-06-01T12:00:00Z",
  "briefs": [{"reference": "/srv/abra/data/example/brief.md", "acceptance_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "requested_delivery": "local-commit", "decision": "request"}],
  "selections": [{
    "id": "selection-01", "recipe": "implement", "version": 1,
    "rationale": "clear code-change request needs worker and independent exact-candidate verification",
    "decision": "select",
    "stages": [{"id": "worker", "attempts": []}, {"id": "verify", "attempts": []}, {"id": "deliver", "attempts": []}]
  }],
  "decisions": [
    {"id": "request", "kind": "operator", "summary": "operator requested a code change; authorized local verified commit only", "evidence": ["/srv/abra/data/example/brief.md"]},
    {"id": "select", "kind": "coordinator", "summary": "selected implement v1 as the smallest suitable recipe; no additional action authority", "evidence": ["/srv/abra/data/example/brief.md"]}
  ],
  "status": "active",
  "current_stage": "worker",
  "checkpoint": "saved full request, acceptance, authority and recipe selection",
  "next_action": "reserve worker attempt and assignment before dispatch",
  "blocker": null,
  "delivery_refs": []
}
```

```sh
# send the complete example on stdin; save the returned revision.
python3 /srv/abra/bin/workflow.py init /srv/abra/data/example/workflow.json \
  --task-id example --proposal -
python3 /srv/abra/bin/workflow.py read /srv/abra/data/example/workflow.json --task-id example
# complete_proposal is the manifest, not the output envelope.
printf '%s\n' "$complete_proposal" | python3 /srv/abra/bin/workflow.py update \
  /srv/abra/data/example/workflow.json --task-id example --revision "$last_read_revision" --proposal -
python3 /srv/abra/bin/workflow.py show /srv/abra/data/example/workflow.json --task-id example
```

## interruption recovery

1. read the full tasks-axi body, manifest, saved original/current brief, filled
   assignment briefs and strict assignment checkpoints. use supplied identity,
   not identity guessed from foreign files. show is an observation aid only.
2. reconcile native harness state/ownership, actual worktree files/heads, commits,
   reports, prs and required checks. timestamps and `active`/`completed` statuses
   never establish liveness, current truth, approval or that an action did not run.
3. an intent with missing native id or missing checkpoint may already have
   dispatched. unknown ownership blocks work; do not authorize a duplicate or
   replacement automatically. confirm prior writer stopped before resume/replacement.
4. if commit/pr/delivery happened before outcome persistence, inspect and record
   that actual result with reconciliation evidence rather than repeating it.
   preserve an uncertain outcome and blocker until resolved. record task notes too.
5. preserve missing-on-resume, malformed, foreign, stale, unsafe or conflicting
   files and leftover temporaries. no reset, automatic repair/promotion/deletion,
   or parsing partial fields for progress. resolve discrepancies before further
   action; record explicit decisions and confirmed artifacts, not inferred success.
6. use revision-checked complete updates, persist next intent, act only within
   authority, then record confirmed outcome. before yielding, save next action,
   blockers and task/manifest/checkpoint links sufficient for a fresh coordinator.

## file guarantees and limits

small safe file primitives are shared with `checkpoint.py`; its strict v1 format,
identity/cli and agent ownership are unchanged. both use pinned no-follow parent
traversal, bounded regular files, exclusive mode-0600 same-directory temporaries,
exclusive hard-link init and atomic replacement update. parents may be created by
init with mode 0700. validate complete replacement before publication; never
truncate the existing destination. update rechecks identity/revision just before
replacement. errors are nonzero redacted json on stderr with operation/path;
argparse usage errors use argparse output. malformed payloads/foreign contents are
not echoed. successful output is on stdout.

this is local posix persistence, not a security boundary, locking, compare-and-swap,
exactly-once execution, or a power-loss/fsync guarantee. single reconciled
coordinator ownership and trusted parent directories remain required. concurrent
writers can race between the last check and replace. interruption before publication
preserves prior state; after publication but before output/cleanup, the new state
may already exist: reread and reconcile, do not claim rollback. an uncatchable kill
can leave an owned temporary; it is not authoritative and is never auto-promoted.
prompt contracts and helper validation cannot ensure model compliance.

## automated interruption trials

`tests/test_workflow.py` exercises disposable project fixtures inside the assigned
worktree's `.cache/workflow-trials/`, cleaned after each test. these are simulated
harness events, not actual native agent interruption trials. a real local git
commit is performed before an intentionally omitted outcome update; recovery
inspects the existing head and records it without another commit. pr interruption
uses a local json receipt instead of an external api. dispatch interruption uses
real checkpoint files with unknown native ids; replacement is rejected until an
explicit ownership reconciliation. trials cover same-assignment resume vs
replacement, failing completed verifier, repair history/limit, criteria/candidate
invalidation, report-vs-code delivery, strict file/path preservation and read-only
show. existing checkpoint, specialty and template contract tests still apply.

these tests do not establish native harness ownership/compliance, real pr/ci
reconciliation, filesystem behavior under power loss, or unattended recovery.
actual native trials still need disposable projects, explicit action authority,
and a coordinator checking native state and artifacts at each interruption point.

## opt-in manifest v2: review reuse and report-only method changes

new workflows may explicitly initialize `version: 2`; recipe versions remain `1`.
v1 remains strict and conservative, including renewed verification after a delivery
revision. neither `update` nor a convenience command migrates between versions.
old binaries reject v2. do not convert an in-flight task or backfill old identities.
all existing fields, validators, single-writer/revision checks and atomic publication
rules still apply. v2 adds these required fields (no unknown fields):

- every brief: `implementation_identity` and `report_identity` (nullable).
- every selection: `change_authorization` (nullable).
- manifest: `implementation_reuses` (initially `[]`) and `method_authorization`
  (nullable, fixed at initialization).

for implement/code delivery, `implementation_identity` is required:

```json
{"base":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","revision":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","contract":"/absolute/task/implementation-contract.md"}
```

`revision` is the sha256 of exact saved substantive contract bytes, asserted by the
coordinator. save the original problem, acceptance, constraints, required local
checks, environment/dependency/security assumptions and review assumptions in that
contract; explain delivery-only exclusions. keep the exact bytes, not a mutable
link. hashes and paths identify assertions, not semantic equivalence or authority.
`report_identity` is null for implement and plan; plan retains exact package rules.
report-only research/investigate may save
`{"reference":"/absolute/task/read-only-contract.md","revision":"<sha256>"}`;
its implementation identity is null.

### explicit reuse, not synthetic verification

append a reuse record only after a new operator-approved full brief/delivery
revision, with a **new coordinator decision**:

```json
{"verify_attempt":"verify-2","acceptance_revision":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","decision":"reuse-1"}
```

it must link the latest actual passed verifier in the current implement selection,
with no intervening worker (even at the same candidate) or verifier. the original
and new saved implementation identities must be exactly equal, including base and
contract path/hash. the coordinator decision must explicitly compare saved contracts,
checks and assumptions, and cite both full briefs, the substantive contract and the
original verifier report as evidence. candidate equality alone is insufficient.
a changed substantive identity requires fresh independent exact-candidate review.
old reusable records remain history but cannot approve a later worker's output.

reuse opens **deliver**, not completion: reserve a new deliver attempt bound to the
current full acceptance/delivery revision; retain prior local receipts. a passed
local deliver cannot complete a pr request. the helper never manufactures a passed
verify, reads git, executes a check or grants action authority. before publication,
the coordinator must independently establish current operator authority/specialty
ceiling, clean worker tree and exact reviewed head, target repo/branch/base and
assumption applicability; inspect existing prs before creation, verify remote/pr
head after push, and inspect required ci at that exact head. record fresh evidence
and decision on the new deliver attempt. pending/failed/unavailable required checks
block delivery; absent checks are not ci passed. reconcile uncertain publication
before retrying. these external checks are not performed by workflow helpers.

### one preauthorized read-only method switch

at initialization only, a report-only task may save:

```json
{"decision":"operator-read-only-preauth","acceptance_revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
```

as `method_authorization`. its operator decision must cite the initial full brief
and saved `report_identity.reference`. those saved bytes must explicitly authorize
at most one research <-> **read-only** investigate method switch without changing
the question, acceptance, scope, access, authority or report deliverable. no new
diagnostic probes. initial recipe autonomy is not this permission. the helper
validates linkage, not the natural-language authority in those bytes.

append a new fixed recipe selection, with a new coordinator comparison decision
citing that same full brief and report contract, and:

```json
{"authorization":"operator-read-only-preauth","prior_selection":"selection-01","reconciliation":"stopped-owners-1"}
```

as `change_authorization`. `reconciliation` must be a new explicit reconciliation
decision. every prior attempt must be terminal; every prior assignment must have
confirmed dispatch and a stopped/reconciled ownership decision. resolve active,
blocked or uncertain dispatch/coordinator intents before switching. all history
is retained. implement, plan, diagnostic execution, publication and a second
coordinator switch are excluded. absent permission uses operator approval, not
inferred eligibility. v1 always needs operator approval for later selections.

this minimal v2 representation conservatively freezes the full report brief revision
for tasks using a preauthorized switch; a later changed contract cannot retain that
switch as eligible. ask for a separately authorized task instead of rewriting
history. operator recipe selections remain possible otherwise, but cumulative
implementation failures and planning validation/blocked budgets across v2 selections
cannot be reset by a detour, acceptance change or replacement.

## typed coordinator operations

`init`, `read`, full-proposal `update` and full `show` remain supported. routine
operations accept a small exact-key json object, bounded to 1 mib, duplicate-free
at every depth, with no non-finite numbers. use the supplied task identity and the
last observed revision:

```sh
python3 /absolute/abra/bin/workflow.py reserve /absolute/data/example/workflow.json \
  --task-id example --revision "$last_read_revision" --request -
```

all typed commands use `--request -` (stdin preferred) or an already authorized
absolute regular file. they copy validated current state, build a complete proposal,
run the same full validator/transition rules, then use `write_workflow` with its
existing identity, two revision checks, exclusive staging and atomic replacement.
v1 stays v1; v2 stays v2. ids are deterministically the first unoccupied
`<stage>-<n>` / `coordinator-<n>` across saved history. assignment ids/paths remain
caller-supplied; collisions reject. output is the usual workflow/revision envelope.
no arbitrary patch, force, approval inference, dispatch, git, tasks-axi or retry.

### reserve / reserve-delivery

`reserve` handles agent/coordinator review stages; `reserve-delivery` handles
`deliver`/`report`. both require exactly:

```json
{
  "stage": "worker",
  "intent": "authorized local implementation; reconcile native ownership and actual artifacts before repeating",
  "assignment": {
    "assignment": "worker-01",
    "predecessor": null,
    "tracker": "/absolute/data/example/agents/worker-01.json",
    "brief": "/absolute/data/example/worker-01.md",
    "working_directory": "/absolute/worker-tree"
  },
  "candidate_commit": null,
  "package": null,
  "checkpoint": "full request and authority saved; no launch yet",
  "next_action": "launch the reserved assignment"
}
```

stage role, attempt id/order, active status, current acceptance, dispatch intent and
empty outcome fields are mechanical; no role is inferred from a checkpoint.
coordinator stages require `assignment: null`. supply the exact candidate for
verify/implement deliver; plan uses null candidate and its complete package object
(or null for initial refine). non-plan `package` is null. replacements require
explicitly reconciled stopped predecessors, never takeover based on status.

for delivery, the caller's `intent` must name the currently authorized target,
candidate/package, delivery ceiling and actual lookup/reconciliation needed before
retrying publication. reservation records an intention, not an observed action or
permission. paused workflow state remains paused; full update handles unusual
reconciled edits and explicit unblocking.

### confirm-dispatch

requires exactly `attempt`, `assignment`, `summary`, `evidence`, `checkpoint`,
`next_action`. example:

```json
{"attempt":"worker-1","assignment":"worker-01","summary":"observed native launch receipt, not stage approval","evidence":["/absolute/data/example/launch-receipt.md"],"checkpoint":"launch confirmed","next_action":"wait for actual result"}
```

only an unresolved dispatch on an unfinished attempt may be confirmed. nonempty
observed evidence and an explicit caller summary are persisted in a new coordinator
decision; repeat confirmation rejects. no native calls or run-id fabrication.

### decide / record-delivery

`decide` requires exactly these fields; the helper derives the linked coordinator
decision id and replayed current stage, never the verdict:

```json
{
  "attempt": "verify-1",
  "status": "passed",
  "verdict": "pass",
  "report": "/absolute/data/example/verify-report.md",
  "candidate_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "result_package": null,
  "outcome": "independent exact-candidate review and all required checks passed",
  "evidence": ["/absolute/data/example/verify-report.md"],
  "summary": "coordinator reviewed actual evidence and accepts this stage",
  "checkpoint": "verification evidence reviewed",
  "next_action": "reserve authorized delivery",
  "blocker": null,
  "workflow_status": "active"
}
```

`status` is explicitly `passed` or `failed`. only verify uses `pass`/`fail` verdict;
plan validate uses `ready`/`needs revision`/`blocked`; all other verdicts are null.
non-plan result packages are null. plan keeps exact input/result/document/evidence
constraints. candidate mutation, wrong stage/role, absent report/evidence, unresolved
dispatch, terminal edits and exhausted repairs reject identically to full update.
`workflow_status`/next action/blocker are explicit caller assertions; a checkpoint
saying completed is never a stage pass. use full update for a blocked nonterminal
attempt, not a manufactured terminal decision.

`record-delivery` is the same exact schema **plus** `delivery_refs`, an array of
new observed references to append (not already recorded). it handles only
`deliver`/`report`. include actual receipt and fresh required-check evidence in
`evidence`, not planned results. explicitly choose `workflow_status: "completed"`
and `next_action: null` only when all requested delivery conditions hold. existing
receipts remain history and must also be supported by the final evidence. failed
or pending publication does not become success through code-review reuse.

### recovery and read-only compact show

an operation may publish before interruption/output failure. reread and reconcile
native ownership and actual artifacts; do not blindly repeat `reserve`, confirmation
or publication with a refreshed revision. stale tokens preserve bytes. helpers do
not lock, guarantee exactly-once actions or prove stopped owners, truthful evidence,
semantic equivalence, authority or power-loss durability.

`workflow.py show PATH --task-id TASK --compact` observes the current selection,
coordinator stage/status/checkpoint/next action/blocker, current/original request
links, latest attempt's coordinator decision/verdict and latest assignment's separate
agent status/progress (including the last agent during coordinator delivery), review
coverage/reuse decision and all reference/checkpoint issues. full `show` is unchanged.
no task writes or cached combined database. it does not inspect tasks-axi, native
liveness, git/remote/pr/ci state, report truth or contract bytes; publication readiness
is always explicitly unchecked. completed agents with failed coordinator verdicts
remain visibly different. missing/malformed/foreign checkpoints and unresolved
intents are observations requiring reconciliation, not authorization to repeat.
use the full records/briefs and actual evidence for recovery even if compact looks
complete. tasks-axi still owns lifecycle; the manifest owns coordinator decisions;
agent checkpoints alone own detailed agent progress.
