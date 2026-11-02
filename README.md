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
research (scout -> report), or [plan](docs/planning.md)
(refine -> ground -> validate -> deliver; report-only product direction).
one coordinator-owned `data/<task-id>/workflow.json` links stable stage attempts
to existing assignment
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

## pipeline

clear implementation request → worker → independent review/tests/docs/lint →
fixes and fresh verification if needed → authorized pr → ci → delivery. for a
local-only request, stop at the verified commit.

general research → scout report; unclear behavior → optional triage report.
product direction → operator-selected [plan](docs/planning.md): spec, outcome-oriented
work slices and independent readiness review; not tickets or implementation design.
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
triage template tests check the portable input/report interface only; the scenario
walkthroughs are static contract reviews, not evidence of live agent behavior.
checkpoint tests guard the json example, shared inputs, and write/recovery
instructions, plus
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
