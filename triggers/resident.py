"""resident trigger backend: one long-lived acp agent session serves every conversation.

messages from all conversations go to one inbox. at most one runtime prompt is
outstanding; arrivals are batched across conversations in arrival order, or
steered into the running turn when the agent supports `_session/steering`. the
agent answers with the bridge's reply(work_id, text) tool.
"""

from datetime import datetime, timezone
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import acp
import mcp_bridge
import runtime
from runtime import log

HERE = Path(__file__).resolve().parent
BRIDGE = HERE / "mcp_bridge.py"
CLI = HERE.parent / "bin" / "abra"
SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
DONE = ("end_turn", "max_tokens", "max_turn_requests")
UNATTENDED = ("bypassPermissions", "agent-full-access")
REPLY_TOOL = "mcp__" + mcp_bridge.NAME + "__" + mcp_bridge.TOOL
MAX_FINAL = 64 * 1024
SOCKET_PATH = 100
SELF_STARTED = ("agent_message_chunk", "agent_thought_chunk", "tool_call")
BOOTSTRAP = (
    "new resident session. run the AGENTS.md startup and reconcile every"
    " unfinished task from its notes; agents and processes from any previous"
    " session are gone."
)
RESTART = (
    "the trigger runtime restarted and resumed this session. background agents and"
    " processes started before the restart are gone; reconcile unfinished tasks"
    " from their notes before relying on them."
)


