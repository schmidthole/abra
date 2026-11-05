# local polling-only linear connector

this is a project-local pi extension plus optional **foreground** watch launcher,
not a service, webhook receiver, tunnel, relay, daemon, custom agent runtime or
replacement backlog. the extension is the sole linear poller/admission/reporter.
manual `/abra-linear start` admits one ticket; `bin/linear-watch` opens a fresh
persisted pi rpc process for each subsequent ticket only after a confirmed safe
handoff. loading either does not auto-enable it. polling ends when its pi process
exits and pauses when the machine sleeps; native async owners may survive a crash
or interruption. no unattended lifetime or automatic recovery is promised.

**watch is an explicit trusted operating contract, not isolation:** the operator
and all coordinator/child briefs prohibit detached, untracked, nested, unsupported
foreground and external background writers. ordinary synchronous bash is allowed
but must complete with no surviving background work before handoff. the host checks
recorded Pi-managed async proofs and workflow/publication intents; it does **not**
detect arbitrary hidden shell descendants or enforce a sandbox. opt in only when
you trust the agents, tools, extensions and operator to honor this boundary. unknown
tracked ownership still halts; an empty managed assignment set is permitted for
coordinator-only reports, not evidence that external writers cannot exist.

## create the linear app/agent identity

these are operator instructions for a later authorized setup, **not actions run by
this build**. public [agents](https://linear.app/developers/agents),
[oauth](https://linear.app/developers/oauth-2-0-authentication) and
[actor authorization](https://linear.app/developers/oauth-actor-authorization)
pages were read on 2026-11-04; live provisioning, scope sufficiency and polling-only
app behavior remain untested. recheck those pages if Linear changes its platform.

1. a workspace admin opens Settings → API → OAuth applications → create a new
   application ([public creation link](https://linear.app/settings/api/applications/new)).
   choose a recognizable name/icon such as abra; these become the installed agent's
   identity. keep its client id and secret in your existing secret manager, not in
   this repository, prompts, tickets or shell history. Linear recommends a separate
   workspace to own/manage the OAuth application because admins can access it.
2. for authorization-code installation, register the exact redirect callback URI
   your existing trusted OAuth client can receive. use a one-time/local callback
   client if suitable; the connector implements **no OAuth callback server**. OAuth
   setup may need this redirect, but ongoing polling needs no public domain,
   webhook endpoint, tunnel or relay. do not invent Linear-axi OAuth commands.
3. have a workspace admin authorize the application using `actor=app` (not default
   `actor=user`, and not deprecated `actor=application`). request only:

   | scope | use |
   | --- | --- |
   | `read` | issues, delegation, comments, teams/states/labels and identity; always present in OAuth |
   | `issues:create` | documented creation **and update** issue access; needed for status updates |
   | `comments:create` | create ordinary pickup/checkpoint/report comments |
   | `app:assignable` | make the app available as issue delegate |

   `app:mentionable` is optional and unnecessary here: mentions do not trigger this
   poller. `write` is broader than the targeted scopes above; do not add it merely
   for comment creation. no customer/initiative scope is needed. `admin` cannot be
   combined with app actor mode and is not needed for connector mutations. restrict
   the installed app's team access as well as the local allowlists. validate the
   granted scopes against current platform behavior before admitting real work;
   an access error is a blocker, not permission to silently broaden scope.
4. construct the authorization URL using your OAuth client (percent-encode values):

   ```text
   https://linear.app/oauth/authorize?client_id=CLIENT_ID&redirect_uri=REGISTERED_REDIRECT_URI&response_type=code&actor=app&scope=read,issues:create,comments:create,app:assignable&state=SECURE_RANDOM_STATE
   ```

   generate a cryptographically random state and verify the returned state before
   using the code. prefer PKCE `S256`: also send `code_challenge` and
   `code_challenge_method=S256`; retain its verifier only in the OAuth client.
   admin approval installs the app in the selected workspace. app assignment now
   sets the issue's **delegate**, not human assignee; humans retain accountability.
   select abra in Linear's delegation/assignment UI and verify `delegate.id`, not
   `assignee.id`. apps cannot be project members or project leads.
5. your trusted OAuth client exchanges the returned code at
   `POST https://api.linear.app/oauth/token` with URL-encoded form data:
   `grant_type=authorization_code`, `code`, the identical `redirect_uri`, `client_id`
   and `client_secret`; with PKCE include `code_verifier` (the secret is optional
   for that flow). save `access_token`, `refresh_token`, expiry and granted scope
   securely. never put actual tokens into the redacted example or command line.
   authorization-code access tokens currently last about 24 hours. the operator's
   client owns refresh: same token endpoint, `grant_type=refresh_token`,
   `refresh_token` and client authentication (or `client_id` for PKCE). retain the
   rotated refresh token and follow the documented 30-minute refresh replay grace
   period; that OAuth-specific rule does **not** permit replaying uncertain issue
   mutations. the connector has no token-refresh code and captures its environment
   credential when built; stop/reconcile and start with fresh credentials rather
   than assuming a running process sees environment changes.
6. alternatively, for your own OAuth app, Linear documents an optional **client
   credentials tokens** toggle. an authorized secret client can request
   `grant_type=client_credentials` plus the same comma-separated scopes at the token
   endpoint using client id/secret authentication. this yields an app actor token
   (currently 30-day expiry, no refresh token), initially with access to all public
   teams in that workspace; restrict access on the app details page. acquire a
   token per run as Linear recommends, not a permanently copied API key. changing
   scopes can revoke existing tokens. this is an operator alternative, not automatic
   connector acquisition/installation, and must pass the same identity checks.
7. revoke access through the app's workspace settings or the documented
   `POST https://api.linear.app/oauth/revoke`, form field `token` and optional
   `token_type_hint=access_token` or `refresh_token`. never combine that field with
   legacy token fields. removing app team access can also interrupt active work.
   rotate an exposed client secret in Settings → API; rotation alone does not revoke
   previously granted workspace access/refresh tokens (client-credentials tokens
   are invalidated). reconcile all active native/publication owners after auth loss.

**platform distinction:** Linear's agents getting-started guide recommends enabling
webhooks/Agent session events and responding with native agent activities (including
a fast acknowledgment). this polling-only connector deliberately does not implement
that native session protocol: it uses public GraphQL issue delegation plus ordinary
comments and configured issue states, not native agent-session activity/status.
leave webhook subscriptions off for this connector; if the current app creation/UI
requires an endpoint or webhook-native agent behavior, stop and validate that
prerequisite with the operator/Linear. do not configure a fake endpoint or claim
that webhook-free installation/native session UX was live-tested.

### obtain ids without guessing

with the **installed app's access token**, use an authorized GraphQL client against
`https://api.linear.app/graphql`, `Authorization: Bearer <access token>`. the following
are read-only examples for future operator use, not queries performed in this build:

```graphql
query AbraSetupIdentity {
  viewer { id name }
  organization { id name }
}
query AbraSetupTeams($after: String) {
  teams(first: 100, after: $after) {
    nodes { id name key }
    pageInfo { hasNextPage endCursor }
  }
}
query AbraSetupLabels($after: String) {
  issueLabels(first: 100, after: $after) {
    nodes { id name team { id } }
    pageInfo { hasNextPage endCursor }
  }
}
query AbraSetupStates($team: ID!, $after: String) {
  workflowStates(first: 100, after: $after, filter: {team: {id: {eq: $team}}}) {
    nodes { id name type team { id } }
    pageInfo { hasNextPage endCursor }
  }
}
```

store `viewer.id` beside the token: it is the workspace-specific **app user id**,
not the OAuth client id, application id, installing admin or a human assignee.
copy it to `personaId`, and `organization.id` to `workspaceId`. paginate each
connection until `hasNextPage` is false using its `endCursor` as `after`; supply
the selected team uuid to the state query. create/select a repository routing
label in Linear and record its uuid and intended team. create/select three distinct
nonterminal workflow states per team: working must have type `started`; in review
and blocked may be `backlog`, `unstarted` or `started`. names alone are not mappings.
if blocked does not exist, an authorized team admin must create/select one; never
reuse completed/canceled or guess. local startup validates all configured mappings.

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
3. create/install an app-user oauth identity using the onboarding section below.
   the connector does not install an app, acquire/refresh/revoke tokens, or store
   credentials. it uses no webhook or native agent-session subscription. a personal
   key for a different viewer is intentionally rejected, not a fallback identity.
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

## foreground watch: opt in, run, stop

requires a POSIX host (macos/linux; Windows watch is rejected), node 24+,
the documented Pi RPC/`entry_appended`/settled lifecycle APIs and
compatible installed `pi-subagents` public event-bus RPC with process-terminal proof
version 1 / lifecycle version 3, bounded native status/fleet projections and
public async lifecycle files (inspected package: 0.84.0). no package installation
is performed by this repository. an absent/incompatible native adapter blocks watch,
even for a coordinator-only task. ordinary one-ticket manual mode needs no watch
adapter. use an already trusted project with working Pi model configuration; watch
never auto-confirms project trust, native permission dialogs or publication prompts.

`docs/linear.example.json` includes this explicit acknowledgment:

```json
{ "watch": { "trustedManagedWork": true } }
```

copying/enabling it accepts the operating contract at the top of this guide. omit
`watch` entirely for manual-only operation. also acknowledge the contract on **each**
launcher invocation; configuration alone never starts anything. configuration is
operator-owned, never populated from ticket text. the exact current CLI is:

```sh
# in the trusted abra checkout, with the configured token environment populated
bin/linear-watch --help
bin/linear-watch --trusted-managed-work
# optional: select the installed pi executable, not a session-resume command
bin/linear-watch --trusted-managed-work --pi /absolute/path/to/pi
```

no `--no-session`, resume, inherited ticket prompts or automatic dialog responses
are sent: each child is `pi --mode rpc` with its normal persisted session resources.
watch consumes events before sending `get_state` or the extension start command.
its per-child nonce is sent only to that child and binds ready/admission/handoff
entries to its native session, connector owner, immutable issue/task and outstanding
request. successful RPC handling, `agent_end`, `agent_settled`, prose and zero exit
are never sufficient handoffs. this is trusted local extension IPC, not a security
boundary against malicious same-process extensions or arbitrary file writers.

watch repeatedly asks the **extension**, not Linear, for a structured outcome:

- `no-work`: keep this same child polling; do not spawn new processes for empty scans.
- `working`: retain the owning child/session; no second ticket admission.
- `awaiting-input`: preserve the clarification session, including an explicit
  `waiting` checkpoint. RPC dialogs are diagnosed but **never auto-answered**;
  the thin launcher has no interactive dialog client. resolve task clarification
  through Linear comments (which halt for saved-steering reconciliation) or
  interrupt and reopen the saved Pi session manually. do not start a replacement
  watch while that task has unresolved owners.
- `handoff` with `review` or `blocked`: require confirmed Linear terminal comment
  and status receipts, bound/sent coordinator dispatch, settled coordinator and
  no pending messages, a validated non-active workflow, all dispatch/publication
  attempts reconciled, and exact native terminal evidence for every recorded run.
- `uncertain`: halt; no blind command retry, stale-lock cleanup or fresh child.

### supported managed handoff boundary

only top-level **single-leaf Pi-managed async** assignments are supported for
automatic handoff. the extension captures public `subagent:async-started` identities
before using any native proof, rejects unknown/active/omitted native status/fleet
projection entries, and checks for ownership changes at handoff. these projections
are supplemental tracked-native checks, not an OS-wide writer inventory. it reads `status.json` only beneath the live native
start's captured canonical artifact directory, never a model-supplied proof path;
it requests targeted native status by the captured run id and checks the public
`details.lifecycleStatus.processTerminal` projection. it requires the exact runner
instance's observed close and any canonical lease release/free observation. this is
separate from task success, which still needs the existing workflow/delivery gates.

every existing workflow assignment must have confirmed dispatch, a stopped/returned
validated checkpoint and recorded `run_ids`; those ids must exactly cover the
captured starts without unknown, duplicated or unassigned runs. every attempt must
be non-active. blocked attempts (including aborted dispatch/publication intents)
need a saved `reconciliation` decision with evidence plus an outcome/evidence on the
attempt, using the existing workflow schema; a model's `stopped: true` is not proof.
actual tracked Pi runner close evidence is still required for blocked/paused runs.
coordinator-only reports may have no assignments under the explicit trusted contract.

foreground native children, native workflow/parallel/chain roots, nested delegation,
external-cli/external-job writers, schedules, revived runs, custom runner launchers,
missing/foreign/stale/malformed native evidence and unresolved intents halt automatic
handoff. supported ordinary synchronous shell work is **not** blanket-blocked;
agent/operator compliance with no surviving untracked shell writers is assumed,
not mechanically proven. revisit this adapter if adding a supported run type or
stronger containment; do not silently replace native proofs with PID tests, timestamps,
result files, exit codes, tracker/model status or arbitrary path assertions.

on a safe handoff the actual extension lock owner saves release/proof receipts and
releases its correlation and lock. watch independently checks the durable connector
record and absent lock against the outcome, rechecks current Pi session/pending
state, closes stdin for orderly shutdown and waits for clean child close before
starting another child. a blocked task stays blocked in tasks-axi; advancing does
not complete or silently resume it. deduplication still prevents re-picking it.

the single tracked Pi child has its own POSIX process group so terminal ctrl-c
reaches watch first. it remains piped, referenced and awaited/reaped; this is signal
isolation, not daemonization or permission for agents to detach writers.

press **ctrl-c** (or send SIGTERM) to stop watch admission and request the extension's
stop/cancellation/reconciliation path, then close the child's stdin. requests and
shutdown have 60-second deadlines; a stuck child receives SIGTERM and diagnostics
say ownership may survive (there is no claim all subagents were killed). active or
unknown owners cause an unsuccessful halt, not a restart or fabricated blocked
handoff. terminal input is not forwarded to the model. diagnostics are concise JSON
on stderr, without raw model/tool stderr, ticket contents or tokens. retain the
saved Pi sessions, connector journal, task manifest/checkpoints and native artifacts
for recovery; child termination alone is **not** owner reconciliation. no cross-machine
or separate-clone lock is provided. after a failure, use the manual recovery section,
not another launcher invocation that deletes evidence.

### first authorized installation / smoke-check checklist

these checks are for a later explicitly authorized operator run; none was live-run
in this build:

1. run `node --version`, `pi --help`, `bin/linear-watch --help`, `make format` and
   `make test`. inspect/trust the checkout and its global/project extensions; verify
   Pi RPC/native APIs match the above prerequisites. do not install/enable globally
   merely to test. loading the project entrypoint must leave `/abra-linear status`
   off; never use `/start` as a read-only credential check.
2. create/install the app through your OAuth client, verify identity and paginated
   ids read-only, and restrict app teams. review every field in the example config;
   check repository registry/path/origin/base and explicitly choose authority and
   three distinct nonterminal states. all example UUIDs/paths must be replaced.
3. inject only the **access token** as the environment variable named by `tokenEnv`
   using your existing secret mechanism; do not expose client secret/refresh token
   to the coordinator. configure Pi/model and report-only harness permissions
   separately. run `pi` in this trusted checkout to inspect available connector
   commands/trust without starting polling, then quit before starting watch.
4. choose a disposable, non-sensitive report-only issue in the allowlisted team,
   apply exactly one mapped repository label, and delegate it to the app (keep a
   human assignee). explicitly authorize the live test before manual `/abra-linear
   start` or the watch command. start validates viewer/workspace/states **before**
   discovery/mutations; it can immediately pick up any eligible current delegation.
5. observe a pickup comment/working state, saved real task/manifest/native ids,
   meaningful approach/checkpoint comments, visible public report + in review **or**
   explicit blocked reason/next action. clarification must retain its session.
   under watch, observe exact stopped native proofs and durable release before a
   fresh process picks up a second test issue. no completion status/merge/deploy.
6. interrupt during waiting and, with separate authorization, active work; inspect
   remaining owners/receipts before manual recovery. verify revoked access or an
   uncertain publication halts instead of replaying. never manufacture stale locks,
   mutate production tasks or kill unknown owners as a casual smoke test.
7. stop, reconcile all test owners and remove/revoke test credentials through the
   operator's normal secret lifecycle. record what was actually tested; local
   fake-boundary tests do not certify live app install, native proofs or PR/CI.

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
| `kind` | `bind`, `approach`, `progress`, `checks`, `waiting`, `blocked`, `review` |
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
a truthful blocked comment/state instead, except an explicit `waiting` checkpoint
retains clarification in its current session without a terminal handoff.

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
uses `kind: waiting` with the question and next action, retaining the session.
a subsequent human reply or acceptance change halts new actions pending saved
steering/owner reconciliation, not automatic brief revision/resumption. completed
issues are never reopened.

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

watch tests additionally use harmless local JSONL rpc subprocesses (never real pi,
model or linear processes) to exercise multiple fresh-child handoffs, no-work
waiting, clarification/dialog retention, blocked safety, wrong/duplicate/out-of-order
outcomes, startup/prompt/timeout/crash/malformed failures, interruption, locks and
uncertain publications. native adapter tests use fake event-bus replies and local
lifecycle files for exact run/runner/lease checks and unsupported owner failures.
these are protocol evidence, not a live native capability handshake or proof of
agent compliance. a future live installation/smoke check requires separate authority.

public references: [graphql](https://linear.app/developers/graphql),
[oauth](https://linear.app/developers/oauth-2-0-authentication),
[agents](https://linear.app/developers/agents),
[published schema](https://github.com/linear/linear/blob/master/packages/sdk/src/schema.graphql).
