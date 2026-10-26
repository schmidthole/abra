# pi tasks widget

minimal, read-only tasks-axi view above pi's editor. source lives here, not in the
auto-loaded `.pi/extensions` directory. nothing is installed or enabled globally.
requires node 22.19+ and pi with `ctx.mode`, component-factory `setWidget`, and
`agent_settled` support; validated with `@earendil-works/pi-coding-agent` 1.4.0.

## try it

from the abra checkout, install only this extension's dependencies (do not install
copies of pi's host-provided peer packages):

```sh
npm --prefix extensions/tasks ci --ignore-scripts --legacy-peer-deps
pi --extension ./extensions/tasks/index.ts
```

by default, the source checkout containing this extension supplies `bin/tasks` and
`data/backlog.md`, regardless of pi's working directory. there is no ancestor search
or automatic discovery of another backlog. to view a different abra checkout,
set an absolute root before starting pi. in particular, the implementation worker
checkout has no live backlog; use the actual coordinator root:

```sh
ABRA_TASKS_ROOT=/Users/taylor/Documents/abra \
  pi --extension /Users/taylor/Documents/abra/.worktrees/abra/pi-tasks-view/extensions/tasks/index.ts
```

use your own absolute paths elsewhere. `ABRA_TASKS_ROOT` must point to a trusted
abra checkout: the extension executes that checkout's `bin/tasks`. it requires an
executable wrapper and a readable regular `data/backlog.md`. it does not create a
missing backlog. the fixed markdown backend and absolute backlog path are passed
explicitly, so tasks-axi environment or user config cannot redirect the read.

for optional persistent loading after review, add the absolute `index.ts` path to
`extensions` in pi's user settings, or `../extensions/tasks/index.ts` in the
checkout's `.pi/settings.json` (project resource paths are relative to `.pi`).
run `/reload` after a settings edit. no settings changes are required to try it.

## behavior

- one counts line, at most three task rows, and a remaining-count line if needed.
- unfinished tasks only; in-flight rows first, otherwise cli order is preserved.
- in-flight and queued counts partition unfinished work. held and blocked counts
  are overlapping subsets, not additional states. each row retains its base state
  and both active flags. holds, expiry dates and dependency resolution are derived
  by tasks-axi, not inferred from prose.
- refresh on `session_start` and `agent_settled` (after automatic agent work has
  stopped), or `/tasks` / `/tasks refresh`. no timers or polling. external edits
  appear at the next refresh, not immediately.
- `/tasks hide` removes the widget and cancels its current read; automatic and
  manual refreshes do nothing while hidden. `/tasks show` enables it and refreshes.
  hiding lasts for the loaded extension runtime, not across restarts/reloads.
- rpc, json and print modes are silent no-ops: no widget, cli read or notification.
- missing files, cli failures and invalid data replace stale rows with a compact
  error. fix the cause and run `/tasks refresh` (or `/tasks show` if hidden).
- each read has a 10-second timeout and 2-mib output limit. newer refreshes, hide
  and session shutdown cancel old reads and discard late results.
- terminal control sequences, control/format characters (including bidi controls)
  and line breaks are removed or flattened before pi's `truncateToWidth` handles
  display columns. narrow terminals truncate without wrapping, including counts.

this extension only invokes `bin/tasks list --fields held,blocked --backend
markdown --file <absolute-backlog>`. abra's wrapper pins tasks-axi 0.2.5 and may
use npx to download it on first use; the view adds no mutation, watcher or daemon.
large backlogs exceeding the output limit show an error rather than partial counts.
tasks-axi truncates list titles to 80 characters (with its own hint); this view does
not fetch full task bodies, expose navigation, or add model context/tools.

## data contract and development

`list --json` is unsupported in tasks-axi 0.2.5. its supported list output is toon:
`count`, a `tasks` table with default `id,state,kind,repo,title` columns plus
`held,blocked` as `yes`/`no`, and optional help. an empty unfiltered list uses
`tasks: 0 tasks in this backlog`. count, row types, states, flags and duplicate ids
are validated; malformed output is not presented as an empty backlog.

`@toon-format/toon` 2.3.1 is the only runtime dependency, pinned with a lockfile.
it is the zero-transitive-dependency decoder for the format the cli actually emits,
including quoted commas, escaped quotes/backslashes and multiline values. no cli
internals, handwritten csv parser, or markdown backend implementation are copied.
pi supplies the tui module and extension types. prettier is development-only.

```sh
npm --prefix extensions/tasks test
npm --prefix extensions/tasks run format
npm --prefix extensions/tasks run format:check
make format
make test
```

the extension tests use the installed pi package's actual loader, widget factory,
theme and width helper, with a small ui sink; they do not require an api key or
model request. by default the host is found at `$(npm root -g)/@earendil-works/pi-coding-agent`;
set `PI_PACKAGE_DIR` to that package's absolute directory for another installation.
tests also exercise the pinned wrapper against a disposable markdown fixture,
never the live backlog. temporary fixtures stay under this checkout's `.cache`
and are removed after the suite. the tests cover supported toon parsing, failure
and timeout handling, controls/unicode/narrow widths/resize, read-only flags,
refresh/hide/show, cancellation, recovery and non-tui modes. actual terminal
placement/focus in regular and fullscreen modes still warrants an interactive
smoke check; no custom screen or input handler is installed.
