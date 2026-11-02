@AGENTS.md

## claude code notes

- spawn scout and verify agents with a non-fork type such as `general-purpose`;
  `fork` inherits coordinator context and breaks independence.
- never use the agent tool's `isolation: "worktree"` option; `bin/worktree.py`
  owns all worktrees.
- agents run in the background; wait for completion notifications and use
  `SendMessage` with the recorded agent id to steer or continue them.

- inspect the selected agent profile's configured tool allowlist, not its name alone.
  worker and verify need bash/git/python/helper/tests plus assigned report/tracker
  writes; read-only product verification does not mean tool-less. record observed
  configuration in capability evidence. restricted profiles block; reconcile any
  launched owner's native state before replacement. no introspection api is assumed.
