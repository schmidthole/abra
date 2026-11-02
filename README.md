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

## operating guide

[AGENTS.md](AGENTS.md) is the coordinator routing/safety index. [routing and startup](docs/routing.md)
cover small answers, opt-in brainstorming, one-scout research and mechanical non-policy
docs; substantive code/policy/security/probes/publication/uncertainty take full work
or clarification. explicit operator recipes and stricter specialties win. relevant
full task reads include cross-repo dependencies/resources/aliases/promises; ambiguous
indexes/global recovery broaden inspection. always inspect full bodies before update.

full initial work selects the smallest suitable fixed [recipe](docs/workflows.md)
with rationale: implement, investigate, research or [plan](docs/planning.md). ask
only for material intent/scope/acceptance/authority ambiguity, not workflow choice.
later recipe changes require operator approval in v1; new opted-in v2 report tasks
alone permit one initially preauthorized same-contract read-only method switch.
selection grants no publication, merge, production or other external-action authority.

- [worker](templates/worker.md): bounded implementation in an isolated worktree.
- [scout](templates/scout.md): read-only research, not code delivery.
- [triage](templates/triage.md): behavior investigation ([walkthroughs](docs/triage.md)).
- [verify](templates/verify.md): fresh independent exact-candidate review; no repairs.

all seven briefs (including plan's three scout roles) embed the complete versioned
[portable checkpoint contract](docs/checkpoint-contract-v1.md), with supplied absolute
helper/tracker/report/worktree paths and immutable detail reference/digest. specialty
overrides keep the same boundaries. old saved briefs remain authoritative. inspect
actual [profile capabilities](docs/capabilities.md) before dispatch; read-only verification
still needs shell/git/tests/helper and tracker/report writes. unknown capability
blocks; no portable introspection api or automatic replacement is assumed.

## state ownership and recovery

| record | authoritative content | update trigger |
| --- | --- | --- |
| tasks-axi | lifecycle and concise discoverable request/authority/steering, resource/dependency/promise links, material blocker, handoff/delivery outcome | material changes, not every agent step |
| coordinator manifest | recipe/attempts/intents/outcomes/evidence-backed stage decisions/next action | before actions and after confirmed outcomes |
| agent checkpoint | assignment/native ids/steps/progress/blocker/artifacts | portable contract triggers |
| saved briefs/reports | full immutable request/authority and check evidence | new revision/report |

`workflow.py show --compact` combines separate observations/decisions read-only; it
never queries tasks-axi/native/git/pr/ci or authorizes recovery. [typed operations](docs/workflows.md)
reserve/confirm/decide/deliver through existing validators, not a runner. full init/
read/update remain. [checkpoint progress](docs/agent-tracking.md) retains agent ownership.
unknown ownership blocks even with missing tracker/id. reconcile full relevant task,
manifest, saved briefs/checkpoints and actual artifacts/native owners before repeating
uncertain actions. statuses are not liveness, verified success or lifecycle completion.

substantive implementation requires fresh independent review/tests/docs/format at
exact candidate; v1 acceptance/delivery changes require fresh review. opt-in v2 may
reuse unchanged substantive identity/base/check assumptions and exact candidate only
with explicit comparison evidence. delivery is always current: clean/head/authority/
target/duplicate-pr/remote-head/required-ci gates remain. required unavailable checks
block; no checks is not ci passed. initial verification plus at most two repair
rounds; fresh verification after fixes, no budget reset through a method switch.
worker summaries are not independent approval; reports do not complete code requests.

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

`make format` uses black and every dependency hash-pinned in `requirements-dev.txt`
(python 3.11+); abra and normal `make test` remain python 3.9 compatible. **inspect
existing formatter environments before installation**. reuse a trusted, complete
separate formatter venv without activating it as a project environment. pass its
absolute bin path and validation evidence in worker/verifier briefs.

first establish provenance: who prepared it, hash-checked installation, trusted
owner/permissions for environment, interpreter and their parent paths (including
symlink targets), no credentials/project hooks or untrusted concurrent mutator.
the read-only stdlib checker rejects unsafe environment permissions, missing tools,
wrong shebang/interpreter/prefix, changed candidate digest and any missing/wrong pin;
it is not an installer, environment manager or proof of package bytes/provenance.
inspect external interpreter parents too; platform package-manager group-write
permissions require an explicitly trusted admin group, not blind acceptance.

```sh
formatter_bin=/absolute/trusted/formatter/bin
requirements_sha256='exact-digest-from-trusted-environment-preparation-or-prior-evidence'
# compare candidate bytes to that saved digest; never refresh it to bypass a mismatch
PYTHONDONTWRITEBYTECODE=1 python3 bin/check_formatter.py --bin "$formatter_bin" \
  --requirements "$PWD/requirements-dev.txt" --requirements-sha256 "$requirements_sha256"
PATH="$formatter_bin:$PATH" PYTHONDONTWRITEBYTECODE=1 BLACK_CACHE_DIR="$PWD/.cache/black" make format
PYTHONDONTWRITEBYTECODE=1 make test
```

save the reported exact requirements hash, resolved interpreter implementation/
version/platform/architecture/prefix and all pins with the assignment evidence;
compare them in each candidate checkout. candidate requirement changes, stale/
partial/wrong-pin envs or unsupported interpreter block required format, not a pass.
no test interpreter PATH change: `make test` uses normal python3. all bytecode,
formatter/test/probe outputs and mutable project environments stay in the supplied
worktree; reusable tooling is read-only during use. never run project installs in it.

only if no compatible trusted environment exists and setup is separately authorized:

```sh
python3.12 -m venv /absolute/new-exclusive/abra-black
/absolute/new-exclusive/abra-black/bin/pip install --require-hashes -r requirements-dev.txt
```

validate completely before handing off; never mutate a shared ready or partial
installation, or let two preparers write one directory. different requirements/
interpreter/platform require a separate authorized environment, not overwriting one
in use. keep reusable tools outside worktree cleanup or retain their owning tree
while readers exist. no automatic cache service or redundant verifier installation.

iteration may use focused tests and formatting changed python. every candidate
commit still requires canonical `make format`, `make test` and task checks; fresh
independent verification reruns them at exact head. formatter changes fail review,
not silent repair. documentation-only work needs no artificial test but retains
required final gates. unavailable required checks block.

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
