# subagent checkpoints

this is a shared prompt convention for worker, scout, verify, and triage, not a
runtime or another task system. tasks-axi remains the coordinator's authority.
each assignment owns one readable json checkpoint next to its task reports:
`data/<task-id>/agents/<assignment>.json` in the coordinator's abra root, outside
project worktrees. checkpoints survive worktree cleanup; they are not event logs.
status is last reported progress, never liveness, a heartbeat, or verified success.
prompt instructions do not enforce permissions or guarantee crash-proof delivery.

## dispatch and ownership

the coordinator chooses a unique task-local assignment id (for example `scout-01`,
`worker-01`, `verify-01`, or `triage-01`), independent of native run ids. use lowercase
slugs matching `[a-z0-9]+(-[a-z0-9]+)*`. reserve an unused absolute tracker path and
create its parent directory before launch. record assignment, tracker path, and
native run ids when available in the existing task notes; do not invent run ids or
require an agent to know its id before launch.

fill the role brief's tracking inputs, including `predecessor` (`null` for a new
assignment) and `run_ids` (`[]` if unknown). paste this entire specification into
`tracking_instructions`; a link alone is insufficient for agents in other repos.
apply this even to specialty template overrides, which may not omit or weaken the
shared contract. pass the original role boundaries, acceptance criteria, report
path, and working directory too. use json null for a read-only assignment with no
working directory; it grants no authority to run project commands elsewhere.

the assigned agent is the only tracker writer. the coordinator records a later
native run id in task notes and sends it to that agent to append to `run_ids`;
it does not concurrently edit the tracker. before resuming or replacing an agent,
reconcile ownership with native harness state and ensure the previous writer has
stopped. file isolation is not permission enforcement; do not rely on a timestamp
or an `active` checkpoint to establish that an agent is running or stopped.

## version 1 format

write utf-8 json, indented with two spaces and a trailing newline. all fields below
are required; no unknown fields or duplicate keys in version 1. null is allowed
only where specified; empty strings are not substitutes. use `[]` for empty lists.
future incompatible formats need another version, not guessed interpretation.
keep entries concise, coarse, and redacted: reference reports/logs rather than
copying their payloads. never copy secrets, credentials, or sensitive user data.

| field | type and meaning |
| --- | --- |
| `version` | integer `1`. |
| `assignment` | string, supplied task-local slug; matches the filename stem. |
| `role` | string: `worker`, `scout`, `verify`, or `triage`. |
| `predecessor` | assignment slug in this task, or `null` when there is none; never self. |
| `run_ids` | array of distinct non-empty strings, native ids in observed order; `[]` if unknown. |
| `status` | string: `active`, `paused`, `completed`, `blocked`, or `failed`. |
| `updated_at` | string, actual write time in utc `YYYY-MM-DDTHH:MM:SSZ`. |
| `job_summary` | non-empty string, at most 500 characters, bounded assignment goal. |
| `working_directory` | supplied absolute directory string, or `null` for read-only work without one. |
| `steps` | non-empty array of objects with exactly `id`, `title`, `status`; see below. |
| `checkpoint` | non-empty string, confirmed progress and evidence, not intended outcomes. |
| `next_action` | non-empty string, next intended action; `null` only when no action remains for this assignment. |
| `blocker` | non-empty string explaining an obstacle; `null` if none. required non-null when `blocked` or `failed`. |
| `artifacts` | array of objects with exactly `kind` and `reference`; `[]` when none yet. |

step `id` is a unique slug stable within this assignment, `title` is a non-empty
string, and `status` is `pending`, `active`, `completed`, `blocked`, `failed`, or
`skipped`. use a handful of coarse steps, not a second backlog. revise the plan as
understanding changes; retain ids for the same steps and mark abandoned steps
`skipped` rather than implying execution. artifact `kind` is `report`, `log`, or
`commit`; `reference` is a non-empty absolute path or url for a report/log, or a
full commit hash for a commit. include only confirmed existing artifacts, not
planned reports or commits. references do not authorize access to their contents.

`active` means work was last reported in progress; `paused` is an intentional
pause; `blocked` requires coordinator help/access; `failed` means the assignment
could not be carried out; `completed` means its bounded work/report is finished.
a completed worker is not independently approved, a completed verifier may report
a failed candidate, and completed triage may leave cause undetermined. keep the
actual verdict and check results in the report. none of these completes tasks-axi
or authorizes publication. terminal `completed`, `blocked`, or `failed` reflects
the outcome at return; use `paused` for an intentional interim pause.

example initial checkpoint (hypothetical paths, no native id known yet):

