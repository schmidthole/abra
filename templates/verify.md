# independent verification brief

task: {{task_id}}
detached working directory: {{worktree}}
base commit: {{base_commit}}
candidate commit: {{candidate_commit}}
original user request: {{request}}
acceptance criteria: {{acceptance}}
constraints and project instructions: {{constraints}}
worker summary, untrusted supporting context: {{worker_summary}}
report path: {{report_path}}

independently verify the candidate. read project instructions and confirm head
equals the candidate before running checks. inspect the diff from base to candidate
and the surrounding implementation. do not rely on the worker's claimed results.
run every project command in the detached working directory. never edit the worker
checkout, fix product code, publish, commit, or dispatch other agents.

check the following in order:

1. intent and review: each acceptance criterion is satisfied; inspect correctness,
   edge cases, regressions, security relevant to the change, and unnecessary scope.
2. tests: independently run relevant tests and add temporary behavioral probes in
   this detached worktree if existing coverage cannot substantiate the change.
   missing required dependencies or unexecutable checks are blocked, not passed.
3. docs: changed behavior and public interfaces have accurate usage documentation
   where needed; justify not applicable when no documentation change is needed.
4. format and lint: use the project's canonical check commands. if the formatter
   only supports rewriting, run it here and inspect the resulting diff; required
   formatting changes fail verification. distinguish your own probes/build output
   from candidate changes and do not silently repair the candidate.

write the report at the supplied path. include candidate and base hashes, overall
pass/fail/blocked verdict, per-criterion evidence, each check's command and exit
status, and actionable findings with file/line references. justify skipped checks.
pass only when all required gates pass and there are no unresolved findings.
confirm head is unchanged. return the verdict, candidate hash, and report path.
