```text
         _
   __ _ | |__   _ __   __ _
  / _` || '_ \ | '__| / _` |
 | (_| || |_) || |   | (_| |
  \__,_||_.__/ |_|    \__,_|

       one voice. many hands.
```

a coordinator workflow using codex or claude code native subagents, tasks-axi, gh-axi, and git.
the coordinator follows `AGENTS.md`; there is no separate runtime.

## setup

requires codex or claude code with native subagents, git, python 3.9+, node 20+, and authenticated
`gh`. the cli wrappers use pinned npm packages through npx; first use downloads
them. authentication and sandbox permissions remain owned by the harness and gh.

```sh
./bin/tasks --help
./bin/github --help
python3 bin/worktree.py register example /absolute/path/to/repo \
  --base origin/main --alias short-name --description "what this project does"
python3 bin/worktree.py list
```

the registry starts empty; register actual checkouts with their actual base refs.
names and aliases must be unambiguous lowercase slugs. `data/repos.json` is a
human-editable map containing each repo's path, origin, base, aliases, and
description. `operator/` holds your own drafts and notes to hand off to the
coordinator, which reads but does not edit them. local state, `operator/`, and
worktrees are gitignored. only one coordinator writes the registry and backlog.
no file needs to be copied into managed projects.

launch codex or claude code here and refer to registered projects by name or alias. `AGENTS.md`
instructs the coordinator to use native subagents and fill the role templates;
claude code loads it through `CLAUDE.md`, which adds claude-specific notes.
templates are portable prompts, not a new spawning api or custom agent runtime.

## roles

- [worker](templates/worker.md): implements a clear, bounded change in an isolated
  worktree.
- [scout](templates/scout.md): researches a bounded question without changing
  project files.
- [triage](templates/triage.md): investigates unclear reported behavior and
  reproduction ([contract walkthroughs](docs/triage.md)).
- [verify](templates/verify.md): independently reviews and tests an exact worker
  commit in a detached worktree; it does not repair product code.

all four roles own a per-assignment json [checkpoint](docs/agent-tracking.md) at
`data/<task-id>/agents/<assignment>.json`, outside project worktree cleanup. the
coordinator supplies its absolute path, absolute `bin/checkpoint.py` helper path,
and full shared instructions at dispatch, including specialty overrides. stable
assignment ids survive native run restarts;
replacement agents get new trackers referencing their predecessors. these are
last-reported progress for recovery and later dashboards, not liveness, verified
success, or a second task system. tasks-axi remains coordinator-owned.

## durable workflows

