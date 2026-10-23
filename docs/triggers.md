# triggers

a trigger connects an external conversation system (slack, linear, jira, zendesk)
to an abra instance. each system gets a thin adapter; intake, the store, and
recovery live in the shared runtime (`triggers/runtime.py` and
`triggers/resident.py`, stdlib only). the runtime hosts one long-lived agent
session over acp (agent client protocol) that serves every conversation; abra
posts back with a `reply` tool. `bin/abra run` stays for one-shot use by hand and
is not used by triggers.

## model

- a conversation (slack thread, linear issue comments, ticket) has a key, `conv`,
  matching `[A-Za-z0-9][A-Za-z0-9:._-]{0,127}`, for example
  `slack:<channel>:<thread_ts>`.
- a conversation starts only when the bot is tagged outside a known conversation.
  the tagged message is its first message; every later message in it, from anybody
  in it, is delivered to the same resident session.
- each conversation is one work item: abra uses its work id as the tasks-axi task
  id and `data/<work_id>/` for reports. the session sees every conversation, so
  work can be shared across threads of the same instance.

## adapter api

one adapter per process and per instance. the adapter has a `name` attribute
(`[a-z0-9]+(-[a-z0-9]+)*`, for example `slack`), which names its store.

intake: call `runtime.submit(Event(kind, conv, msg_id, sender, text))` from any
thread. it returns true when the message was queued.

- `kind`: `start` when the bot was tagged outside a known conversation, `message`
  for any other message in a conversation. adapters may send `start` whenever the
  bot is tagged; a `start` on a known conversation is treated as a `message`.
- `msg_id`: unique within the conversation, same pattern as `conv`, and ordered by
  arrival in `history()`.
- `sender`: platform user id, `[A-Za-z0-9][A-Za-z0-9@:._ -]{0,127}`.
- `text`: non-empty; one message must encode to at most 32 kib.

