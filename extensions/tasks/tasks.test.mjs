import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { after, test } from "node:test";
import { encode } from "@toon-format/toon";

const directory = dirname(fileURLToPath(import.meta.url));
const root = resolve(directory, "../..");
const host =
  process.env.PI_PACKAGE_DIR ??
  join(
    execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim(),
    "@earendil-works/pi-coding-agent",
  );
const hostRequire = createRequire(join(host, "package.json"));
const { createJiti } = hostRequire("jiti");
const tuiPath = hostRequire.resolve("@earendil-works/pi-tui");
const jiti = createJiti(import.meta.url, {
  alias: { "@earendil-works/pi-tui": tuiPath },
});
const { parseTasks, readTasks, tasksRoot, taskLines, safeText } =
  await jiti.import(join(directory, "index.ts"));
const { visibleWidth } = await import(pathToFileURL(tuiPath));
const { loadExtensions } = await import(
  pathToFileURL(join(host, "dist/core/extensions/loader.js"))
);
const { getThemeByName } = await import(
  pathToFileURL(join(host, "dist/modes/interactive/theme/theme.js"))
);
const theme = getThemeByName("dark");
assert.ok(theme);
await mkdir(join(root, ".cache"), { recursive: true });
const temporary = await mkdtemp(join(root, ".cache/tasks-test-"));
after(async () => {
  await rm(temporary, { recursive: true, force: true });
});

function task(id = "task-a", overrides = {}) {
  return {
    id,
    state: "queued",
    kind: "task",
    repo: "-",
    title: "a task",
    held: "no",
    blocked: "no",
    ...overrides,
  };
}
function output(tasks) {
  return encode({
    count: tasks.length,
    tasks: tasks.length ? tasks : "0 tasks in this backlog",
    help: ["a hint"],
  });
}
async function fixture(name, text = output([task()]), source) {
  const path = join(temporary, name);
  await mkdir(join(path, "bin"), { recursive: true });
  await mkdir(join(path, "data"));
  await writeFile(join(path, "data/backlog.md"), "fixture backlog\n");
  await writeFile(join(path, "output"), text);
  await writeFile(
    join(path, "bin/tasks"),
    source ??
      `#!/usr/bin/env node
import fs from 'node:fs';
fs.appendFileSync('calls', JSON.stringify(process.argv.slice(2)) + '\\n');
process.stdout.write(fs.readFileSync('output'));
`,
    { mode: 0o755 },
  );
  return path;
}
async function harness(path, callback, mode = "tui") {
  const previous = process.env.ABRA_TASKS_ROOT;
  process.env.ABRA_TASKS_ROOT = path;
  try {
    const loaded = await loadExtensions([join(directory, "index.ts")], root);
    assert.deepEqual(loaded.errors, []);
    assert.equal(loaded.extensions.length, 1);
    const extension = loaded.extensions[0];
    const widgets = [];
    const notifications = [];
    const ctx = {
      mode,
      hasUI: mode === "tui" || mode === "rpc",
      ui: {
        setWidget: (key, content, options) =>
          widgets.push({ key, content, options }),
        notify: (...args) => notifications.push(args),
      },
    };
    const emit = async (event) => {
      for (const handler of extension.handlers.get(event) ?? [])
        await handler({ type: event }, ctx);
    };
    const command = (args = "") =>
      extension.commands.get("tasks").handler(args, ctx);
    const render = (width = 120) =>
      widgets.at(-1).content({}, theme).render(width);
    await callback({ ctx, widgets, notifications, emit, command, render });
    await emit("session_shutdown");
  } finally {
    if (previous === undefined) delete process.env.ABRA_TASKS_ROOT;
    else process.env.ABRA_TASKS_ROOT = previous;
  }
}

test("root defaults to extension checkout, not session cwd; override must be absolute", () => {
  assert.equal(tasksRoot(undefined), process.env.ABRA_TASKS_ROOT ?? root);
  assert.equal(tasksRoot(temporary), temporary);
  for (const invalid of ["", "relative", "~/abra", "/tmp/\nabra"]) {
    assert.throws(() => tasksRoot(invalid), /absolute path/);
  }
});

test("toon decoding preserves quoted commas, escapes, multiline values and unicode", () => {
  const rows = [
    task("quoted", { title: 'commas, "quotes", \\slashes\nnext\t界🪄' }),
  ];
  assert.deepEqual(parseTasks(output(rows)), rows);
});

test("empty cli scalar and done filtering", () => {
  assert.deepEqual(parseTasks(output([])), []);
  assert.deepEqual(parseTasks(output([task("done", { state: "done" })])), []);
});