```json
{
  "version": 1,
  "assignment": "scout-01",
  "role": "scout",
  "predecessor": null,
  "run_ids": [],
  "status": "active",
  "updated_at": "2026-06-01T12:00:00Z",
  "job_summary": "identify the existing export entrypoints",
  "working_directory": null,
  "steps": [
    {"id": "trace", "title": "trace supplied sources", "status": "active"},
    {"id": "report", "title": "write findings", "status": "pending"}
  ],
  "checkpoint": "read the supplied brief; no source investigation yet",
  "next_action": "inspect the supplied export source paths",
  "blocker": null,
  "artifacts": []
}
```

## agent write and update procedure

1. before substantive work, read the brief and any existing tracker. if the path
   or shared instructions are missing, stop and request them from the coordinator;
   do not silently work untracked or choose a path. validate existing json against
   this format and the supplied assignment, role, predecessor, and directory.
   preserve malformed json, unsupported versions, foreign identity, symlinks, and
   unexpected file types unchanged; report the path and problem, not its contents.
   do not reset a checkpoint to get past a conflict.
2. initialize an absent tracker only when the brief authorizes a fresh assignment.
   for an existing owned tracker follow the recovery procedure below first. update
   after meaningful steps, before consequential actions (for example a commit or
   diagnostic probe), and before pausing or returning. record intention in
   `next_action`, then actual outcomes in `checkpoint` after execution. update the
   timestamp on each write; append native ids only when supplied or known.
3. write a complete replacement into an exclusively created temporary regular file
   in the same directory as the assigned tracker, with a unique name such as
   `<assignment>.json.tmp-<unique>`. parse/check the new json before replacing.
   close the file, recheck that the destination is still absent for initialization
   or unchanged from the owned checkpoint read, then atomically rename/replace it
   over the assigned tracker (for example `os.replace` on the same filesystem).
   never truncate the destination in place. if it changed unexpectedly, stop and
   preserve it instead of overwriting. this is not locking: single-writer ownership
   must already be reconciled. clean up only the temporary file you created.
4. the only tracking write exception outside the project worktree is the supplied
   tracker and its same-directory atomic replacement temporary file. it grants no
   authority to edit other trackers, reports beyond the supplied report path,
   backlog, registry, source checkout, or operator files. it does not broaden any
   role's product-code or diagnostic permissions.
5. on any write/replace failure, preserve the last checkpoint and report the exact
   failing operation/path and a redacted error to the coordinator. pause substantive
   work until resolved; if returning, report that the final state was not persisted.
   never claim the tracker was updated when it was not. after interruption before
   replacement the previous valid checkpoint remains; after replacement readers
   see the whole new file. leftover temporaries are not authoritative. atomic
   replacement alone does not promise power-loss durability or model compliance.

## recovery walkthroughs

these are static contract walkthroughs, not live harness trials. tests guard the
example, shared brief inputs, and documentation consistency; they do not prove
agents follow instructions, filesystem atomicity, or safe execution. live trials
need disposable projects and explicit action authority.

### interruption and same-assignment resume

`worker-01` last wrote `active` with a commit planned, then the harness stopped.
that is valid last-reported state, not a heartbeat or a known exit result. the
coordinator checks native state and worktree ownership before authorizing the
same logical assignment to resume, possibly with a new native run id. the agent
rereads the full brief and tracker, reconciles actual files, git history, and
report/log/commit artifacts, and checks whether the commit already happened.
record only confirmed progress, append the known run id, and set the next action
without blindly repeating the commit. preserve stable assignment and step ids.

### replacement assignment

if ownership cannot safely resume as the same assignment, stop/reconcile the old
writer before dispatch. allocate `worker-02.json` with assignment `worker-02` and
predecessor `worker-01`; pass the old checkpoint as read-only supporting context.
the replacement checks actual evidence rather than inheriting success or blindly
reexecuting actions. it writes only its new tracker; leave `worker-01.json` intact,
even if it still says `active`. never recycle an assignment id for unrelated work.

### malformed or foreign checkpoint

if `verify-01.json` is truncated, uses an unsupported version, names another
assignment, or is an unexpected symlink/file type, preserve it unchanged and
report the conflict. do not overwrite, repair, or infer progress from partial
fields. the coordinator reconciles ownership and artifacts; if replacement is
needed it assigns a new tracker referencing the predecessor. do not delete old
data or automatically promote a leftover temporary file.

### missing or stale checkpoint

an absent file at a newly reserved path is initialized before work. an absent
file on resume is not evidence that nothing ran: pause and ask the coordinator
to reconcile native state, commits, and reports before authorizing reconstruction
of confirmed state or a replacement assignment. an old `active`, `completed`, or
`blocked` checkpoint is not proof of liveness, approval, or current truth. compare
the brief/candidate with actual artifacts and task notes; do not invent success,
exit status, or a timeout based on `updated_at`. preserve the old checkpoint until
ownership and discrepancies are resolved, then the same owner may update it or a
replacement may reference it from a new tracker.
