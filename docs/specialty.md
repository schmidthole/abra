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
  jobs/               optional: prompts for scheduled jobs
    nightly.md
  mcp.json            optional: mcp config referenced by mcp_config
```

## specialty.json

unknown keys are rejected at every level, and duplicate json keys are refused.

| field | required | meaning |
| --- | --- | --- |
| `name` | yes | lowercase slug. |
| `description` | yes | string. |
| `repos` | yes | non-empty map of repo name to entry, same shape as `data/repos.json` entries. |
| `secrets` | no | list of required environment variable names (never values). |
| `egress` | no | list of lowercase hostnames the deployment should allow. informational only. |
| `mcp_config` | no | relative path inside the pack to an mcp config json object. |
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
`jobs.<name>.schedule` is informational for whatever runner schedules jobs; abra does
not run a scheduler. merging is never granted by a specialty.

all relative paths (`mcp_config`, job prompts, every entry in the `templates/` tree)
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
  the coordinator must supply the full [shared checkpoint contract](agent-tracking.md)
  and its inputs, including the absolute `bin/checkpoint.py` helper path, to all
  four roles even when an override omits them; overrides cannot weaken the tracking or original role boundaries.
- overrides must also receive the [workflow context](workflows.md): absolute
  read-only workflow path, selected recipe/version and selection id, stage and
  attempt ids. overrides cannot weaken operator selection, coordinator-only
  manifest ownership, intent-before-action, ownership reconciliation or exact
  candidate/acceptance verification. missing override fields are supplied by the
  coordinator, never silently omitted. no tracker ownership changes.
- delivery stops at the `delivery` ceiling.

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
  "mcp_config": "mcp.json",
  "jobs": {
    "weekly-review": {"prompt": "jobs/weekly-review.md", "schedule": "0 9 * * 1"}
  },
  "delivery": "draft-pr"
}
```

`SPECIALTY.md` for the same pack might say: "you maintain the example documentation
site. only change files under `docs/`. open draft prs for review."
