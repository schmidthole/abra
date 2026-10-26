# pi tasks widget

minimal, read-only tasks-axi view above pi's editor. the tracked
`.pi/settings.json` loads `../extensions/tasks/index.ts` automatically when pi
starts in this abra checkout after project trust is granted. no skill invocation,
model instruction, `--extension` flag or environment variable is needed for normal
use. nothing is installed or enabled globally.

this is pi-specific presentation, not pi-specific task ownership: `bin/tasks`,
tasks-axi's backlog and the agent-neutral prompts/skills remain unchanged. other
agents can use the same cli and data without this widget or any ansi output added
to the cli.

requires node 22.19+ and pi with `ctx.mode`, component-factory `setWidget`,
`turn_end` and `agent_settled` support; validated with
`@earendil-works/pi-coding-agent` 1.4.0.

## setup and automatic loading

once per checkout, install only this extension's dependencies (do not install
copies of pi's host-provided peer packages):

```sh
npm --prefix extensions/tasks ci --ignore-scripts --legacy-peer-deps
pi
```

pi does not install or modify local extension/package dependencies automatically.
this explicit setup is required before loading; the extension factory never runs
an installer or hides a network install. rerun `npm ci` if the lockfile changes or
`node_modules` is removed. a missing dependency produces a pi extension-load error,
not a widget: install dependencies and run `/reload`.

grant project trust only after reviewing this checkout's code and configuration.
pi's usual trust prompt/saved decision applies; declining trust skips the widget.
`pi --no-extensions` also disables it. if pi is already running when this
configuration arrives, run `/reload` once (and grant project trust if requested).
future trusted starts from the checkout root load it automatically. this describes
the checked-out configuration, not an installation into a different checkout or a
running coordinator session.

by default, the source checkout containing this extension supplies `bin/tasks` and
`data/backlog.md`. start pi from that checkout root so its project settings are
discovered. there is no ancestor search or automatic discovery of another backlog.
the extension requires an executable wrapper and a readable regular backlog; it
does not create a missing backlog. implementation/verification worktrees normally
have no live backlog and will show a compact error rather than silently reading
another checkout.

for an optional one-off view from elsewhere, explicitly load the extension with
`pi --extension /absolute/abra/extensions/tasks/index.ts`. to read a different abra
checkout, optionally set `ABRA_TASKS_ROOT=/absolute/other-abra` before starting pi.
the override must be an absolute path to a trusted checkout: the extension executes
that checkout's `bin/tasks`. neither option is needed for normal use within abra.
the fixed markdown backend and absolute backlog path are passed explicitly, so
tasks-axi environment or user config cannot redirect the read.

## behavior

- one counts line, at most three task rows, and a remaining-count line if needed.
- unfinished tasks only; in-flight rows first, otherwise cli order is preserved.
- in-flight and queued counts partition unfinished work. held and blocked counts
  are overlapping subsets, not additional states. each row retains its base state
  and both active flags. holds, expiry dates and dependency resolution are derived
  by tasks-axi, not inferred from prose.
- refresh on `session_start`, every `turn_end` (after the model response and its
  tool calls, including task listings/mutations), and `agent_settled` (after
  automatic agent work has stopped), or `/tasks` / `/tasks refresh`. no shell
  command-string parsing, timers or polling. settlement reuses a turn read that
  finished within the last 250 ms to avoid an immediate duplicate; later turns
  and manual refreshes always read again. external edits, including `!` shell
  commands, appear at the next refresh, not immediately.
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

the extension tests use the installed pi package's actual resource loader with
project trust and normal cwd discovery (no explicit extension path), plus its
extension loader, widget factory, theme and width helper with a small ui sink.
a disposable checkout fixture proves automatic startup reads the default root
without `ABRA_TASKS_ROOT`; denying trust or disabling extensions prevents loading.
no api key or model request is required. by default the host is found at `$(npm root -g)/@earendil-works/pi-coding-agent`;
set `PI_PACKAGE_DIR` to that package's absolute directory for another installation.
tests also exercise the pinned wrapper against a disposable markdown fixture,
never the live backlog. temporary fixtures stay under this checkout's `.cache`
and are removed after the suite. the tests cover supported toon parsing, failure
and timeout handling, controls/unicode/narrow widths/resize, read-only flags,
turn/settled/manual refresh and bounded coalescing, hide/show, cancellation,
recovery and non-tui modes. actual terminal
placement/focus in regular and fullscreen modes still warrants an interactive
smoke check; no custom screen or input handler is installed.