test("malformed, truncated, duplicate and wrong-schema output fail closed", () => {
  for (const text of [
    "",
    "npm failed",
    "count: 0",
    "count: 0\ntasks: surprise",
    output([task()]).replace("count: 1", "count: 2"),
    output([task()]).replace("tasks[1]", "tasks[2]"),
    output([task(), task()]),
    output([task("bad", { held: true })]),
    output([task("bad", { blocked: "maybe" })]),
    output([task("bad", { state: "held" })]),
    output([task("bad", { title: 42 })]),
    output([task("", {})]),
  ])
    assert.throws(() => parseTasks(text), /invalid cli data/, text);
});

test("compact bounded lines count overlapping hold/block flags and prioritize in-flight", () => {
  const tasks = [
    task(),
    task("held", { held: "yes", blocked: "yes" }),
    task("active", { state: "in_flight" }),
    task("extra"),
  ];
  const lines = taskLines({ tasks }, 200);
  assert.equal(lines.length, 5);
  assert.equal(lines[0], "tasks: 1 in-flight · 3 queued · 1 held · 1 blocked");
  assert.match(lines[1], /^in-flight active:/);
  assert.match(lines[3], /^queued\/held\/blocked held:/);
  assert.equal(lines[4], "+1 more · /tasks refresh");
  assert.deepEqual(taskLines({ tasks: [] }, 100), [
    "tasks: no unfinished tasks",
  ]);
});

test("rendering strips terminal controls, bidi and newlines at every width and resize", () => {
  const title =
    "\x1b[31mred\x1b[0m\x1b]52;c;payload\x07\r\n\t\x00\x9b2J\u202e界👩‍💻é";
  const snapshot = { tasks: [task("unsafe\x1b[2J", { title })] };
  assert.doesNotMatch(safeText(title), /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u);
  for (const width of [0, 1, 2, 3, 8, 20, 80, 200, 1, 80]) {
    for (const line of taskLines(snapshot, width)) {
      assert.ok(visibleWidth(line) <= width, `${width}: ${line}`);
      assert.doesNotMatch(
        line.replace(/\x1b\[0m/g, ""),
        /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u,
      );
    }
  }
  assert.deepEqual(taskLines({ error: title }, 0), []);
});

test("read command uses only supported flags and fixed backlog; never mutates", async () => {
  const path = await fixture("read");
  const before = await readFile(join(path, "data/backlog.md"), "utf8");
  assert.deepEqual(await readTasks(path), [task()]);
  assert.deepEqual(
    JSON.parse((await readFile(join(path, "calls"), "utf8")).trim()),
    [
      "list",
      "--fields",
      "held,blocked",
      "--backend",
      "markdown",
      "--file",
      join(path, "data/backlog.md"),
    ],
  );
  assert.equal(await readFile(join(path, "data/backlog.md"), "utf8"), before);
});

test("missing cli/backlog, subprocess error, oversized output and aborted reads", async () => {
  await assert.rejects(readTasks(temporary), /bin\/tasks missing/);
  const path = await fixture("missing");
  await rm(join(path, "data/backlog.md"));
  await assert.rejects(readTasks(path), /backlog missing/);
  const failure = await fixture(
    "failed",
    "",
    '#!/usr/bin/env node\nprocess.stderr.write("secret\\x1b[2J"); process.exit(1);',
  );
  await assert.rejects(readTasks(failure), /cli unavailable or failed/);
  const large = await fixture(
    "large",
    "",
    '#!/usr/bin/env node\nprocess.stdout.write("a".repeat(3 * 1024 * 1024));',
  );
  await assert.rejects(readTasks(large), /cli unavailable or failed/);
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    readTasks(failure, controller.signal),
    /cli unavailable or failed/,
  );
});

test(
  "stalled cli is bounded by the read timeout",
  { timeout: 13000 },
  async () => {
    const path = await fixture(
      "timeout",
      "",
      "#!/usr/bin/env node\nsetTimeout(() => {}, 20000);",
    );
    await assert.rejects(readTasks(path), /cli unavailable or failed/);
  },
);

