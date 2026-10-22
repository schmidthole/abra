"""stdlib acp v1 client: json-rpc 2.0 over newline-delimited stdio to an agent adapter.

one reader thread parses agent output and one dispatcher thread handles it in
arrival order: session/update notifications go to on_update, agent requests are
answered, and responses wake the waiting call. a waiter thread reaps the agent;
when it exits, its process group is killed and pending calls fail.

callbacks (on_update, permission, on_exit) run on the dispatcher thread and must
return quickly: while one runs, no update, response, or agent request is handled.
they must never block on client requests (that would deadlock) or wait on a human;
cancel() is safe because it only writes.
"""

import itertools
import json
import logging
import os
import queue
import re
import signal
import subprocess
import threading
import time

PROTOCOL_VERSION = 1
MAX_LINE = 8 * 1024 * 1024
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
STEERING = "_session/steering"
REJECT_KINDS = ("reject_once", "reject_always")
DEFAULT = object()
SAFE = re.compile(r"[A-Za-z0-9_./$-]{1,64}")

log = logging.getLogger("abra.acp")


class AcpError(Exception):
    """base class for every error this client raises."""


class RemoteError(AcpError):
    """the agent answered a request with a json-rpc error."""

    def __init__(self, code, message, data=None):
        # the agent's message and data stay off str() so logging the error is safe
        super().__init__("acp error " + str(code))
        self.code = code
        self.message = message
        self.data = data


class MethodNotFound(RemoteError):
    """the agent does not implement the method (-32601)."""


class Unsupported(AcpError):
    """the agent did not advertise the capability; nothing was sent."""


class ProtocolError(AcpError):
    """the agent sent a response this client cannot use."""


class AgentExited(AcpError):
    """the agent closed its output or exited, or the client was closed."""


def safe(value):
    """an agent-controlled name for logs: allowlisted characters or a placeholder."""
    return value if isinstance(value, str) and SAFE.fullmatch(value) else "<unsafe>"


def reject(params):
    """default permission policy: reject everything."""
    return None


class _Pending:
    def __init__(self, method):
        self.method = method
        self.done = threading.Event()
        self.result = None
        self.error = None


