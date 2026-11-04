# local polling-only linear connector

this is a project-local pi extension, not a service, webhook receiver, tunnel,
relay, daemon, custom agent runtime or replacement backlog. **one ticket per
explicit `/abra-linear start`**: while waiting, the dedicated local session polls
for eligible work. after terminal reporting it admits nothing else. release all
owners, then use another explicit start for the next ticket. nothing runs when pi
exits or the machine sleeps; no unattended lifetime is promised.

## setup and authority

requires node 24+ and pi with the documented session replacement/lifecycle api
(`newSession`, `session_start.reason`, `session_shutdown`, `getSessionId`). the
implementation was developed against installed pi docs and examples, including
`send-user-message.ts` and `13-session-runtime.ts`. it has **not** been installed,
started against linear, or tested with live credentials as part of this delivery.

1. review/trust this checkout. pi discovers `.pi/extensions/abra-linear/index.ts`
   after project trust; `/reload` loads changes. no npm install is needed: the
   entrypoint uses host pi exports and the connector uses node built-ins only.
   loading/registering commands makes no network calls and starts no timer.
2. register each real repository through the existing worktree registry; check
   its path/origin/base and project instructions. map it explicitly below. never
   use a ticket-supplied path or guess an unknown project.
3. prepare a workspace-installed oauth app with its own agent app-user persona
   and delegation capability (`app:assignable`); authorize only the scopes needed
   to read scoped issues/comments/states and write ordinary comments/issue status.
   follow linear's current public oauth documentation for provisioning/refresh.
   the connector does not install an app, refresh tokens, or store credentials.
   no webhook or native agent-session subscription is required. a personal key
   for a different viewer is intentionally rejected, not a fallback identity.
4. copy `docs/linear.example.json` to `.pi/abra-linear.json` and replace **all**
   example values. that local configuration is gitignored. `tokenEnv` is an
   environment variable **name**, never a token or shell command. populate that
   variable in the dedicated pi process using your existing secret mechanism.
   `viewer.id` must equal `personaId`, and `organization.id` must equal
   `workspaceId`; the credential itself must enforce the intended app identity.
5. allowlist each team and exact working/in-review/blocked status uuid. all three
   must differ, belong to that team, and be nonterminal; working must be `started`.
   blocked is never guessed from a label/name/category. no completed/canceled
   transition is implemented. start validates identity and all paginated states
   before discovery or any mutation.
6. map exactly one explicit linear **routing label uuid** to each registered
   repository (`name`, local `path`, github `remote`, target `base`, `teamId`).
   linear issues have no universal repository field: this is an operator-owned
   mapping, not a title/url heuristic. an eligible issue is currently delegated
   to the configured persona, belongs to an allowlisted team, is nonterminal,
   and matches exactly one routing label for that team. issues with ambiguous
   labels or more than 100 labels are not admitted (routing coverage is unknown).
7. the operator's configuration/start authorizes pickup and reporting for **all
   current delegations inside this scope**, under the configured ceiling. if
   that is too broad, restrict the team/routing labels/app's access before start.
   ticket text and comment authors cannot elevate permissions. use a dedicated
   workspace/team when arbitrary users can delegate untrusted requests.

`authority` defaults to `{ "mode": "report" }`. this permits research/report
work and linear progress/report comments, **not source implementation or github
publication**. if original intent requires code without code/publication authority,
report blocked, not a substitute report marked in review. optional bounded code/pr
operation requires operator-owned configuration such as:

```json
{ "mode": "pr", "maxFiles": 8, "maxChangedLines": 400 }
```

these ceilings apply in addition to the configured repositories/base and normal
abra delivery checks. no merge/deployment/issue-close authority is supported.
configuration changes are not silently applied to old correlations: their identity
hash must match. never reset old metadata to broaden authority. reconcile existing
owners and preserve/archive their evidence before a separately approved config
migration. scope/path permissions remain the operator's responsibility.

## controls and clean-session boundary

- `/abra-linear start`: requires idle pi, no queued messages, configured credentials,
  no unresolved correlation or host lock, and explicit UI confirmation. saves the
  unrelated current session as parent, then opens a clean dedicated task session.
  only this new-session handoff arms polling. no old pi/context is used after
  replacement. the new runtime owns timers and dispatch. waiting is autonomous;
  admission of one issue consumes that session even if dispatch is uncertain.
- `/abra-linear pause`: stop admission; active issue control polling continues.
- `/abra-linear status`: mode, last successful poll, next scheduled poll, error,
  active issue, dispatch outcome, halt reason, terminal outcome and pending
  publication keys. off does not imply stopped native agents.
- `/abra-linear poll`: one serialized reconciliation while started/paused; never
  dispatches when paused. while off, use explicit start or reconciled resume first.
- `/abra-linear stop`: immediately disable admission, abort current connector I/O,
  request coordinator cancellation/reconciliation and report blocked if accessible.
  active control polling continues so outstanding receipts can be observed. this
  is not proof that subprocesses/native subagents have stopped.
