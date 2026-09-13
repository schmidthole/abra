```text
         _
   __ _ | |__   _ __   __ _
  / _` || '_ \ | '__| / _` |
 | (_| || |_) || |   | (_| |
  \__,_||_.__/ |_|    \__,_|

       one voice. many hands.
```

a coordinator workflow using codex native subagents, tasks-axi, gh-axi, and git.
the coordinator follows `AGENTS.md`; there is no separate runtime.

## setup

requires codex with native subagents, git, python 3.9+, node 20+, and authenticated
`gh`. the cli wrappers use pinned npm packages through npx; first use downloads
them. authentication and sandbox permissions remain owned by codex and gh.

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
description. local state and worktrees are gitignored. only one coordinator writes
the registry and backlog. no file needs to be copied into managed projects.

launch codex here and refer to registered projects by name or alias. `AGENTS.md`
instructs the coordinator to use native subagents and fill the role templates.
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

## pipeline

worker → independent review/tests/docs/lint → fixes and fresh verification if needed
→ authorized pr → ci → delivery. for a local-only request, stop at the verified
commit. scouts return reports without entering the code delivery pipeline.

this adopts no-mistakes' review/test/docs/lint/pr/ci goal using native subagents.
it does not install its git proxy or enforce a server-side publishing gate:
the coordinator follows the documented checks. independence means a fresh agent
and separate checkout, not a guarantee that two instances of a model cannot share
the same blind spot. a closed codex session is not an always-on service.

## first live checks

1. register a disposable repo and record two tasks through `bin/tasks`.
2. dispatch a scout and worker using the templates; collect both native results.
3. verify the worker commit in a detached worktree. plant a known defect in a
   disposable candidate and require a failing verdict before testing its repair.
4. confirm a changed candidate requires fresh verification; inspect a failed ci run
   before trying pr delivery in a disposable github repo.
5. reopen codex and reconcile unfinished tasks from the backlog and worktrees.

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

references: [tasks-axi](https://github.com/kunchenguid/tasks-axi),
[gh-axi](https://github.com/kunchenguid/gh-axi),
[no-mistakes](https://github.com/kunchenguid/no-mistakes).
