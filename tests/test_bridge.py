"""exercise the mcp bridge shim and the runtime's reply handler over a unix socket."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

TRIGGERS = Path(__file__).resolve().parents[1] / "triggers"
sys.path.insert(0, str(TRIGGERS))

import mcp_bridge  # noqa: E402
import runtime  # noqa: E402

TOKEN = "t" * 43


class Adapter:
    name = "test"

    def __init__(self):
        self.posts = []

    def reply(self, conv, text):
        self.posts.append((conv, text))

    def ack(self, conv, msg_id, state):
        pass

    def history(self, conv):
        return []


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "bin").mkdir()
        (self.root / "bin/abra").write_text("#!/bin/sh\n")
        (self.root / "bin/abra").chmod(0o755)
        self.private = self.root / "data/triggers"
        self.private.mkdir(parents=True, mode=0o700)
        self.adapter = Adapter()
        self.runtime = runtime.Runtime(self.adapter, self.root)
        self.runtime.convs["t:c1:1"] = dict(work_id="abra-aaaa", pending=[])
        self.runtime.convs["t:c2:1"] = dict(work_id="abra-bbbb", pending=[])
        self.path = str(self.private / "bridge.sock")
        self.server = mcp_bridge.Server(self.path, TOKEN, self.runtime.bridge)
        self.server.start()
        self.addCleanup(self.server.stop)

    def call(self, **fields):
        request = {"token": TOKEN, "op": "reply"}
        request.update(fields)
        return mcp_bridge.call(self.path, request)

    def test_socket_is_private(self):
        mode = os.lstat(self.path).st_mode
        self.assertTrue(stat.S_ISSOCK(mode))
        self.assertEqual(stat.S_IMODE(mode), 0o600)

    def test_refuses_public_directory(self):
        public = self.root / "public"
        public.mkdir(mode=0o755)
        public.chmod(0o755)
        server = mcp_bridge.Server(str(public / "b.sock"), TOKEN, self.runtime.bridge)
        with self.assertRaises(ValueError):
            server.start()

    def test_refuses_non_socket_path(self):
        other = self.private / "file.sock"
        other.write_text("x")
        server = mcp_bridge.Server(str(other), TOKEN, self.runtime.bridge)
        with self.assertRaises(ValueError):
            server.start()
        self.assertTrue(other.is_file())

    def test_valid_reply_posts_to_owning_conversation(self):
        with self.assertLogs("abra.triggers", "INFO") as logs:
            response = self.call(
                work_id="abra-bbbb", text="secret status", tool_use_id="toolu_01"
            )
        self.assertEqual(response, {"ok": True})
        self.assertEqual(self.adapter.posts, [("t:c2:1", "secret status")])
        self.assertIn("t:c2:1", self.runtime.replied)
        text = "\n".join(logs.output)
        self.assertIn("abra-bbbb", text)
        self.assertIn("toolu_01", text)
        self.assertNotIn("secret", text)
        self.assertNotIn(TOKEN, text)

    def test_unknown_and_invalid_work_ids(self):
        self.assertEqual(
            self.call(work_id="abra-zzzz", text="hi"),
            {"ok": False, "error": "unknown work id"},
        )
        for bad in ("../x", "ABRA", "", 7, None):
            response = self.call(work_id=bad, text="hi")
            self.assertEqual(response, {"ok": False, "error": "invalid work id"})
        self.assertEqual(self.adapter.posts, [])

    def test_bad_or_missing_token(self):
        with self.assertLogs("abra.bridge", "WARNING"):
            response = mcp_bridge.call(
                self.path, {"token": "wrong", "op": "reply", "work_id": "abra-aaaa"}
            )
        self.assertEqual(response, {"ok": False, "error": "unauthorized"})
        response = mcp_bridge.call(self.path, {"op": "reply", "work_id": "abra-aaaa"})
        self.assertEqual(response, {"ok": False, "error": "unauthorized"})
        self.assertEqual(self.adapter.posts, [])

    def test_text_limits(self):
        oversize = "x" * (runtime.MAX_TEXT + 1)
        self.assertFalse(self.call(work_id="abra-aaaa", text=oversize)["ok"])
        self.assertFalse(self.call(work_id="abra-aaaa", text="  ")["ok"])
        self.assertFalse(self.call(work_id="abra-aaaa", text=["x"])["ok"])
        self.assertFalse(self.call(work_id="abra-aaaa", text="\ud800")["ok"])
        self.assertEqual(self.adapter.posts, [])

    def test_unknown_op_and_malformed_requests(self):
        self.assertEqual(self.call(op="post")["error"], "unknown op")
        for raw in (b"not json\n", b"[1]\n"):
            with mcp_bridge.socket.socket(mcp_bridge.socket.AF_UNIX) as sock:
                sock.connect(self.path)
                sock.sendall(raw)
                self.assertIn(b"invalid request", mcp_bridge.read_line(sock, 4096))

    def test_rate_limit_per_conversation(self):
        for _ in range(runtime.REPLY_LIMIT):
            self.assertTrue(self.call(work_id="abra-aaaa", text="hi")["ok"])
        limited = self.call(work_id="abra-aaaa", text="hi")
        self.assertEqual(limited["ok"], False)
        self.assertIn("rate limited", limited["error"])
        self.assertTrue(self.call(work_id="abra-bbbb", text="hi")["ok"])

    def shim(self, lines, env=None):
        environment = dict(os.environ)
        environment.update(
            {mcp_bridge.SOCKET_ENV: self.path, mcp_bridge.TOKEN_ENV: TOKEN}
        )
        environment.update(env or {})
        result = subprocess.run(
            [sys.executable, str(TRIGGERS / "mcp_bridge.py")],
            input="".join(line + "\n" for line in lines),
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result, [json.loads(line) for line in result.stdout.splitlines()]

    def test_shim_speaks_mcp_and_relays_reply(self):
        call = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "reply",
                "arguments": {"work_id": "abra-aaaa", "text": "done"},
                "_meta": {"claudecode/toolUseId": "toolu_9"},
            },
        }
        lines = [
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
                }
            ),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            json.dumps(call),
        ]
        result, replies = self.shim(lines)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(replies[0]["result"]["capabilities"], {"tools": {}})
        tools = replies[1]["result"]["tools"]
        self.assertEqual([tool["name"] for tool in tools], ["reply"])
        self.assertEqual(
            sorted(tools[0]["inputSchema"]["properties"]), ["text", "work_id"]
        )
        self.assertEqual(replies[2]["result"]["isError"], False)
        self.assertEqual(self.adapter.posts, [("t:c1:1", "done")])

    def test_shim_rejects_malformed_input(self):
        def tool(arguments, name="reply"):
            return json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                }
            )

        lines = [
            "not json",
            "[1]",
            "x" * (mcp_bridge.MAX_LINE + 10),
            json.dumps({"jsonrpc": "2.0", "id": 4, "method": "resources/list"}),
            tool({"work_id": "abra-aaaa", "text": "x", "channel": "C1"}),
            tool({"work_id": "abra-aaaa", "text": "x"}, name="post"),
            tool({"work_id": "abra-zzzz", "text": "x"}),
        ]
        result, replies = self.shim(lines)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(replies[0]["error"]["code"], -32601)
        self.assertTrue(all(reply["result"]["isError"] for reply in replies[1:]))
        self.assertIn("unknown work id", replies[3]["result"]["content"][0]["text"])
        self.assertEqual(self.adapter.posts, [])
        self.assertNotIn("x" * 100, result.stderr)

    def test_shim_with_wrong_token_or_no_socket(self):
        call = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "reply",
                    "arguments": {"work_id": "abra-aaaa", "text": "x"},
                },
            }
        )
        _, replies = self.shim([call], {mcp_bridge.TOKEN_ENV: "wrong"})
        self.assertIn("unauthorized", replies[0]["result"]["content"][0]["text"])
        missing = str(self.private / "missing.sock")
        _, replies = self.shim([call], {mcp_bridge.SOCKET_ENV: missing})
        self.assertTrue(replies[0]["result"]["isError"])
        result, _ = self.shim([call], {mcp_bridge.TOKEN_ENV: ""})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.adapter.posts, [])


if __name__ == "__main__":
    unittest.main()