the operator selects a fixed [workflow recipe](docs/workflows.md): implement
(worker -> verify -> deliver), investigate (triage -> coordinator review -> report),
or research (scout -> report). one coordinator-owned
`data/<task-id>/workflow.json` links stable stage attempts to existing assignment
checkpoints and saved full briefs. `bin/workflow.py` provides strict init/read,
revision-checked complete update and read-only show, not a runner or task system.
tasks-axi owns lifecycle; the coordinator links the manifest in task notes and
records operator steering, intent before dispatch/delivery and confirmed outcomes
afterwards. unknown ownership blocks recovery; statuses never establish liveness
or approval. stage success requires coordinator evidence and requested delivery.
see the [recovery protocol and limitations](docs/workflows.md#interruption-recovery).

## worktrees

```sh
python3 bin/worktree.py resolve short-name
python3 bin/worktree.py create example fix-login
python3 bin/worktree.py create example fix-login --verify <full-commit-hash>
```

worker paths are `.worktrees/<repo>/<task>` on `abra/<task>` branches. verification
paths include the full candidate hash and use detached head. output records the
resolved commit. existing paths or branches are refused without modification.
the source checkout can have uncommitted changes; these are never copied or reset.
fetch the intended remote before creation when a fresh remote base is required.
worktrees are file isolation, not a security boundary.

after delivery, confirm the worker/verifier has stopped using its directory, then
preview and execute cleanup:

```sh
python3 bin/worktree.py cleanup example fix-login --idle
python3 bin/worktree.py cleanup example fix-login --idle --yes
python3 bin/worktree.py cleanup example fix-login --verify <full-commit-hash> --idle --yes
```

`--idle` asserts that no agent or process still uses the worktree; the command does
not scan processes. cleanup refuses dirty/untracked work, locked worktrees, unsafe
paths, and commits not preserved by a branch or tag. `--yes` removes the worktree
including ignored files such as dependencies, caches, and local configuration.
branches, reports, and the source checkout remain. save any needed ignored files
first. clean up obsolete verification attempts too; if a directory contains probes
or changes, inspect them and remove only known disposable files before retrying.
there is no force option, background cleanup, or automatic deletion on context reset.

## specialty

an optional pack in `specialty/` (or `$ABRA_SPECIALTY_DIR`) specializes abra for one
purpose: `SPECIALTY.md` guides the model, `specialty.json` fixes the repo registry,
declared secrets, and delivery ceiling. lint it with `python3 bin/specialty.py check`.
see [docs/specialty.md](docs/specialty.md).

## headless runner

`bin/abra` runs one event through claude code without an interactive session.
each conversation key (a chat thread, ticket, or job run) resumes its own session.

```sh
bin/abra run --key thread-123 --from U0123 --text "fix the login bug in example"
bin/abra run --key ticket-42 --from alice --text-file /path/to/event.txt
bin/abra run --key slack:C01:1700.1 --messages-file /path/to/batch.json \
  --work-id abra-x7k2 --session-id 0f8fad5b-d9cb-469f-a165-70867728950e
bin/abra job daily-digest
bin/abra sessions prune --older-than 90
```

`run` wraps the text in a delimited untrusted-data block naming the requester and
key, pipes it on stdin to `claude -p --output-format json` in this directory, prints the result
text to stdout, and logs progress to stderr. session ids are stored per key in
`data/sessions.json`. keys match `[A-Za-z0-9][A-Za-z0-9:._-]{0,127}` (uppercase is
allowed for chat ids); requesters also allow `@` and spaces; event text is limited
to 32 kib of utf-8. `job <name>` reads `jobs.<name>.prompt` from the specialty's
`specialty.json` and uses the key `job:<name>:<utc yyyy-mm-dd>`. when a resident
trigger runtime is running on this root (`data/triggers/bridge.json`), the job is
handed to its session as a runtime event instead of running one-shot.

`run` options for callers that batch a conversation's queued messages (the
trigger runtime no longer uses them; it hosts a resident session):

- `--messages-file M` replaces `--text`/`--text-file`: a json array of 1 to 50
  objects with exactly `from` (requester pattern) and non-empty `text`, at most
  32 kib. each message gets its own delimited untrusted block naming its sender,
  in order. `--from` is a usage error with it.
- `--work-id W` (`[a-z0-9]+(-[a-z0-9]+)*`, at most 64 chars) tells abra the
  conversation is work item `W`: it uses `W` as the tasks-axi task id and
  `data/W/` for reports, creating the task if missing and reusing it otherwise.
- `--session-id U` (canonical lowercase uuid) pre-assigns the claude session id so
  the caller can announce it before the run. it is only for a fresh key: a key
  with a stored session exits 1. the resume retry below never reuses it.
- `--context-file C` (utf-8, non-empty, at most 256 kib) is prior conversation
  history for resurrecting an archived conversation. it is wrapped in its own
  untrusted block before the new messages, and used only when the key has no
  stored session (fresh start or the resume retry); otherwise it is ignored with a
  log line.

`sessions prune --older-than DAYS` (integer 1 to 3650) removes stored sessions
whose `updated` time (last successful use) is older than `DAYS`, or missing or
unparsable, and prints each removed key on its own line. the caller picks the age,
for example 90 days.

when `specialty/` (or `ABRA_SPECIALTY_DIR`, which must be an absolute path to a
directory; empty means unset) exists, `SPECIALTY.md` is appended to
the system prompt and `mcp_config` is passed with `--strict-mcp-config`; paths must
stay inside the specialty directory. if `bin/specialty.py` exists, its `check` must
pass before the harness runs.

| variable | effect |
| --- | --- |
| `ABRA_CLAUDE_BIN` | harness binary, default `claude` |
| `ABRA_SPECIALTY_DIR` | specialty directory, default `specialty/` |
| `ABRA_MAX_CONCURRENCY` | concurrent runs across keys, default 2 |
| `ABRA_AGENT_MODE` | `1` passes `--dangerously-skip-permissions` |

agent mode is off by default. enable it only inside an isolated container whose
credentials and network egress are already scoped; it removes every permission
prompt and check.

if a stored session cannot be resumed, the runner clears it and retries once in a
fresh session with a note to rebuild context from the task body and backlog; if
that also fails, the key's session stays cleared.

