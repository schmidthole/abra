#!/usr/bin/env python3
"""mcp bridge: a stdio mcp server exposing reply(work_id, text) to the resident agent.

the agent spawns this shim from session/new mcpServers. each tool call is relayed
to the trigger runtime over a unix socket and authenticated with a per-start token
from the shim environment. the runtime side of the socket is `Server`.
"""

import hmac
import json
import logging
import os
import re
import socket
import stat
import sys
import threading

NAME = "abra"
TOOL = "reply"
SOCKET_ENV = "ABRA_BRIDGE_SOCKET"
TOKEN_ENV = "ABRA_BRIDGE_TOKEN"
MAX_LINE = 1024 * 1024
MAX_REQUEST = 256 * 1024
TIMEOUT = 30
VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
TOOL_USE = re.compile(r"[A-Za-z0-9_-]{1,128}")
SCHEMA = {
    "type": "object",
    "properties": {
        "work_id": {
            "type": "string",
            "description": "the work id named in the event for the conversation",
        },
        "text": {"type": "string", "description": "the message to post"},
    },
    "required": ["work_id", "text"],
    "additionalProperties": False,
}
DESCRIPTION = (
    "post a message to the conversation that owns work_id. use the work id from the"
    " runtime event; the runtime resolves where it goes."
)
log = logging.getLogger("abra.bridge")


# runtime side


class Server:
    """unix socket server for the runtime; one json line request and response each.

    handle(request) receives a dict with op and its fields (never the token) and
    returns a response dict; raising valueerror answers with its message.
    """

    def __init__(self, path, token, handle):
        self.path = str(path)
        self.token = token.encode("utf-8")
        self.handle = handle
        self.sock = None
        self.thread = None
        self.stopping = threading.Event()

    def start(self):
        directory = os.path.dirname(self.path)
        # a symlinked directory is fine (the deployer may put data on a volume)
        mode = os.stat(directory).st_mode
        if not stat.S_ISDIR(mode) or stat.S_IMODE(mode) & 0o077:
            raise ValueError("bridge socket directory must be a private directory")
        try:
            if stat.S_ISSOCK(os.lstat(self.path).st_mode):
                os.unlink(self.path)
            else:
                raise ValueError("bridge socket path exists and is not a socket")
        except FileNotFoundError:
            pass
        if len(self.path.encode("utf-8")) > 100:
            raise ValueError("bridge socket path is too long for a unix socket")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        # the private directory guards the moment between bind and chmod
        sock.bind(self.path)
        os.chmod(self.path, 0o600)
        sock.listen(16)
        sock.settimeout(0.5)
        self.sock = sock
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        log.info("bridge listening")

    def stop(self):
        self.stopping.set()
        if self.thread:
            self.thread.join()
            self.thread = None
        if self.sock:
            self.sock.close()
            self.sock = None
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def _serve(self):
        while not self.stopping.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError as error:
                log.error("bridge accept failed: %s", type(error).__name__)
                continue
            with conn:
                conn.settimeout(5)
                try:
                    response = self._answer(read_line(conn, MAX_REQUEST))
                except (OSError, ValueError) as error:
                    log.warning("bridge connection failed: %s", type(error).__name__)
                    continue
                try:
                    conn.sendall(json.dumps(response).encode("utf-8") + b"\n")
                except OSError as error:
                    log.warning("bridge response failed: %s", type(error).__name__)

    def _answer(self, line):
        try:
            request = json.loads(line)
        except (ValueError, RecursionError):
            log.warning("bridge dropped invalid request")
            return {"ok": False, "error": "invalid request"}
        if not isinstance(request, dict):
            log.warning("bridge dropped non-object request")
            return {"ok": False, "error": "invalid request"}
        token = request.pop("token", None)
        if not isinstance(token, str) or not hmac.compare_digest(
            token.encode("utf-8"), self.token
        ):
            log.warning("bridge rejected a request with a bad token")
            return {"ok": False, "error": "unauthorized"}
        try:
            return self.handle(request)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        except Exception as error:
            log.error("bridge handler failed: %s", type(error).__name__)
            return {"ok": False, "error": "internal error"}


