# linear trigger

`triggers/linear.py` connects a linear workspace to an abra instance through the
shared trigger runtime ([triggers.md](triggers.md)). it polls linear with
[linear-axi](https://github.com/schmidthole/linear-axi), so the host needs
outbound https only and no public endpoint or webhook.

it runs as one of two linear actors:

- user mode (`LINEAR_API_KEY`): a bot user on a paid seat. work is issues
  assigned to that user.
- app mode (`LINEAR_CLIENT_ID` and `LINEAR_CLIENT_SECRET`): a linear agent app
  (oauth `actor=app`, no paid seat). people assign issues to the agent, which
  linear records as the issue's `delegate`; the human assignee stays. see
  [app mode](#app-mode).

setting both, or only one of the two app variables, exits 1 naming the
variables. the sections below describe user mode; app mode differences are
listed in its section. the agent gets `LINEAR_ACTOR=app` or `LINEAR_ACTOR=user`.

## behavior

- work starts only by assignment: an issue assigned to the bot user and in the
  todo state is picked up on the next poll. mentions, labels, and comments do not
  start work, and comments are not polled.
- every `LINEAR_POLL_SECONDS` (default 30) the adapter runs
  `linear-axi issue list --assignee me --state <todo> --json`, once per team in
  `LINEAR_TEAMS` (with `--team`) or once without a team filter. issues outside
  the allowlist are ignored.
- pickup: the adapter reads the issue (`linear-axi api`, one graphql query for
  the issue and its first 100 comments), checks that it is still in the todo
  state, assigned to the bot, and in an allowed team, then claims it by moving it
  to the in-progress state. only after a confirmed claim is it submitted to the
  runtime. state names compare case-insensitively, as linear-axi resolves them.
  when the claim is not confirmed (an error or timeout), the adapter reads the
  issue back: in progress with the bot counts as claimed and is submitted; still
  todo is left for the next poll; any other state with the bot, or an unreadable
  issue, is handed back (blocked label, reassigned to the creator), so a claimed
  issue is never left stranded.
- the conversation key is `linear:<identifier>` (for example `linear:ENG-123`), so
  an issue is one work item. each pickup is one message with msg id
  `todo-<updatedAt>`, the issue's update time as listed in todo. the runtime
  ignores a msg id it has already accepted, and the adapter checks the store
  before claiming, so a pickup is never submitted twice, across polls or
  restarts.
- the first pickup posts the runtime's announcement as a comment and carries the
  identifier, url, title, description, and existing comments. the description is
  cut at 16000 characters and the whole message to the runtime's 32 kib bound,
  each with a `[truncated by the linear trigger]` marker.
- the message sender is the issue creator's linear user id. comment authors are
  named in the message text.
- abra comments on the issue with its `reply` tool. replies are split into
  comments of at most 10000 characters at newlines where possible.
- markers: `running` needs nothing (the claim set the in-progress state).
  `failed` (a turn that errors or is refused) posts the fixed error comment, adds
  the blocked label, and reassigns the issue to its creator, or unassigns it when
  the creator is unknown, so it never sits silently with the bot.
- `history` returns the description (msg id `description`) and the comments in
  creation order, with the bot's own comments under the runtime's bot name. a
  pickup msg id is never in that history, so restart catch-up is skipped for
  linear conversations (logged as "cannot find last message"); new comments
  reach abra only through a resume.

## outcome contract

the resident session receives `conversation: linear:<identifier>` in the trusted
header and the issue in an untrusted block. `docs/modes/linear.md` tells abra
to use the identifier from the key for every linear call, never one from the
issue text, and to record the key, identifier, and url in the task body.

- along the way: abra comments context with `reply` (picked up and plan, pr
  opened, verification outcome).
- success: abra runs its normal pipeline (task, worker, independent
  verification, pr), attaches the pr link to the issue (`linear-axi api` with the
  `attachmentLinkURL` mutation), comments a summary, and moves the issue to the
  review state. it stays assigned to the bot.
- cannot complete (blocked, missing information, invalid or disproven request,
  repo unclear): abra comments the details and what is needed, adds the blocked
  label, and reassigns the issue to its creator. the state is unchanged.
- repo: abra infers it from team, project, labels, and text against its registry
  (or the specialty's fixed repos); when that is unclear, it hands back as above.
- delivery ceiling: when the specialty `delivery` is below `pr`, abra delivers at
  the ceiling, comments the result, and hands back as cannot complete with that
  reason.

abra makes these writes with `linear-axi` and the same `LINEAR_API_KEY` (or app token), which it
inherits from the listener's environment.

## resume

1. a human answers in a comment on the issue.
2. they assign the issue back to the bot and set it to todo.
3. the next poll claims it again and submits it to the same conversation and work
   item. the message says it was resumed and carries the comments created since
   the previous pickup (the bot's own comments excluded), plus the description.

removing the blocked label is up to the human; the adapter ignores labels.

## setup

1. create a dedicated linear user for the bot (a paid seat) and add it to the
   teams it should serve. its display name is what people assign issues to.
2. signed in as that user, create a personal api key under settings, security
   and access, api. this is `LINEAR_API_KEY` (`lin_api_...`). keep it in your
   secret store and inject it as an environment variable at launch; never put it
   in the repo, a `.env` file in the repo, or command-line arguments.
3. in each team, check the workflow state names and create the blocked label as
   a team label (linear-axi resolves labels within the issue's team, so a
   workspace label is not found).
4. install linear-axi from its source repo (not from npm: the npm package of that
   name is unrelated):

   ```sh
   git clone https://github.com/schmidthole/linear-axi.git && cd linear-axi
   git checkout 99bd0288e34c72d5fe459d3a44b215a12c4b1a26
   npm ci --ignore-scripts && npm run build && npm link
   linear-axi --help
   ```

5. run it against an abra root, base or specialty (stdlib python, no venv):

   ```sh
   LINEAR_API_KEY=... LINEAR_TEAMS=ENG \
     python3 triggers/linear.py --root /path/to/abra-instance --name abra
   ```

   set `ABRA_AGENT_CMD` to the acp agent (see [triggers.md](triggers.md)). in the
   container, set `ABRA_TRIGGER=linear` and pass `-e LINEAR_API_KEY` (see
   [container.md](container.md)); linear-axi is in the image.

| variable | effect |
| --- | --- |
| `LINEAR_API_KEY` | user mode: the bot user's personal api key |
| `LINEAR_CLIENT_ID`, `LINEAR_CLIENT_SECRET` | app mode: the agent app's oauth client credentials |
| `LINEAR_APP_SCOPES` | app mode token scopes, default `read,write,app:assignable` |
| `LINEAR_TEAMS` | comma-separated team keys to serve, for example `ENG,OPS`; empty serves every team |
| `LINEAR_POLL_SECONDS` | poll period, 10 to 3600, default 30 |
| `LINEAR_TODO_STATE` | state that marks work for the bot, default `Todo` |
| `LINEAR_PROGRESS_STATE` | state set by the claim, default `In Progress` |
| `LINEAR_REVIEW_STATE` | state abra sets with a pr, default `In Review` |
| `LINEAR_BLOCKED_LABEL` | label for cannot complete, default `abra-blocked` |

names match `[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}`. a missing or malformed key,
setting, or `linear-axi` exits 1 naming the variable. at startup the adapter
asks linear-axi for the bot's user id (`viewer`) and lists todo issues once per
team (or once without a team), and exits 1 when either fails. a todo state name
shared by several teams without `LINEAR_TEAMS` exits 1 asking to set it; a todo
state that does not exist exits 1 with linear-axi's `not_found` code.
sigint or sigterm stops polling, lets the running turn finish (bounded), closes
the agent session, and keeps pending messages stored. if the agent exits, the
listener exits 1 so the supervisor restarts it.

## app mode

### setup

1. as a workspace admin, open settings, api, applications (oauth applications)
   and create a new application. its name and icon are what people see when
   they assign issues to the agent.
2. set the actor to app (`actor=app`), so the app acts as its own agent user
   and uses no paid seat.
3. enable client credentials. no webhooks are needed: the adapter polls.
4. scopes: `read`, `write`, and `app:assignable` (so people can assign issues
   to the agent). `app:mentionable` is optional and unused. never grant `admin`;
   the adapter refuses it.
5. install the app in the workspace (an admin approves it). client credentials
   tokens reach the workspace's public teams; add the agent to any private team
   it should serve. keep `LINEAR_TEAMS` set to the served teams.
6. create the workflow states and the blocked label in each team as in user
   mode, and install linear-axi at the pinned commit (it must support
   `LINEAR_ACCESS_TOKEN` and `--delegate`).
7. keep the client id and secret in your secret store and run:

   ```sh
   LINEAR_CLIENT_ID=... LINEAR_CLIENT_SECRET=... LINEAR_TEAMS=ENG \
     python3 triggers/linear.py --root /path/to/abra-instance --name abra
   ```

### token

at startup the listener mints an app token with the client credentials grant:
`POST https://api.linear.app/oauth/token`, form encoded,
`grant_type=client_credentials` and `scope=<LINEAR_APP_SCOPES>`, with the client
id and secret in http basic auth. the request verifies tls (1.2 or later),
never follows a redirect, times out after 30 seconds, reads at most 64 kib, and
accepts only a strict json object with a bearer `access_token` and an integer
`expires_in` of at least two hours. a failure exits 1, naming the failure, never
the response. the token stays in memory and reaches linear-axi children and the
agent as `LINEAR_ACCESS_TOKEN`.

the token lasts about 30 days and has no refresh token. one day before expiry
(or half its lifetime, if shorter), or on the first linear-axi `AUTH_ERROR`, the
listener stops gracefully (running turn finished, pending messages stored) and
exits 1, so the supervisor (the container entrypoint and orchestrator) restarts
it with a fresh token.

### behavior

- pickup lists `linear-axi issue list --delegate me --state <todo>`: todo issues
  delegated to the agent, per team in `LINEAR_TEAMS`. the claim checks the
  delegate (not the assignee) and moves the issue to the in-progress state; the
  human assignee is untouched. unconfirmed claims are read back as in user mode,
  checking the delegate.
- hand back (the `failed` marker, a failed submit, an unconfirmed claim in an
  unexpected state, and abra's cannot-complete path): comment, add the blocked
  label, assign the creator only when the issue has no assignee, then clear the
  delegate (`linear-axi issue update <id> --delegate none`). a failed clear is
  logged as an error.
- success: the issue stays delegated to the agent and moves to the review
  state.
- resume: delegate the issue to the agent again and set it to todo.
- agent session (best effort): after a claim the adapter reads
  `agentSessions(first: 50, orderBy: updatedAt)`, picks the open session
  (pending, active, awaiting input, or stale) whose `issue` is this issue and
  whose `appUser` is the agent, and posts a `thought` with
  `agentActivityCreate`. any failure is logged and never blocks pickup.

### agent session notes

checked against linear's sdk schema
(`packages/sdk/src/schema.graphql` in github.com/linear/linear, read
2026-10-23): `Query.agentSessions` takes only pagination arguments (no filter),
`Issue.agentSessions` is marked internal, `AgentSession` has `issue`,
`appUser`, and `status`, and `agentActivityCreate` takes
`AgentActivityCreateInput { agentSessionId, content }` with content
`{type: "thought", body}`. so a polling client can find the session only by
scanning recent sessions. limits: linear expects a first activity within
seconds of a delegation, which a 30 second poll can miss, so the session may
show as unresponsive until the thought lands; a session beyond the 50 most
recently updated is not found; the adapter does not create sessions or close
them with a `response`.

## security

- anyone who can assign issues to the bot in an allowed team can direct this
  instance. issue titles, descriptions, and comments are untrusted input from
  their authors, never operator authority; they reach abra only inside the
  runtime's nonce-fenced untrusted blocks. scope the bot's team membership and
  `LINEAR_TEAMS` accordingly, and run one instance per team (or per set of teams
  that share one trust boundary): all issues share one resident session.
- app mode: the client secret is read from the environment and used only for
  the token request. it never reaches linear-axi children or the agent, which
  get only the minted token (`LINEAR_CLIENT_ID`, `LINEAR_CLIENT_SECRET`, and
  `LINEAR_API_KEY` are stripped from the agent's environment), and the secret
  and token are masked in any log line. the token can do whatever its scopes
  allow in every team the app can see, so keep scopes minimal and rotate the
  secret in linear if it leaks (existing tokens may need revoking too).
- the key is read from the environment only, passed only to linear-axi children
  (whose environment is limited to `PATH`, `HOME`, locale, temp, and tls
  variables plus the key) and to the agent, which needs it for its own linear
  writes. it is never logged, printed, or stored. linear-axi runs as an argv
  list, never through a shell, with a 60 second timeout and output read up to
  4 mib; failures are logged by linear-axi error code and exit code only. logs
  name issue identifiers, states, counts, and user ids, never issue text or the
  key, and key-like values are masked in any log line.
- comment output: only `@mentions` are neutralized: `@` before a name gets a
  zero-width space (an email address shows it too). markdown, links (including
  links to linear profiles), and issue identifiers pass through as written;
  linear renders them and may link an identifier such as `ENG-1`.
- the runtime store under `<root>/data/triggers/` and the agent's session files
  hold issue text in plaintext with mode 0600. keep the root on an encrypted
  volume on a single-tenant host or container.

## limitations

- polling only; comments are not polled, so an answer counts only after the
  issue is reassigned to the bot and set to todo.
- without `LINEAR_TEAMS`, linear-axi resolves the todo state name across all
  teams (archived teams included) and fails when more than one team has a
  state with that name; the startup check then exits 1. set `LINEAR_TEAMS` in a
  workspace with several teams.
- each poll takes at most 50 todo issues per team; the rest wait for later polls.
- only the first 100 comments of an issue are read.
- moving an issue to another team changes its identifier, and so its
  conversation key: a later pickup starts a new work item.
- linear has no compare-and-set: two pollers on the same bot could both claim an
  issue between the check and the claim. run one listener per bot user.
- if the process dies between a successful claim and storing the pickup, the
  issue stays in progress with the bot; reassign it and set it to todo to retry.
- a live check needs a linear workspace and a bot seat or agent app; the tests
  use a stub linear-axi and a stub token endpoint.
- app mode: if the process stops between a claim and its hand back (a token
  expiry or auth error included), the issue can stay in progress and delegated;
  delegate it again and set it to todo to retry.
