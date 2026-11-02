# specialty packs

a specialty is an optional pack that specializes abra for one purpose. it layers on
top of the base `AGENTS.md`: a model-read `SPECIALTY.md` describes the purpose and
workflow, and a machine-read `specialty.json` is enforced by code. without a pack,
abra behaves exactly as before.

## location

- default: `<abra root>/specialty/` (gitignored; mounted or copied in by the deployer).
- override: env `ABRA_SPECIALTY_DIR` (absolute path). both `bin/worktree.py` and
  `bin/specialty.py` honor it. an empty value is treated as unset; a relative or
  missing path is an error.
- no directory = base abra, behavior unchanged.

## layout

```text
specialty/
  SPECIALTY.md        required: purpose, scope, workflow guidance, delivery notes
  specialty.json      required: machine-read manifest
  templates/          optional: briefs looked up before base templates/
    worker.md
  jobs/               optional: prompt files referenced by job metadata
    nightly.md
```

## specialty.json

unknown keys are rejected at every level, and duplicate json keys are refused.
the former `mcp_config` key is no longer supported; remove it from existing packs.

| field | required | meaning |
| --- | --- | --- |
| `name` | yes | lowercase slug. |
| `description` | yes | string. |
| `repos` | yes | non-empty map of repo name to entry, same shape as `data/repos.json` entries. |
| `secrets` | no | list of required environment variable names (never values). |
| `egress` | no | list of lowercase hostnames the deployment should allow. informational only. |
| `jobs` | no | map of job name (slug) to `{"prompt": "<relative path>", "schedule": "<cron>"}`. |
| `delivery` | no | delivery ceiling: `report`, `local-commit`, `draft-pr`, or `pr`. default `draft-pr`. |

repo entries:

| field | required | meaning |
| --- | --- | --- |
| `path` | yes | absolute path to the git checkout root. |
| `base` | yes | base ref for new worktrees; must not start with `-`. |
| `origin` | no | remote url; default empty. |
| `aliases` | no | list of slugs; default empty. |
| `description` | no | string; default empty. |

repo names and aliases are slugs and must be unambiguous across the whole map.
`jobs` remains validated metadata only: prompt files must exist and schedules must
be non-empty strings, but abra provides no scheduler or job executor. merging is
never granted by a specialty.

all relative paths (job prompts, every entry in the `templates/` tree)
must resolve inside the pack: absolute paths, `..`, symlinks that escape, and broken
or looping symlinks are refused. `specialty.json` is limited to 64 KiB, every other
checked file to 256 KiB, and `templates/` to 1000 entries. json that is invalid or
nested too deeply to parse is refused.

## precedence

a specialty may narrow or add to base `AGENTS.md` rules, never loosen them. on
conflict the base rule wins and abra flags the conflict to the operator.

when a pack is present:

- the registry is fixed to `specialty.json` repos. `worktree.py list`, `resolve`,
  `create`, and `cleanup` use them and ignore `data/repos.json`; `register` is refused.
- briefs are looked up in the pack `templates/` first, then base `templates/`.
  supply the entire embedded compact-checkpoint-v1 [shared checkpoint contract](agent-tracking.md),
  all identity/path inputs and immutable detail snapshot path/digest even when an
  override omits them; never weaken sole-writer/revision/stop/recovery or role boundaries.
- full work overrides receive absolute read-only workflow path, recipe/selection,
  stage/attempt context. eligible opted-in lightweight scout variants instead carry
  saved task/request/authority/reservation/intent links from [routing](routing.md),
  never fabricated manifest ids. a stricter specialty may require full work.
- overrides retain coordinator-only manifest ownership, intent-before-action,
  stopped ownership reconciliation and exact candidate/acceptance verification.
  initial selection records smallest suitable rationale, honors explicit operator
  choices and asks for material intent/scope/acceptance/authority ambiguity. later
  recipe changes require operator approval in v1; only new opted-in v2 report tasks
  permit one initially preauthorized same-contract read-only method switch, never
  budget/blocked-intent escape. missing fields are supplied, not silently omitted.
- capability evidence must inspect actual profile/tool configuration and required
  helper/report writes plus role execution/independence; failure blocks and reconciles
  before replacement. portable contracts cannot invent an introspection api.
- plan briefs (`plan-refine.md`, `plan-ground.md`, `plan-validate.md`) follow the same
  override lookup and shared scout checkpoint/workflow contracts. preserve the
  [planning](planning.md) boundaries, package byte checks, fresh independent validation
  and report-only delivery even when a specialty permits code delivery.
- recipe selection grants no publication, merge, production or other external-action
  authority; separate action authority still applies and delivery stops at the
  `delivery` ceiling.

## startup check

```sh
python3 bin/specialty.py check
```

validates the manifest (required keys, types, slugs, unknown keys, alias ambiguity,
path containment, referenced files, size bounds), confirms each declared secret env
var is set without printing its value, and confirms each repo path is a git checkout
root whose base resolves to a commit. it exits 0 when the pack is valid or absent
and nonzero with lowercase `error:` lines otherwise.

## security

prompts are not a security boundary. `SPECIALTY.md`, templates, and `AGENTS.md` guide
the model; they cannot stop it. real limits come from what the deployment grants:
scoped credentials, network egress policy, and container or filesystem isolation.
`egress` and `secrets` only declare what the deployer should provide; abra does not
enforce network policy. keep secret values in the environment, never in the pack.

## example

a generic pack for illustration only; do not commit real packs to this repo.

```json
{
  "name": "example-docs",
  "description": "keeps example project documentation current",
  "repos": {
    "example-site": {
      "path": "/srv/repos/example-site",
      "origin": "https://example.com/org/example-site.git",
      "base": "origin/main",
      "aliases": ["site"],
      "description": "example documentation site"
    }
  },
  "secrets": ["EXAMPLE_API_TOKEN"],
  "egress": ["example.com", "api.example.com"],
  "jobs": {
    "weekly-review": {"prompt": "jobs/weekly-review.md", "schedule": "0 9 * * 1"}
  },
  "delivery": "draft-pr"
}
```

`SPECIALTY.md` for the same pack might say: "you maintain the example documentation
site. only change files under `docs/`. open draft prs for review."
