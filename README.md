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
bin/abra job daily-digest
```

`run` wraps the text in a delimited untrusted-data block naming the requester and
key, invokes `claude -p --output-format json` in this directory, prints the result
text to stdout, and logs progress to stderr. session ids are stored per key in
`data/sessions.json`. keys match `[A-Za-z0-9][A-Za-z0-9:._-]{0,127}` (uppercase is
allowed for chat ids); requesters also allow `@` and spaces; event text is limited
to 32 kib of utf-8. `job <name>` reads `jobs.<name>.prompt` from the specialty's
`specialty.json` and uses the key `job:<name>:<utc yyyy-mm-dd>`.

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
usage errors exit 2 and other failures exit 1. the prompt and `SPECIALTY.md` are
passed as process arguments, visible in the host process list, so run on a
single-tenant host or container. there are no service, systemd, or cron files: scheduling,
retries, and process supervision belong to the deployer.

## pipeline

worker → independent review/tests/docs/lint → fixes and fresh verification if needed
→ authorized pr → ci → delivery. for a local-only request, stop at the verified
commit. scouts return reports without entering the code delivery pipeline.

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

## development

install `black` for formatting, then run:

```sh
make format
make test
```

tests use temporary git repositories to check alias resolution, collisions,
dirty-checkout preservation, worker isolation, and exact-commit verification.
runner tests use a stub harness through `ABRA_CLAUDE_BIN`.

references: [tasks-axi](https://github.com/kunchenguid/tasks-axi),
[gh-axi](https://github.com/kunchenguid/gh-axi),
[no-mistakes](https://github.com/kunchenguid/no-mistakes).
