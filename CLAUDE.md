@AGENTS.md

## claude code notes

- spawn scout and verify agents with a non-fork type such as `general-purpose`;
  `fork` inherits coordinator context and breaks independence.
- never use the agent tool's `isolation: "worktree"` option; `bin/worktree.py`
  owns all worktrees.
- agents run in the background; wait for completion notifications and use
  `SendMessage` with the recorded agent id to steer or continue them.
