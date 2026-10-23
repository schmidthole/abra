# headless runner

`bin/abra` handles one event through a native cli and exits. select
`ABRA_AGENT_PROVIDER=claude` (the default) or `codex`; each conversation key resumes
one session belonging to that provider. scheduling, retries, and process
supervision belong to the deployer. resident mode uses a separate acp adapter;
`ABRA_RESIDENT_AGENT_CMD` does not select the headless executable.

```sh
ABRA_AGENT_PROVIDER=codex bin/abra run --key thread-123 --from alice \
  --work-id fix-login --text "fix the login bug in example"
bin/abra run --key ticket-42 --from alice --text-file /path/to/event.txt
bin/abra run --key slack:C01:1700.1 --messages-file /path/to/batch.json
bin/abra job daily-digest
bin/abra sessions prune --older-than 90
```

## provider configuration

codex headless mode requires python 3.11+ and is implemented against codex cli
0.163.0. claude headless mode retains python 3.9 compatibility. use a dedicated
`CODEX_HOME` with operator-provisioned authentication and persistent session
storage; do not mount an unrelated interactive configuration into a deployment.
existing codex login credentials remain available when user config is ignored.
`CODEX_API_KEY` can supply authentication for `codex exec` as documented by codex;
abra does not copy credentials or run login on the operator's behalf.

| variable | effect |
| --- | --- |
| `ABRA_AGENT_PROVIDER` | `claude` or `codex`; default `claude` |
| `ABRA_CLAUDE_BIN` | claude executable, default `claude` |
| `ABRA_CODEX_BIN` | codex executable, default `codex` |
| `ABRA_MODEL` | optional explicit model for either provider |
| `ABRA_REASONING_EFFORT` | optional codex effort; unsupported in claude headless mode |
| `ABRA_SPECIALTY_DIR` | absolute specialty directory; default `specialty/`; empty means unset |
| `ABRA_MAX_CONCURRENCY` | simultaneous runs across keys, integer 1–64, default 2 |
| `ABRA_AGENT_MODE` | only `1` enables the selected provider's permission/sandbox bypass |
| `CODEX_HOME` | codex-owned authentication and session directory |

when model or effort is omitted, codex selects its effective default; abra does
not guess a model. supported effort labels are `none`, `minimal`, `low`, `medium`,
`high`, `xhigh`, `max`, and `ultra`; the selected model/client must support the
requested value or the run fails. explicit model/effort settings override project
config. user config is ignored, while ordinary project config remains usable.

codex receives `exec --json --ignore-user-config --skip-git-repo-check` and the
prompt on stdin. resumption uses `exec resume <exact thread id> -`, never `--last`.
native multi-agent tools are explicitly enabled; account apps and plugins are
disabled to keep mcp tools scoped to the specialty. the git check is skipped because the trusted deployment root may intentionally
have no `.git`; this does not disable sandboxing. ordinary runs explicitly use
`workspace-write` and `approval_policy="never"`: commands needing additional
permission fail instead of waiting for an absent user. `ABRA_AGENT_MODE=1` passes
`--dangerously-bypass-approvals-and-sandbox` to codex or
`--dangerously-skip-permissions` to claude. enable that opt-in only in an isolated
deployment whose credentials and network access are already scoped. these options
cannot override managed policy.

## inputs and results

`run` wraps event text in delimited untrusted-data blocks naming the requester and
key. the provider's final answer is printed to stdout, progress/errors to stderr.
claude uses `-p --output-format json`; codex JSONL is accepted only with a thread
id, completed turn, and final agent message. malformed/incomplete output, terminal
errors, and nonzero process exits are failures even if an answer was emitted.

keys match `[A-Za-z0-9][A-Za-z0-9:._-]{0,127}`; requesters also allow `@` and spaces.
event text is limited to 32 kib of utf-8. supported options:

- `--text T` or `--text-file F`: one non-empty event; `--from` defaults to `unknown`.
- `--messages-file M`: replaces text input with a json array of 1–50 objects with
  exactly `from` and non-empty `text`, at most 32 kib total. messages retain arrival
  order and individual senders. combining it with `--from` is a usage error.
- `--work-id W`: stable tasks-axi/report identity, lowercase slug at most 64 chars.
  use `W` as the task id and `data/W/` for reports. it is stored with the session,
  reused when omitted on later events, and cannot change on the same conversation.
  use it when callers need to announce an identity before the provider starts.
