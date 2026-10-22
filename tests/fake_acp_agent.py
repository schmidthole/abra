"""fake acp agent for tests: speaks json-rpc over stdio, driven by prompt text.

usage: fake_acp_agent.py LOG [--bare] [--stubborn] [--v2]
  LOG        file that receives every message read from stdin, one per line
  --bare     advertise no load, resume, close, or steering; steering is -32601
  --stubborn ignore sigterm and stdin eof so the client must sigkill
  --v2       answer initialize with protocol version 2
"""

import json
import os
import signal
import subprocess
import sys
import time

log_path = sys.argv[1]
bare = "--bare" in sys.argv
if "--stubborn" in sys.argv:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
held = None
next_id = 1000


def send(message):
    message["jsonrpc"] = "2.0"
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def raw(data):
    sys.stdout.write(data)
    sys.stdout.flush()


def update(session_id, text):
    send(
        {
            "method": "session/update",
            "params": {
                "sessionId": session_id,
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": text},
                },
            },
        }
    )


def read():
    line = sys.stdin.readline()
    if not line:
        if "--stubborn" in sys.argv:
            time.sleep(120)
        sys.exit(0)
    with open(log_path, "a") as handle:
        handle.write(line)
    return json.loads(line)


def ask(method, params):
    """send an agent -> client request and return the client's reply."""
    global next_id
    next_id += 1
    send({"id": next_id, "method": method, "params": params})
    while True:
        message = read()
        if message.get("id") == next_id and "method" not in message:
            return message
        handle(message)


def prompt(request_id, params):
    global held
    sid = params["sessionId"]
    text = params["prompt"][0]["text"]
    if text == "hello":
        update(sid, "alpha")
        update(sid, "beta")
    elif text == "later":
        send({"id": request_id, "result": {"stopReason": "end_turn"}})
        update(sid, "out of turn")
        return
    elif text == "permission":
        reply = ask(
            "session/request_permission",
            {
                "sessionId": sid,
                "toolCall": {"toolCallId": "call_1"},
                "options": [
                    {"optionId": "allow-once", "name": "allow", "kind": "allow_once"},
                    {
                        "optionId": "reject-once",
                        "name": "reject",
                        "kind": "reject_once",
                    },
                ],
            },
        )
        update(sid, json.dumps(reply.get("result")))
    elif text == "no-reject-option":
        reply = ask(
            "session/request_permission",
            {
                "sessionId": sid,
                "toolCall": {"toolCallId": "call_2"},
                "options": [
                    {"optionId": "allow-once", "name": "allow", "kind": "allow_once"}
                ],
            },
        )
        update(sid, json.dumps(reply.get("result")))
    elif text == "requests":
        codes = []
        for method in ("fs/read_text_file", "terminal/create", "x/unknown"):
            reply = ask(method, {"sessionId": sid, "path": "/etc/passwd"})
            codes.append(reply.get("error", {}).get("code"))
        update(sid, json.dumps(codes))
    elif text == "garbage":
        raw("{not json secret-garbage\n")
        raw("[1, 2, 3]\n")
        raw('{"secret-oversize": "' + "x" * 4096 + '"}\n')
        raw('{"jsonrpc": "2.0", "id": 99999, "result": {}}\n')
        update(sid, "survived")
    elif text == "crash":
        update(sid, "partial")
        os._exit(3)
    elif text == "hold":
        held = request_id
        return
    elif text == "spawn":
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal, time\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "time.sleep(120)\n",
            ]
        )
        update(sid, str(child.pid))
    elif text == "deep":
        raw("[" * 200000 + "\n")
        update(sid, "survived")
    elif text == "orphan":
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal, time\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "time.sleep(120)\n",
            ]
        )
        os._exit(5)
    elif text == "bad-permission":
        reply = ask(
            "session/request_permission",
            {"sessionId": sid, "toolCall": {"toolCallId": "c"}, "options": 5},
        )
        update(sid, json.dumps(reply.get("error", {}).get("code")))
    elif text == "evil":
        send({"method": "evil\nforged-notification", "params": {}})
        reply = ask("evil\nforged-request", {})
        update(sid, json.dumps(reply.get("error", {}).get("code")))
        send({"id": request_id, "result": {"stopReason": "end_turn\nforged-stop"}})
        return
    elif text == "error":
        send({"id": request_id, "error": {"code": -32000, "message": "boom"}})
        return
    send({"id": request_id, "result": {"stopReason": "end_turn"}})


def handle(message):
    global held
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    if method is None:
        return
    if method == "initialize":
        result = {
            "protocolVersion": params.get("protocolVersion"),
            "agentCapabilities": {},
        }
        if "--v2" in sys.argv:
            result["protocolVersion"] = 2
        if not bare:
            result["agentCapabilities"] = {
                "loadSession": True,
                "sessionCapabilities": {"resume": {}, "close": {}},
            }
            result["_meta"] = {"steering": {"supported": True}}
        send({"id": request_id, "result": result})
    elif method == "session/new":
        send({"id": request_id, "result": {"sessionId": "s1"}})
    elif method == "session/load":
        update(params["sessionId"], "replay one")
        update(params["sessionId"], "replay two")
        send({"id": request_id, "result": {}})
    elif method in ("session/resume", "session/close"):
        send({"id": request_id, "result": {}})
    elif method == "session/set_mode":
        if params.get("modeId") == "bad":
            send({"id": request_id, "error": {"code": -32602, "message": "bad mode"}})
        else:
            send({"id": request_id, "result": {}})
    elif method == "session/prompt":
        prompt(request_id, params)
    elif method == "session/cancel":
        if held is not None:
            send({"id": held, "result": {"stopReason": "cancelled"}})
            held = None
    elif method == "_session/steering" and not bare:
        if held is not None:
            send({"id": request_id, "result": {"outcome": "injected"}})
            update(params["sessionId"], "steered")
            send({"id": held, "result": {"stopReason": "end_turn"}})
            held = None
        elif params.get("_meta", {}).get("steering", {}).get("idleBehavior"):
            result = {"outcome": "promptRequired", "reason": "noRunningTurn"}
            send({"id": request_id, "result": result})
        else:
            send({"id": request_id, "result": {"outcome": "startedNewTurn"}})
    elif request_id is not None:
        send({"id": request_id, "error": {"code": -32601, "message": "not found"}})


while True:
    handle(read())
