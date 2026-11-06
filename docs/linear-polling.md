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
   type `started`; in-review/blocked may be `backlog`, `unstarted` or `started`.
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
   UUIDs. existing identity pins cannot change through setup. existing authority
   and watch opt-in are preserved; fresh config is **report-only**, without watch
   opt-in. final confirmation summarizes saved scope and storage consent.
6. setup saves gitignored `.pi/abra-linear.json` only after final confirmation;
   existing config requires an additional replacement confirmation. no polling
   starts. active ownership/locks, untrusted/busy sessions or incompatible journal
   identity block setup. an existing journal is never migrated, reset or deleted;
   changed configuration may require manual preservation/archival **only after**
   all old owners and receipts have been reconciled (see recovery below). setup
   cannot rotate identity or expand authority. no work may start during setup.
7. only when ready, `/abra-linear start` opens the dedicated session after a
   separate admission confirmation. delegate disposable report-only issues to the
   **app**, verifying `delegate.id`, not human `assignee.id`. a local token/setup
   check is not a reason to admit real work. see the smoke-check guidance below.

### credential lifecycle and legacy compatibility

client credentials are exchanged at `POST https://api.linear.app/oauth/token`
using form-encoded `grant_type=client_credentials`, `client_id`, `client_secret`
and the fixed comma-separated scopes above. returned scopes must match exactly.
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
  name/path, GitHub remote and base. only nonterminal issues delegated to this app
  in an allowlisted team with exactly one matching label are eligible; ambiguous
  routing or truncated labels admit nothing. do not use ticket-supplied paths.
- configuration/start authorizes all current eligible delegations, not just new
  ones. restrict teams/labels/app access if that scope is too broad.
- authority defaults to `{"mode":"report"}`: research/reporting only, not source
  implementation or GitHub publication. code intent without authority is blocked,
  not replaced by a report. optional `{"mode":"pr","maxFiles":8,"maxChangedLines":400}`
  bounds code/PR work in addition to normal independent review/delivery checks.
  no merge, deployment or issue-close authority is supported.

in pi, `/abra-linear start` requires idle/no pending messages, no unresolved task
or lock, credentials and UI confirmation. it saves the current session as parent
and opens a clean dedicated session; admission consumes that session once. controls:

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
`ci: "passed"`, and concrete `externalEvidence`. checks must be `pass` (docs alone
may be `not-applicable`). the existing checkpoint/journal stores this receipt; no
separate delivery manifest. the connector checks exact candidate, clean separate
worktree roots, detached verifier, readable report, local repository/origin,
configured base/ancestry and file/changed-line ceilings (binary changes rejected).
the coordinator must independently inspect original intent, real verifier findings,
publication authority, actual PR target/head and required CI through gh-axi and
supply that evidence. these are trusted coordinator assertions, **not independent
GitHub verification by the connector**. pending/failed/unavailable/no CI is not pass.
changed candidate/acceptance requires fresh independent verification; at most two
repair rounds. report-only mode must block code intent even if a report is supplied.

review posts a confirmed comment before in-review status; blocked posts a concrete
reason/next action and blocked status. partial publication retains receipts. settling
without a terminal checkpoint produces truthful blocked fallback (except explicit
waiting); prose, native exit and pi idle never prove task success. terminal reporting
does not mark tasks-axi done or release owners automatically.

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

each child is persisted `pi --mode rpc`, with normal trusted resources, no resume,
`--no-session` or automatic dialog approvals. nonce/session/owner/task/request
correlation binds extension outcomes. no-work keeps one child; working/waiting
retains its session. dialogs are diagnosed but not answered; resolve through Linear
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
child. blocked tasks remain blocked, deduped in tasks-axi and the connector.

ctrl-c/SIGTERM reaches watch before the child's separate process group. it stops
admission and requests reconciliation. control/shutdown deadlines are 60 seconds;
a stuck child receives SIGTERM and an unsuccessful halt with surviving ownership
unknown. the child stays piped/referenced/awaited, not daemonized. diagnostics on
stderr omit raw model/tool stderr and secrets. no restart after a crash/timeout.

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
3. exact saved comment body **and persona** or observed target status reconcile
   uncertain receipts. absence does not prove a timed-out mutation failed. explicitly
   retry the same checkpoint key/body to finish reporting only, not execution.
   if independent evidence proves the original request ended **without applying**,
   UI-confirm a receipt using `/abra-linear reconcile /absolute/path/receipt.json`:

   ```json
   {"key":"terminal-blocked","state":"not-applied","evidence":"confirmed original request ended; inspected remote status and surviving owners"}
   ```

   `comment: "not-applied"` is analogous and requires no exact remote comment.
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
suitable report-only harness permissions and never expose broad credentials to
untrusted work. redaction removes all session-acquired connector tokens/client secrets, common secret patterns and
home paths, not arbitrary confidential content; prepare public summaries carefully.

`make format` and `make test` cover baseline worktrees plus fake GraphQL/pi/native
boundaries and harmless RPC subprocesses: credential acquisition/proactive renewal,
revocation/failure, single-flight/cancellation, secret storage/redaction, wizard
cancellation/persistence/legacy migration, dedupe, scope/control, cancellation,
report/delivery gates, uncertain receipts, exact native proofs, session handoffs and
failure/interrupt/lock handling. no live Linear/OAuth/pi model/PR/CI behavior is
certified. a later authorized smoke check should use disposable report-only issues,
verify identity/states and all config fields first, observe pickup/checks/report or
blocked, two fresh-session handoffs, clarification retention and interruption, then
reconcile owners and revoke test credentials. never admit real work merely to check
credentials or claim installation/provisioning passed from these local tests.