- `--session-id U`: preassign a canonical lowercase uuid for a fresh **claude**
  session only. codex returns its own thread id; this option fails before launch
  for codex and when a session already exists.
- `--context-file C`: non-empty utf-8 prior history, at most 256 kib, framed as
  untrusted historical data. it is used only for a fresh conversation; a stored
  session causes it to be ignored with a log message.

`job <name>` reads `jobs.<name>.prompt` from the specialty and uses the key
`job:<name>:<utc yyyy-mm-dd>`. if a resident runtime is listening on this root's
bridge, the job is handed to that resident session instead of invoking a cli.

one key never runs twice concurrently. a busy key or full concurrency cap exits
75 without queueing; usage errors exit 2, other failures exit 1. prompts and prior
history travel on stdin rather than command-line arguments. specialty instructions
and translated codex configuration are arguments; keep secrets out of literal
specialty configuration and use environment-aware server wrappers.

## session continuity and recovery

`data/sessions.json` stores version 1 entries with `provider`, `session_id`,
`work_id`, and `updated`, written atomically with owner-only permissions under a
shared lock. old entries without version/provider are interpreted as claude and
migrated on the next write. unknown versions/providers fail closed. switching
providers on an existing key fails before launch and preserves its mapping; use a
new key with the same work id and an explicit context file for an intentional
provider migration.

failed runs never automatically replay the event in a fresh session. a turn may
have performed external actions before its failure. any valid returned thread id
is saved even after a partial failure so the next event can ask the agent to
reconcile its work. malformed output without an id preserves the old mapping.
a codex resume returning a different thread id is rejected without replacing the
stored mapping. this detects unexpected fallback but cannot undo actions already
performed by the provider.

if a session is genuinely missing, first reconcile its task notes and external
outcomes. then start a new conversation key with the same work id and a context
file. do not blindly replay the original request. `sessions prune --older-than
DAYS` (1–3650) removes mappings whose last recorded thread activity is older than
the threshold, missing, or unparsable; it prints removed keys. pruning does not
delete native provider history. it is an operator action, never an agent action.

## specialty and mcp

when a specialty exists its startup check must pass before either provider runs.
claude retains `--append-system-prompt` and `--mcp-config --strict-mcp-config`.
codex injects specialty text through `developer_instructions`, explicitly stating
that the base `AGENTS.md` rules win on conflict. normal project instructions remain
loaded. instructions guide the model; deployment permissions enforce isolation.

codex translates the specialty's `mcp_config` json into an explicit `mcp_servers`
configuration. only these losslessly mapped forms are accepted:

- `{"mcpServers":{"name":{"command":"server","args":[],"env":{}}}}` for stdio;
  an explicit `"type":"stdio"` is optional.
- `{"mcpServers":{"name":{"type":"http","url":"https://example.com/mcp","headers":{}}}}`
  for streamable http; `headers` becomes `http_headers`.

unknown fields, unsupported transports, invalid values, and `${...}` variable
expansion fail before launch. use a server wrapper that reads its credentials from
the environment when the existing configuration needs expansion. every configured
server is marked required, so initialization failure fails the run. no specialty
mcp configuration means an empty explicit server set.

`--ignore-user-config` excludes the normal `CODEX_HOME/config.toml`. because codex
can merge other config layers, abra also rejects non-empty `mcp_servers`,
`profiles`, or `plugins` in `/etc/codex/config.toml` and the install root's
`.codex/config.toml`. `project_root_markers=[]` explicitly makes that working
root the project boundary, including git-free deployments; unrelated ancestor
config and instructions are not inherited. the error names the source; move tool definitions into
the specialty or use an isolated deployment. ordinary project settings and
`AGENTS.md` are allowed. managed deployment policies remain authoritative; this
configuration check is not an operating-system security boundary.

## validation

unit fixtures cover provider selection, exact resume, legacy migration, provider
switch rejection, partial failures without replay, work id continuity, concurrent
keys, permissions, and specialty translation. the versioned JSONL contract fixture
is synthetic, derived from the official example; it is not a live model capture.

before deploying, run fresh and resumed no-tool smoke prompts in a disposable
root and persistent dedicated `CODEX_HOME`; verify the same native thread is
returned. then exercise the intended specialty mcp tools and native subagents in
an isolated environment. fake harness tests cannot establish authentication,
model availability, sandbox behavior, or live delegation parity.

references: [non-interactive codex](https://developers.openai.com/codex/noninteractive),
[codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference),
and the installed `codex exec --help` / `codex exec resume --help`.