def read_line(conn, limit):
    """one newline-terminated line of at most limit bytes."""
    data = b""
    while not data.endswith(b"\n"):
        chunk = conn.recv(65536)
        if not chunk:
            break
        data += chunk
        if len(data) > limit:
            raise ValueError("request too large")
    return data


def call(path, request, timeout=TIMEOUT):
    """send one request to the runtime socket and return its response dict."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(path)
        sock.sendall(json.dumps(request).encode("utf-8") + b"\n")
        response = json.loads(read_line(sock, MAX_REQUEST))
    if not isinstance(response, dict):
        raise ValueError("invalid bridge response")
    return response


# agent side: stdio mcp server


def send(message):
    message["jsonrpc"] = "2.0"
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def result(text, error=False):
    return {"content": [{"type": "text", "text": text}], "isError": error}


def tool_call(params, path, token):
    if not isinstance(params, dict) or params.get("name") != TOOL:
        return result("unknown tool", True)
    arguments = params.get("arguments")
    if not isinstance(arguments, dict) or set(arguments) != {"work_id", "text"}:
        return result("reply takes exactly work_id and text", True)
    meta = params.get("_meta")
    use = meta.get("claudecode/toolUseId") if isinstance(meta, dict) else None
    request = {
        "token": token,
        "op": "reply",
        "work_id": arguments["work_id"],
        "text": arguments["text"],
        "tool_use_id": use if isinstance(use, str) and TOOL_USE.fullmatch(use) else "",
    }
    try:
        response = call(path, request)
    except (OSError, ValueError) as error:
        log.error("bridge relay failed: %s", type(error).__name__)
        return result("the runtime is unreachable", True)
    if response.get("ok") is True:
        return result("posted")
    reason = response.get("error")
    return result(reason if isinstance(reason, str) else "rejected", True)


def answer(message, path, token):
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params")
    if request_id is None:
        return
    if method == "initialize":
        asked = params.get("protocolVersion") if isinstance(params, dict) else None
        send(
            {
                "id": request_id,
                "result": {
                    "protocolVersion": asked if asked in VERSIONS else VERSIONS[2],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": NAME, "version": "1"},
                },
            }
        )
    elif method == "ping":
        send({"id": request_id, "result": {}})
    elif method == "tools/list":
        tool = {"name": TOOL, "description": DESCRIPTION, "inputSchema": SCHEMA}
        send({"id": request_id, "result": {"tools": [tool]}})
    elif method == "tools/call":
        send({"id": request_id, "result": tool_call(params, path, token)})
    else:
        send(
            {"id": request_id, "error": {"code": -32601, "message": "method not found"}}
        )


def main():
    logging.basicConfig(
        level=logging.INFO, format="abra-bridge: %(message)s", stream=sys.stderr
    )
    path = os.environ.get(SOCKET_ENV, "")
    token = os.environ.get(TOKEN_ENV, "")
    if not path or not token:
        log.error("missing bridge socket or token")
        return 1
    stream = sys.stdin.buffer
    while True:
        line = stream.readline(MAX_LINE + 1)
        if not line:
            return 0
        if len(line) > MAX_LINE and not line.endswith(b"\n"):
            while line and not line.endswith(b"\n"):
                line = stream.readline(MAX_LINE + 1)
            log.warning("dropped oversize line")
            continue
        try:
            message = json.loads(line)
        except (ValueError, RecursionError):
            log.warning("dropped invalid line")
            continue
        if not isinstance(message, dict):
            log.warning("dropped non-object line")
            continue
        try:
            answer(message, path, token)
        except Exception as error:
            log.error("request failed: %s", type(error).__name__)
            if message.get("id") is not None:
                send(
                    {
                        "id": message["id"],
                        "error": {"code": -32603, "message": "internal error"},
                    }
                )


if __name__ == "__main__":
    sys.exit(main())
