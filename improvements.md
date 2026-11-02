# instruction improvements

## autonomous workflow selection

recommend updating `AGENTS.md`, `docs/workflows.md`, and related recipe-selection
instructions so the coordinator autonomously selects the smallest suitable fixed,
versioned recipe for a clear request, records the choice and rationale, and proceeds
without asking the operator to choose a workflow. retain explicit operator choices
and ask only when intent, scope, acceptance, or authority is materially ambiguous.

recipe selection must not itself grant publication, merge, production, or other
external-action authority. keep independent verification, delivery ceilings,
coordinator-owned manifests, and ownership/recovery safeguards unchanged. this is
a recommendation for a focused instruction update, not a rewrite of authorization
policy as part of the runtime cleanup.
