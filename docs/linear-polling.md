# linear polling for pi

this optional project-local extension polls Linear while pi is alive. it is not a
service, webhook receiver, tunnel or replacement backlog. `/abra-linear start`
opens a dedicated one-ticket coordinator; the foreground `bin/linear-watch` launcher
can open fresh persisted sessions for successive tasks after safe handoff. nothing
starts on extension load/reload. machine sleep pauses polling; native async owners
can survive pi exit. no unattended lifetime or automatic recovery is promised.

## interactive setup and automatic authentication

requires node 24+, an installed pi with documented native dialog/session APIs, a
trusted abra checkout and a workspace admin. no live credentials are needed for
local tests. `/abra-linear setup` runs in **interactive terminal mode only**, not
RPC/print/model tools. it never polls issues, admits work or mutates Linear issues.

1. create/edit your own OAuth app at Settings → API → OAuth applications
   ([creation page](https://linear.app/settings/api/applications/new)); enable
   **client credentials tokens**. choose a recognizable app name/icon. use a
   dedicated app whose client-credentials tokens all use exactly `read`,
   `issues:create`, `comments:create`, `app:assignable`. do not request broad
   `write`/`admin`, `app:mentionable` or extra scopes. Linear revokes existing app
   tokens when client-credentials scopes differ; setup explicitly asks you to
   acknowledge this prerequisite before acquiring a token. no scope upgrades,
   authorization callback, webhook server or native AgentSession implementation
   are provided. this is the existing delegation/comment/status polling connector.
2. register actual repositories with `bin/worktree.py` in this checkout and verify
   path/origin/base/instructions. the wizard reads `data/repos.json` without editing
   it, and lets you choose one or multiple repositories by name. each needs a
   unique existing routing label in Linear (global or belonging to its team).
   create three **distinct nonterminal** states per team first: working must have
   type `started`; in-review may be `backlog`, `unstarted` or `started`. map
   `blocked` to the team's **Todo** state (type `unstarted`), not a blocked column.
   an authorized team admin must create missing states/labels; the wizard only reads.
3. supply client id/secret using your secret manager's environment injection when
   launching pi. the default reference names are `ABRA_LINEAR_CLIENT_ID` and
   `ABRA_LINEAR_CLIENT_SECRET`; setup asks for **names only, never secret values**.
   alternatively, from a private external bash terminal (not pi chat or model tools),
   use masked shell input, never literal secrets in commands/history:

   ```bash
   set +x
   IFS= read -r -p 'linear client id: ' ABRA_LINEAR_CLIENT_ID
   IFS= read -r -s -p 'linear client secret: ' ABRA_LINEAR_CLIENT_SECRET
   printf '\n'
   export ABRA_LINEAR_CLIENT_ID ABRA_LINEAR_CLIENT_SECRET
   pi
   ```

   use a trusted terminal without recording and trusted extensions/tools. do not
   paste credentials into `/abra-linear`, chat, tickets, config, logs or reports.
   if launching through another environment/terminal/service, inject the references
   there too; exporting into one shell does not update an already-running pi.
4. run `/abra-linear setup`. acknowledge prerequisites, choose references, then
   either keep secret-manager/env references or explicitly consent at final save
   to **plaintext local credential storage**. the latter writes only client
   credentials to a new random `~/.abra-linear/<uuid>.json`, outside the checkout,
   with POSIX file mode `0600` and directory `0700`, owned by your user; symlinks, hardlinks
   and broad modes reject. it never overwrites another credential file. this is
   not encryption or an OS keychain. access tokens are never persisted. cancelling
   any dialog (escape), including the discovery progress/cancel dialog, leaves
   existing config unchanged and removes any newly allocated secret file on failed
   save. token issuance itself cannot be undone by cancelling: acquired tokens
   expire normally; revoke in Linear if required.
5. read-only, fully paginated discovery shows app/workspace identity, teams, states
   and labels. verify the displayed workspace **and app persona** before confirming
   pins. `viewer.id` is the workspace-specific app user, not OAuth client id or an
   installing admin. client-credentials grants are app-actor tokens; initial access
   covers **all public teams**. restrict the app's team access in Linear's app
   details page before starting work, in addition to the wizard's local allowlists.
   select each repository's team, three states and routing label without copying
   UUIDs. existing identity pins cannot change through setup. select implementation
   and PR delivery, keep existing authority, or explicitly choose investigation-only.
   fresh config defaults to **PR delivery**, without PR size limits or watch opt-in. final confirmation summarizes authority, scope and
   storage consent; setup never starts implementation.
6. setup saves gitignored `.pi/abra-linear.json` only after final confirmation;
   existing config requires an additional replacement confirmation. no polling
   starts. active ownership/locks, untrusted/busy sessions or incompatible journal
   identity block setup. an existing journal is never reset or deleted;
   changed configuration may require manual preservation/archival **only after**
   all old owners and receipts have been reconciled (see recovery below). setup
   cannot rotate identity. an explicitly selected authority-only change can update
   journal identity after every prior owner and receipt is released; history is
   preserved. scope changes still require manual reconciliation. no work may start
   during setup.
7. only when ready, `/abra-linear start` opens the dedicated session after a
   separate admission confirmation. delegate disposable report-only issues to the
   **app**, verifying `delegate.id` or the app’s `assignee.id`, not a human assignee. a local token/setup
   check is not a reason to admit real work. see the smoke-check guidance below.

### credential lifecycle and legacy compatibility

client credentials are exchanged at `POST https://api.linear.app/oauth/token`
using form-encoded `grant_type=client_credentials`, `client_id`, `client_secret`
and the fixed comma-separated scopes above. returned scopes may be a scope string
or a legacy array of strings; either must match the exact allowed scope set.
missing/extra scopes and malformed or nonstring array entries reject authentication.
each new connector/foreground launcher child acquires its own in-memory token;
Linear currently documents a 30-day lifetime, with no refresh token. requests use
expiry from the response and renew **before** expiry (five-minute margin, or 10%
for short lifetimes), on the next polling/API request. normal live polling provides
proactive renewal without restarting pi. concurrent callers share one acquisition
and identity check; cancelled callers do not cancel other waiters, but cancelling
all waiters/shutdown aborts acquisition. token requests have bounded deadlines and
no automatic retry. every new token must match the pinned workspace/app before
any issue request. no timer/service runs while the connector is off; a sleeping or
stopped process cannot renew. after wake the next request renews before use.

HTTP/GraphQL authentication failure invalidates the cached token, pauses admission
and halts active work for local owner reconciliation; it never blindly retries an
uncertain issue/comment/status mutation. explicit later reads can acquire again,
but renewing credentials does not resume halted work. revoked credentials, changed
identity/scopes or unavailable access fail closed, without broadening permissions.
secret rotation invalidates client-credentials tokens; reconcile work before
rotation/restart. revoke via workspace app settings (or Linear's documented revoke
endpoint), not by deleting the local journal. old consented credential files are
not automatically removed on reconfiguration; remove them manually only when no
process/config still uses them.

`docs/linear.example.json` shows environment-reference client credentials for
manual inspection, not a second setup requirement. durable private-file mode saves
`"auth": {"credentialsFile": "/absolute/private/path/<uuid>.json"}` instead.
keep `tokenEnv` **or** `auth`, never both. existing version-1 `"tokenEnv":
"ABRA_LINEAR_TOKEN"` configs still work unchanged with operator-managed tokens;
legacy tokens are not acquired/renewed automatically. rerun setup with client
references to migrate, preserving existing pins/authority. no access/refresh token
is requested through the UI, sent to the model, written to config or placed in
process arguments. secret references/files remain accessible to trusted code with
your OS permissions; this is not a sandbox against malicious tools/extensions.

Linear's current native [agents](https://linear.app/developers/agents) guide instead
recommends webhooks and AgentSession activities; this connector deliberately does
not implement that protocol. do not invent a fake webhook endpoint if installation
requires it; validate your polling-only app with the operator/Linear. references:
[OAuth/client credentials](https://linear.app/developers/oauth-2-0-authentication),
[app actors](https://linear.app/developers/oauth-actor-authorization),
[GraphQL](https://linear.app/developers/graphql). documentation inspected during this
build; no live app provisioning/authentication certified.

## configure and start

requires node 24+, pi's documented session replacement/settled/RPC APIs and a trusted
abra checkout. pi discovers `.pi/extensions/abra-linear/index.ts`; no npm dependency
installation is needed. inspect your installed harness docs and agent tool profiles.

- use `/abra-linear setup` above, or manually populate **every** field in
  `docs/linear.example.json` and save as gitignored `.pi/abra-linear.json`.
- `auth` references client credentials, never secret literals or commands; legacy
  `tokenEnv` still references an operator-managed token environment variable. start
  validates viewer/workspace and all paginated states before any admission.
- each configured repository maps one routing label UUID and team to its registered
  name/path, GitHub remote and base. only nonterminal issues assigned or delegated to this app
  in an allowlisted team with exactly one matching label are eligible; another
  delegate takes precedence and is never displaced, even if abra is assignee; ambiguous
  routing or truncated labels admit nothing. do not use ticket-supplied paths.
- configuration/start authorizes all current eligible assignments/delegations, not just new
  ones. restrict teams/labels/app access if that scope is too broad.
- authority defaults to `{"mode":"pr"}`:
  implement, test, independently verify, push and open a PR, attach it to the Linear
  issue and transition to In Review after required checks pass. delegation authorizes
  that full lifecycle; do not stop at investigation. there are no connector-imposed
  file-count, changed-line or binary-file restrictions on PRs.
  explicit `{"mode":"report"}` is an optional investigation-only restriction, not
  the connector's capability. existing explicit report-only configs must be changed
  in setup before code work; code intent cannot be replaced by a successful report.
  genuinely impossible implementation ends with findings and a concrete blocked
  handoff. no merge, deployment or issue-close authority is supported.

in pi, `/abra-linear start` requires idle/no pending messages, no unresolved task
or lock, credentials and UI confirmation. it records the current session path as
parent and opens a dedicated session; admission consumes that session once. before
ownership acquisition or any pickup mutation, documented `newSession({ setup })`
SessionManager APIs append a dedicated recovery marker and truthful user bootstrap
context, without requesting a model turn or making network calls. the connector
reads back the saved header, exact session id, marker and complete fresh bootstrap;
an allocated path or custom-entry event alone is not persistence proof. ephemeral
storage, write/read failure or an unexpected conversation blocks admission. the
bootstrap grants no extra authority and is not an issue dispatch. an empty outgoing
parent may itself remain unsaved under pi's normal lazy storage behavior. controls:

| command | behavior |
| --- | --- |
| `setup` | interactive read-only configuration wizard; never starts polling or admits work |
| `status` | show mode, issue/dispatch, errors, terminal and pending receipts; off is not stopped-owner proof |
| `pause` | stop admission; active control polling continues |
| `poll` | serialized explicit poll while enabled, not redispatch |
| `stop` | abort connector I/O, stop admission, request native cancellation/reconciliation; not proof owners stopped |
| `resume` | explicitly resume **recorded owning pi session**, after inspecting saved task/native ownership; controls only, admission paused |
| `release <stopped-owner evidence>` | UI-confirm all owners stopped and receipts reconciled; requires idle/terminal/confirmed reporting; saves evidence and frees correlation/lock |
| `reconcile <absolute receipt.json>` | UI-confirm explicit uncertain publication/dispatch reconciliation, described below |

use `/abra-linear <command>`. unrelated prompts and session switch/fork/tree are
refused while an issue is active. shutdown drains connector I/O and releases its
process lock, never its active correlation. reload/restart stays off.

tasks-axi owns lifecycle and concise continuity: original source/acceptance,
material steering, dispatch intent/native ids, worktrees, commits/reports and next
action/blocker. no workflow manifests or agent checkpoint files are required.
existing old tasks/journals are never migrated or deleted automatically; incompatible
connector journal versions reject clearly. preserve them and use git history for
old recovery contracts before an operator-approved reconciliation/config migration.

## checkpoints and delivery

the coordinator records `linear-<issue-uuid>` with the configured repo in tasks-axi
and saves the verbatim original issue JSON as `data/<task-id>/source.json`. its
title/description remain authoritative original intent/acceptance, not a rewritten
summary. retain these exact standalone lines in the task body:

```text
original source and acceptance: data/<task-id>/source.json
requested delivery: pr
```

use `report` instead of `pr` only for genuinely requested report work. this is the
trusted coordinator's assertion of original intent, **not** a natural-language
classifier or a choice based on available authority/output. before native dispatch,
call `abra_linear_checkpoint` with `kind: "bind"`, `task: "linear-<issue-uuid>"`,
and matching `requestedDelivery: "report"` or `"pr"`. the connector observes
`bin/tasks show <task-id> --full --backend markdown --file <root>/data/backlog.md`,
checks task id/repo and both body references, and matches the snapshot's issue and
source fingerprint. it pins the source content hash/reference and requested
delivery in the existing journal, with no second task manifest. missing/foreign
records or unsupported tasks-axi full-detail formatting block binding. old bound
journals without this assertion reject unchanged for manual reconciliation.

code intent still binds as `pr` under report-only authority, then must report
`blocked` without dispatch; approach/progress/review cannot substitute report work.
review reobserves the task references and unchanged snapshot, and its delivery kind
must match the original binding under either authority mode. routine task continuity
may change without rewriting these lines/source. changed acceptance/delivery needs
explicit operator reconciliation with preserved evidence, never a terminal class
change or automatic rebinding. blocked reporting remains available when authority,
source artifacts or publication are unavailable.

all calls need
stable lowercase `key`, public `summary` and `nextAction`; optional `approach` and
`checks` explain meaningful approach/tests, including failed/unrun checks. kinds
`approach`, `progress`, `checks`, `waiting`, `blocked`, `review` publish comments;
`waiting` retains clarification, `blocked` requires `blocker`, and `review` requires
structured `delivery`. keys/bodies are immutable across retries.

report review uses `delivery: {kind: "report", reference: "https://..."}` or a public
file inside that task's artifact directory. files must be nonempty/readable and at
most 12000 bytes; their full redacted content is posted, not a private path. comments
are bounded to 16000 characters. prepare safe deliverables, never raw logs/reasoning.

code review requires actual authorized PR delivery, not a local commit or report.
`delivery` contains `kind: "pr"`, configured-repo PR `reference`, `candidate`,
`baseCommit`, `workerDirectory`, `verifierDirectory`, `verificationReport`,
`verifiedCommit`, `checks: {intent, tests, docs, format}`, `prHead`, `prBase`,
`ci: "passed"` (or `"not-required"` after confirming no required checks), and
concrete `externalEvidence`. checks must be `pass` (docs alone
may be `not-applicable`). the existing checkpoint/journal stores this receipt; no
separate delivery manifest. the connector checks exact candidate, clean separate
worktree roots, detached verifier, readable report, local repository/origin,
configured base/ancestry. PR size and binary changes are not policy restrictions.
the coordinator must independently inspect original intent, real verifier findings,
publication authority, actual PR target/head and required CI through gh-axi and
supply that evidence. these are trusted coordinator assertions, **not independent
GitHub verification by the connector**. pending/failed/unavailable required checks
prevent delivery. no configured required checks may use `not-required` with explicit
inspection evidence; never describe that as CI passed.
changed candidate/acceptance requires fresh independent verification; at most two
repair rounds. report-only mode must block code intent even if a report is supplied.

review posts a confirmed comment and upserts the PR attachment before in-review
status. attachment creation is idempotent by issue and URL; an attachment failure
prevents the review transition. review then removes abra's delegation and its assignee
only if that assignee is abra (a human assignee is preserved). blocked posts a concrete
reason/findings/next action, returns the issue to **Todo**, then uses the same
unassignment. control stops and genuine settled failures also use that blocked handoff.
partial publication retains receipts, including uncertain unassignment; release waits
for reconciliation. a lost successful review-unassignment response is reconciled before
checking eligibility, so removing abra does not itself halt successful work. only an
unchanged source, in-review status and confirmed comment/status/unassignment receipts
can complete that reconciliation, without more remote mutations. changed source or
another delegate cannot authorize review writes. terminal reporting does not mark
tasks-axi done or release owners automatically.

comments explain the actual plan, findings/changes, checks and next action. optional
approach/check sections are omitted when absent, not filled with "not changed" or
"not run". pickup names the issue; review links the PR/report; blocked explains the
actual failure and how to proceed. a failed or empty scout/worker result is inspected
before deciding what to do, never treated as proof that the issue is impossible.

### async continuation, not premature blocking

both manual and watch coordinators retain the originating session across async yields.
pi's `agent_settled` means the parent is idle, not that detached children have finished.
the connector captures documented `subagent:async-started` identities, checks targeted
native `status` and lifecycle-v3 `status.json`, and waits while runs are queued/running.
file age and recent event activity are not liveness proofs. native `subagent-notify`
messages (matched by `details.runs[].runId` at `message_start`) normally wake the parent,
which inspects real results and continues to implementation, verification or a concrete
blocked report. terminal artifacts can precede a grouped notification; that gap is not
a blocker.

if a terminal result has no delivered notice, the existing active control poll sends
one result-inspection continuation for those exact runs, without relaunching anything.
this repairs reporting only; it does not resume/replay uncertain execution. if the
coordinator then stops with no pending async work or terminal/clarification checkpoint,
it gets one bounded request to finish the original task and reporting. stopping again
produces a readable blocked handoff, not endless idle waiting. an explicit abort or
unconfirmable native status blocks without auto-resuming; any native owners remain
retained for inspection. explicit waiting still retains the session; a subsequent
progress/check checkpoint clears waiting.

settled handlers only arm detection through a nonce-correlated internal command sent
with documented `sendUserMessage(..., {expandPromptTemplates: true})`. pi executes it
after every settled handler returns; it performs no publication and does not start a
model turn. native wakes queued by later handlers can then drain. only the existing
control poll checks for a genuinely stopped coordinator, never the settled handler
itself. the fallback captures the settlement/activity version and rechecks it, idle
state and pending messages after awaited reads and immediately before each mutation
and terminal marking. a new run or native completion notice aborts in-flight fallback
requests. pi's `isIdle()` alone does not expose deferred settled-handler wakes.

canceling before any remote request leaves no empty publication or intent receipt.
if a fallback request already started, cancellation cannot prove it was not applied
and cannot retract a public comment. all issued comment/status/unassignment intents
and confirmations are retained. only interrupted **automatic** fallback publications
may carry `canceled: true`; their reserved keys (`settled-without-terminal`, then
`settled-without-terminal-2`, `-3`, etc.) cannot be used by ordinary checkpoints or
replayed. remaining never-issued steps are not obligations to perform stale Todo
or unassignment mutations. issued uncertainties still block release until observed
receipts or explicit known-not-applied reconciliation resolve them; the latter is
retained in `notApplied` with reconciliation evidence. release still requires a later
valid terminal checkpoint and every exact native stopped-owner proof. neither a
canceled fallback nor its partial public comment establishes task success.

a canceled receipt does not disable later settlement handling. native running/result
checks continue, including result-inspection wakes. after a cancellation, an otherwise
idle coordinator gets **one additional reporting reminder per session**, never one per
poll or wake. if it still stops without delivery, the next stable settlement can post
a new blocked decision under the next reserved key while retaining every canceled
receipt. actual new activity can invalidate that decision through the same guards;
after activity stops, a stable decision can complete Todo/unassignment. there is no
loop of reporting prompts, execution retries or canceled-key replay. a queued wake
cancellation requires a new settlement before another fallback decision, not merely
another control poll. unknown native ownership still blocks safely, and unresolved
issued fallback intents prevent conflicting status/unassignment mutations and release
until remote receipts or explicit reconciliation resolve them.

these hooks follow installed pi 1.5.0 `docs/extensions.md` agent lifecycle and message
APIs and the `notify.ts`, `send-user-message.ts`, `event-bus.ts` examples; pi-subagents
0.86.0 `docs/extension-api.md` (host session lifetime/completion wakes, RPC),
`docs/observability.md` (async artifacts, completion notifications) and
`docs/workflows.md` (recommended async orchestration). continuation observations never
replace the exact process-terminal proofs required for watch release.

## foreground launcher and ownership

watch additionally requires POSIX and compatible pi-subagents public event-bus RPC,
process-terminal proof v1/lifecycle v3 and bounded status/fleet projections. omit
`watch` in config for manual-only use, or explicitly set
`"watch": {"trustedManagedWork": true}` and acknowledge on **each** invocation:

```sh
bin/linear-watch --help
bin/linear-watch --trusted-managed-work
bin/linear-watch --trusted-managed-work --pi /absolute/path/to/pi
```

this accepts a **trusted operating contract, not a sandbox**: no detached, untracked,
nested, unsupported foreground or external background writers; synchronous bash
must finish without surviving background work. all native work must be top-level
single-leaf Pi-managed async runs, with this contract in every child brief. native
workflows/chains/parallel roots, schedules, revival and external runners are not
supported. operator/agent compliance is assumed for arbitrary shell descendants;
the launcher cannot discover hidden writers. revisit the adapter before adding
run types or stronger containment, never replace proofs with PID/age heuristics.

each child starts with `pi --mode rpc`, with normal trusted resources, no resume,
`--no-session` or automatic dialog approvals. startup checks the initial empty idle
session, then `/abra-linear watch-start` creates a replacement with the saved
bootstrap described above. a second, internal `watch-arm` handshake requires the
exact launcher nonce and initial session id, a new idle session containing only the
recognized bootstrap conversation, and fresh saved-file checks before ready or
ownership acquisition. it runs in the replacement extension instance, not a stale
pre-switch context. cancellation, reload, extra messages or persistence failure
cannot arm polling. nonce/session/owner/task/request correlation then binds
extension outcomes to the saved replacement identity. no-work keeps one child;
working/waiting retains its session. dialogs are diagnosed but not answered; resolve through Linear
comments (which halt for saved steering reconciliation) or interrupt and reopen
manually. uncertainty halts without fresh children or blind command retry.

handoff requires bound/sent coordinator, settled/idle with no queued messages,
confirmed reporting receipts and exact terminal proof for **every captured native
start**, not agent trackers/assignment graphs. only the captured native artifact
root is read; targeted status must match session/run/runner, observed close and free
canonical lease. unknown/omitted/active/unsupported ownership or unresolved launch
calls block. coordinator-only reports may have zero runs under the trusted contract.
execution proofs establish stopped ownership, not successful delivery. the extension
saves proof/release receipts and frees its lock; watch checks durable correlation,
receipts and pi state, closes stdin, and awaits clean child close before another
child. blocked tasks retain their task/report continuity, but are not permanently
blacklisted by the journal. after owner release, a fresh session can pick the issue
up when explicitly re-delegated to abra. admission replaces the released blocked
correlation, with session-specific comment markers; it reuses the existing task and
source snapshot and reconciles acceptance changes rather than creating duplicates.
unfinished owners/uncertain receipts still prevent duplicate execution.

ctrl-c/SIGTERM reaches watch before the child's separate process group. it stops
admission and requests reconciliation. control/shutdown deadlines are 60 seconds;
a stuck child receives SIGTERM and an unsuccessful halt with surviving ownership
unknown. the child stays piped/referenced/awaited, not daemonized. diagnostics on
stderr omit raw model/tool stderr and secrets. no restart after a crash/timeout.

### reading the watch terminal

watch prints timestamped, plain-language status lines on **stderr** (stdout stays
empty except for `--help`). it explains startup checks, waiting for eligible
issues, task pickup, work in progress, clarification/dialog input, handoff checks,
shutdown and failures. unchanged polling stays quiet; a heartbeat about once a
minute repeats the current wait and any action needed, only while status checks
are returning. it is reassurance that watch is checking, not proof that model or
worker execution is making progress. blocked startup/control calls still use the
existing bounded deadlines, not an independent heartbeat timer.

for example (times and task ids vary):

```text
[12:00:00 utc] linear watch: starting; checking configuration and saved ownership before opening a coordinator. ctrl-c requests a safe stop.
[12:00:01 utc] linear watch: waiting for an eligible assigned or delegated issue; none admitted. checking automatically; no action needed.
[12:01:01 utc] linear watch: still checking: waiting for an eligible assigned or delegated issue; none admitted. checking automatically; no action needed.
```

- pickup/work lines identify the task as `linear-<issue-uuid>` from the existing
  correlated outcome. human issue keys/titles are not in that outcome, so watch
  does not fetch them merely for display or print ticket text, raw model/tool
  streams, dialog contents, credentials, session paths or native run ids.
- **no action needed** means watch will keep checking. it does not mean the task
  is done. work status includes waiting for reporting and stopped-worker evidence;
  it cannot distinguish coding, testing or worker shutdown from this status alone.
- **action needed** for clarification means read/reply on the Linear issue and
  follow saved-steering/owner reconciliation; replies never automatically resume
  work. a dialog request is not approved or answered in this terminal. if it is
  still open, interrupt, reconcile owners and reopen the saved pi session manually.
  watch conservatively retains the dialog warning for that session because it
  does not receive dialog-dismissal proof.
- a coordinator's **reported handoff** is not yet confirmed: watch must still
  check saved receipts, idle session and clean child close. only then is **safe
  handoff confirmed** printed. review means output awaits review, not merged or
  issue completed. blocked means inspect the issue's blocker/next steps, not success;
  a safe blocked handoff may still let watch check for another issue.
- **stop requested** means please wait for reconciliation/shutdown. **halted** or
  **unable to continue** means operator action is needed before restart; preserve
  the evidence and follow recovery below. watch never claims that closing pi alone
  stopped native workers and never retries or removes locks automatically.

failures include a bounded phase (for example, **checking task status**) and a
fixed diagnostic code/cause with local next steps. common codes:

| code | next action |
| --- | --- |
| `options-invalid` / `acknowledgment-required` | read `bin/linear-watch --help`; provide the explicit trusted-work acknowledgment |
| `configuration-invalid` / `watch-opt-in-required` | inspect local configuration and explicit watch opt-in |
| `journal-invalid` / `ownership-unresolved` | preserve saved evidence and reconcile existing ownership; never reset it to start |
| `child-start-failed` | check the pi executable and local permissions |
| `rpc-command-failed` / `extension-failed` / `outcome-missing` / `rpc-protocol-invalid` | inspect the saved session and installed pi/extension compatibility |
| `rpc-timeout` | inspect the retained session and owners; no blind command retry |
| `connector-auth-failed` / `connector-request-failed` | check credential references, pinned app/workspace access or connectivity locally; reconcile any uncertain mutations |
| `publication-pending` / `native-ownership-uncertain` | reconcile remote publication receipts or every captured native owner respectively |
| `connector-check-failed` / `connector-operation-failed` / `unknown-failure` | no narrower safe cause is available; inspect saved task/session/owner evidence locally |

codes and explanations are allowlisted local text, not redacted exception messages.
unknown/untyped failures use a fixed fallback; raw exceptions/stacks, RPC error
payloads, model/tool stderr, ticket text, credentials and private paths are never
rendered by watch. connector `status` additionally exposes a nullable `diagnostic`
code for poll failures; its `error` explanation uses the same fixed vocabulary.
a startup uncertainty can explain a failed safety check without asserting readiness
or stopped ownership. no failure code authorizes retry, restart or lock removal.

these are presentation-only messages: admission, reporting, ownership proofs and
handoff gates are unchanged. the injected `diagnose` callback still receives
structured per-poll outcomes for local tests/integrations; only the default terminal
reporter suppresses repeats. no raw-event/verbose command-line mode is provided.

## stop and recovery

discovery/control/checkpoints serialize. defaults: discovery 30 seconds, active
control 10 seconds, bounded requests with jitter/backoff/Retry-After; manual poll
explicitly overrides scheduling. scans paginate completely before consumption.
undelegation, scope/source changes, completed/canceled issues, new/edited human
comments (including `/abra stop`), unavailable controls or auth loss halt new work
and request cancellation. own comments do not loop. human steering fingerprints
persist before notification; uncertain notifications are not blindly replayed.
clarification replies require saved-steering/owner reconciliation, not automatic
brief revision/resumption. GraphQL refetches cannot eliminate remote mutation races.

`data/linear/connector.json` is a bounded correlation/reporting journal, not a task
or agent database; `data/linear/owner.lock/owner.json` is its exclusive local host
lock. one trusted host/root per persona: separate clones/machines do not share it.
trusted parents/single writer are required; atomic replacement is not fsync durability.
malformed/foreign/incompatible/symlink/leftover-temporary evidence rejects unchanged.

1. after interruption, preserve journal/lock/temporaries, task source/body, pi
   session, native artifacts and actual commits/PR/report/remote comments/status.
   resolve every possibly executed action; timestamps, missing PID or closed pi
   do not prove owners stopped. unknown ownership blocks replacement.
2. after positively establishing the old lock owner stopped, preserve its metadata
   as incident evidence, then manually remove only its `owner.json`/empty lock
   directory. never delete the journal/task to force admission. reopen the recorded
   pi session and `/abra-linear resume` for paused controls, never redispatch.
   the saved header identity and dedicated marker must still match; another session
   cannot take over. even a failure during pickup before first coordinator dispatch
   now leaves that owning session reopenable. reload/resume never arms a bootstrap
   or automatically retries pickup. this is prevention, not repair of old incidents:
   a historic missing owning session remains unresolved and blocks replacement;
   do not fabricate a marker/session, alter journal ownership or weaken the guard.
   saved-file readback provides process-exit recoverability, not fsync/power-loss
   durability or proof that remote mutations/native owners stopped.
3. exact saved comment body **and persona** or observed target status reconcile
   uncertain receipts. absence does not prove a timed-out mutation failed. explicitly
   retry the same checkpoint key/body to finish reporting only, not execution.
   if independent evidence proves the original request ended **without applying**,
   UI-confirm a receipt using `/abra-linear reconcile /absolute/path/receipt.json`:

   ```json
   {"key":"terminal-blocked","state":"not-applied","evidence":"confirmed original request ended; inspected remote status and surviving owners"}
   ```

   `comment: "not-applied"` is analogous and requires no exact remote comment.
   `unassign: "not-applied"` likewise permits an explicit retry only after proving
   the original unassignment request finished without applying. remote absence of
   abra's delegation/assignment confirms a lost successful response automatically.
   preserve confirmed partial success. only when **no dispatch occurred/no native
   owners exist**, `key: "pickup", dispatch: "not-sent"` can finish saved pickup
   and send unchanged source once; sent/bound/halted tasks cannot use this route.
4. finish truthful blocked/review reporting, stop/reconcile every owner, then
   release. watch cannot reconstruct its live captured proofs after restart:
   recovery is manual. retain old evidence; no stale-lock stealing, automatic
   migration, destructive reset or blind replay. at 1 MiB journal capacity, stop
   and preserve/archive only after reconciliation, never silently drop dedupe.

## validation and trust limits

extensions/tools share OS permissions; worktrees/prompts are not containment. use
suitable task-scoped harness permissions and never expose broad credentials to
untrusted work. redaction removes all session-acquired connector tokens/client secrets, common secret patterns and
home paths, not arbitrary confidential content; prepare public summaries carefully.

`make format` and `make test` cover baseline worktrees plus fake GraphQL/pi/native
boundaries and harmless RPC subprocesses: credential acquisition/proactive renewal,
revocation/failure, single-flight/cancellation, secret storage/redaction, wizard
cancellation/persistence/legacy migration, dedupe, scope/control, cancellation,
report/delivery gates, uncertain receipts, exact native proofs, session handoffs and
failure/interrupt/lock handling. session regression tests additionally require an
installed pi package (resolved beside the node executable, or set
`PI_CODING_AGENT_PACKAGE` to its absolute package root). they exercise installed
SessionManager lazy persistence and new-session runtime replacement offline,
including bootstrap failure, exact owner reopening before dispatch and paused
recovery; no mocked custom-entry event substitutes for those storage checks.
validated against pi 1.5.0 and documented pi-subagents 0.86.0 boundaries; inspect/retest the installed public APIs after upgrades.
no live Linear/OAuth/pi model/PR/CI behavior is certified. a later authorized smoke check should use disposable report-only issues,
verify identity/states and all config fields first, observe pickup/checks/report or
blocked, two fresh-session handoffs, clarification retention and interruption, then
reconcile owners and revoke test credentials. never admit real work merely to check
credentials or claim installation/provisioning passed from these local tests.
