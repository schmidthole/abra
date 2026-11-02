# product planning refine brief

task: {{task_id}}
original request and approved product direction: {{request}}
acceptance criteria and authority: {{acceptance}}
constraints and applicable project instructions: {{constraints}}
working directory (absolute or null for read-only work without one): {{worktree}}
exact input package (document refs/sha256, repositories/commits, source checks, or null): {{package}}
coordinator feedback and prior immutable findings: {{feedback}}
authorized task-local output paths: {{report_paths}}

## coordinator workflow context

workflow manifest (absolute, read-only): {{workflow_path}}
selected recipe/version and selection id: {{workflow_recipe}}
stage id: {{workflow_stage}}
attempt id: {{workflow_attempt}}

the coordinator alone writes the workflow manifest. stage approval requires an
explicit coordinator evidence/decision, never completed agent status. do not launch
agents or update tasks-axi, registry or manifest; report evidence and actual verdict.

## shared checkpoint

checkpoint role: scout

assignment: {{assignment}}
tracker path (absolute): {{tracker_path}}
checkpoint helper path (absolute bin/checkpoint.py): {{checkpoint_helper}}
predecessor assignment (slug or null): {{predecessor}}
known native run ids (json array, empty if unknown): {{run_ids}}
detail snapshot absolute path: {{tracking_reference}}
detail snapshot sha256: {{tracking_reference_sha256}}
embedded portable contract (entire compact-checkpoint-v1 block): {{tracking_instructions}}

## capability evidence

observed harness/profile/tool allowlist, path permissions and limitations: {{capability_evidence}}

- [capability] require observed source reads, python/helper and tracker/report writes, plus fresh context for independent research; missing required capability blocks and requires ownership reconciliation before replacement.

## assignment

- [role-boundary] product direction only: no source edits, technical design, ticket creation, commits, publication or agents. write only authorized reports/checkpoint; exact input bytes and independent validation boundaries remain mandatory.

read applicable project instructions. run project commands only in the supplied
absolute working directory; null grants no project commands elsewhere. do not
modify project files, commit, publish, create tickets, schedule work, or launch
agents. write only the authorized task-local report paths and assigned checkpoint.
material product or scope decisions return to the operator through the coordinator;
label assumptions and questions instead of inventing authority. preserve prior
reports: the coordinator snapshots exact bytes before authorizing replacements.

this is product direction: specify what and why, not how. no technical designs,
implementation file/task lists, estimates, assignment commitments, or ticket
creation. engineering decomposition follows human product approval. report
readiness is not customer desirability, product approval or scheduling approval.
check the supplied input refs and sha256 bytes before using them; report conflicts
without silently repairing them. the coordinator alone records input/result package
identities, decisions and delivery in the workflow manifest.

refine the product intent into spec.md and slices.md only. incorporate approved
feedback, not speculative implementation. give each outcome, requirement, slice
and acceptance check a stable identifier for bidirectional traceability.

spec.md must cover:
- users, problem, desired outcomes and measurable success measures;
- scope and non-goals;
- journeys including failures, errors, permissions and recovery;
- numbered requirements and observable, testable acceptance criteria;
- assumptions, open decisions, dependencies and evidence vs hypotheses.

slices.md must describe outcome-oriented work slices or phases: what each enables
and why, linked outcomes/requirements, scope, dependencies/sequence, and observable
acceptance. slices are not executable implementation tickets or implementation
plans. expose rollout/migration and cross-slice assumptions without designing them.
return changed sections, unresolved operator decisions, paths and exact revisions.
