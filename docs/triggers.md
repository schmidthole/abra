# triggers

a trigger connects an external conversation system (slack, linear, jira, zendesk)
to an abra instance. each system gets a thin adapter; all session, queue, archive,
and recovery behavior lives in the shared runtime, `triggers/runtime.py` (stdlib
only). the runtime only ever calls `<root>/bin/abra`; it never runs claude itself.

v1 is queue + batch only: there is no mid-turn steering, interrupt, or stop command.

## model

- a conversation (slack thread, linear issue comments, ticket) is one session.
  its key, `conv`, matches `[A-Za-z0-9][A-Za-z0-9:._-]{0,127}`, for example
  `slack:<channel>:<thread_ts>`, and is passed to `bin/abra run --key`.
- a new session starts only when the bot is tagged outside a known conversation.
  the tagged message is the first message of the session.
- every later message in the conversation, from anybody in it, adds to the session.
- each conversation is one work item: abra uses its work id as the tasks-axi task id
  and `data/<work_id>/` for reports.

## adapter api

one adapter per process. the adapter has a `name` attribute (`[a-z0-9]+(-[a-z0-9]+)*`,
for example `slack`), which names its store.

intake: call `runtime.submit(Event(kind, conv, msg_id, sender, text))` from any
thread. it returns true when the message was queued.

- `kind`: `start` when the bot was tagged outside a known conversation, `message`
  for any other message in a conversation. adapters may send `start` whenever the
  bot is tagged; a `start` on a known conversation is treated as a `message`.
- `msg_id`: unique within the conversation, same pattern as `conv`, and ordered by
  arrival in `history()`.
- `sender`: platform user id, `[A-Za-z0-9][A-Za-z0-9@:._ -]{0,127}`.
- `text`: non-empty; one message must encode to at most 32 kib.

