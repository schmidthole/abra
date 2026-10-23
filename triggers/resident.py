"""resident trigger backend: one long-lived acp agent session serves every conversation.

messages from all conversations go to one inbox. at most one runtime prompt is
outstanding; arrivals are batched across conversations in arrival order, or
steered into the running turn when the agent supports `_session/steering`. the
agent answers with the bridge's reply(work_id, text) tool.
"""

from datetime import datetime, timezone
import fcntl
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
CHILD_DONE = ("completed", "failed", "cancelled", "disconnected")
REPLY_TOOL = "mcp__" + mcp_bridge.NAME + "__" + mcp_bridge.TOOL
MAX_FINAL = 64 * 1024
MAX_JOBS = 20
SOCKET_PATH = 100
CHECKPOINT = (
    "checkpoint: this session is about to be cleared because abra is idle. save"
    " your notes now: update every unfinished task body so a fresh session can"
    " continue from it, then end the turn without posting."
)
SELF_STARTED = ("agent_message_chunk", "agent_thought_chunk", "tool_call")
BOOTSTRAP = (
    "new resident session. run the AGENTS.md startup, read docs/modes/resident.md,"
    " and reconcile every unfinished task from its notes; agents and processes"
    " from any previous session are gone."
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


def stdio_env(values):
    return [{"name": k, "value": v} for k, v in values.items()]


def translate(config):
    """claude-style mcp config servers as acp mcpServers; never drop settings."""
    servers = config.get("mcpServers") if isinstance(config, dict) else None
    if not isinstance(servers, dict):
        raise ValueError("mcp_config must contain mcpservers")
    result = []
    for name, entry in (servers or {}).items() if isinstance(servers, dict) else ():
        if not isinstance(entry, dict) or name == mcp_bridge.NAME:
            raise ValueError("invalid or reserved specialty mcp server")
        kind = entry.get("type", "stdio")
        allowed = (
            {"type", "command", "args", "env"}
            if kind == "stdio"
            else {"type", "url", "headers"}
        )
        if set(entry) - allowed:
            raise ValueError("unsupported specialty mcp settings")
        pairs = entry.get("headers" if kind in ("http", "sse") else "env") or {}
        if not isinstance(pairs, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in pairs.items()
        ):
            raise ValueError("invalid specialty mcp settings")
        if kind == "stdio":
            command, args = entry.get("command"), entry.get("args") or []
            if (
                not isinstance(command, str)
                or not isinstance(args, list)
                or not all(isinstance(a, str) for a in args)
            ):
                raise ValueError("invalid specialty mcp command")
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
            raise ValueError("unsupported specialty mcp transport")
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
        idle_clear=600.0,
        max_age=7 * 24 * 3600.0,
        rotate_idle=60.0,
        inflight=None,
        provider=None,
    ):
        super().__init__(adapter, root, name=name, catchup_hours=catchup_hours)
        argv = shlex.split(agent_cmd) if isinstance(agent_cmd, str) else agent_cmd
        if not argv or not all(isinstance(a, str) and a for a in argv):
            raise ValueError("abra_agent_cmd must name an acp agent command")
        self.argv = list(argv)
        self.agent_mode = agent_mode
        self.env = dict(os.environ if env is None else env)
        self.provider = provider or self.env.get("ABRA_AGENT_PROVIDER", "claude")
        if self.provider not in ("claude", "codex"):
            raise ValueError("abra_agent_provider must be claude or codex")
        self.env["ABRA_AGENT_PROVIDER"] = self.provider
        if self.provider == "codex":
            config = json.loads(self.env.get("CODEX_CONFIG") or "{}")
            if not isinstance(config, dict):
                raise ValueError("codex_config must be a json object")
            if any(config.get(key) for key in ("mcp_servers", "profiles", "plugins")):
                raise ValueError(
                    "put codex mcp servers in the specialty, not codex_config"
                )
            if config.get("project_root_markers", []) != []:
                raise ValueError(
                    "resident codex project root must be the instance root"
                )
            config["project_root_markers"] = []
            features = config.setdefault("features", {})
            if not isinstance(features, dict):
                raise ValueError("codex_config features must be an object")
            for feature, value in (
                ("multi_agent", True),
                ("apps", False),
                ("plugins", False),
            ):
                if feature in features and features[feature] is not value:
                    raise ValueError("conflicting resident codex feature configuration")
                features[feature] = value
            self.env["CODEX_CONFIG"] = json.dumps(config)
        self.stop_timeout = stop_timeout
        self.wake_grace = wake_grace
        self.heartbeat = heartbeat
        self.idle_clear = idle_clear
        self.max_age = max_age
        self.rotate_idle = rotate_idle
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
        self.instance = None
        self.wrote_handoff = False
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
        self.retried = set()
        self.jobs = []
        self.steer_busy = False
        self.loading = False
        self.activity = time.monotonic()
        self.tools = set()
        self.background = set()
        self.native_children = False
        self.children = {}
        self.reply_calls = set()
        self.setup_failure = False
        self.draining = False
        self.wake_at = None
        self.finished = 0
        self.beat_at = time.monotonic() + heartbeat if heartbeat else None
        self.beating = False

    # lifecycle

    def start(self):
        self.cli.preflight(self.root, self.env)
        if self.provider == "codex":
            self.cli.codex_config_check(self.root, self.env, ignore_user_config=False)
        try:
            self._open()
            self._boot()
        except BaseException:
            self._teardown()
            raise

    def _boot(self):
        # one resident session per root, whichever adapter hosts it
        descriptor = os.open(
            self.directory / "resident.lock", os.O_WRONLY | os.O_CREAT, 0o600
        )
        os.fchmod(descriptor, 0o600)
        self.instance = os.fdopen(descriptor, "a")
        try:
            fcntl.flock(self.instance, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another resident runtime already runs on this root")
        # resident files belong to whoever holds the lock, so sweep only now
        stale = list(self.directory.glob(".resident.json*.tmp"))
        stale += list(self.directory.glob(".bridge.json*.tmp"))
        for path in stale:
            path.unlink()
        if stale:
            log.info("removed %d stale resident temporary files", len(stale))
        with self.lock:
            for conv in self.convs:
                self._schedule(conv)
        self._catch_up()
        state = self._load_state()
        jobs = state.get("jobs")
        if isinstance(jobs, list):
            self.jobs = [j for j in jobs if isinstance(j, str)][:MAX_JOBS]
            self.events.extend(self.jobs)
        if (
            state.get("agent") == self.digest
            and state.get("provider", "claude") == self.provider
            and state.get("session_id")
        ):
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
        self.wrote_handoff = True
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
        self.client.initialize(subagents=self.provider == "codex")
        self.native_children = self.provider == "codex" and self.client.supports(
            "subagents"
        )
        # codex steering may start a turn that this client cannot await.
        self.steering = self.provider == "claude" and self.client.supports("steering")
        log.info("resident agent ready (steering %s)", self.steering)
        self.dispatcher = threading.Thread(target=self._loop, daemon=True)
        self.dispatcher.start()

    def stop(self):
        """stop intake, let the running turn finish (bounded), close the session,
        and kill the agent's process group. pending messages stay stored."""
        if self.holder is None:
            return
        self.draining = True
        with self.changed:
            self.changed.notify_all()
            drained = self.changed.wait_for(
                lambda: (self.turn is None and self._quiet()) or self.crashed.is_set(),
                self.stop_timeout,
            )
            self.stopping.set()
            self.changed.notify_all()
        if not drained:
            log.warning("stopping with work still running; its messages stay pending")
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
        # a refused start must not touch the running runtime's handoff
        if self.wrote_handoff:
            self.wrote_handoff = False
            try:
                os.unlink(self.handoff)
            except OSError:
                pass
        if self.socket_dir:
            shutil.rmtree(self.socket_dir, ignore_errors=True)
            self.socket_dir = None
        if self.instance:
            self.instance.close()
            self.instance = None
        if self.holder:
            self.holder.close()
            self.holder = None

    def wait_idle(self, timeout=None):
        """block until nothing is pending or running, or the agent stopped."""
        with self.changed:
            return self.changed.wait_for(
                lambda: self.crashed.is_set() or (self.turn is None and self._quiet()),
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
        if self.draining or self.stopping.is_set():
            log.info("ignoring event while stopping")
            return False
        return super().submit(event)

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
            if self.draining or self.stopping.is_set():
                raise ValueError("the runtime is stopping")
            if len(self.jobs) >= MAX_JOBS:
                raise ValueError("too many jobs are waiting")
            # stored until a turn delivers it, so a crash does not lose it
            self.jobs.append(event)
            self._save_state()
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
                # an internal error: stop like a crash so the supervisor restarts
                # the runtime; pending messages stay stored
                self._crash("dispatch failed (" + type(error).__name__ + ")")
                return

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
        if not self.draining and self.turn is None and self.session and self._quiet():
            idle = moment - self.activity
            age = time.time() - runtime.seconds(self.started)
            due = []
            if self.idle_clear:
                due.append(self.idle_clear - idle)
            if self.max_age and age >= self.max_age:
                due.append(self.rotate_idle - idle)
            if due and min(due) <= 0:
                log.info("session is idle; checkpointing before clearing it")
                turn = dict(
                    batch=[],
                    ids=set(),
                    events=[CHECKPOINT],
                    final=[],
                    size=0,
                    prompting=False,
                    steer=False,
                    checkpoint=True,
                )
                self.turn = turn
                self.replied = set()
                return (lambda: self._spawn(turn)), None
            if due:
                delays.append(min(due))
        if self.turn is None and self.wake_at is not None:
            delays.append(self.wake_at - moment)
        if (
            self.turn is None
            and self.session
            and not self.draining
            and self.beat_at is not None
            and not self.beating
        ):
            if moment >= self.beat_at:
                self.beating = True
                return self._beat, None
            delays.append(self.beat_at - moment)
        return None, (max(0.0, min(delays)) if delays else None)

    def _quiet(self):
        """nothing pending, queued, or running in the background; holds the lock."""
        return not (
            self.order
            or self.events
            or self.kick
            or self.background
            or any(child["state"] == "running" for child in self.children.values())
            or self.tools
            or self.wake_at is not None
            or self.steer_busy
            or any(entry["pending"] for entry in self.convs.values())
        )

    def _clear(self):
        """close the session after a checkpoint; the next event starts a new one."""
        if self.client.supports("close"):
            try:
                self.client.close_session(self.session)
            except (acp.RemoteError, acp.ProtocolError, TimeoutError) as error:
                log.warning("could not close the session: %s", type(error).__name__)
        with self.lock:
            self.session = None
            self.started = None
            self.background = set()
            self.tools = set()
            self.children = {}
            self.reply_calls = set()
            self.finished = 0
            self.wake_at = None
            self._save_state()
            self.changed.notify_all()
        log.info("cleared the resident session; the next event starts a new one")

    # wake and heartbeat

    def _wake(self):
        """queue one background-finished event; caller holds the lock."""
        count, self.finished, self.wake_at = self.finished, 0, None
        log.info("background work finished with no self-started turn; waking")
        self.events.append(
            "background work finished ("
            + str(count)
            + (" native subagents" if self.native_children else " tool calls")
            + "). check the results, update the task notes, and post"
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
        except Exception as error:
            self._crash("session setup failed (" + type(error).__name__ + ")")
            return
        try:
            text = self.cli.resident_prompt(
                self._sections(turn["batch"]), extra + turn["events"]
            )
            with self.lock:
                if self.crashed.is_set():
                    return
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
        except Exception as error:
            log.warning("resident turn failed: %s", type(error).__name__)
        try:
            self._end(turn, reason)
        except Exception as error:
            self._crash("ending a turn failed (" + type(error).__name__ + ")")

    def _end(self, turn, reason):
        if turn.get("checkpoint"):
            # clear however the checkpoint ended (a rejected tool can cancel it),
            # while the turn still blocks new prompts on the old session
            self._clear()
        failed = reason is None or reason == "refusal"
        with self.changed:
            # a prompt may finish before an accepted injection's response arrives.
            # retain all injected input until the turn and the steering rpc finish.
            self.changed.wait_for(lambda: not self.steer_busy or self.crashed.is_set())
            if self.crashed.is_set():
                return
            ids = turn["ids"]
            ordered = sorted_ids(turn)
            dropped = ordered
            if reason == "cancelled":
                # the runtime cancels only when stopping; an agent-side cancel (for
                # example after a rejected permission) gets one retry per message
                retry = [
                    i
                    for i in ordered
                    if self.stopping.is_set() or i not in self.retried
                ]
                dropped = [i for i in ordered if i not in retry]
                self.retried.update(retry)
                self.order[:0] = [i for i in retry if i not in self.order]
                failed = bool(dropped)
            self._forget(set(dropped))
            self.retried -= set(dropped)
            convs = list(dict.fromkeys(conv for conv, _ in dropped))
            self.delivered -= ids
            jobs = [e for e in turn["events"] if e in self.jobs]
            again = []
            if reason == "cancelled":
                again = [
                    e for e in jobs if self.stopping.is_set() or e not in self.retried
                ]
                self.retried.update(again)
                if not self.stopping.is_set():
                    self.events[:0] = [e for e in again if e not in self.events]
            done = [e for e in jobs if e not in again]
            if done:
                self.jobs = [j for j in self.jobs if j not in done]
                self.retried -= set(done)
                self._save_state()
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
            if not self.native_children:
                self.background |= self.tools
            self.tools = set()
            self.reply_calls = set()
            self.changed.notify_all()
        log.info("turn ended (%s) for %d conversations", acp.safe(reason), len(convs))
        if failed:
            for conv in convs:
                self._reply(conv, self._text(runtime.error_text))
            for conv, msg_id in dropped:
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
                # accepted by an unowned turn: preserve durable input and stop;
                # replay requires the restart reconciliation, never an immediate retry.
                self._crash("steering started an untracked turn")
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
        instructions = self._instructions()
        system_prompt = None
        if self.provider == "codex":
            if self.client.supports("systemPrompt"):
                system_prompt = instructions
            else:
                spec = self.cli.specialty(self.root, self.env)
                if spec and spec["prompt"]:
                    raise acp.Unsupported(
                        "codex adapter must support specialty system instructions"
                    )
        stored, self.stored = self.stored, None
        if stored:
            for kind in ("resume", "load"):
                if not self.client.supports(kind):
                    continue
                method = getattr(self.client, kind + "_session")
                self.loading = True
                try:
                    result = method(
                        stored, str(self.root), servers, meta, system_prompt
                    )
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
                return [RESTART, self._child_policy()]
            log.info("starting a new session instead of the stored one")
        result = self.client.new_session(str(self.root), servers, meta, system_prompt)
        session = result["sessionId"]
        if not SESSION.fullmatch(session):
            raise acp.ProtocolError("session id has unexpected characters")
        log.info("started a new resident session")
        self._ready(session, result, runtime.now())
        return [BOOTSTRAP, self._child_policy()]

    def _ready(self, session, result, started):
        if self.setup_failure:
            raise acp.ProtocolError("required mcp server did not start")
        with self.lock:
            self.session = session
            self.started = started or runtime.now()
            self._save_state()
        if self.agent_mode:
            self._unattended(result)
        for variable, config_id in (
            ("ABRA_MODEL", "model"),
            ("ABRA_REASONING_EFFORT", "reasoning_effort"),
        ):
            value = self.env.get(variable)
            if value:
                options = result.get("configOptions", [])
                if not any(
                    isinstance(o, dict) and o.get("id") == config_id for o in options
                ):
                    raise acp.Unsupported("requested model setting is not advertised")
                result = self.client.set_config(self.session, config_id, value)
                if not any(
                    isinstance(o, dict)
                    and o.get("id") == config_id
                    and o.get("currentValue") == value
                    for o in result.get("configOptions", [])
                ):
                    raise acp.ProtocolError(
                        "agent did not apply requested model setting"
                    )

    def _unattended(self, result):
        modes = result.get("modes") if isinstance(result, dict) else None
        listed = modes.get("availableModes") if isinstance(modes, dict) else None
        ids = [m.get("id") for m in listed or () if isinstance(m, dict)]
        for mode in (UNATTENDED[0 if self.provider == "claude" else 1],):
            if mode not in ids:
                continue
            try:
                self.client.set_mode(self.session, mode)
            except acp.RemoteError:
                continue
            log.info("agent mode on: session mode set to %s", mode)
            return
        raise acp.Unsupported(
            "agent mode requested but no unattended mode is available"
        )

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
        capabilities = self.client.capabilities.get("mcpCapabilities", {})
        for server in servers:
            kind = server.get("type", "stdio")
            if kind != "stdio" and capabilities.get(kind) is not True:
                raise acp.Unsupported("specialty mcp transport is not advertised")
        return servers

    def _meta(self):
        if self.provider == "claude":
            return {"systemPrompt": {"append": self._instructions()}}
        return None

    def _child_policy(self):
        if self.native_children or self.provider == "claude":
            return "child policy: background completion is tracked; dispatch and end the turn when useful."
        return "child policy: background completion is unavailable; wait for all native subagents in this turn before ending it."

    def _instructions(self):
        spec = self.cli.specialty(self.root, self.env)
        return self._child_policy() + (
            "\n\nfollow AGENTS.md and the active mode rules. specialty instructions below"
            " specialize the task; they never override those base rules.\n\n"
            + spec["prompt"]
            if spec and spec["prompt"]
            else ""
        )

    def _permission(self, params):
        """allow only the bridge's reply tool, once; reject everything else."""
        call = params.get("toolCall") if isinstance(params, dict) else None
        meta = call.get("_meta") if isinstance(call, dict) else None
        claude = meta.get("claudeCode") if isinstance(meta, dict) else None
        claude = claude if isinstance(claude, dict) else {}
        with self.lock:
            session = self.session
            if self.provider == "codex":
                approval = params.get("_meta", {})
                if (
                    not self.native_children
                    or not isinstance(approval, dict)
                    or approval.get("is_mcp_tool_approval") is not True
                    or not isinstance(call, dict)
                    or call.get("toolCallId") not in self.reply_calls
                ):
                    return None
            else:
                server = claude.get("mcpServer")
                if (
                    claude.get("toolName") != REPLY_TOOL
                    or not isinstance(server, dict)
                    or server.get("name") != mcp_bridge.NAME
                ):
                    return None
        if not session or params.get("sessionId") != session:
            # not a subagent check: without the acp subagents capability,
            # claude-agent-acp sends subagent requests with the root session id
            log.warning("rejected a reply outside the resident session")
            return None
        if self.provider == "claude" and claude.get("parentToolUseId"):
            # a subagent's call; best effort, the adapter can omit this field
            log.warning("rejected a reply from a subagent")
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
            # the pinned codex adapter reports required mcp startup failures as
            # failed tool calls, including while session/new has not returned.
            call_id = update.get("toolCallId")
            if (
                self.provider == "codex"
                and kind == "tool_call"
                and update.get("status") == "failed"
                and isinstance(call_id, str)
                and call_id.startswith("mcp_startup.")
                and (self.session is None or params.get("sessionId") == self.session)
            ):
                self.setup_failure = True
                self._crash("required mcp server failed to start")
                return
            if self.loading:
                return
            source = params.get("sessionId")
            if self.native_children and kind in (
                "subagent_spawned",
                "subagent_state_update",
            ):
                self._child_update(source, kind, update)
                return
            if not self.session or source != self.session:
                # child text and tools are not root output or root permissions.
                return
            self.activity = time.monotonic()
            if self.provider == "codex" and self.turn is None and kind in SELF_STARTED:
                self._crash("untracked root turn; reconcile before resuming")
                return
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

    def _child_update(self, source, kind, update):
        """accept native child lifecycle only from its recorded parent session."""
        if not self.session or (source != self.session and source not in self.children):
            return
        child_id = update.get("subagentSessionId")
        if (
            not isinstance(child_id, str)
            or not SESSION.fullmatch(child_id)
            or child_id == self.session
        ):
            return
        child = self.children.get(child_id)
        if kind == "subagent_spawned":
            if child is not None or (
                source in self.children and self.children[source]["state"] != "running"
            ):
                return
            # reopened native sessions have a fresh generation-specific id;
            # a duplicate spawn cannot resurrect a completed generation.
            self.children[child_id] = {"parent": source, "state": "running"}
        else:
            state = update.get("state")
            if (
                not child
                or child["parent"] != source
                or child["state"] != "running"
                or state not in CHILD_DONE
            ):
                return
            child["state"] = state
            self.finished += 1
            self.wake_at = time.monotonic() + self.wake_grace
        self.activity = time.monotonic()
        self._save_state()
        self.changed.notify_all()

    def _track(self, kind, update):
        """follow tool calls that outlive their turn; caller holds the lock."""
        call = update.get("toolCallId")
        status = update.get("status")
        idle = self.turn is None
        if (
            self.provider == "claude"
            and idle
            and self.wake_at is not None
            and kind in SELF_STARTED
        ):
            # legacy claude adapters do not expose an external turn lifecycle.
            log.info("agent woke by itself after background work")
            self.wake_at = None
            self.finished = 0
        if kind in ("tool_call", "tool_call_update") and isinstance(call, str):
            if self.provider == "codex" and kind == "tool_call":
                self.reply_calls.discard(call)
                raw = update.get("rawInput")
                if (
                    isinstance(raw, dict)
                    and raw.get("server") == mcp_bridge.NAME
                    and raw.get("tool") == mcp_bridge.TOOL
                    and status not in ("completed", "failed")
                ):
                    self.reply_calls.add(call)
            if status in ("completed", "failed"):
                self.reply_calls.discard(call)
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
                    "version": 2,
                    "agent": self.digest,
                    "provider": self.provider,
                    "session_id": self.session,
                    "started": self.started,
                    "last_prompt": self.last_prompt,
                    "jobs": self.jobs,
                    "children": self.children,
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
    command = env.get("ABRA_RESIDENT_AGENT_CMD", env.get("ABRA_AGENT_CMD", ""))
    if not command.strip():
        raise ValueError("abra_agent_cmd is required")
    settings = dict(agent_mode=env.get("ABRA_AGENT_MODE", "") == "1", env=env)
    for variable, key in (
        ("ABRA_WAKE_GRACE", "wake_grace"),
        ("ABRA_HEARTBEAT", "heartbeat"),
        ("ABRA_IDLE_CLEAR", "idle_clear"),
        ("ABRA_MAX_SESSION_AGE", "max_age"),
    ):
        value = env.get(variable, "")
        if value:
            if not re.fullmatch(r"[0-9]{1,7}", value):
                raise ValueError(variable.lower() + " must be a number of seconds")
            settings[key] = int(value)
    settings.update(options)
    return Resident(adapter, args.root, command, name=args.name, **settings)
