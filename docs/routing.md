# routing and relevant startup

these are active boundaries for new work, not a fifth workflow recipe. existing
saved full workflows/briefs keep their contracts; do not remove a manifest to save
ceremony. opt in explicitly in the saved request/authority record for newly covered
lightweight work. explicit full recipe or stricter specialty wins. ambiguity asks
for a decision or uses the full path, never assumes reduced safeguards.

## routing decision order

1. unknown scope/authority/ownership blocks dispatch pending clarification/reconciliation.
2. explicit full recipe or specialty requirement uses the specified full recipe.
3. substantive code, config, dependencies, interfaces, operating policy, security,
   sensitive data, diagnostic execution, publication/merge/production or multiple
   agents/stages with unclear scope are excluded from lightweight handling.
4. certified reviewed spec/slice packages use plan v1 (refine/ground/validate/deliver).
5. small questions may be answered directly. opt-in brainstorming/critique answers
   are ideas with assumptions/limits, never grounded readiness or independent validation.
6. opt-in bounded one-scout read-only research may use the lightweight scout brief
   variant below. no diagnostic probes, source edits or publication.
7. opt-in mechanical/unambiguous non-policy docs may be done locally in an isolated
   worktree with saved request, authority, diff/check evidence and exact local commit/
   outcome. canonical final project gates remain required. a tiny policy/security
   edit is substantive, not trivial. uncertain eligibility uses full implement.
8. otherwise select the smallest suitable full recipe with recorded rationale;
   clear initial selection needs no workflow-choice question, but grants no action authority.

normative decision cases (fixtures review actual decisions, not keyword occurrence):

| case | supplied facts | route | required outcome |
| --- | --- | --- | --- |
| small-answer | bounded question; no action or unresolved ownership | direct | answer with limits |
| brainstorm | opt-in ideas only; no certified package | lightweight-direct | saved request/authority/outcome; no readiness claim |
| certified-package | reviewed product spec and slices requested | plan | exact package with independent validation |
| one-scout | opt-in single bounded read-only question; known owner | lightweight-scout | task reservation/intent/outcome/checkpoint/report/lifecycle |
| typo | opt-in unambiguous non-policy prose only; local commit | lightweight-docs | isolated diff/checks/exact commit/outcome |
| policy-line | one sentence changes verification authority | implement | fresh independent exact-candidate review |
| security-doc | security guidance even without executable code | full-or-ask | substantive safety review; no lightweight exemption |
| code | substantive code/config/dependency/interface change | implement | worker and independent verify |
| probe | diagnostic execution requested | investigate | explicit probe authority and isolated worktree |
| external | push/pr/merge/production action requested | full-or-ask | explicit action authority and publication gates |
| explicit-full | otherwise lightweight research but operator selects research v1 | research | full manifest and stages |
| specialty-full | otherwise trivial docs but pack requires full review | implement | stricter specialty and full review |
| no-opt-in | bounded delegated research without lightweight opt-in | research | full manifest and stages |
| unknown-owner | missing old native id; checkpoint absent on resume | blocked | reconcile all potential writers before dispatch |
| uncertain-scope | unclear policy/security impact or multiple uncertain repos | ask | clarify before reduced routing |

## lightweight saved record and portable brief variant

- [lightweight-record] use tasks-axi lifecycle and existing task-local saved request/report files, not a
new database, schema or helper. for brainstorming/docs save concise original request,
acceptance, authority, lightweight opt-in, scope/resources/dependencies/promises,
limits and actual outcome; link it in the task's discoverable handoff. for delegated
research additionally save **before launch** assignment/predecessor, unique absolute
tracker/helper/report/worktree (or null) paths, full filled brief, dispatch intent
and recovery lookup. after launch record observed outcome/native ids (not inferred
from missing tracker) and send later ids to the checkpoint owner. the scout owns
its checkpoint and report. coordinator reads the actual report, records explicit
review/delivery outcome and lifecycle; completed scout status alone does not finish
the task. an unresolved launch intent remains a warning in task notes.

