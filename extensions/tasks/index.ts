import { execFile } from "node:child_process";
import { constants } from "node:fs";
import { access, stat } from "node:fs/promises";
import { dirname, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify, stripVTControlCharacters } from "node:util";
import type {
  ExtensionAPI,
  ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import { truncateToWidth } from "@earendil-works/pi-tui";
import { decode } from "@toon-format/toon";

const executeFile = promisify(execFile);
const defaultRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const widgetKey = "abra-tasks";
const rowLimit = 3;
const settledRefreshWindowMs = 250;

export interface Task {
  id: string;
  title: string;
  state: "in_flight" | "queued" | "done";
  held: "yes" | "no";
  blocked: "yes" | "no";
}

type Snapshot = { tasks: Task[] } | { error: string };

export function tasksRoot(override = process.env.ABRA_TASKS_ROOT): string {
  if (override === undefined) return defaultRoot;
  if (!isAbsolute(override) || /[\p{Cc}\p{Cf}]/u.test(override)) {
    throw new Error("tasks: abra_tasks_root must be an absolute path");
  }
  return resolve(override);
}

export function parseTasks(output: string): Task[] {
  const invalid = () => new Error("tasks: invalid cli data");
  let value: unknown;
  try {
    value = decode(output);
  } catch {
    throw invalid();
  }
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw invalid();
  const { count, tasks } = value as Record<string, unknown>;
  if (!Number.isSafeInteger(count) || (count as number) < 0) throw invalid();
  if (count === 0 && tasks === "0 tasks in this backlog") return [];
  if (!Array.isArray(tasks) || tasks.length !== count) throw invalid();
  const ids = new Set<string>();
  for (const task of tasks) {
    if (
      !task ||
      typeof task !== "object" ||
      typeof task.id !== "string" ||
      !task.id.trim() ||
      ids.has(task.id) ||
      typeof task.title !== "string" ||
      !task.title.trim() ||
      !["in_flight", "queued", "done"].includes(task.state) ||
      !["yes", "no"].includes(task.held) ||
      !["yes", "no"].includes(task.blocked)
    )
      throw invalid();
    ids.add(task.id);
  }
  return (tasks as Task[]).filter((task) => task.state !== "done");
}

export async function readTasks(
  root: string,
  signal?: AbortSignal,
): Promise<Task[]> {
  const cli = resolve(root, "bin/tasks");
  const backlog = resolve(root, "data/backlog.md");
  try {
    await access(cli, constants.X_OK);
    if (!(await stat(cli)).isFile()) throw new Error();
  } catch {
    throw new Error("tasks: bin/tasks missing or not executable");
  }
  try {
    await access(backlog, constants.R_OK);
    if (!(await stat(backlog)).isFile()) throw new Error();
  } catch {
    throw new Error("tasks: backlog missing or unreadable");
  }
  let stdout: string;
  try {
    ({ stdout } = await executeFile(
      cli,
      [
        "list",
        "--fields",
        "held,blocked",
        "--backend",
        "markdown",
        "--file",
        backlog,
      ],
      {
        cwd: root,
        signal,
        timeout: 10000,
        maxBuffer: 2 * 1024 * 1024,
        encoding: "utf8",
      },
    ));
  } catch {
    throw new Error("tasks: cli unavailable or failed (10s / 2mib limit)");
  }
  return parseTasks(stdout);
}

export function safeText(text: string): string {
  return stripVTControlCharacters(text)
    .replace(/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/gu, " ")
    .replace(/\s+/gu, " ")
    .trim();
}

export function taskLines(snapshot: Snapshot, width: number): string[] {
  if (width <= 0) return [];
  let lines: string[];
  if ("error" in snapshot) {
    lines = [snapshot.error];
  } else {
    const tasks = snapshot.tasks;
    const flight = tasks.filter((task) => task.state === "in_flight").length;
    const queued = tasks.length - flight;
    const held = tasks.filter((task) => task.held === "yes").length;
    const blocked = tasks.filter((task) => task.blocked === "yes").length;
    lines =
      tasks.length === 0
        ? ["tasks: no unfinished tasks"]
        : [
            `tasks: ${flight} in-flight · ${queued} queued · ${held} held · ${blocked} blocked`,
          ];
    const ordered = [...tasks].sort(
      (a, b) =>
        Number(b.state === "in_flight") - Number(a.state === "in_flight"),
    );
    for (const task of ordered.slice(0, rowLimit)) {
      const labels = [task.state === "in_flight" ? "in-flight" : "queued"];
      if (task.held === "yes") labels.push("held");
      if (task.blocked === "yes") labels.push("blocked");
      lines.push(`${labels.join("/")} ${task.id}: ${task.title}`);
    }
    if (tasks.length > rowLimit)
      lines.push(`+${tasks.length - rowLimit} more · /tasks refresh`);
  }
  return lines.map((line) => truncateToWidth(safeText(line), width, ""));
}

export default function tasksExtension(pi: ExtensionAPI) {
  let visible = true;
  let generation = 0;
  let pending: AbortController | undefined;
  let lastTurnRefresh = -Infinity;

  function cancel() {
    generation++;
    pending?.abort();
    pending = undefined;
  }

  async function refresh(ctx: ExtensionContext) {
    if (ctx.mode !== "tui" || !visible) return;
    cancel();
    const request = generation;
    const controller = new AbortController();
    pending = controller;
    let snapshot: Snapshot;
    try {
      snapshot = { tasks: await readTasks(tasksRoot(), controller.signal) };
    } catch (error) {
      snapshot = {
        error: error instanceof Error ? error.message : "tasks: unavailable",
      };
    }
    if (request !== generation) return;
    pending = undefined;
    ctx.ui.setWidget(
      widgetKey,
      (_tui, theme) => ({
        render: (width) =>
          taskLines(snapshot, width).map((line) => theme.fg("dim", line)),
        invalidate() {},
      }),
      { placement: "aboveEditor" },
    );
    return true;
  }

  pi.on("session_start", async (_event, ctx) => {
    await refresh(ctx);
  });
  pi.on("turn_end", async (_event, ctx) => {
    if (await refresh(ctx)) lastTurnRefresh = performance.now();
  });
  pi.on("agent_settled", async (_event, ctx) => {
    // reuse a just-finished turn read, but never skip a later turn or manual read.
    if (performance.now() - lastTurnRefresh >= settledRefreshWindowMs)
      await refresh(ctx);
  });
  pi.on("session_shutdown", async () => {
    cancel();
  });
  pi.registerCommand("tasks", {
    description: "refresh tasks widget; /tasks hide or /tasks show",
    handler: async (args, ctx) => {
      if (ctx.mode !== "tui") return;
      switch (args.trim()) {
        case "hide":
          visible = false;
          cancel();
          ctx.ui.setWidget(widgetKey, undefined);
          break;
        case "show":
          visible = true;
          await refresh(ctx);
          break;
        case "":
        case "refresh":
          await refresh(ctx);
          break;
        default:
          ctx.ui.notify("usage: /tasks [refresh|hide|show]", "info");
      }
    },
  });
}