one key never runs twice at once. a busy key or full concurrency cap fails fast
with exit code 75 instead of queueing, so the caller decides whether to retry.
usage errors exit 2 and other failures exit 1. the prompt, including any batched
messages and context file, is sent to the harness on stdin, not in its arguments;
`SPECIALTY.md` is still passed as an argument. there are no service, systemd, or
cron files: scheduling,
retries, and process supervision belong to the deployer.

## triggers

`triggers/` holds a shared runtime that feeds chat or ticket conversations into
one resident agent session over acp (claude via `claude-agent-acp`, codex via
`codex-acp`, or any acp agent in `ABRA_AGENT_CMD`): tag the bot to start a work
item, reply in the thread to add to it, and abra answers each thread with its
`reply` tool. adapters are thin; `triggers/cli.py` is the json-lines reference adapter and
`triggers/slack.py` serves slack threads ([docs/slack.md](docs/slack.md)), and
`triggers/linear.py` polls linear for issues assigned to the bot
([docs/linear.md](docs/linear.md)). see [docs/triggers.md](docs/triggers.md).

## container

the `Dockerfile` builds a debian image for headless and trigger deployments:
key-only sshd for operators, an optional trigger listener, and a persistent
home volume holding the instance root. see [docs/container.md](docs/container.md).

## pipeline

clear implementation request → worker → independent review/tests/docs/lint →
fixes and fresh verification if needed → authorized pr → ci → delivery. for a
local-only request, stop at the verified commit.

general research → scout report; unclear behavior → optional triage report.
the coordinator reviews findings and decides on a bounded worker task, an
information/access request, or a report-only conclusion. reports do not replace
independent worker verification or complete a request for code delivery.

this adopts no-mistakes' review/test/docs/lint/pr/ci goal using native subagents.
it does not install its git proxy or enforce a server-side publishing gate:
the coordinator follows the documented checks. independence means a fresh agent
and separate checkout, not a guarantee that two instances of a model cannot share
the same blind spot. a closed harness session is not an always-on service.

## first live checks

1. register a disposable repo and record two tasks through `bin/tasks`.
2. dispatch a scout and worker using the templates; collect both native results.
3. verify the worker commit in a detached worktree. plant a known defect in a
   disposable candidate and require a failing verdict before testing its repair.
4. confirm a changed candidate requires fresh verification; inspect a failed ci run
   before trying pr delivery in a disposable github repo.
5. reopen the harness and reconcile unfinished tasks from the backlog and worktrees.

these are live harness acceptance checks, not claims already established by the
script tests. use disposable projects and explicitly authorized github delivery.
for checkpoint recovery, exercise interruption, same-assignment resume, replacement,
and malformed/missing/stale cases from the [walkthroughs](docs/agent-tracking.md#recovery-walkthroughs)
before relying on live agent compliance.

## development

`make format` uses the black version hash-pinned with its dependencies in
`requirements-dev.txt`. those pins need python 3.11+ to install and run; abra
itself and `make test` stay python 3.9 compatible. install it into a separate venv:

```sh
python3.12 -m venv ~/.venvs/abra-black   # any python 3.11+
~/.venvs/abra-black/bin/pip install --require-hashes -r requirements-dev.txt
```

with that venv's `bin` on `PATH`, run:

```sh
make format
make test
```

tests use temporary git repositories to check alias resolution, collisions,
dirty-checkout preservation, worker isolation, and exact-commit verification.
runner tests use a stub harness through `ABRA_CLAUDE_BIN`. triage template tests
check the portable input/report interface only; the scenario walkthroughs are
static contract reviews, not evidence of live agent behavior. checkpoint tests
guard the json example, shared inputs, and write/recovery instructions, plus
exercise the standard-library [helper](docs/agent-tracking.md#deterministic-helper)
against disposable files and cli inputs; they do not establish live model compliance.

workflow tests run disposable local simulated interruption trials under the
worktree's `.cache/workflow-trials/`: actual git commit-before-outcome recovery,
local pr receipts, dispatch ambiguity and ownership reconciliation, repairs and
approval invalidation. they are not actual native harness or live github trials;
see [trial limits](docs/workflows.md#automated-interruption-trials).

references: [tasks-axi](https://github.com/kunchenguid/tasks-axi),
[gh-axi](https://github.com/kunchenguid/gh-axi),
[no-mistakes](https://github.com/kunchenguid/no-mistakes).
