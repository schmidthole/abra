"""fake acp agent for resident runtime tests, driven by message text keywords.

usage: fake_resident_agent.py CONFIG
CONFIG is a json file: {"log": path, "steering": bool, "steer_outcome": str,
"advertise": bool, "resume": bool, "fail_resume": bool, "modes": [ids], "wake": bool}. every message
read from stdin is appended to the log as one json line; tests assert on it.

keywords in a message's text decide the turn: "do-reply" answers every work id
through the bridge, "do-silent" streams free text only, "do-hold" keeps the prompt
open until steering or cancel, "do-slow" sleeps first, "do-fail" errors,
"do-refuse" refuses, "do-crash" exits, "do-permission" asks for the reply tool and
for bash, "do-shim" replies through a spawned mcp_bridge.py, "do-background"
starts background work that finishes later (and wakes itself when config wake is
set).
"""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "triggers"))

import mcp_bridge  # noqa: E402

config = json.loads(Path(sys.argv[1]).read_text())
lock = threading.Lock()
held = None
servers = []
next_id = 1000
answers = {}
answered = threading.Condition()


def send(message):
    message["jsonrpc"] = "2.0"
    with lock:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()


def record(entry):
    with open(config["log"], "a") as handle:
        handle.write(json.dumps(entry) + "\n")


def update(sid, kind, **fields):
    fields["sessionUpdate"] = kind
    send({"method": "session/update", "params": {"sessionId": sid, "update": fields}})


def chunk(sid, text):
    update(sid, "agent_message_chunk", content={"type": "text", "text": text})


def ask(method, params):
    global next_id
    with answered:
        next_id += 1
        request_id = next_id
    send({"id": request_id, "method": method, "params": params})
    with answered:
        answered.wait_for(lambda: request_id in answers, 10)
        return answers.pop(request_id, None)


def bridge():
    entry = next(s for s in servers if s["name"] == "abra")
    return {e["name"]: e["value"] for e in entry["env"]}, entry


def reply(work_id, text):
    env, _ = bridge()
    response = mcp_bridge.call(
        env[mcp_bridge.SOCKET_ENV],
        {
            "token": env[mcp_bridge.TOKEN_ENV],
            "op": "reply",
            "work_id": work_id,
            "text": text,
        },
    )
    record({"reply": work_id, "response": response})


def shim_reply(work_id, text):
    env, entry = bridge()
    environment = dict(os.environ)
    environment.update(env)
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "reply",
                "arguments": {"work_id": work_id, "text": text},
            },
        },
    ]
    result = subprocess.run(
        [entry["command"]] + entry["args"],
        input="".join(json.dumps(line) + "\n" for line in lines),
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    record({"shim": [json.loads(line) for line in result.stdout.splitlines()]})


def work_ids(text):
    return re.findall(r"^work id: (\S+)$", text, re.M)


def handle_turn(sid, text):
    """act on the keywords in text; returns the stop reason or an error."""
    if "do-crash" in text:
        os._exit(7)
    if "do-slow" in text:
        time.sleep(float(config.get("slow", 0.5)))
    if "do-permission" in text:
        outcomes = []
        reply_tool = "mcp__abra__reply"
        server = {"name": "abra", "source": "config"}
        for claude in (
            {"toolName": reply_tool, "mcpServer": server},
            {"toolName": "Bash"},
            {"toolName": reply_tool, "mcpServer": server, "parentToolUseId": "t0"},
            {"toolName": reply_tool, "mcpServer": {"name": "other"}},
        ):
            response = ask(
                "session/request_permission",
                {
                    "sessionId": sid,
                    "toolCall": {
                        "toolCallId": claude["toolName"],
                        "_meta": {"claudeCode": claude},
                    },
                    "options": [
                        {"optionId": "a1", "name": "allow", "kind": "allow_once"},
                        {"optionId": "a2", "name": "always", "kind": "allow_always"},
                        {"optionId": "r1", "name": "reject", "kind": "reject_once"},
                    ],
                },
            )
            outcomes.append(response["result"]["outcome"])
        record({"permission": outcomes})
    if "do-reply" in text:
        for work_id in work_ids(text):
            reply(work_id, "re " + work_id)
    if "do-shim" in text:
        for work_id in work_ids(text):
            shim_reply(work_id, "shim " + work_id)
    if "do-silent" in text:
        chunk(sid, "thinking")
        update(sid, "tool_call", toolCallId="t1", title="read", status="completed")
        chunk(sid, "free text ")
        chunk(sid, "answer")
    if "do-spawn" in text:
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal, time\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "time.sleep(120)\n",
            ]
        )
        record({"spawned": child.pid})
    if "do-background" in text:
        update(sid, "tool_call", toolCallId="bg1", title="agent", status="in_progress")
        threading.Thread(target=background, args=(sid,), daemon=True).start()
    if "do-fail" in text:
        return {"code": -32000, "message": "secret failure detail"}
    if "do-refuse" in text:
        return "refusal"
    if "do-cancel" in text:
        return "cancelled"
    return "end_turn"


