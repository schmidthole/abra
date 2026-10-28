# triage contract walkthroughs

triage is an optional specialized investigation role, not a new runtime. use
[the brief](../templates/triage.md) when a behavior report needs identification or
reproduction before a bounded worker task is clear. use a worker directly for a
clear implementation request and a scout for general research. the coordinator
records the task and reviews the report before deciding the next action.

these are static contract walkthroughs using hypothetical evidence, not executed
probes or live agent acceptance results. `tests/test_triage.py` guards the portable
inputs and report interface; it cannot establish investigation quality, safe tool
use, or reliable live reproduction. those require authorized disposable-project
harness trials. no scenario below authorizes commands or shared-system changes.

## known bug

input: "the export worker drops the final row; probably the queue." supply the
export and queue repositories, a version, sample input/output, and an isolated
worktree with explicit authority to run only the local export regression test on
disposable data. stop at a bounded handoff; do not fix the bug.

contract walkthrough:

- normalize expected row count vs reported output, version and occurrence time;
  distinguish reporter attribution to the queue from verified evidence.
- trace enqueue, dequeue, and serialization boundaries. rank a serializer boundary
  error against queue truncation; compare the queue payload with the exported
  output as the cheapest discriminating check. an intact payload weakens queue
  truncation; a truncated payload redirects investigation upstream.
- propose the minimal input and exact local test invocation with prerequisites,
  expected vs actual output, and cleanup. keep it planned until executed. preserve
  the resulting test output and any temporary instrumentation separately.
- if an authorized test actually drops a row, report reproduction as reproduced;
  if it does not, report not reproduced with the tested environment, not "no bug."
  even a reproduced symptom leaves cause suspected until discriminating evidence
  establishes the causal boundary; reading suspicious code alone is not execution.
- hand off the evidence, relevant serializer/queue paths, minimal reproduction,
  and a no-dropped-rows acceptance check when sufficiently established. the
  coordinator decides worker scope; a worker fix still needs independent review.

review result: the workflow permits a bounded worker handoff without accepting
reported cause, conflating reproduction with causal proof, or implementing a fix.

## environment/configuration issue

input: "sign-in fails in staging after deployment; auth service must be broken."
provide redacted gateway and auth logs, release versions, expected issuer config,
and repository paths. default authority is read-only; staging access is absent.

contract walkthrough:

- normalize the failed operation, deployment time, environments, and log provenance.
  trace client → gateway → auth, keeping ownership cross-system until localized.
- rank issuer/config mismatch vs auth regression. a gateway rejection before an
  auth request supports the former; a matching effective issuer or downstream
  failure contradicts it. propose comparing effective issuer/version with a known
  good environment as the cheapest check, explaining both possible outcomes.
- distinguish reading supplied logs/config from executing a sign-in. configuration
  files alone may not prove effective deployment state. leave unavailable checks
  planned; request the minimum redacted effective config and matching request logs.
- report reproduction blocked by missing staging access (or not attempted if no
  probe was needed), and cause suspected or undetermined according to evidence.
  do not edit staging config or claim a sign-in was reproduced from log inspection.
- recommend information/access or a report-only configuration finding if evidence
  already suffices. a product-code handoff is premature without a bounded defect.

review result: the contract supports non-code and cross-system causes, negative
and contradictory evidence, and a useful access request without unsafe mutations.

## underspecified report

input: "it sometimes doesn't work; fix it." no repository, operation, environment,
version, timestamp, or evidence is known; no probes are authorized. stop when
material missing information prevents useful checks.

contract walkthrough:

- state observed behavior as a vague reporter claim and expected behavior unknown;
  do not invent a system, owner, root cause, or reproduction command.
- ask for the failing operation, expected/actual outcome, affected project or url,
  version/environment, approximate occurrence time, and a redacted error/example.
  prioritize information that would distinguish systems and guide the next check.
- mark affected system unknown, reproduction not attempted, and cause undetermined.
  if a concrete check is identified but cannot run, use blocked with its reason.
  record hypotheses as unrankable until evidence arrives, with no executed checks
  or diagnostic artifacts. proposed reproduction prerequisites remain unfulfilled.
- recommend an information request; explain why worker handoff is premature.
  return the report rather than guessing or exploring unrelated repositories.

review result: the completion boundary permits a useful incomplete investigation
without fabricating certainty, execution, or a code-delivery outcome.