for an eligible scout, use `templates/scout.md` with exactly this documented variant:
replace the entire `## coordinator workflow context` section (through the next
heading) with this block. do not fill workflow/stage/attempt fields with fabricated
ids or add nullable fields to strict manifests. keep every other section including
the full portable contract, capability evidence and read-only role boundary.

```text
## lightweight task context

mode: opt-in lightweight-scout; no workflow manifest or stage/attempt ids
saved request/acceptance/authority/opt-in reference: <absolute saved request path>
coordinator task handoff with assignment reservation and dispatch intent: <task id and saved reference>
recovery lookup: <native ownership and actual report/checkpoint lookup>
coordinator alone records dispatch outcome, report review/delivery and task lifecycle.
do not launch agents or update tasks-axi, registry or manifests. report only the
bounded question; substantive implementation or new access requires escalation.
```

### interruption and escalation walkthroughs

- [interrupted-intent] intent saved, launch response lost: missing checkpoint/native id does not prove
  nothing ran. block, inspect native state and real artifacts, reconcile all owners,
  then confirm the actual launch or authorize a stopped-owner replacement. never
  duplicate-dispatch merely because there is no manifest.

- [report-before-outcome] report written, coordinator outcome not saved: read the actual report and checkpoint,
  compare the saved request/authority, record explicit review/delivery outcome and
  update lifecycle. do not rerun the scout or infer success from completed status.

- [escalation] scout discovers a code/policy/probe need: stop at report boundary, preserve prior
  records and reconcile stopped ownership. save separately authorized full work and
  link earlier evidence; initialize a normal workflow without retroactive stage
  passes. no new access, authority or budget reset follows from escalation.

## scoped startup

read dashboard and worktree registry/inventory, resolve current project aliases,
and inspect project instructions before routing. then read full target/resumed
body, likely duplicates, dependencies and tasks sharing repository/worktree/branch/
assignment resources or material promises. include relevant held tasks. repository
name inequality alone cannot establish irrelevance: follow shared libraries/services,
multi-repo work, common publication targets, shared tooling/operator inputs and aliases.

| case | discovery facts | inspection |
| --- | --- | --- |
| unrelated-held | clear indexed scope; no dependencies/resources/promises overlap | summary-sufficient |
| same-repo-duplicate | overlapping request or shared branch/worktree | full-relevant |
| cross-repo-dependency | target depends on another repo/service/library task | full-relevant |
| shared-resource | shared tooling/operator input/publication target/assignment | full-relevant |
| promise | material follow-up can affect request even across repos | full-relevant |
| alias-ambiguity | alias or repo identity not resolved | broaden-and-resolve |
| missing-summary | missing links/poor index cannot exclude overlap | broaden-full |
| global-recovery | genuine global/session recovery | full-unfinished |
| unknown-old-writer | missing native identity or uncertain writer even across repos | full-and-block |

- [startup-broadening] broaden whenever summaries are ambiguous, links are missing, index information is
insufficient, ownership is uncertain or global recovery requires it. use actual
cli help before filters; no new tasks query api is assumed. existing poor summaries
require broader reads until a normal material handoff improves them; no bulk rewrite.
read the **full body before every update**, regardless of startup scope. fully
reconcile each reused assignment/worktree from task, manifest, saved briefs,
checkpoints, native state and actual artifacts, regardless of status. `worktree.py
list` is registered inventory, not agent liveness. if a conflict emerges mid-work,
pause affected actions and read/reconcile/record it before continuing.

cross-repo recovery example: a service task says held while its shared-library
worker checkpoint says active and native id is unknown. read both full bodies,
briefs/manifests/checkpoints and inspect actual owners/artifacts. new dispatch stays
blocked until stopped ownership is established; a dashboard status cannot resolve it.

these tables and walkthroughs are static contracts, not live routing compliance
or native recovery trials. independent review must assess omitted/ambiguous cases;
unit tests do not enforce agent behavior.
