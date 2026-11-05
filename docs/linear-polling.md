# linear polling for pi

this optional project-local extension polls Linear while pi is alive. it is not a
service, webhook receiver, tunnel or replacement backlog. `/abra-linear start`
opens a dedicated one-ticket coordinator; the foreground `bin/linear-watch` launcher
can open fresh persisted sessions for successive tasks after safe handoff. nothing
starts on extension load/reload. machine sleep pauses polling; native async owners
can survive pi exit. no unattended lifetime or automatic recovery is promised.

## app onboarding (operator setup, not performed by this build)

1. a workspace admin creates an OAuth application in Settings → API → OAuth
   applications ([creation page](https://linear.app/settings/api/applications/new)).
   choose its name/icon; keep client id/secret in your existing secret manager.
   use an existing trusted OAuth client with the exact registered redirect URI;
   this connector supplies no callback server. ongoing polling needs no endpoint.
2. authorize with **`actor=app`**, not `actor=user` or deprecated `application`.
   request `read`, `issues:create` (documented issue creation/update access),
   `comments:create` and `app:assignable`. `app:mentionable` is unnecessary; mentions
   do not trigger this connector. broad `write`/`admin` access is not required.
   restrict installed app team access as well as the local allowlists. validate
   current scope sufficiency before real work; an access error is a blocker, not
   permission to broaden scopes automatically.
3. your OAuth client constructs the authorization URL, with percent-encoded values:

   ```text
   https://linear.app/oauth/authorize?client_id=CLIENT_ID&redirect_uri=REGISTERED_REDIRECT_URI&response_type=code&actor=app&scope=read,issues:create,comments:create,app:assignable&state=SECURE_RANDOM_STATE
   ```

   generate/verify cryptographically random state. prefer PKCE `S256`, retaining
   the verifier only in that client. exchange the returned code at
   `POST https://api.linear.app/oauth/token`, form fields `grant_type=authorization_code`,
   `code`, identical `redirect_uri`, `client_id`, `client_secret`; PKCE also supplies
   `code_verifier` and makes the secret optional. save access/refresh tokens, expiry
   and scopes securely, never in tickets/config/prompts/shell history.
4. the operator's client owns refresh (`grant_type=refresh_token`, `refresh_token`,
   client authentication or PKCE client id). authorization-code access tokens
   currently expire after about 24 hours; retain rotated refresh tokens. the
   documented 30-minute OAuth refresh replay grace does not authorize replaying
   uncertain issue mutations. alternatively, your own OAuth app may enable client
   credentials tokens: request `grant_type=client_credentials` and scopes with
   client authentication. these currently last 30 days without refresh, initially
   access all public teams, and should be acquired per run with restricted teams.
   the connector neither acquires nor refreshes credentials and captures its token
   when built: stop/reconcile before restarting with new credentials.
5. use the installed app token for authorized read-only GraphQL setup queries at
   `https://api.linear.app/graphql` with `Authorization: Bearer <access token>`:

   ```graphql
   query AbraIdentity { viewer { id name } organization { id name } }
   query AbraTeams($after: String) {
     teams(first: 100, after: $after) {
       nodes { id name key } pageInfo { hasNextPage endCursor }
     }
   }
   query AbraLabels($after: String) {
     issueLabels(first: 100, after: $after) {
       nodes { id name team { id } } pageInfo { hasNextPage endCursor }
     }
   }
   query AbraStates($team: ID!, $after: String) {
     workflowStates(first: 100, after: $after, filter: {team: {id: {eq: $team}}}) {
       nodes { id name type team { id } } pageInfo { hasNextPage endCursor }
     }
   }
   ```

   paginate using `endCursor` until `hasNextPage=false`. `viewer.id` is the
   workspace-specific **app user** (`personaId`), not OAuth client/application id
   or installing admin. `organization.id` is `workspaceId`. record exact team,
   repository-routing label and three distinct nonterminal status UUIDs. working
   must be `started`; in-review/blocked may be `backlog`, `unstarted` or `started`.
   never guess states by name or reuse completed/canceled. an authorized team
   admin must create/select a blocked state if absent.
6. delegate issues to the app in Linear's assignment UI, verifying `delegate.id`,
   not human `assignee.id`; retain a human assignee for accountability. apps cannot
   be project members/leads. revoke in workspace app settings or with
   `POST https://api.linear.app/oauth/revoke`, form `token` and optional
   `token_type_hint=access_token|refresh_token` (not legacy fields). secret rotation
   alone does not revoke previously granted access/refresh tokens, though it
   invalidates client-credentials tokens. reconcile owners after any access loss.

Linear's native agents guide recommends webhooks/agent-session activities. this
connector deliberately uses public issue delegation, ordinary comments and issue
states instead, not that native protocol. leave webhook subscriptions off. if the
current installation UI requires an endpoint/native protocol, stop and validate
with the operator/Linear; do not invent a fake endpoint. onboarding/scopes/polling-only
installation were not live-tested. public references:
[agents](https://linear.app/developers/agents),
[OAuth](https://linear.app/developers/oauth-2-0-authentication),
[app actors](https://linear.app/developers/oauth-actor-authorization),
[GraphQL](https://linear.app/developers/graphql).

## configure and start

requires node 24+, pi's documented session replacement/settled/RPC APIs and a trusted
abra checkout. pi discovers `.pi/extensions/abra-linear/index.ts`; no npm dependency
installation is needed. inspect your installed harness docs and agent tool profiles.

- register actual repositories with `bin/worktree.py`; confirm path/origin/base and
  project instructions. copy `docs/linear.example.json` to gitignored
  `.pi/abra-linear.json` and replace **every** example value.
- `tokenEnv` names an environment variable supplied through your secret mechanism,
  not a token/command. start validates viewer/workspace and all paginated states.
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

the coordinator records `linear-<issue-uuid>` in tasks-axi and snapshots original
source under `data/<task-id>/`. `abra_linear_checkpoint` first binds that task with
`kind: "bind"` and `task: "linear-<issue-uuid>"`, before dispatch. all calls need
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
untrusted work. redaction removes the connector token, common secret patterns and
home paths, not arbitrary confidential content; prepare public summaries carefully.

`make format` and `make test` cover baseline worktrees plus fake GraphQL/pi/native
boundaries and harmless RPC subprocesses: dedupe, scope/control, cancellation,
report/delivery gates, uncertain receipts, exact native proofs, session handoffs and
failure/interrupt/lock handling. no live Linear/OAuth/pi model/PR/CI behavior is
certified. a later authorized smoke check should use disposable report-only issues,
verify identity/states and all config fields first, observe pickup/checks/report or
blocked, two fresh-session handoffs, clarification retention and interruption, then
reconcile owners and revoke test credentials. never admit real work merely to check
credentials or claim installation/provisioning passed from these local tests.
