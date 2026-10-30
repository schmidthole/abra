# durable coordinator workflows

one coordinator owns `data/<task-id>/workflow.json` in abra's root, outside project
worktrees. tasks-axi still owns the task lifecycle, holds and completion; link the
manifest's absolute path in the existing task body. the helper never calls tasks-axi,
launches agents, polls native state, or performs delivery. small direct answers need
no workflow. for delegated tasks, the operator selects a predefined recipe; the
coordinator may recommend, not silently choose or branch. save the full original
request, acceptance criteria, authority, constraints and requested delivery in a
brief under `data/<task-id>/` before initialization. reference the operator's actual
selection/authority, not an invented approval.

## fixed version 1 recipes

| recipe | stable ordered stage ids | completion meaning |
| --- | --- | --- |
| `implement` | `worker`, `verify`, `deliver` | requested verified local commit, pr, or merge, within explicit authority |
| `investigate` | `triage`, `review`, `report` | coordinator reviews findings, then delivers the requested investigation report |
| `research` | `scout`, `report` | delivers the requested research report |

`review`, `deliver` and `report` are coordinator stages, not new agent roles. there
is no generic dag, plugin, scheduler, runner or automatic branching. if research or
triage reveals implementation work, record the recommendation, obtain an explicit
operator recipe change (or create a separately authorized task), and append a new
selection. do not treat a report as code delivery. delivery/acceptance steering on
the same task appends a saved brief revision and explicit operator decision. retain prior scope, approvals and attempts; never
automatically branch or infer new authority.

## ownership and action protocol

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
  (operator decision id), `stages`. changing recipe requires appending a selection
  and a new operator decision; never rewrite the selected recipe in place.
- stage: `id`, `attempts`. stages exactly match the fixed recipe in order. no
  separate stage status: the coordinator's attempt outcomes determine progress.
- attempt: `id`, `order`, `status`, `intent`, `assignments`, `acceptance_revision`,
  `candidate_commit`, `verdict`, `report`, `outcome`, `evidence`, `decision`.
  `order` is contiguous from 1 across the current selection, regardless of stage;
  per-stage arrays retain that order. ids are unique across the whole workflow.
  status is `active`, `blocked`, `passed`, or `failed`. intent is nonempty;
  outcome/decision are null until resolved. evidence is a distinct reference
  array, initially empty. a terminal attempt needs nonempty outcome/evidence and
  a new distinct coordinator decision id. `candidate_commit` is null or a full lowercase
  40/64-hex commit; passed worker and every verify/deliver attempt need the exact
  candidate. `verdict` is null except verify (`pass`, `fail`, `blocked`). terminal
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
changing acceptance or delivery scope requires a new saved brief and operator
decision and fresh verification even if code is unchanged. a changed report scope
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
  "briefs": [{"reference": "/srv/abra/data/example/brief.md", "acceptance_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "requested_delivery": "local-commit", "decision": "select"}],
  "selections": [{
    "id": "selection-01", "recipe": "implement", "version": 1,
    "rationale": "operator requested a bounded implementation",
    "decision": "select",
    "stages": [{"id": "worker", "attempts": []}, {"id": "verify", "attempts": []}, {"id": "deliver", "attempts": []}]
  }],
  "decisions": [{"id": "select", "kind": "operator", "summary": "operator selected implement; authorized local verified commit only", "evidence": ["/srv/abra/data/example/brief.md"]}],
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
