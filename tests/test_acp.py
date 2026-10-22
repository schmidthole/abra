"""exercise the acp client against a fake stdlib acp agent."""

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "triggers"))

import acp  # noqa: E402

FAKE = str(TESTS / "fake_acp_agent.py")


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_for(predicate, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class AcpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.dir = Path(self.temporary.name)
        self.log = self.dir / "received.log"
        self.updates = []
        self.exits = []
        self.exited = threading.Event()

    def on_update(self, params):
        self.updates.append(params)

    def on_exit(self, code):
        self.exits.append(code)
        self.exited.set()

    def client(self, *flags, **options):
        options.setdefault("on_update", self.on_update)
        options.setdefault("on_exit", self.on_exit)
        options.setdefault("timeout", 10)
        options.setdefault("kill_timeout", 1)
        client = acp.Client(
            [sys.executable, FAKE, str(self.log)] + list(flags), **options
        )
        client.start()
        self.addCleanup(client.close)
        return client

    def session(self, *flags, **options):
        client = self.client(*flags, **options)
        client.initialize()
        return client, client.new_session(str(self.dir))["sessionId"]

    def received(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def texts(self):
        return [u["update"]["content"]["text"] for u in self.updates]

    def test_handshake_advertises_no_fs_or_terminal(self):
        client = self.client()
        result = client.initialize()
        self.assertEqual(result["protocolVersion"], 1)
        sent = self.received()[0]
        self.assertEqual(sent["method"], "initialize")
        self.assertEqual(sent["params"]["protocolVersion"], 1)
        self.assertEqual(
            sent["params"]["clientCapabilities"],
            {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
        )
        for name in ("load", "resume", "close", "steering"):
            self.assertTrue(client.supports(name))

    def test_unsupported_protocol_version_closes(self):
        client = self.client("--v2")
        with self.assertRaises(acp.ProtocolError):
            client.initialize()
        self.assertTrue(self.exited.wait(5))
        with self.assertRaises(acp.AgentExited):
            client.new_session(str(self.dir))

    def test_new_load_resume_close_and_mode(self):
        client, sid = self.session()
        self.assertEqual(sid, "s1")
        client.load_session(sid, str(self.dir), [{"name": "x", "command": "/bin/x"}])
        self.assertEqual(self.texts(), ["replay one", "replay two"])
        client.resume_session(sid, str(self.dir))
        self.assertEqual(len(self.updates), 2)
        client.set_mode(sid, "default")
        client.close_session(sid)
        sent = self.received()
        methods = [m["method"] for m in sent]
        self.assertEqual(
            methods,
            [
                "initialize",
                "session/new",
                "session/load",
                "session/resume",
                "session/set_mode",
                "session/close",
            ],
        )
        self.assertEqual(sent[2]["params"]["mcpServers"][0]["name"], "x")
        self.assertEqual(sent[3]["params"]["sessionId"], "s1")
        ids = [m["id"] for m in sent]
        self.assertEqual(ids, sorted(set(ids)))

    def test_unadvertised_methods_send_nothing(self):
        client, sid = self.session("--bare")
        for call in (
            lambda: client.load_session(sid, str(self.dir)),
            lambda: client.resume_session(sid, str(self.dir)),
            lambda: client.close_session(sid),
        ):
            with self.assertRaises(acp.Unsupported):
                call()
        self.assertEqual(len(self.received()), 2)

    def test_input_validation(self):
        with self.assertRaises(ValueError):
            acp.Client("claude-agent-acp")
        with self.assertRaises(ValueError):
            acp.Client([])
        with self.assertRaises(ValueError):
            acp.Client(["x"], max_line=0)
        client, sid = self.session()
        with self.assertRaises(ValueError):
            client.new_session("relative/dir")
        with self.assertRaises(ValueError):
            client.prompt(sid, [])
        with self.assertRaises(ValueError):
            client.prompt("", "hello")

    def test_remote_error_is_typed(self):
        client, sid = self.session()
        with self.assertRaises(acp.RemoteError) as caught:
            client.set_mode(sid, "bad")
        self.assertEqual(caught.exception.code, -32602)
        self.assertEqual(caught.exception.message, "bad mode")
        self.assertNotIsInstance(caught.exception, acp.MethodNotFound)
        with self.assertRaises(acp.RemoteError) as caught:
            client.prompt(sid, "error")
        self.assertEqual(caught.exception.code, -32000)

    def test_prompt_streams_updates_before_returning(self):
        client, sid = self.session()
        self.assertEqual(client.prompt(sid, "hello"), "end_turn")
        self.assertEqual(self.texts(), ["alpha", "beta"])
        self.assertEqual(self.updates[0]["sessionId"], "s1")

    def test_update_outside_prompt_turn(self):
        client, sid = self.session()
        self.assertEqual(client.prompt(sid, "later"), "end_turn")
        self.assertTrue(wait_for(lambda: self.texts() == ["out of turn"]))

    def test_steering_injected_while_prompt_runs(self):
        client, sid = self.session()
        results = []
        thread = threading.Thread(
            target=lambda: results.append(client.prompt(sid, "hold"))
        )
        thread.start()
        self.assertTrue(
            wait_for(
                lambda: any(
                    m.get("method") == "session/prompt" for m in self.received()
                )
            )
        )
        self.assertEqual(client.steer(sid, "more"), "injected")
        thread.join(10)
        self.assertEqual(results, ["end_turn"])
        self.assertIn("steered", self.texts())
        steer = [m for m in self.received() if m["method"] == "_session/steering"][0]
        self.assertEqual(
            steer["params"]["_meta"], {"steering": {"idleBehavior": "promptRequired"}}
        )

    def test_steering_prompt_required_when_idle(self):
        client, sid = self.session()
        self.assertEqual(client.steer(sid, "more"), "promptRequired")
        self.assertEqual(
            client.steer(sid, "more", prompt_required=False), "startedNewTurn"
        )

    def test_steering_unsupported_raises_method_not_found(self):
        client, sid = self.session("--bare")
        self.assertFalse(client.supports("steering"))
        with self.assertRaises(acp.MethodNotFound) as caught:
            client.steer(sid, "more")
        self.assertEqual(caught.exception.code, -32601)

    def test_cancel_ends_held_prompt(self):
        client, sid = self.session()
        results = []
        thread = threading.Thread(
            target=lambda: results.append(client.prompt(sid, "hold"))
        )
        thread.start()
        self.assertTrue(
            wait_for(
                lambda: any(
                    m.get("method") == "session/prompt" for m in self.received()
                )
            )
        )
        client.cancel(sid)
        thread.join(10)
        self.assertEqual(results, ["cancelled"])
        self.assertNotIn("id", self.received()[-1])

    def outcome(self, text="permission", **options):
        client, sid = self.session(**options)
        client.prompt(sid, text)
        return json.loads(self.texts()[-1])

    def test_permission_default_rejects(self):
        self.assertEqual(
            self.outcome(),
            {"outcome": {"outcome": "selected", "optionId": "reject-once"}},
        )

    def test_permission_policy_allows(self):
        seen = []

        def policy(params):
            seen.append(params["toolCall"]["toolCallId"])
            return "allow-once"

        self.assertEqual(
            self.outcome(permission=policy),
            {"outcome": {"outcome": "selected", "optionId": "allow-once"}},
        )
        self.assertEqual(seen, ["call_1"])

    def test_permission_invalid_choice_rejects(self):
        self.assertEqual(
            self.outcome(permission=lambda params: "not-offered"),
            {"outcome": {"outcome": "selected", "optionId": "reject-once"}},
        )

    def test_permission_policy_exception_rejects(self):
        def policy(params):
            raise RuntimeError("secret-policy-detail")

        with self.assertLogs("abra.acp", "INFO") as logs:
            outcome = self.outcome(permission=policy)
        self.assertEqual(
            outcome, {"outcome": {"outcome": "selected", "optionId": "reject-once"}}
        )
        text = "\n".join(logs.output)
        self.assertIn("permission policy failed (RuntimeError)", text)
        self.assertNotIn("secret-policy-detail", text)

    def test_permission_without_reject_option_cancels(self):
        self.assertEqual(
            self.outcome("no-reject-option", permission=lambda params: None),
            {"outcome": {"outcome": "cancelled"}},
        )

    def test_agent_requests_get_method_not_found(self):
        client, sid = self.session()
        client.prompt(sid, "requests")
        self.assertEqual(json.loads(self.texts()[-1]), [-32601, -32601, -32601])

    def test_malformed_and_oversize_lines_are_dropped(self):
        client, sid = self.session(max_line=1024)
        with self.assertLogs("abra.acp", "INFO") as logs:
            self.assertEqual(client.prompt(sid, "garbage"), "end_turn")
        self.assertEqual(self.texts(), ["survived"])
        text = "\n".join(logs.output)
        self.assertIn("dropped invalid line (JSONDecodeError)", text)
        self.assertIn("dropped non-object line (list)", text)
        self.assertIn("dropped oversize line", text)
        self.assertIn("dropped response for unknown id", text)
        self.assertNotIn("secret", text)

    def test_logs_never_contain_prompt_or_update_text(self):
        client, sid = self.session()
        with self.assertLogs("abra.acp", "DEBUG") as logs:
            client.prompt(sid, "hello")
        text = "\n".join(logs.output)
        self.assertIn("sent session/prompt id", text)
        self.assertNotIn("hello", text)
        self.assertNotIn("alpha", text)

    def test_crash_mid_prompt_fails_pending_and_signals_exit(self):
        client, sid = self.session()
        with self.assertRaises(acp.AgentExited):
            client.prompt(sid, "crash")
        self.assertTrue(self.exited.wait(5))
        self.assertEqual(self.exits, [3])
        self.assertEqual(self.texts(), ["partial"])
        with self.assertRaises(acp.AgentExited):
            client.prompt(sid, "hello")
        with self.assertRaises(acp.AgentExited):
            client.cancel(sid)

    def test_close_kills_process_group_including_grandchild(self):
        client, sid = self.session("--stubborn")
        client.prompt(sid, "spawn")
        grandchild = int(self.texts()[-1])
        agent = client.proc.pid
        self.assertTrue(alive(grandchild))
        self.assertEqual(os.getpgid(grandchild), agent)
        client.close()
        self.assertEqual(client.proc.returncode, -9)
        self.assertTrue(wait_for(lambda: not alive(grandchild)))
        self.assertTrue(self.exited.wait(5))
        self.assertEqual(len(self.received()), 3)
        with self.assertRaises(acp.AgentExited):
            client.prompt(sid, "hello")

    def test_close_while_prompt_blocks(self):
        client, sid = self.session()
        errors = []

        def run():
            try:
                client.prompt(sid, "hold")
            except acp.AgentExited as exc:
                errors.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(
            wait_for(
                lambda: any(
                    m.get("method") == "session/prompt" for m in self.received()
                )
            )
        )
        client.close()
        thread.join(10)
        self.assertEqual(len(errors), 1)

    def test_callback_failures_do_not_stop_the_client(self):
        def broken(params):
            raise ValueError("secret-callback")

        client, sid = self.session(on_update=broken)
        with self.assertLogs("abra.acp", "INFO") as logs:
            self.assertEqual(client.prompt(sid, "hello"), "end_turn")
        text = "\n".join(logs.output)
        self.assertIn("update callback failed (ValueError)", text)
        self.assertNotIn("secret-callback", text)


if __name__ == "__main__":
    unittest.main()