class Client:
    """one agent process; use start(), initialize(), then session methods."""

    def __init__(
        self,
        argv,
        cwd=None,
        env=None,
        on_update=None,
        permission=reject,
        on_exit=None,
        max_line=MAX_LINE,
        timeout=300.0,
        kill_timeout=5.0,
        stderr=subprocess.DEVNULL,
    ):
        if (
            not isinstance(argv, (list, tuple))
            or not argv
            or not all(isinstance(a, str) and a for a in argv)
        ):
            raise ValueError("argv must be a non-empty list of strings")
        if isinstance(max_line, bool) or not isinstance(max_line, int) or max_line < 1:
            raise ValueError("max_line must be a positive integer")
        self.argv = list(argv)
        self.cwd = cwd
        self.env = env
        self.on_update = on_update
        self.permission = permission or reject
        self.on_exit = on_exit
        self.max_line = max_line
        self.timeout = timeout
        self.kill_timeout = kill_timeout
        self.stderr = stderr
        self.proc = None
        self.agent = None
        self.capabilities = {}
        self.returncode = None
        self.lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.ids = itertools.count(1)
        self.pending = {}
        self.inbox = queue.Queue(maxsize=1024)
        self.exited = threading.Event()
        self.closed = False
        self.threads = []

    # lifecycle

    def start(self):
        if self.proc is not None:
            raise AcpError("client already started")
        self.proc = subprocess.Popen(
            self.argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            cwd=self.cwd,
            env=self.env,
            start_new_session=True,
        )
        log.info("acp: started agent pid %d", self.proc.pid)
        for target, name in (
            (self._read, "reader"),
            (self._dispatch, "dispatcher"),
            (self._wait, "waiter"),
        ):
            thread = threading.Thread(target=target, name="acp-" + name, daemon=True)
            thread.start()
            self.threads.append(thread)
        return self

    def __enter__(self):
        return self.start() if self.proc is None else self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        """send nothing; close stdin, sigterm the process group, sigkill it after
        kill_timeout, reap, and stop the threads."""
        with self.lock:
            self.closed = True
        if self.proc is None:
            return
        # a writer stuck on a full pipe holds the lock; the signals below free it.
        if self.write_lock.acquire(timeout=1):
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            finally:
                self.write_lock.release()
        self._signal(signal.SIGTERM)
        waiter = self.threads[2]
        waiter.join(self.kill_timeout)
        if waiter.is_alive():
            log.warning("acp: agent ignored sigterm; sending sigkill")
            self._signal(signal.SIGKILL)
        current = threading.current_thread()
        for thread in self.threads:
            if thread is not current:
                thread.join(self.kill_timeout + 5)

    def _signal(self, sig):
        try:
            os.killpg(self.proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    # waiter thread

    def _wait(self):
        """reap the agent, then kill what is left of its group and end the session."""
        self.proc.wait()
        self.returncode = self.proc.returncode
        log.info("acp: agent process exited")
        if self.write_lock.acquire(timeout=1):
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            finally:
                self.write_lock.release()
        # the group outlives its leader while any member is alive, so these reach
        # children that kept running or kept stdout open.
        self._signal(signal.SIGTERM)
        reader = self.threads[0]
        reader.join(self.kill_timeout)
        self._signal(signal.SIGKILL)
        reader.join(self.kill_timeout)
        if reader.is_alive():
            log.warning("acp: agent output is still open after exit")
        self.inbox.put(None)

    # requests

    def request(self, method, params, timeout=None):
        """send a request and block until its response; returns the result."""
        with self.lock:
            if self.closed or self.exited.is_set():
                raise AgentExited("agent is not running")
            request_id = next(self.ids)
            pending = _Pending(method)
            self.pending[request_id] = pending
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        try:
            size = self._write(message)
        except AgentExited:
            with self.lock:
                self.pending.pop(request_id, None)
            raise
        log.info("acp: sent %s id %d (%d bytes)", method, request_id, size)
        if not pending.done.wait(timeout):
            with self.lock:
                self.pending.pop(request_id, None)
            log.warning("acp: %s id %d timed out", method, request_id)
            raise TimeoutError(method + " timed out")
        if pending.error is not None:
            raise pending.error
        return pending.result

    def notify(self, method, params):
        with self.lock:
            if self.closed or self.exited.is_set():
                raise AgentExited("agent is not running")
        size = self._write({"jsonrpc": "2.0", "method": method, "params": params})
        log.info("acp: sent %s notification (%d bytes)", method, size)

    def _write(self, message):
        data = json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        with self.write_lock:
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            except (OSError, ValueError):
                raise AgentExited("agent stdin is closed") from None
        return len(data)

    def _result(self, method, params, timeout=DEFAULT):
        result = self.request(
            method, params, self.timeout if timeout is DEFAULT else timeout
        )
        if not isinstance(result, dict):
            raise ProtocolError(method + " result is not an object")
        return result

    # acp methods

    def initialize(self):
        result = self._result(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
                "clientInfo": {"name": "abra", "version": "1"},
            },
        )
        version = result.get("protocolVersion")
        if version != PROTOCOL_VERSION:
            log.error("acp: agent chose unsupported protocol version")
            self.close()
            raise ProtocolError("unsupported protocol version")
        capabilities = result.get("agentCapabilities") or {}
        if not isinstance(capabilities, dict):
            raise ProtocolError("agentCapabilities is not an object")
        self.agent = result
        self.capabilities = capabilities
        log.info("acp: initialized protocol version %d", version)
        return result

    def supports(self, name):
        """whether the agent advertised load, resume, close, or steering."""
        if name == "load":
            return self.capabilities.get("loadSession") is True
        if name in ("resume", "close"):
            session = self.capabilities.get("sessionCapabilities")
            return isinstance(session, dict) and session.get(name) is not None
        if name == "steering":
            meta = (self.agent or {}).get("_meta")
            steering = meta.get("steering") if isinstance(meta, dict) else None
            return isinstance(steering, dict) and steering.get("supported") is True
        raise ValueError("unknown capability " + repr(name))

    def new_session(self, cwd, mcp_servers=(), meta=None):
        params = self._setup(None, cwd, mcp_servers, meta)
        result = self._result("session/new", params)
        if not isinstance(result.get("sessionId"), str) or not result["sessionId"]:
            raise ProtocolError("session/new returned no session id")
        return result

    def load_session(self, session_id, cwd, mcp_servers=(), meta=None):
        """replays history as session/update notifications before returning."""
        self._require("load", "session/load")
        params = self._setup(session_id, cwd, mcp_servers, meta)
        return self._result("session/load", params)

    def resume_session(self, session_id, cwd, mcp_servers=(), meta=None):
        self._require("resume", "session/resume")
        params = self._setup(session_id, cwd, mcp_servers, meta)
        return self._result("session/resume", params)

    def close_session(self, session_id):
        self._require("close", "session/close")
        return self._result("session/close", {"sessionId": _sid(session_id)})

    def set_mode(self, session_id, mode_id):
        if not isinstance(mode_id, str) or not mode_id:
            raise ValueError("mode id must be a non-empty string")
        return self._result(
            "session/set_mode", {"sessionId": _sid(session_id), "modeId": mode_id}
        )

    def prompt(self, session_id, prompt, timeout=None):
        """run one prompt turn; blocks until the agent returns its stop reason."""
        params = {"sessionId": _sid(session_id), "prompt": _blocks(prompt)}
        result = self._result("session/prompt", params, timeout)
        reason = result.get("stopReason")
        if not isinstance(reason, str):
            raise ProtocolError("session/prompt returned no stop reason")
        log.info("acp: prompt ended with %s", safe(reason))
        return reason

    def cancel(self, session_id):
        self.notify("session/cancel", {"sessionId": _sid(session_id)})

    def steer(self, session_id, prompt, prompt_required=True):
        """inject into the running turn via _session/steering.

        returns the agent's outcome: "injected", or "promptRequired" when idle and
        prompt_required is set (claude-agent-acp); codex-acp may also return
        "startedNewTurn" or "failed". raises MethodNotFound when unsupported.
        """
        params = {"sessionId": _sid(session_id), "prompt": _blocks(prompt)}
        if prompt_required:
            params["_meta"] = {"steering": {"idleBehavior": "promptRequired"}}
        outcome = self._result(STEERING, params).get("outcome")
        if not isinstance(outcome, str):
            raise ProtocolError("steering returned no outcome")
        log.info("acp: steering outcome %s", safe(outcome))
        return outcome

    def _require(self, name, method):
        if not self.supports(name):
            raise Unsupported(method + " is not advertised by the agent")

    @staticmethod
    def _setup(session_id, cwd, mcp_servers, meta):
        if not isinstance(cwd, str) or not os.path.isabs(cwd):
            raise ValueError("cwd must be an absolute path")
        servers = list(mcp_servers)
        if not all(isinstance(s, dict) for s in servers):
            raise ValueError("mcp servers must be objects")
        params = {"cwd": cwd, "mcpServers": servers}
        if session_id is not None:
            params["sessionId"] = _sid(session_id)
        if meta is not None:
            if not isinstance(meta, dict):
                raise ValueError("meta must be an object")
            params["_meta"] = meta
        return params

    # reader thread

    def _read(self):
        stream = self.proc.stdout
        try:
            while True:
                line = stream.readline(self.max_line + 1)
                if not line:
                    break
                if len(line) > self.max_line and not line.endswith(b"\n"):
                    size = len(line)
                    while line and not line.endswith(b"\n"):
                        line = stream.readline(self.max_line + 1)
                        size += len(line)
                    log.warning("acp: dropped oversize line (%d bytes)", size)
                    continue
                try:
                    message = json.loads(line)
                except (ValueError, RecursionError) as exc:
                    log.warning("acp: dropped invalid line (%s)", type(exc).__name__)
                    continue
                if not isinstance(message, dict):
                    log.warning(
                        "acp: dropped non-object line (%s)", type(message).__name__
                    )
                    continue
                self.inbox.put(message)
        except Exception as exc:
            log.error("acp: reader failed (%s)", type(exc).__name__)
        finally:
            # without a reader the session is over: kill the group so the waiter
            # reaps it and fails pending calls.
            stream.close()
            log.info("acp: agent output closed")
            self._signal(signal.SIGTERM)
            if self.proc.poll() is None:
                time.sleep(0.1)
                self._signal(signal.SIGKILL)

    # dispatcher thread

    def _dispatch(self):
        while True:
            message = self.inbox.get()
            if message is None:
                break
            try:
                self._handle(message)
            except Exception as exc:
                log.error("acp: failed to handle message (%s)", type(exc).__name__)
        with self.lock:
            self.exited.set()
            pending, self.pending = self.pending, {}
        for request_id, item in pending.items():
            log.warning("acp: %s id %d failed: agent exited", item.method, request_id)
            item.error = AgentExited("agent exited before responding")
            item.done.set()
        log.info("acp: agent exited with code %s", self.returncode)
        if self.on_exit is not None:
            try:
                self.on_exit(self.returncode)
            except Exception as exc:
                log.error("acp: on_exit callback failed (%s)", type(exc).__name__)

    def _handle(self, message):
        method = message.get("method")
        if isinstance(method, str):
            if "id" in message:
                self._answer(message["id"], method, message.get("params"))
            elif method == "session/update":
                self._update(message.get("params"))
            else:
                log.info("acp: ignored %s notification", safe(method))
            return
        if "id" in message and ("result" in message or "error" in message):
            self._resolve(message)
            return
        log.warning("acp: dropped message with no method or result")

    def _update(self, params):
        if not isinstance(params, dict):
            log.warning("acp: dropped session/update with invalid params")
            return
        if self.on_update is None:
            return
        try:
            self.on_update(params)
        except Exception as exc:
            log.error("acp: update callback failed (%s)", type(exc).__name__)

    def _resolve(self, message):
        request_id = message["id"]
        with self.lock:
            pending = (
                self.pending.pop(request_id, None)
                if isinstance(request_id, int) and not isinstance(request_id, bool)
                else None
            )
        if pending is None:
            log.warning("acp: dropped response for unknown id")
            return
        error = message.get("error")
        if "error" in message:
            code = error.get("code") if isinstance(error, dict) else None
            text = error.get("message") if isinstance(error, dict) else None
            if isinstance(code, bool) or not isinstance(code, int):
                code = INTERNAL_ERROR
            kind = MethodNotFound if code == METHOD_NOT_FOUND else RemoteError
            data = error.get("data") if isinstance(error, dict) else None
            pending.error = kind(code, text if isinstance(text, str) else "", data)
            log.warning(
                "acp: %s id %d failed with code %d", pending.method, request_id, code
            )
        else:
            pending.result = message.get("result")
            log.info("acp: %s id %d succeeded", pending.method, request_id)
        pending.done.set()

    def _answer(self, request_id, method, params):
        name = safe(method)
        log.info("acp: agent requested %s", name)
        if method == "session/request_permission":
            try:
                reply = {"result": {"outcome": self._decide(params)}}
            except Exception as exc:
                log.warning("acp: invalid permission request (%s)", type(exc).__name__)
                reply = {"error": {"code": INVALID_PARAMS, "message": "invalid params"}}
        else:
            reply = {"error": {"code": METHOD_NOT_FOUND, "message": "method not found"}}
            log.info("acp: answered %s with %d", name, METHOD_NOT_FOUND)
        reply.update(jsonrpc="2.0", id=request_id)
        try:
            self._write(reply)
        except AgentExited:
            log.warning("acp: could not answer %s: agent stdin is closed", name)

    def _decide(self, params):
        """ask the policy hook; anything but a valid offered option id rejects."""
        options = params.get("options") if isinstance(params, dict) else None
        if not isinstance(options, list):
            raise ValueError("options must be a list")
        options = [o for o in options if isinstance(o, dict)]
        offered = [o.get("optionId") for o in options]
        try:
            choice = self.permission(params)
        except Exception as exc:
            log.error(
                "acp: permission policy failed (%s); rejecting", type(exc).__name__
            )
            choice = None
        if choice is not None and isinstance(choice, str) and choice in offered:
            log.info("acp: permission granted by policy")
            return {"outcome": "selected", "optionId": choice}
        for kind in REJECT_KINDS:
            for option in options:
                if option.get("kind") == kind and isinstance(
                    option.get("optionId"), str
                ):
                    log.info("acp: permission rejected (%s)", kind)
                    return {"outcome": "selected", "optionId": option["optionId"]}
        log.info("acp: permission rejected (no reject option; cancelled)")
        return {"outcome": "cancelled"}


def _sid(session_id):
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("session id must be a non-empty string")
    return session_id


def _blocks(prompt):
    if isinstance(prompt, str):
        return [{"type": "text", "text": prompt}]
    blocks = list(prompt)
    if not blocks or not all(isinstance(b, dict) for b in blocks):
        raise ValueError("prompt must be text or a non-empty list of content blocks")
    return blocks