invalid events are dropped with a log line and never reach the agent. a repeated
`msg_id` (the conversation's last accepted message or one still pending) is
ignored, so platform redelivery is safe. a conversation holds at most 200 pending
messages; past that, new messages are dropped with a log line and acked `failed`.
events submitted while the runtime is stopping are ignored (catch-up picks them up
on the next start).

output, implemented by the adapter (called from runtime threads, so make them
thread-safe; `reply` and `ack` from `submit` run while the runtime holds its lock,
so keep them quick):

- `reply(conv, text)`: post text into the conversation. the adapter chunks to its
  platform limits and escapes platform control sequences.
- `ack(conv, msg_id, state)`: state is `running` when the message reaches the
  agent, or `failed`. replace the previous marker on that message (slack: 👀 ❌).
- `history(conv) -> list[Message(msg_id, sender, text)]`: full ordered history,
  used for restart catch-up. report the bot's own posts with `sender` equal to the
  runtime's bot name: catch-up skips them.

exceptions raised by adapter methods are logged by type and never stop the runtime.

## fixed texts

no llm is involved in these; `<name>` is the configured bot name. an adapter
may word them for its platform by defining `announcement(name, work_id)` or
`error_text(name)` returning text (the linear adapter does: issues have no thread
replies).

- announcement, posted on `start` before the message is queued:
  `<name> is on it. this thread is now work item <work_id>. reply in this thread to add to it.`
- error, posted to each conversation of a turn that errors or is refused:
  `<name> hit an error on this turn. reply here to try again.`

work ids are `<slug(name)>-<4 lowercase base32 chars>`, unique in the store and
not already present under `data/`.

## store

`<root>/data/triggers/<adapter name>.json`, written atomically (temp file, fsync,
rename) with mode 0600 in a 0700 directory, under a lock. a sibling `.lock` file
(0600) is held for the process lifetime, so a second runtime for the same adapter
on the same root refuses to start, and `resident.lock` refuses a second runtime
of any adapter on the root. a corrupt store fails closed at startup. stale
temp files of this store and of `resident.json` and `bridge.json` are removed at
startup.

```json
{"version": 1, "convs": {"slack:C1:1712.1": {
  "work_id": "abra-k3q7", "created": "2026-10-21T12:00:00Z",
  "last_used": "2026-10-21T12:05:00Z", "last_msg_id": "1712.9", "pending": []}}}
```

`pending` holds accepted messages whose turn has not ended; they survive restarts
and are delivered again at startup (at least once). stores written by the old
one-shot runtime load as is: their `session_id`, `archived`, `fresh`, and
`resumed` fields are dropped.

## catch-up

at startup, for each conversation used within `catchup_hours` (24), history
messages after `last_msg_id` are queued (bot posts skipped). if `last_msg_id` is
not in the history, catch-up is skipped for that conversation.

## security

- all event fields and history are untrusted. inputs are validated against fixed
  patterns and size bounds; invalid events are dropped. every message reaches the
  agent in a nonce-delimited untrusted block naming its sender.
- logs name conv keys, work ids, msg ids, sender ids, counts, sizes, and error
  codes only; never message text, agent output, or tokens. log lines are lowercase.
- the store, `resident.json`, and the agent's own session files contain message
  text in plaintext (0600). keep instance roots on an encrypted volume on a
  single-tenant host or container.
- anybody who can post in a conversation the bot was tagged into can add messages.
  scope the bot's platform membership accordingly; abra treats every message as a
  request from its sender, never as operator authority.
- one instance is one trust boundary: every conversation shares the resident
  session's context.

## running against an instance root

any abra root works, base or specialty; one runtime per root.

```sh
ABRA_AGENT_CMD="npx @agentclientprotocol/claude-agent-acp" \
  python3 triggers/cli.py --root /path/to/abra-instance --name helper
```

| setting | effect |
| --- | --- |
| `--root` | abra instance root; must contain an executable `bin/abra` |
| `--name` | bot name used in fixed texts and work ids, default `abra` |

the agent settings are in the table under resident session below.

## slack adapter

`triggers/slack.py` serves slack threads over socket mode. see
[slack.md](slack.md) for setup and security notes.

## linear adapter

`triggers/linear.py` polls linear with linear-axi for todo issues assigned to the
bot user, one issue per conversation. see [linear.md](linear.md) for setup, the
outcome contract, and security notes.

## reference adapter

`triggers/cli.py` reads json-lines events on stdin and writes replies and acks as
json lines on stdout. history is served from the events and replies it has seen.
at end of input it waits until nothing is pending or running, then exits; it
exits 1 if the agent stopped. sigint or sigterm stops it like the slack adapter.

```sh
printf '%s\n' '{"kind": "start", "conv": "cli:demo:1", "msg_id": "1", "sender": "U1", "text": "hello"}' \
  | ABRA_AGENT_CMD="npx @agentclientprotocol/claude-agent-acp" python3 triggers/cli.py --root "$PWD"
```

```json
{"type": "reply", "conv": "cli:demo:1", "text": "abra is on it. ..."}
{"type": "ack", "conv": "cli:demo:1", "msg_id": "1", "state": "running"}
```

## writing an adapter

1. create `triggers/<platform>.py` with a class that has `name`, `reply`, `ack`,
   and `history`.
2. build the runtime with `runtime.add_arguments(parser)` and
   `runtime.from_args(adapter, args, os.environ)`, then `start()`.
3. map platform events: a bot mention outside a known conversation is `start`;
   every other message in a thread or conversation is `message`. ignore the bot's
   own posts at intake.
4. call `submit` for each event; call `stop()` on shutdown and exit non-zero when
   `runtime.crashed` is set. pending work stays stored and resumes on the next
   start.
5. keep platform credentials in the deployer's secret store, never in the repo.

## resident session

- start: runs the specialty check, opens the bridge socket, spawns `ABRA_RESIDENT_AGENT_CMD`
  (split like a shell would, run as an argv list with cwd = the instance root, in
  its own process group) and initializes it. `ABRA_AGENT_CMD` remains the legacy
  fallback. `ABRA_AGENT_PROVIDER=claude|codex` defaults to claude. a stored session for the same provider and command
  (`data/triggers/resident.json`, 0600) is resumed (session/resume, else
  session/load) with a restart event; otherwise a new session starts lazily with
  the bootstrap event when the first message arrives.
- inbox: messages from all conversations queue in arrival order. at most one
  runtime prompt is outstanding; the next prompt batches every waiting message
  (up to 50 messages or 256 kib), grouped by conversation.
- steering: claude receives `_session/steering` (`idleBehavior: promptRequired`).
  injected messages remain durable until both the steering rpc and prompt finish,
  including when their responses race. `promptRequired`, `failed`, or an error
  leave messages for the next prompt; -32601 turns steering off. an unexpected
  `startedNewTurn` stops the runtime with messages retained for reconciliation.
  codex always queues arrivals for the next awaited prompt: its steering extension
  can start an unowned turn, so using it would risk losing durable messages.
- framing: `bin/abra`'s `resident_prompt` (shared with the one-shot framing): a
  trusted header and `runtime event:` lines, then per conversation its key and work
  id and one nonce-fenced untrusted block per message with `msg_id` and `from`.
- replies: abra posts with `reply(work_id, text)` through the mcp bridge. if a
  turn's messages all came from one conversation and abra did not reply to it, the
  turn's final text (after its last tool call) is posted there.
- markers: `running` (eyes on slack) when a message reaches the agent; `failed`
  (x) with the fixed error text when the prompt errors or is refused. when the
  agent itself ends a turn `cancelled` (claude-agent-acp does after a rejected
  permission), its messages get one more turn, then fail the same way. an
  unexpected error while preparing a turn fails that batch; an internal error in
  the dispatcher stops the runtime like a crash. no queued or
  done markers. messages stay pending in the store until their turn ends, so a
  crash re-delivers them (at least once).
- permissions: the runtime answers permission requests itself and allows only the
  bridge's reply tool, once: claude-agent-acp's `toolName` must be
  `mcp__abra__reply`, its `mcpServer` must be present and named `abra`, and the
  request must carry the resident session's id. for the legacy claude path the session check does not tell
  subagents apart: abra does not advertise its acp `subagents` capability, so
  claude-agent-acp sends their requests with the root session id too. a request
  carrying `parentToolUseId` (a subagent's call) is rejected, but that is best
  effort, since the adapter can miss it. "only the coordinator posts" therefore
  rests on the `docs/modes/resident.md` rule plus this check; a reply that slips
  through still reaches only this instance's work ids and is rate limited.
  codex instead requires native subagent capability, a root `tool_call` with
  structured `rawInput.server=abra` and `rawInput.tool=reply`, and a matching
  `toolCallId` on an approval marked `_meta.is_mcp_tool_approval=true`. child,
  unknown, completed, and unrelated calls are rejected; titles never authorize.
  everything else is rejected. without native child identity codex reply approvals
  fail closed; use the supported pinned adapter for multi-conversation operation.
  with `ABRA_AGENT_MODE=1` (container only) it sets
  the session mode to `bypassPermissions` (claude) or `agent-full-access` (codex)
  when advertised. absence or rejection of the requested mode stops setup before
  prompting, preserving pending messages. unattended mode bypasses the approval
  check, so the coordinator-only reply instruction remains mandatory.
- jobs: `bin/abra job NAME` hands the job to a running resident runtime over the
  bridge socket (named with its token in `data/triggers/bridge.json`, 0600; the
  socket moves to a private temp directory when the root's path is too long for a
  unix socket); the runtime reads
  the job prompt from the specialty and sends it as a runtime event. waiting jobs
  (at most 20) are kept in `resident.json` until a turn delivers them, so a crash
  does not lose them. with no runtime listening, the job runs one-shot as before.
- specialty: `SPECIALTY.md` goes to claude-agent-acp as `_meta.systemPrompt.append`
  and to codex using the advertised `systemPrompt` extension with append mode and
  text content. a codex adapter missing that capability cannot use a specialty
  prompt. the bootstrap still runs the AGENTS.md startup. the pack's `mcp_config`
  stdio and advertised http/sse servers are passed in `mcpServers`; unsupported
  transports/settings fail setup rather than silently dropping tools. codex's
  reported mcp startup failures also stop the runtime. use a dedicated codex home
  without ambient mcp servers: upstream configuration can override supplied names.
  startup checks user, system, and instance-root TOML configuration and rejects ambient
  MCP, profile, or plugin definitions, including those supplied in `CODEX_CONFIG`.
  codex mode requires python 3.11 or newer for TOML validation.
  codex's `CODEX_CONFIG` must be a json object; the runtime preserves its settings
  and requires `features.multi_agent=true`, `features.apps=false`, and
  `features.plugins=false` so native delegation is available and explicit MCP
  configuration determines integrations. conflicting explicit values fail startup.
  `project_root_markers=[]` fixes project discovery at the instance root; also set
  it in a dedicated codex home's `config.toml` so the adapter's initial config
  discovery uses the same boundary before opening a session.
- model: `ABRA_MODEL` and `ABRA_REASONING_EFFORT`, when set, must be advertised ACP
  configuration options and successfully applied using `session/set_config_option`
  before prompting. otherwise setup fails. when unset the adapter's configured
  defaults apply; use a dedicated provider home for reproducible settings.
- wake: the codex client advertises `subagents: {}` and requires the agent's
  `sessionCapabilities.subagents` before tracking native sessions. parent-scoped
  `subagent_spawned` and terminal `subagent_state_update` events maintain a child
  tree, including descendants and distinct reopened generation ids. duplicate,
  unknown-parent, mismatched-parent, and stale-generation updates cannot finish or
  resurrect another child. completions schedule one reconciliation wake after
  `ABRA_WAKE_GRACE` seconds (default 20), coalescing arrivals during that grace;
  a completion during another conversation's prompt remains queued for afterward.
  live descendants prevent idle clear and stdin-eof drain even if their parents
  have completed. recorded ids in `resident.json` are diagnostic; after restart
  the agent must reconcile its task notes, not assume those children are alive.
  claude retains its legacy open-tool tracking and observed self-start suppression.
  codex adapters lacking the lifecycle capability receive an in-turn wait policy.
- external turns: the pinned codex adapter does not expose a complete root-turn
  lifecycle over ACP. unsolicited root text/thought/tool activity outside an awaited
  runtime turn stops the runtime for reconciliation instead of racing another
  prompt or clearing an active session. do not enable autonomous goal continuations
  in this resident backend. normal child lifecycle updates are supported.
- heartbeat: every `ABRA_HEARTBEAT` seconds (default 1800, 0 turns it off) while
  a session is live and idle, the runtime runs `bin/tasks list --state in_flight` and sends a heartbeat
  event only when tasks are in flight. no file watchers.
- idle clear: when nothing is pending, queued, or running in the background and
  the session has been idle for `ABRA_IDLE_CLEAR` seconds (default 600, 0 is off),
  the runtime sends a checkpoint event ("save your notes": update every
  unfinished task body), waits for it to end however it ends, closes the
  session, and forgets its id. the instance then stays cold (no heartbeat) until
  the next event, which starts a new session with the bootstrap event. a session
  older than `ABRA_MAX_SESSION_AGE` seconds (default 7 days) is rotated the same
  way after one quiet minute. messages that arrive during a checkpoint wait for
  the new session.
- crash: if the agent exits, the runtime stops dispatching and the adapter exits
  non-zero for the orchestrator to restart it; pending messages are re-delivered
  on the next start. sigterm stops intake, drains queued input, running turns,
  native descendants and reconciliation wakes for up to 60 seconds, closes the session, and
  kills the agent's process group. the session id stays stored for the restart.
  on timeout, unfinished messages and diagnostic child ids remain stored; the
  next session must reconcile ownership from task notes before redispatching.

| setting | effect |
| --- | --- |
| `ABRA_AGENT_PROVIDER` | `claude` (default) or `codex`; stored sessions cannot cross providers |
| `ABRA_RESIDENT_AGENT_CMD` | acp agent command; falls back to legacy `ABRA_AGENT_CMD` |
| `ABRA_MODEL`, `ABRA_REASONING_EFFORT` | optional advertised ACP session configuration; unsupported values fail setup |
| `ABRA_AGENT_MODE` | `1` sets the unattended session mode (container only) |
| `ABRA_WAKE_GRACE` | seconds to wait for a self-started turn, default 20 |
| `ABRA_HEARTBEAT` | idle heartbeat period in seconds, default 1800; 0 is off |
| `ABRA_IDLE_CLEAR` | idle seconds before checkpoint and clear, default 600; 0 is off |
| `ABRA_MAX_SESSION_AGE` | session age in seconds before rotation, default 604800 |

the codex ACP contract is pinned to source commit
[`082be156aacac3ef21e231da2efcdf5f6af34a6b`](https://github.com/agentclientprotocol/codex-acp/tree/082be156aacac3ef21e231da2efcdf5f6af34a6b).
its package declares `@agentclientprotocol/codex-acp` version `2.2.2`, but the
registry artifact with that version has different code; use the container's
source-pinned build. `tests/fixtures/codex-acp-082be156.json` records source-derived
v1 lifecycle and permission examples, not a live inference capture.

## acp client

`triggers/acp.py` is a stdlib acp v1 client (agent client protocol, json-rpc 2.0
over newline-delimited stdio) for driving an agent adapter such as
`claude-agent-acp` or `codex-acp`. the resident session runs on it.

- `Client(argv, ...)` spawns the adapter (argv list, no shell) in its own process
  group. `start()`, `initialize(subagents=False)` (protocol version 1, no fs or terminal
  capabilities; codex enables native subagents), then `new_session`, `load_session`, `resume_session`, `prompt`
  (blocks until the stop reason), `cancel`, `set_mode`, `close_session`, and
  `steer` (`_session/steering`; returns the outcome, raises `MethodNotFound` when
  the agent lacks it). load, resume, and close raise `Unsupported` without sending
  when the agent did not advertise them.
- `on_update(params)` receives every `session/update`, during or outside a prompt.
  `permission(params)` returns an offered option id; anything else, including an
  exception, rejects (default: reject all). other agent requests (`fs/*`,
  `terminal/*`, unknown) get -32601.
- callbacks run on one dispatcher thread in arrival order, so a prompt returns
  only after its updates were delivered. they must return quickly: never make
  blocking client calls or wait on a human from a callback.
- lines over `max_line` (8 mib), invalid or too deeply nested json, and non-objects
  are dropped and logged by type. logs carry allowlisted method names, ids, sizes,
  and error codes, never content. `RemoteError` keeps the agent's message in
  `.message`, not in `str()`.
- a waiter thread reaps the agent: when it exits (even if a child keeps stdout
  open), the rest of its process group is killed, pending calls fail with
  `AgentExited`, and `on_exit(code)` runs. `close()` sends nothing, closes stdin,
  sigterms the process group, sigkills it after `kill_timeout`, and reaps.

## mcp bridge

`triggers/mcp_bridge.py` gives a resident agent one tool, `reply(work_id, text)`.
the agent spawns it as a stdio mcp server (`mcpServers` in session/new); each call
is relayed to the runtime over a unix socket in `data/triggers/` (directory 0700,
socket 0600) with a random per-start token from the shim's environment, compared
in constant time. the runtime:

- accepts only `[a-z0-9]+(-[a-z0-9]+)*` work ids that it minted, and resolves the
  conversation from its own store; no tool takes a channel, thread, or user id.
- refuses empty text and text over 32 kib, and allows at most 20 replies per
  conversation per minute.
- posts through the adapter, which escapes output as for any reply.
- logs the work id, conversation key, size, and tool use id; never text or token.
