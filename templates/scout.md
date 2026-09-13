# scout brief

task: {{task_id}}
repository path or confirmed github repository: {{repo}}
question and original user request: {{request}}
scope and project instructions: {{constraints}}
report path: {{report_path}}

investigate the question independently. read applicable project instructions.
do not modify project files, run mutating project commands, publish, or dispatch
other agents. use gh-axi for github reads when needed. distinguish observed facts
from inference and identify unresolved questions. write a concise report only at
the supplied report path, with file/line or source links and an actionable answer.
return the report path and key findings to the coordinator.