test("real pi loader, component factory, events, manual refresh and hide/show", async () => {
  const path = await fixture("events");
  await harness(
    path,
    async ({ widgets, notifications, emit, command, render }) => {
      assert.equal(widgets.length, 0);
      await emit("session_start");
      assert.equal(widgets.at(-1).options.placement, "aboveEditor");
      assert.match(render().map(safeText).join("\n"), /queued task-a/);
      for (const width of [1, 10, 80]) {
        for (const line of render(width))
          assert.ok(visibleWidth(line) <= width);
      }
      await writeFile(
        join(path, "output"),
        output([task("after-work", { state: "in_flight" })]),
      );
      await emit("agent_settled");
      assert.match(render().map(safeText).join("\n"), /after-work/);
      await command();
      await command("refresh");
      assert.equal(widgets.length, 4);
      await command("hide");
      assert.equal(widgets.at(-1).content, undefined);
      await emit("agent_settled");
      await command("refresh");
      assert.equal(widgets.length, 5);
      await command("show");
      assert.equal(widgets.length, 6);
      await command("bad argument");
      assert.deepEqual(notifications, [
        ["usage: /tasks [refresh|hide|show]", "info"],
      ]);
      assert.equal(
        (await readFile(join(path, "calls"), "utf8")).trim().split("\n").length,
        5,
      );
    },
  );
});

test("errors replace stale tasks and recovery is explicit", async () => {
  const path = await fixture("recovery");
  await harness(path, async ({ emit, command, render }) => {
    await emit("session_start");
    await writeFile(join(path, "output"), "broken");
    await command();
    assert.deepEqual(render().map(safeText), ["tasks: invalid cli data"]);
    await writeFile(join(path, "output"), output([]));
    await command();
    assert.deepEqual(render().map(safeText), ["tasks: no unfinished tasks"]);
  });
  await harness("relative", async ({ emit, render }) => {
    await emit("session_start");
    assert.deepEqual(render().map(safeText), [
      "tasks: abra_tasks_root must be an absolute path",
    ]);
  });
});

test("hide, shutdown and overlapping refresh suppress late subprocess results", async () => {
  const path = await fixture(
    "races",
    "",
    `#!/usr/bin/env node
import fs from 'node:fs';
fs.appendFileSync('calls', 'called\\n');
setTimeout(() => process.stdout.write(fs.readFileSync('output')), 150);
`,
  );
  await writeFile(join(path, "output"), output([task()]));
  await harness(path, async ({ widgets, emit, command }) => {
    const first = emit("session_start");
    const second = command("refresh");
    await Promise.all([first, second]);
    assert.equal(widgets.length, 1);
    const hiding = command("refresh");
    await command("hide");
    await hiding;
    assert.equal(widgets.length, 2);
    assert.equal(widgets.at(-1).content, undefined);
    const showing = command("show");
    await emit("session_shutdown");
    await showing;
    assert.equal(widgets.length, 2);
  });
});

for (const mode of ["rpc", "json", "print"]) {
  test(`${mode} has no widget, notifications or subprocess reads`, async () => {
    const path = await fixture(mode);
    await harness(
      path,
      async ({ widgets, notifications, emit, command }) => {
        await emit("session_start");
        await emit("agent_settled");
        for (const args of ["", "refresh", "hide", "show", "bad"])
          await command(args);
        assert.deepEqual(widgets, []);
        assert.deepEqual(notifications, []);
        await assert.rejects(readFile(join(path, "calls")), { code: "ENOENT" });
      },
      mode,
    );
  });
}

test("real pinned tasks-axi list derives holds/blocks, parses quoted title, and is read-only", async () => {
  const path = join(temporary, "real-backlog.md");
  const markdown =
    '# backlog\n\n## In flight\n\n- [ ] active - active task\n\n## Queued\n\n- [ ] waiting - commas, "quotes" and \\slashes 界 blocked-by: active (hold: paused)\n- [ ] expired - old hold (hold: paused) (hold-until: 2000-01-01)\n\n## Done\n\n- [x] done - completed\n';
  await writeFile(path, markdown);
  const result = execFileSync(
    join(root, "bin/tasks"),
    [
      "list",
      "--fields",
      "held,blocked",
      "--backend",
      "markdown",
      "--file",
      path,
    ],
    {
      cwd: root,
      encoding: "utf8",
      timeout: 30000,
      env: { ...process.env, npm_config_cache: join(root, ".cache/npm") },
    },
  );
  const tasks = parseTasks(result);
  assert.equal(tasks.length, 3);
  assert.equal(tasks.find((task) => task.id === "waiting").held, "yes");
  assert.equal(tasks.find((task) => task.id === "waiting").blocked, "yes");
  assert.match(
    tasks.find((task) => task.id === "waiting").title,
    /commas, "quotes" and \\slashes 界/,
  );
  assert.equal(tasks.find((task) => task.id === "expired").held, "no");
  assert.equal(await readFile(path, "utf8"), markdown);
});