- `/abra-linear resume`: after inspecting saved task/manifest/dispatch/native owners,
  reopen the **recorded owning pi session** and explicitly confirm control polling.
  admission stays paused. reload/restart never auto-enables, redispatches or replays
  uncertain writes. ordinary interactive prompts are rejected in dedicated sessions;
  use linear comments for steering and slash controls for local operations.
- `/abra-linear release <concrete stopped-owner evidence>`: explicitly confirm all
  native/subprocess owners stopped/reconciled. requires a terminal checkpoint, idle
  coordinator, non-active validated workflow and resolved publication receipts.
  saves the redacted evidence, releases the correlation and local lock. a blocked
  task does not free ownership automatically. blocked work remains in tasks-axi;
  release does not mark it complete or authorize replacement.

session switching, forking and tree navigation are refused while this extension
owns an active issue. shutdown/reload cancels connector I/O, drains its serialized
operations and releases only its process lock, never the active correlation. pi's
session tree remains the conversation store; tasks-axi remains lifecycle authority,
workflow manifests coordinator decisions, and native agents execution/ownership.

## pickup, checkpoints and delivery

discovery refetches current issue/delegation and ingests existing human comments
before reservation. correlation uses workspace/config identity and immutable issue
uuid, never a mutable title. it records pickup and dispatch intents **before** the
external action. accepted work gets a pickup comment and the configured working
state; only after confirmed pickup does the coordinator receive the original
source snapshot and policy prompt. repeated scans, reloads, title edits and missed
delegate toggles never create a second execution. there is no automatic rerun
protocol in v1; a genuinely new request should use a new issue after reconciliation.

coordinator instructions require original intent/acceptance, local project rules,
scoped startup, saved immutable source/task, task/worktree/manifest/native ownership,
intent-before-dispatch, canonical tests, fresh independent exact-candidate verification
for substantive changes, authorized actual PR/report delivery, then in review **or
blocked**. the task id is `linear-<issue-uuid>`. create its real tasks-axi task and
`data/<task-id>/workflow.json` using existing helpers, not connector-private tasks.

`abra_linear_checkpoint` is the structured coordinator tool:

| field | contract |
| --- | --- |
| `kind` | `bind`, `approach`, `progress`, `checks`, `blocked`, `review` |
| `key` | stable unique lowercase checkpoint slug; retries keep the same key/body |
| `summary` | concise public confirmed facts, never raw reasoning/tool logs |
| `approach`, `checks` | meaningful approach and checks/tests including failures/unrun checks |
| `nextAction` | explicit next safe action, including at terminal handoff |
| `blocker` | required for blocked; concrete reason, not generic failure |
| `report` | for report review, exact confirmed workflow delivery reference |

first bind the task's existing validated manifest before native dispatch. bind
checks the deterministic helper's schema/identity, not a model's “done” string.
post approach, meaningful progress, check/test outcomes and blockers at milestones,
not every token/tool call. checkpoint comments are bounded to 16000 characters.

review requires the real workflow to validate as completed using `bin/workflow.py
read`; the existing helper enforces recipe/decision/candidate/delivery discipline.
for code it must be **pr delivery**, opt-in code authority, a PR URL under the
configured remote, worker and independent exact-candidate pass, current clean
worker head/origin and bounded file/changed-line diff against the configured base.
source code still relies on the existing coordinator's approved delivery receipts
for actual PR target/head/required CI and authorization; this connector does not
independently poll github or grant authority from a URL. a local commit is not an
accessible PR. a report is not code delivery. no success is inferred from
`agent_end`, `agent_settled` or prose. settling without a terminal checkpoint posts
a truthful blocked comment/state instead.

for a report, supply a confirmed HTTPS report URL, or a concise public report file
**inside the task artifact directory** that is itself in `delivery_refs`. local
files are limited to 12000 bytes; the entire public content is posted to linear,
not just a private local path. create a redacted deliverable intentionally, not raw
logs or the private internal report. oversize/missing/unreadable/empty reports block
the transition. the checkpoint comment is confirmed **before** status mutation.
partial outcomes remain visible in connector receipts; do not rerun task execution
to fix reporting.

active issue polling is independent of discovery: undelegation, foreign team,
terminal state, routing change, material title/description/label edits, new/edited
human comments (including `/abra stop`) or unavailable control polling halt new
work and request cancellation/reconciliation. ordinary comments are the reliable
polling-only baseline; no internal/native agent-session APIs are used. own persona
comments never feed back as work. new human steering is durably fingerprinted
before notification; uncertain notification is not blindly resent. clarification
or acceptance changes stop as blocked pending saved steering/owner reconciliation,
not automatic brief revision/resumption. completed issues are never reopened.

## retries, interruption and recovery

all connector polls/checkpoints serialize. paginated discovery/comments/states must
finish before consumption; failed partial scans admit nothing. active controls use
10-second default cadence, discovery 30 seconds; timers schedule after completion
with positive jitter, request timeout, exponential backoff and `retry-after`.
manual polling is an explicit operator override of scheduling. auth failures pause
admission and active work; no continuously-online claim or guaranteed remote-stop
latency is made. before pickup/review mutation delegation/source is refetched, and
again before status writes. graphql has no atomic compare-and-set across these
fields: an intervening remote change can still race; coordinator publication must
also revalidate through existing delivery gates.