invalid events are dropped with a log line and never reach `bin/abra`. a repeated
`msg_id` (the conversation's last accepted message or one still pending) is ignored,
so platform redelivery is safe, including on an archived conversation (no resume
text is posted). a conversation holds at most 200 pending messages; past that, new
messages are dropped with a log line and acked `failed`.

output, implemented by the adapter (called from runtime threads, so make them
thread-safe; `reply` and `ack` from `submit` run while the runtime holds its lock,
so keep them quick):

- `reply(conv, text)`: post text into the conversation. the adapter chunks to its
  platform limits.
- `ack(conv, msg_id, state)`: state is `queued`, `running`, `done`, or `failed`.
  replace the previous marker on that message (slack: ⏳ 👀 ✅ ❌).
- `history(conv) -> list[Message(msg_id, sender, text)]`: full ordered history,
  used for resurrection and restart catch-up. report the bot's own posts with
  `sender` equal to the runtime's bot name: catch-up skips them and resurrection
  keeps them as context.

exceptions raised by adapter methods are logged by type and never stop the runtime.

## turns, queue, and batch

- at most one turn runs per conversation; different conversations run concurrently
  up to `workers`.
- a message is acked `queued` when accepted. messages that arrive while a turn runs
  stay queued and all go into the next turn, in order, as one `--messages-file`.
  a batch holds at most 50 messages and 32 kib (bin/abra's limits); any remainder
  runs in the following turn.
- a turn acks its messages `running`, then `done` (exit 0) or `failed`.
- the turn call is

  ```sh
  <root>/bin/abra run --key <conv> --messages-file <tmp> --work-id <work_id> \
    [--session-id <uuid>] [--context-file <tmp>]
  ```

  `--session-id` is passed on the first turn of a session (and after resurrection);
  `--context-file` only when resurrecting. temp files are 0600 under
  `data/triggers/tmp/<adapter name>/` (0700) and removed after the call, including
  when writing them fails. at startup the runtime removes only its own adapter's
  leftover temp files and stale store temp files. it refuses to start if
  `data/triggers/tmp` or its adapter directory is a symlink or not a directory
  (a symlinked `data/triggers` is allowed). argv lists only; no shell.
- exit 0: the stdout result text is posted with `reply` (nothing is posted when it
  is empty).
- exit 75 (busy): the batch is acked `queued` again and retried after a backoff
  (5s doubling, capped at 300s). there is no `failed` ack.
- any other exit: the fixed error reply is posted and the batch is acked `failed`.
  the messages are not retried; a new reply starts a new turn.

bin/abra's stderr is inherited by the runtime's stderr (the deployer's log). stderr,
tracebacks, and stdout from failed calls are never posted to the conversation.

## fixed texts

no llm is involved in these; `<name>` is the configured bot name.

- announcement, posted on `start` before the message is queued or any agent runs:
  `<name> is on it. this thread is now work item <work_id> (session <uuid>). reply in this thread to add to it.`
- resume, posted when an archived conversation gets a message:
  `<name> is resuming work item <work_id> (session <uuid>).`
- error: `<name> hit an error on this turn. reply here to try again.`

work ids are `<slug(name)>-<4 lowercase base32 chars>`, unique in the store and
not already present under `data/`. session ids are lowercase uuid4.

## store

`<root>/data/triggers/<adapter name>.json`, written atomically (temp file, fsync,
rename) with mode 0600 in a 0700 directory, under a lock. a sibling `.lock` file
(0600) is held for the process lifetime, so a second runtime for the same adapter
on the same root refuses to start. a corrupt store fails closed at startup.

```json
{"version": 1, "convs": {"slack:C1:1712.1": {
  "work_id": "abra-k3q7", "session_id": "<uuid or null>",
  "created": "2026-10-21T12:00:00Z", "last_used": "2026-10-21T12:05:00Z",
  "last_msg_id": "1712.9", "archived": false,
  "fresh": false, "resumed": false, "pending": []}}}
```

`pending` holds accepted messages that have not completed a turn, including the
batch of a turn interrupted by a restart; they survive restarts and are re-acked
`queued` and run at startup. `fresh` means the next turn passes `--session-id`;
`resumed` means it also passes `--context-file`. `fresh` clears after any completed
turn (exit other than 75), because bin/abra may have stored a session by then and
rejects `--session-id` for a key with a session. `resumed` clears only after a turn
exits 0, so a failed resurrection turn keeps the history for the next attempt;
bin/abra ignores the context once a session is stored.

## archive and resurrection

- at startup and every 24h, conversations idle longer than `archive_days` (no
  pending work, `last_used` older than the cutoff) are marked archived: `work_id` is
  kept and `session_id` cleared. then `bin/abra sessions prune --older-than
  <archive_days>` runs.
- a message on an archived conversation resurrects it: a new uuid is minted, the
  resume text is posted, and the next turn passes `--session-id` plus a context file
  built from `history(conv)`: a note pointing at `data/<work_id>/`, then the first
  message and the most recent messages that fit in 256 kib, with a count of omitted
  messages between them. messages in the current batch are left out of the context.

## catch-up

at startup, for each non-archived conversation used within `catchup_hours` (24),
history messages after `last_msg_id` are queued (bot posts skipped). if
`last_msg_id` is not in the history, catch-up is skipped for that conversation.

## security

- all event fields and history are untrusted. inputs are validated against fixed
  patterns and size bounds; invalid events are dropped. bin/abra wraps every message
  and the context in nonce-delimited untrusted blocks naming the sender.
- logs name conv keys, work ids, msg ids, sender ids, counts, and exit codes only;
  never message text or history content. log lines are lowercase.
- the store and temp files contain message text in plaintext (0600). keep instance
  roots on an encrypted volume on a single-tenant host or container.
- anybody who can post in a conversation the bot was tagged into can add turns.
  scope the bot's platform membership accordingly; bin/abra treats every message
  as a request from its sender, never as operator authority.

## running against an instance root

any abra root works, base or specialty; many runtimes can run in parallel against
different roots or with different adapters.

```sh
python3 triggers/cli.py --root /path/to/abra-instance --name helper
```

| setting | effect |
| --- | --- |
| `--root` | abra instance root; must contain an executable `bin/abra` |
| `--name` | bot name used in fixed texts and work ids, default `abra` |
| `ABRA_ARCHIVE_DAYS` | days before an idle conversation is archived, default 90 |
| `ABRA_TRIGGER_WORKERS` | concurrent turns, default 2 |

bin/abra's own `ABRA_MAX_CONCURRENCY` still applies; busy exits are retried.

## slack adapter

`triggers/slack.py` serves slack threads over socket mode. see
[slack.md](slack.md) for setup and security notes.

## reference adapter

`triggers/cli.py` reads json-lines events on stdin and writes replies and acks as
json lines on stdout. history is served from the events and replies it has seen.
at end of input it waits for queued work to finish, then exits.

```sh
printf '%s\n' '{"kind": "start", "conv": "cli:demo:1", "msg_id": "1", "sender": "U1", "text": "hello"}' \
  | python3 triggers/cli.py --root "$PWD"
```

```json
{"type": "reply", "conv": "cli:demo:1", "text": "abra is on it. ..."}
{"type": "ack", "conv": "cli:demo:1", "msg_id": "1", "state": "queued"}
```

## writing an adapter

1. create `triggers/<platform>.py` with a class that has `name`, `reply`, `ack`,
   and `history`.
2. build the runtime with `runtime.add_arguments(parser)` and
   `runtime.from_args(adapter, args, os.environ)`, then `start()`.
3. map platform events: a bot mention outside a known conversation is `start`;
   every other message in a thread or conversation is `message`. ignore the bot's
   own posts at intake.
4. call `submit` for each event; call `stop()` on shutdown. pending work stays
   stored and resumes on the next start.
5. keep platform credentials in the deployer's secret store, never in the repo.

## acp client

`triggers/acp.py` is a stdlib acp v1 client (agent client protocol, json-rpc 2.0
over newline-delimited stdio) for driving an agent adapter such as
`claude-agent-acp` or `codex-acp`. it is groundwork for a resident session; the
runtime above does not use it yet.

- `Client(argv, ...)` spawns the adapter (argv list, no shell) in its own process
  group. `start()`, `initialize()` (protocol version 1, no fs or terminal
  capabilities), then `new_session`, `load_session`, `resume_session`, `prompt`
  (blocks until the stop reason), `cancel`, `set_mode`, `close_session`, and
  `steer` (`_session/steering`; returns the outcome, raises `MethodNotFound` when
  the agent lacks it). load, resume, and close raise `Unsupported` without sending
  when the agent did not advertise them.
- `on_update(params)` receives every `session/update`, during or outside a prompt.
  `permission(params)` returns an offered option id; anything else, including an
  exception, rejects (default: reject all). other agent requests (`fs/*`,
  `terminal/*`, unknown) get -32601.
- callbacks run on one dispatcher thread in arrival order, so a prompt returns
  only after its updates were delivered. they must not make blocking client calls.
- lines over `max_line` (8 mib) and invalid json are dropped and logged by type.
  logs carry method names, ids, sizes, and error codes, never content.
- agent exit fails pending calls with `AgentExited` and calls `on_exit(code)`.
  `close()` sends nothing, closes stdin, sigterms the process group, sigkills it
  after `kill_timeout`, and reaps.