def load_cli(path=CLI):
    """bin/abra as a module: the single home of prompt framing and specialty reads."""
    loader = importlib.machinery.SourceFileLoader("abra_cli", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def announcement(name, work_id):
    return (
        name
        + " is on it. this thread is now work item "
        + work_id
        + ". reply in this thread to add to it."
    )


def stdio_env(values):
    return [{"name": k, "value": v} for k, v in values.items()]


def translate(config):
    """claude-style mcp config servers as acp mcpServers; invalid entries skipped."""
    servers = config.get("mcpServers") if isinstance(config, dict) else None
    result = []
    for name, entry in (servers or {}).items() if isinstance(servers, dict) else ():
        if not isinstance(entry, dict) or name == mcp_bridge.NAME:
            log.warning("skipping a specialty mcp server with an invalid entry")
            continue
        kind = entry.get("type", "stdio")
        pairs = entry.get("headers" if kind in ("http", "sse") else "env") or {}
        if not isinstance(pairs, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in pairs.items()
        ):
            log.warning("skipping a specialty mcp server with invalid settings")
            continue
        if kind == "stdio":
            command, args = entry.get("command"), entry.get("args") or []
            if not isinstance(command, str) or not all(
                isinstance(a, str) for a in args
            ):
                log.warning("skipping a specialty mcp server with an invalid command")
                continue
            result.append(
                {
                    "name": name,
                    "command": command,
                    "args": args,
                    "env": stdio_env(pairs),
                }
            )
        elif kind in ("http", "sse") and isinstance(entry.get("url"), str):
            result.append(
                {
                    "type": kind,
                    "name": name,
                    "url": entry["url"],
                    "headers": stdio_env(pairs),
                }
            )
        else:
            log.warning("skipping a specialty mcp server of an unsupported type")
    return result


class Resident(runtime.Runtime):
    def __init__(
        self,
        adapter,
        root,
        agent_cmd,
        name="abra",
        agent_mode=False,
        catchup_hours=24,
        env=None,
        stop_timeout=60.0,
        kill_timeout=5.0,
        timeout=300.0,
        wake_grace=20.0,
        heartbeat=1800.0,
        inflight=None,
    ):
        super().__init__(adapter, root, name=name, catchup_hours=catchup_hours)
        argv = shlex.split(agent_cmd) if isinstance(agent_cmd, str) else agent_cmd
        if not argv or not all(isinstance(a, str) and a for a in argv):
            raise ValueError("abra_agent_cmd must name an acp agent command")
        self.argv = list(argv)
        self.agent_mode = agent_mode
        self.env = dict(os.environ if env is None else env)
        self.stop_timeout = stop_timeout
        self.wake_grace = wake_grace
        self.heartbeat = heartbeat
        self.inflight = inflight or self._inflight
        self.kill_timeout = kill_timeout
        self.timeout = timeout
        self.cli = load_cli()
        self.state_path = self.directory / "resident.json"
        self.socket_path = None
        self.socket_dir = None
        self.handoff = self.directory / "bridge.json"
        self.digest = hashlib.sha256("\0".join(self.argv).encode()).hexdigest()[:16]
        self.token = None
        self.client = None
        self.server = None
        self.dispatcher = None
        self.session = None
        self.stored = None
        self.started = None
        self.last_prompt = None
        self.kick = False
        self.order = []
        self.delivered = set()
        self.events = []
        self.turn = None
        self.steering = True
        self.steer_busy = False
        self.loading = False
        self.activity = time.monotonic()
        self.tools = set()
        self.background = set()
        self.wake_at = None
        self.finished = 0
        self.beat_at = time.monotonic() + heartbeat if heartbeat else None
        self.beating = False

    # lifecycle

    def start(self):
        self.cli.preflight(self.root, self.env)
        self._open()
        try:
            self._boot()
        except BaseException:
            self._teardown()
            raise

    def _boot(self):
        with self.lock:
            for conv, entry in self.convs.items():
                entry["archived"] = False
                self._schedule(conv)
        self._catch_up()
        state = self._load_state()
        if state.get("agent") == self.digest and state.get("session_id"):
            self.stored = state["session_id"]
            self.started = state.get("started")
            self.kick = True
        self.token = secrets.token_urlsafe(32)
        self.socket_path = self.directory / "bridge.sock"
        if len(str(self.socket_path).encode("utf-8")) > SOCKET_PATH:
            # unix socket paths are short; fall back to a private temp directory
            self.socket_dir = tempfile.mkdtemp(prefix="abra-")
            self.socket_path = Path(self.socket_dir) / "bridge.sock"
            log.info("bridge socket moved to a private temp directory")
        runtime.write_private(
            self.handoff, {"socket": str(self.socket_path), "token": self.token}
        )
        self.server = mcp_bridge.Server(self.socket_path, self.token, self.bridge)
        self.server.start()
        self.client = acp.Client(
            self.argv,
            cwd=str(self.root),
            env=self.env,
            on_update=self._update,
            permission=self._permission,
            on_exit=self._exited,
            timeout=self.timeout,
            kill_timeout=self.kill_timeout,
        )
        self.client.start()
        self.client.initialize()
        self.steering = self.client.supports("steering")
        log.info("resident agent ready (steering %s)", self.steering)
        self.dispatcher = threading.Thread(target=self._loop, daemon=True)
        self.dispatcher.start()

    def stop(self):
        """stop intake, let the running turn finish (bounded), close the session,
        and kill the agent's process group. pending messages stay stored."""
        if self.holder is None:
            return
        self.stopping.set()
        with self.changed:
            self.changed.notify_all()
            drained = self.changed.wait_for(
                lambda: (self.turn is None and not self.steer_busy)
                or self.crashed.is_set(),
                self.stop_timeout,
            )
        if not drained:
            log.warning("stopping with a turn still running; its messages stay pending")
        if (
            self.client
            and self.session
            and not self.crashed.is_set()
            and self.client.supports("close")
        ):
            try:
                self.client.close_session(self.session)
                log.info("closed the resident session")
            except (acp.AcpError, TimeoutError) as error:
                log.warning("could not close the session: %s", type(error).__name__)
        self._teardown()
        log.info("stopped %s", self.path.name)

    def _teardown(self):
        self.stopping.set()
        if self.client:
            self.client.close()
        with self.changed:
            self.changed.notify_all()
        if self.dispatcher and self.dispatcher is not threading.current_thread():
            self.dispatcher.join()
        if self.server:
            self.server.stop()
            self.server = None
        try:
            os.unlink(self.handoff)
        except OSError:
            pass
        if self.socket_dir:
            shutil.rmtree(self.socket_dir, ignore_errors=True)
            self.socket_dir = None
        if self.holder:
            self.holder.close()
            self.holder = None

    def wait_idle(self, timeout=None):
        """block until nothing is pending or running, or the agent stopped."""
        with self.changed:
            return self.changed.wait_for(
                lambda: self.crashed.is_set()
                or (
                    self.turn is None
                    and not self.order
                    and not self.events
                    and not self.kick
                    and not any(e["pending"] for e in self.convs.values())
                ),
                timeout,
            )

    def _exited(self, code):
        if not self.stopping.is_set():
            self._crash("agent exited with code " + str(code))

    def _crash(self, reason):
        if self.crashed.is_set():
            return
        log.error("resident agent stopped: %s; pending messages stay stored", reason)
        self.crashed.set()
        with self.changed:
            self.changed.notify_all()

    # intake hooks

    def submit(self, event):
        if self.stopping.is_set():
            log.info("ignoring event while stopping")
            return False
        return super().submit(event)

    def _announce(self, conv, work_id, session_id):
        self._reply(conv, announcement(self.name, work_id))

    def _resurrect(self, conv, entry):
        entry["archived"] = False
        self._save()

    def _ack(self, conv, msg_id, state):
        # resident markers: running when the agent gets a message, failed on errors
        if state in ("running", "failed"):
            super()._ack(conv, msg_id, state)

    def _schedule(self, conv):
        """queue this conversation's undelivered messages in arrival order."""
        known = set(self.order) | self.delivered
        for message in self.convs[conv]["pending"]:
            item = (conv, message["msg_id"])
            if item not in known:
                self.order.append(item)
        self.changed.notify_all()

    # bridge

    def bridge(self, request):
        if request.get("op") == "job":
            return self._job(request.get("name"))
        return super().bridge(request)

    def _job(self, name):
        if not isinstance(name, str) or not self.cli.JOB.fullmatch(name):
            raise ValueError("invalid job name")
        text = self.cli.job_text(self.cli.specialty(self.root, self.env), name)
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        event = self.cli.job_event(name, "job:" + name + ":" + day, text)
        with self.lock:
            if self.stopping.is_set():
                raise ValueError("the runtime is stopping")
            self.events.append(event)
            self.changed.notify_all()
        log.info("queued job %s as a runtime event", name)
        return {"ok": True}

    # dispatcher

    def _loop(self):
        while True:
            with self.changed:
                while True:
                    action, delay = self._next()
                    if action is not None:
                        break
                    self.changed.wait(delay)
            if action == "stop":
                return
            try:
                action()
            except Exception as error:
                log.error("resident dispatch failed: %s", type(error).__name__)

    def _next(self):
        """the next dispatcher action, or none and how long to wait; holds the lock."""
        if self.crashed.is_set() or self.stopping.is_set():
            return "stop", None
        moment = time.monotonic()
        if self.turn is None and self.wake_at is not None and moment >= self.wake_at:
            self._wake()
        if self.turn is None and (self.order or self.events or self.kick):
            if self.wake_at is not None:
                self._wake()
            batch = self._take()
            turn = dict(
                batch=batch,
                ids=set(batch),
                events=self.events,
                final=[],
                size=0,
                prompting=False,
                steer=self.steering,
            )
            self.events = []
            self.kick = False
            self.turn = turn
            self.replied = set()
            return (lambda: self._spawn(turn)), None
        turn = self.turn
        if (
            turn is not None
            and turn["prompting"]
            and turn["steer"]
            and self.steering
            and self.order
            and not self.steer_busy
        ):
            batch = self._take()
            if batch:
                self.steer_busy = True
                return (lambda: self._steer(batch)), None
        delays = []
        if self.turn is None and self.wake_at is not None:
            delays.append(self.wake_at - moment)
        if self.turn is None and self.beat_at is not None and not self.beating:
            if moment >= self.beat_at:
                self.beating = True
                return self._beat, None
            delays.append(self.beat_at - moment)
        return None, (max(0.0, min(delays)) if delays else None)

    # wake and heartbeat

    def _wake(self):
        """queue one background-finished event; caller holds the lock."""
        count, self.finished, self.wake_at = self.finished, 0, None
        log.info("background work finished with no self-started turn; waking")
        self.events.append(
            "background work finished ("
            + str(count)
            + " tool calls). check the results, update the task notes, and post"
            " progress with reply."
        )

    def _beat(self):
        """heartbeat when idle; only while tasks-axi reports in-flight work."""
        try:
            count = self.inflight()
        except Exception as error:
            log.warning("heartbeat check failed: %s", type(error).__name__)
            count = 0
        with self.lock:
            self.beating = False
            self.beat_at = time.monotonic() + self.heartbeat
            if count and self.turn is None and not self.order:
                log.info("heartbeat with %d tasks in flight", count)
                self.events.append(
                    "heartbeat: "
                    + str(count)
                    + " tasks are in flight. check on running work and post"
                    " progress with reply where it helps."
                )
            self.changed.notify_all()

    def _inflight(self):
        tasks = self.root / "bin/tasks"
        if not os.access(tasks, os.X_OK):
            return 0
        result = subprocess.run(
            [str(tasks), "list", "--state", "in_flight"],
            cwd=self.root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        match = re.search(r"^count: ([0-9]{1,6})$", result.stdout, re.M)
        return int(match.group(1)) if match and not result.returncode else 0

    def _take(self):
        """the longest arrival-order prefix that fits one prompt; marks it delivered."""
        batch, size = [], 0
        while self.order and len(batch) < runtime.MAX_BATCH:
            conv, msg_id = self.order[0]
            message = self._message(conv, msg_id)
            if message is None:
                self.order.pop(0)
                continue
            cost = len(runtime.encoded(message))
            if batch and size + cost > runtime.MAX_CONTEXT:
                break
            batch.append(self.order.pop(0))
            size += cost
        self.delivered.update(batch)
        return batch

    def _message(self, conv, msg_id):
        entry = self.convs.get(conv)
        for message in entry["pending"] if entry else ():
            if message["msg_id"] == msg_id:
                return message
        return None

    def _sections(self, batch):
        sections, index = [], {}
        with self.lock:
            for conv, msg_id in batch:
                message = self._message(conv, msg_id)
                if message is None:
                    continue
                if conv not in index:
                    index[conv] = len(sections)
                    sections.append((conv, self.convs[conv]["work_id"], []))
                sections[index[conv]][2].append(
                    {
                        "msg_id": message["msg_id"],
                        "from": message["sender"],
                        "text": message["text"],
                    }
                )
        return sections

    def _spawn(self, turn):
        thread = threading.Thread(target=self._run_turn, args=(turn,), daemon=True)
        thread.start()

    def _run_turn(self, turn):
        reason = None
        try:
            extra = self._ensure()
            text = self.cli.resident_prompt(
                self._sections(turn["batch"]), extra + turn["events"]
            )
            with self.lock:
                turn["prompting"] = True
                self.last_prompt = runtime.now()
                self._save_state()
                self.changed.notify_all()
            for conv, msg_id in turn["batch"]:
                self._ack(conv, msg_id, "running")
            log.info(
                "sending a prompt with %d messages and %d events",
                len(turn["batch"]),
                len(extra) + len(turn["events"]),
            )
            reason = self.client.prompt(self.session, text)
        except acp.AgentExited:
            self._crash("agent exited during a turn")
            return
        except (acp.AcpError, TimeoutError, ValueError, OSError) as error:
            log.warning("resident turn failed: %s", type(error).__name__)
        self._end(turn, reason)

    def _end(self, turn, reason):
        failed = reason is None or reason == "refusal"
        with self.lock:
            ids = turn["ids"]
            convs = list(dict.fromkeys(conv for conv, _ in sorted_ids(turn)))
            if reason == "cancelled":
                self.order[:0] = [i for i in sorted_ids(turn) if i not in self.order]
            else:
                self._forget(ids)
            self.delivered -= ids
            final = "".join(turn["final"]).strip()
            fallback = (
                reason in DONE
                and len(convs) == 1
                and convs[0] not in self.replied
                and final
            )
            self.turn = None
            self.activity = time.monotonic()
            # tool calls still open after their turn are background work
            self.background |= self.tools
            self.tools = set()
            self.changed.notify_all()
        log.info("turn ended (%s) for %d conversations", acp.safe(reason), len(convs))
        if failed:
            for conv in convs:
                self._reply(conv, runtime.error_text(self.name))
            for conv, msg_id in sorted_ids(turn):
                self._ack(conv, msg_id, "failed")
        elif fallback:
            log.info("posting the final text to %s (no reply this turn)", convs[0])
            self._reply(convs[0], runtime.clip(final))

    def _forget(self, ids):
        """drop handled messages from the store; caller holds the lock."""
        for conv in {conv for conv, _ in ids}:
            entry = self.convs.get(conv)
            if entry:
                entry["pending"] = [
                    m for m in entry["pending"] if (conv, m["msg_id"]) not in ids
                ]
                entry["last_used"] = runtime.now()
        try:
            self._save()
        except OSError as error:
            log.error("could not store handled messages: %s", type(error).__name__)

    def _steer(self, batch):
        outcome = None
        try:
            text = self.cli.resident_prompt(self._sections(batch))
            outcome = self.client.steer(self.session, text)
        except acp.MethodNotFound:
            log.info("agent has no steering; queueing until the turn ends")
            with self.lock:
                self.steering = False
        except acp.AgentExited:
            self._crash("agent exited while steering")
        except (acp.AcpError, TimeoutError, ValueError, OSError) as error:
            log.warning("steering failed: %s", type(error).__name__)
        ids = set(batch)
        consumed = outcome in ("injected", "startedNewTurn")
        with self.lock:
            self.steer_busy = False
            self.delivered -= ids
            turn = self.turn
            if outcome == "injected" and turn is not None and turn["prompting"]:
                # handled when the running turn ends
                turn["ids"] |= ids
                turn["batch"] = turn["batch"] + batch
                self.delivered |= ids
            elif consumed:
                # a turn we do not await took them; treat them as handled now
                self._forget(ids)
            else:
                # not delivered: they go in the next prompt; no retry this turn
                self.order[:0] = batch
                if turn is not None:
                    turn["steer"] = False
            self.changed.notify_all()
        if consumed:
            for conv, msg_id in batch:
                self._ack(conv, msg_id, "running")

    # agent session

    def _ensure(self):
        """make sure a session exists; returns runtime events it implies."""
        if self.session:
            return []
        servers = self._servers()
        meta = self._meta()
        stored, self.stored = self.stored, None
        if stored:
            for kind in ("resume", "load"):
                if not self.client.supports(kind):
                    continue
                method = getattr(self.client, kind + "_session")
                self.loading = True
                try:
                    result = method(stored, str(self.root), servers, meta)
                except (acp.RemoteError, acp.ProtocolError, TimeoutError) as error:
                    log.warning(
                        "could not %s the stored session: %s",
                        kind,
                        type(error).__name__,
                    )
                    continue
                finally:
                    self.loading = False
                log.info("resumed the stored session with %s", kind)
                self._ready(stored, result, self.started)
                return [RESTART]
            log.info("starting a new session instead of the stored one")
        result = self.client.new_session(str(self.root), servers, meta)
        session = result["sessionId"]
        if not SESSION.fullmatch(session):
            raise acp.ProtocolError("session id has unexpected characters")
        log.info("started a new resident session")
        self._ready(session, result, runtime.now())
        return [BOOTSTRAP]

    def _ready(self, session, result, started):
        with self.lock:
            self.session = session
            self.started = started or runtime.now()
            self._save_state()
        if self.agent_mode:
            self._unattended(result)

    def _unattended(self, result):
        modes = result.get("modes") if isinstance(result, dict) else None
        listed = modes.get("availableModes") if isinstance(modes, dict) else None
        ids = [m.get("id") for m in listed or () if isinstance(m, dict)]
        for mode in UNATTENDED:
            if ids and mode not in ids:
                continue
            try:
                self.client.set_mode(self.session, mode)
            except acp.RemoteError:
                continue
            log.info("agent mode on: session mode set to %s", mode)
            return
        log.warning("agent mode requested but the agent offers no unattended mode")

    def _servers(self):
        servers = [
            {
                "name": mcp_bridge.NAME,
                "command": sys.executable,
                "args": [str(BRIDGE)],
                "env": stdio_env(
                    {
                        mcp_bridge.SOCKET_ENV: str(self.socket_path),
                        mcp_bridge.TOKEN_ENV: self.token,
                    }
                ),
            }
        ]
        spec = self.cli.specialty(self.root, self.env)
        if spec and spec["mcp"]:
            config = self.cli.load_json(spec["mcp"], "mcp_config")
            servers += translate(config)
        return servers

    def _meta(self):
        """claude-agent-acp appends _meta.systemPrompt; other agents ignore it."""
        spec = self.cli.specialty(self.root, self.env)
        if spec and spec["prompt"]:
            return {"systemPrompt": {"append": spec["prompt"]}}
        return None

    def _permission(self, params):
        """allow only the bridge's reply tool, once; reject everything else."""
        call = params.get("toolCall") if isinstance(params, dict) else None
        meta = call.get("_meta") if isinstance(call, dict) else None
        claude = meta.get("claudeCode") if isinstance(meta, dict) else None
        tool = claude.get("toolName") if isinstance(claude, dict) else None
        if tool != REPLY_TOOL:
            return None
        for option in params.get("options") or ():
            if isinstance(option, dict) and option.get("kind") == "allow_once":
                return option.get("optionId")
        return None

    def _update(self, params):
        """acp updates; runs on the client's dispatcher thread, so it never blocks."""
        update = params.get("update")
        if not isinstance(update, dict):
            return
        kind = update.get("sessionUpdate")
        with self.lock:
            if self.loading or params.get("sessionId") != self.session:
                return
            self.activity = time.monotonic()
            self._track(kind, update)
            turn = self.turn
            if turn is None or not turn["prompting"]:
                return
            if kind == "tool_call":
                turn["final"], turn["size"] = [], 0
            elif kind == "agent_message_chunk":
                content = update.get("content")
                text = content.get("text") if isinstance(content, dict) else None
                if isinstance(text, str) and turn["size"] + len(text) <= MAX_FINAL:
                    turn["final"].append(text)
                    turn["size"] += len(text)

    def _track(self, kind, update):
        """follow tool calls that outlive their turn; caller holds the lock."""
        call = update.get("toolCallId")
        status = update.get("status")
        idle = self.turn is None
        if kind in ("tool_call", "tool_call_update") and isinstance(call, str):
            if status in ("completed", "failed"):
                self.tools.discard(call)
                if call in self.background:
                    self.background.discard(call)
                    if idle:
                        self.finished += 1
                        self.wake_at = time.monotonic() + self.wake_grace
                        self.changed.notify_all()
                return
            if kind == "tool_call":
                self.tools.add(call)
                return
        if idle and self.wake_at is not None and kind in SELF_STARTED:
            # the agent started a turn by itself; no wake needed
            log.info("agent woke by itself after background work")
            self.wake_at = None
            self.finished = 0

    # resident store

    def _load_state(self):
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (ValueError, RecursionError, OSError):
            log.warning("ignoring an unreadable resident.json")
            return {}
        if not isinstance(data, dict):
            return {}
        session = data.get("session_id")
        if not isinstance(session, str) or not SESSION.fullmatch(session):
            data["session_id"] = None
        return data

    def _save_state(self):
        """caller holds the lock."""
        try:
            runtime.write_private(
                self.state_path,
                {
                    "version": 1,
                    "agent": self.digest,
                    "session_id": self.session,
                    "started": self.started,
                    "last_prompt": self.last_prompt,
                },
            )
        except OSError as error:
            log.error("could not store resident.json: %s", type(error).__name__)


def sorted_ids(turn):
    """a turn's message ids in delivery order."""
    seen = set()
    result = []
    for item in turn["batch"]:
        if item in turn["ids"] and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def from_env(adapter, args, env, **options):
    """resident settings: abra_agent_cmd (required) and abra_agent_mode=1."""
    command = env.get("ABRA_AGENT_CMD", "")
    if not command.strip():
        raise ValueError("abra_agent_cmd is required when abra_resident=1")
    settings = dict(agent_mode=env.get("ABRA_AGENT_MODE", "") == "1", env=env)
    for variable, key in (
        ("ABRA_WAKE_GRACE", "wake_grace"),
        ("ABRA_HEARTBEAT", "heartbeat"),
    ):
        value = env.get(variable, "")
        if value:
            if not re.fullmatch(r"[0-9]{1,7}", value):
                raise ValueError(variable.lower() + " must be a number of seconds")
            settings[key] = int(value)
    settings.update(options)
    return Resident(adapter, args.root, command, name=args.name, **settings)