`data/linear/connector.json` stores only correlation/control fingerprints, pi session
ids, publication bodies/receipts, terminal/release evidence. it is not a lifecycle
queue or native agent database. `data/linear/owner.lock/owner.json` records the local
process owner. a second host refuses the lock. **one trusted host/root per persona**:
separate clones/machines do not share a lock; distributed exactly-once is not claimed.
atomic local replacement is not power-loss/fsync durability. trusted local parents
and the reconciled single writer are required. unsafe paths, foreign metadata,
leftover temporaries and malformed records are preserved and rejected.

on crash/reload:

1. keep all metadata/temporaries, read the full task, manifest, immutable brief,
   agent checkpoints, native runs, actual files/commits/PR/report and remote
   comments/status. neither pid, timestamps, stopped pi nor a terminal comment
   proves all owners stopped. reconcile who owns each possibly executed action.
2. clean reload normally releases the process lock. after a crash, do **not** steal
   a stale lock based on age/pid. after positively establishing its owner stopped,
   preserve the lock metadata as incident evidence, then manually remove only that
   confirmed owner's `owner.json` and empty lock directory. never delete the journal
   or task records to force admission. unknown ownership blocks.
3. resume the owning pi session and use `/abra-linear resume`. it only polls
   controls/receipts. a pending comment is recognized only from exact saved body
   **and persona**, across all comment pages. a pending status is recognized only
   when the issue is observed in the target state. no absent receipt is proof a
   timed-out mutation did not happen; no automatic replay of an intent occurs.
4. when remote observation confirms the outcome, retry the exact structured
   checkpoint key/body explicitly to finish remaining reporting. never repeat
   execution. if an operator has independent evidence the original request has
   finished and **did not apply**, save a local receipt file, e.g.:

   ```json
   {
     "key": "terminal-blocked",
     "state": "not-applied",
     "evidence": "confirmed original request ended without status change; inspected remote issue and all surviving owners"
   }
   ```

   `/abra-linear reconcile /absolute/path/to/receipt.json` requires UI confirmation.
   `comment: "not-applied"` similarly resolves an uncertain comment only if no exact
   remote body exists. this is explicit operator-attested reconciliation, **not**
   inferred exactly-once. then retry the original checkpoint. preserve proof of
   partial success; never erase a confirmed comment to replay it.
5. if pickup failed before coordinator dispatch, or dispatch outcome was uncertain,
   only after proving **no dispatch occurred and no native owners exist**, use a
   receipt with `key: "pickup"`, `dispatch: "not-sent"` and concrete evidence (plus
   `comment`/`state: "not-applied"` only if separately established). this explicitly
   finishes saved pickup and sends the saved unchanged task once. sent/bound/halted
   tasks cannot use this recovery route; unknown owners must stay blocked.
6. finish blocked/review reporting with evidence, reconcile/stop owners, then release.
   no automatic stale-lock repair, blind redispatch, destructive metadata reset or
   uncertain mutation replay. metadata is bounded to 1 mib: if full, stop and
   preserve/archive only after reconciliation, never silently drop dedupe history.

## privacy, security and validation limits

issue/comment content is untrusted. the prompt never allows it to change the saved
operator ceiling. deterministic reporting gates supplement, not replace, coordinator
compliance and external-action permissions. extensions and native tools share pi's
os permissions: worktrees and prompts are **not a security sandbox**. use suitable
harness permissions for report-only operation; do not expose credentials or broader
publication credentials to untrusted work. local config/journal permissions are
restrictive for newly created files, but trusted ancestors still matter.

only explicitly supplied checkpoint fields/public reports are published. the connector
redacts its known credential, common authorization/secret patterns and private home
paths; heuristic redaction cannot prove absence of arbitrary secrets or sensitive
business data. coordinators must prepare safe public summaries, never feed raw logs,
reasoning or confidential artifacts to reporting. review the operator scope and
privacy before the first authorized live start.

`make test` runs the node built-in tests with fake graphql/pi boundaries and real
local workflow schema rejection, plus the existing python suite. tests cover
identity/status mappings, pagination, dedupe, process/session ownership, reload,
non-overlapping polling, stop/control edits/comments, backoff/cancellation, pickup,
workflow-bound checkpoints, report visibility, authority/terminal evidence failures,
redaction and lost comment/status/dispatch responses. they do not establish live
linear oauth scopes/schema compatibility, pi model/native agent compliance, webhook-
free app provisioning, real PR delivery/CI, or actual end-to-end recovery. those
remain separately authorized live checks, not claims of this local build.

public references: [graphql](https://linear.app/developers/graphql),
[oauth](https://linear.app/developers/oauth-2-0-authentication),
[agents](https://linear.app/developers/agents),
[published schema](https://github.com/linear/linear/blob/master/packages/sdk/src/schema.graphql).
