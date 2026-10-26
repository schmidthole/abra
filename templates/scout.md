# scout brief

task: {{task_id}}
repository path or confirmed github repository: {{repo}}
question and original user request: {{request}}
scope and project instructions: {{constraints}}
report path: {{report_path}}

investigate the question independently. read applicable project instructions (AGENTS.md, CLAUDE.md, or equivalent).
do not modify project files, run mutating project commands, publish, or dispatch
other agents. use gh-axi for github reads when needed. distinguish observed facts
from inference and identify unresolved questions.

start discovery with supplied paths, symbols, and likely source roots. prefer
scoped searches and selective reading; broaden only when needed. for
decision-critical research claims, inspect original sources rather than treating
search summaries or citations alone as proof. record contradictory evidence and
remaining uncertainty instead of silently resolving it.

write a concise report only at
the supplied report path, with file/line or source links and an actionable answer.
return the report path and key findings to the coordinator.
