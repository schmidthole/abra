# subagent checkpoints

checkpoints are agent-owned observations, never task lifecycle, liveness or approval.
use the complete [portable contract](checkpoint-contract-v1.md) for **new** briefs:
expand its entire marked block into `tracking_instructions`, not a link. supply
assignment/role/predecessor/run ids and absolute worktree/report/tracker/helper paths.
all seven role templates and specialty overrides retain this contract and their
role boundaries. saved old briefs remain unchanged and authoritative for their owners.

## dispatch and immutable reference

reserve a unique absolute `data/<task-id>/agents/<assignment>.json` outside project
worktrees; create the parent before launch. the agent alone initializes and writes
its tracker through the supplied absolute `bin/checkpoint.py` helper. the coordinator
records native ids in task notes and sends later-known ids to that owner.

save the exact [checkpoint detail snapshot v1](reference/checkpoint-v1.md) with the
filled brief (or use an accessible immutable committed copy), supply its absolute
path as `tracking_reference` and sha256 as `tracking_reference_sha256`:
`4c295c5589a807c7b5afd821b39eba2ecd9e07c81da94c3df18be53d6d0002a3`.
the compact block is versioned as compact-checkpoint-v1. do not change either
version's bytes in place; issue a new version and retain old references. verify
reference bytes before nonroutine recovery/schema use; inaccessible or mismatched
references block, never silently substitute the current manual. initialization
needs only the embedded operational block, including its complete json example.

## deterministic helper and recovery walkthroughs

`init`, `read`, full-proposal `update` and typed `progress` use the same strict v1
schema and persistence path. [schema, help and recovery walkthroughs](reference/checkpoint-v1.md)
cover interruption, same-assignment resume, replacement, malformed/foreign,
missing-on-resume and stale records. these are static walkthroughs, not live trials.
read full relevant task/brief/manifest/checkpoint evidence and reconcile native owners
and actual artifacts before action. global or ambiguous recovery broadens startup
reads; the compact view is never recovery authorization.

## field ownership

| record | authoritative content | update trigger |
| --- | --- | --- |
| tasks-axi | lifecycle, concise discoverable request/authority/steering, resource/dependency/promise links, material blocker and handoff/delivery outcome | material steering or ownership/next-safe-action/lifecycle change |
| coordinator manifest | selections, attempts, action intents/outcomes, evidence-backed stage decisions and coordinator next action/blocker | before coordinator actions, after confirmed outcomes |
| agent checkpoint | immutable assignment/run ids, coarse steps, confirmed progress, agent next action/blocker/artifacts | compact contract update triggers |
| saved briefs/reports | full request/authority/assignment and exact check evidence | new immutable revision/report |

routine agent steps and manifest transitions need not be mirrored in task notes.
link the records and keep scope/conflicts discoverable; a link-only handoff is not
enough. unresolved intents need a concise task warning. disagreements are reconciled,
not timestamp-merged. full-body-before-update and ownership recovery remain mandatory.

## typed progress convenience

`init`, `read` and complete `update` remain supported with unchanged v1 fields.
`progress` reduces repeated identity/timestamp json for ordinary updates:

```sh
python3 /absolute/abra/bin/checkpoint.py progress /absolute/data/example/agents/scout-01.json \
  --assignment scout-01 --role scout --working-directory null \
  --revision "$last_read_revision" --request -
```

stdin (or an already authorized absolute regular file) must contain exactly:

```json
{
  "status": "active",
  "steps": [{"id":"trace","title":"trace supplied sources","status":"completed"},{"id":"report","title":"write findings","status":"active"}],
  "checkpoint": "source trace confirmed; report not yet delivered",
  "next_action": "write the authorized findings report",
  "blocker": null,
  "artifacts": [],
  "run_ids": ["observed-native-id"]
}
```

supply the full coherent steps/progress/blocker/artifacts, not an arbitrary patch.
`run_ids` means observed ids to append in order, retaining previous ids and ignoring
already-recorded observations; duplicate ids within the request reject. identity,
predecessor, job summary and step ids/titles are retained; mark abandoned steps
skipped, do not remove/rename them. progress refuses completed/failed assignments;
unusual reconciled edits require the full update path, not automatic resumption.

bounded strict duplicate-free json, full validation, supplied immutable identity,
last-read revision and the existing timestamp/atomic write path all still apply.
request success asserts agent progress only, never stage approval or liveness.
sole-writer ownership, allowed write boundaries and stop-on-helper-failure rules
are unchanged. uncertain publication/output failure requires read and reconciliation,
not a blind retry with a new token. this command neither dispatches nor updates a
workflow/task, and does not migrate the checkpoint format.