def background(sid):
    time.sleep(float(config.get("background", 0.3)))
    update(sid, "tool_call_update", toolCallId="bg1", status="completed")
    if config.get("wake"):
        time.sleep(0.05)
        chunk(sid, "background finished by itself")


def finish(request_id, outcome):
    if isinstance(outcome, dict):
        send({"id": request_id, "error": outcome})
    else:
        send({"id": request_id, "result": {"stopReason": outcome}})


def prompt(request_id, params):
    global held
    sid = params["sessionId"]
    text = "".join(b.get("text", "") for b in params["prompt"])
    if "do-hold" in text and held is None:
        held = (request_id, sid, text)
        return
    finish(request_id, handle_turn(sid, text))


def session_result(sid):
    result = {"sessionId": sid}
    if config.get("modes"):
        result["modes"] = {
            "currentModeId": config["modes"][0],
            "availableModes": [{"id": m, "name": m} for m in config["modes"]],
        }
    return result


def handle(message):
    global held, servers
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    if method is None:
        with answered:
            answers[request_id] = message
            answered.notify_all()
        return
    if method == "initialize":
        capabilities = {}
        if config.get("resume", True):
            capabilities = {
                "loadSession": True,
                "sessionCapabilities": {"resume": {}, "close": {}},
            }
        result = {"protocolVersion": 1, "agentCapabilities": capabilities}
        if config.get("advertise", config.get("steering", True)):
            result["_meta"] = {"steering": {"supported": True}}
        send({"id": request_id, "result": result})
    elif method == "session/new":
        servers = params["mcpServers"]
        update("s-new", "available_commands_update", availableCommands=[])
        send({"id": request_id, "result": session_result("s-" + str(os.getpid()))})
    elif method in ("session/resume", "session/load"):
        servers = params["mcpServers"]
        if config.get("fail_resume"):
            send({"id": request_id, "error": {"code": -32002, "message": "gone"}})
        else:
            if method == "session/load":
                chunk(params["sessionId"], "replayed history")
            send({"id": request_id, "result": session_result(params["sessionId"])})
    elif method in ("session/set_mode", "session/close"):
        send({"id": request_id, "result": {}})
        if method == "session/close" and held is not None:
            finish(held[0], "cancelled")
            held = None
    elif method == "session/prompt":
        threading.Thread(target=prompt, args=(request_id, params)).start()
    elif method == "session/cancel":
        if held is not None:
            finish(held[0], "cancelled")
            held = None
    elif method == "_session/steering" and config.get("steering", True):
        forced = config.get("steer_outcome")
        if forced:
            send({"id": request_id, "result": {"outcome": forced}})
        elif held is not None:
            send({"id": request_id, "result": {"outcome": "injected"}})
            request, sid, text = held
            held = None
            steered = "".join(b.get("text", "") for b in params["prompt"])
            finish(request, handle_turn(sid, text + steered))
        else:
            send(
                {
                    "id": request_id,
                    "result": {"outcome": "promptRequired", "reason": "noRunningTurn"},
                }
            )
    elif request_id is not None:
        send({"id": request_id, "error": {"code": -32601, "message": "not found"}})


for line in sys.stdin:
    message = json.loads(line)
    record(message)
    handle(message)
