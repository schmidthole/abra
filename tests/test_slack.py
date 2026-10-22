"""exercise the slack adapter with a fake slack client and a stub bin/abra."""

import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from test_triggers import STUB, TRIGGERS

import runtime  # noqa: E402
import slack  # noqa: E402


class ApiError(Exception):
    """shaped like slack_sdk's slackapierror: a response dict with an error code."""

    def __init__(self, code):
        super().__init__("api failure while posting secret words xoxb-leaked-token")
        self.response = {"ok": False, "error": code}


class FakeClient:
    def __init__(self, pages=None):
        self.calls = []
        self.failures = {}
        self.pages = pages or {}
        self.lock = threading.Lock()

    def _record(self, method, fields):
        with self.lock:
            self.calls.append((method, fields))
            codes = self.failures.get(method)
            if codes:
                raise ApiError(codes.pop(0))

    def auth_test(self):
        self._record("auth_test", {})
        return {"ok": True, "user_id": "UBOT", "bot_id": "BBOT"}

    def chat_postMessage(self, **fields):
        self._record("chat_postMessage", fields)
        return {"ok": True, "ts": "999.1"}

    def reactions_add(self, **fields):
        self._record("reactions_add", fields)
        return {"ok": True}

    def reactions_remove(self, **fields):
        self._record("reactions_remove", fields)
        return {"ok": True}

    def conversations_replies(self, **fields):
        self._record("conversations_replies", fields)
        return self.pages[fields.get("cursor")]

    def made(self, method):
        with self.lock:
            return [fields for name, fields in self.calls if name == method]


def mention(text="<@UBOT> please help", ts="100.1", **fields):
    event = {"type": "app_mention", "channel": "C1", "user": "U1", "text": text}
    event.update(ts=ts, **fields)
    return event


def message(text="more context", ts="100.2", thread_ts="100.1", **fields):
    event = {
        "type": "message",
        "channel": "C1",
        "channel_type": "channel",
        "user": "U2",
        "text": text,
        "ts": ts,
        "thread_ts": thread_ts,
    }
    event.update(fields)
    return {k: v for k, v in event.items() if v is not None}


class SlackAdapterTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.adapter = slack.SlackAdapter(self.client, "abra")
        self.adapter.identify()

    def test_identify_uses_bot_user_id_and_fails_closed(self):
        self.assertEqual((self.adapter.user_id, self.adapter.bot_id), ("UBOT", "BBOT"))
        self.client.failures["auth_test"] = ["invalid_auth"]
        with self.assertRaises(ValueError):
            slack.SlackAdapter(self.client, "abra").identify()

    def test_top_level_mention_starts_conversation(self):
        event = self.adapter.intake(mention(), True)
        self.assertEqual(
            event,
            runtime.Event(
                "start", "slack:C1:100.1", "100.1", "U1", "@abra please help"
            ),
        )

    def test_mention_inside_existing_thread_uses_thread_ts(self):
        event = self.adapter.intake(mention(ts="100.5", thread_ts="100.1"), True)
        self.assertEqual(
            (event.kind, event.conv, event.msg_id), ("start", "slack:C1:100.1", "100.5")
        )

    def test_thread_reply_is_message_from_anybody(self):
        event = self.adapter.intake(message(), False)
        self.assertEqual(
            event,
            runtime.Event("message", "slack:C1:100.1", "100.2", "U2", "more context"),
        )
        private = self.adapter.intake(
            message(channel="G1", channel_type="group"), False
        )
        self.assertEqual(private.conv, "slack:G1:100.1")
        broadcast = self.adapter.intake(message(subtype="thread_broadcast"), False)
        self.assertEqual(broadcast.kind, "message")

    def test_ignored_events(self):
        cases = [
            message(thread_ts=None),
            message(thread_ts="100.2"),
            message(text="hey <@UBOT> look"),
            message(user="UBOT"),
            message(bot_id="BBOT"),
            message(bot_id="BOTHER", user="U9"),
            message(subtype="bot_message"),
            message(subtype="message_changed"),
            message(subtype="message_deleted"),
            message(subtype="channel_join"),
            message(text="   "),
            message(text=None),
            message(channel_type="im"),
            message(channel="D1"),
            message(channel="C1; rm"),
            message(ts="../1"),
            message(thread_ts="x"),
            message(user=None),
            "not a dict",
        ]
        with self.assertLogs("abra.triggers", level="INFO") as logs:
            for case in cases:
                self.assertIsNone(self.adapter.intake(case, False), case)
            self.assertIsNone(self.adapter.intake(mention(user="UBOT"), True))
            self.assertIsNone(self.adapter.intake(mention(bot_id="BX"), True))
            self.assertIsNone(
                self.adapter.intake(mention(subtype="message_changed"), True)
            )
        output = "\n".join(logs.output)
        self.assertNotIn("look", output)
        self.assertNotIn("help", output)
        self.assertIn("top-level message", output)
        self.assertIn("mention handled by app_mention", output)

    def test_mention_rewrite_uses_id_not_display_name(self):
        text = "<@UBOT> and <@UBOT|abra> but not <@U1> or @abra"
        self.assertEqual(
            self.adapter.intake(mention(text), True).text,
            "@abra and @abra but not <@U1> or @abra",
        )
        named = slack.SlackAdapter(self.client, "Helper Bot")
        named.identify()
        self.assertEqual(named.intake(mention(), True).text, "@Helper Bot please help")

    def test_reply_posts_in_thread_and_chunks_on_newlines(self):
        lines = ["line " + str(i) + " " + "x" * 90 for i in range(100)]
        text = "\n".join(lines)
        self.adapter.reply("slack:C1:100.1", text)
        posts = self.client.made("chat_postMessage")
        self.assertGreater(len(posts), 1)
        for post in posts:
            self.assertEqual((post["channel"], post["thread_ts"]), ("C1", "100.1"))
            self.assertLessEqual(len(post["text"]), 3900)
            self.assertTrue(post["text"].startswith("line "))
            self.assertTrue(post["text"].endswith("x"))
        self.assertEqual("\n".join(p["text"] for p in posts), text)
        self.assertEqual([len(c) for c in slack.chunks("y" * 8000)], [3900, 3900, 200])
        self.assertEqual(slack.chunks("short"), ["short"])

    def test_reply_stops_and_logs_code_only_on_api_error(self):
        self.client.failures["chat_postMessage"] = ["channel_not_found"]
        with self.assertLogs("abra.triggers", level="WARNING") as logs:
            self.adapter.reply("slack:C1:100.1", "secret words\n" + "z" * 5000)
        self.assertEqual(len(self.client.made("chat_postMessage")), 1)
        output = "\n".join(logs.output)
        self.assertIn("channel_not_found", output)
        self.assertNotIn("secret", output)
        self.assertNotIn("xoxb", output)
        with self.assertRaises(ValueError):
            self.adapter.reply("other:C1:1", "x")

    def test_ack_replaces_previous_marker(self):
        self.adapter.intake(message(), False)
        conv = "slack:C1:100.1"
        self.adapter.ack(conv, "100.2", "queued")
        self.assertEqual(self.client.made("reactions_remove"), [])
        self.adapter.ack(conv, "100.2", "running")
        self.adapter.ack(conv, "100.2", "done")
        added = [f["name"] for f in self.client.made("reactions_add")]
        removed = [f["name"] for f in self.client.made("reactions_remove")]
        self.assertEqual(added, ["hourglass_flowing_sand", "eyes", "white_check_mark"])
        self.assertEqual(removed, ["hourglass_flowing_sand", "eyes"])
        for fields in self.client.made("reactions_add"):
            self.assertEqual((fields["channel"], fields["timestamp"]), ("C1", "100.2"))
        self.adapter.ack(conv, "100.2", "done")
        self.assertEqual(len(self.client.made("reactions_add")), 3)

    def test_ack_on_unknown_message_clears_every_other_marker(self):
        self.adapter.ack("slack:C1:100.1", "100.9", "failed")
        self.assertEqual([f["name"] for f in self.client.made("reactions_add")], ["x"])
        self.assertEqual(
            sorted(f["name"] for f in self.client.made("reactions_remove")),
            ["eyes", "hourglass_flowing_sand", "white_check_mark"],
        )

    def test_ack_tolerates_reaction_errors_and_logs_others_by_code(self):
        self.client.failures["reactions_add"] = ["already_reacted", "ratelimited"]
        self.client.failures["reactions_remove"] = ["no_reaction"]
        with self.assertLogs("abra.triggers", level="WARNING") as logs:
            self.adapter.ack("slack:C1:100.1", "100.9", "queued")
            self.adapter.ack("slack:C1:100.1", "100.9", "running")
        output = "\n".join(logs.output)
        self.assertNotIn("already_reacted", output)
        self.assertNotIn("no_reaction", output)
        self.assertIn("slack reactions_add failed: ratelimited", output)
        self.assertNotIn("secret", output)

    def test_history_paginates_orders_and_maps_senders(self):
        self.client.pages = {
            None: {
                "messages": [
                    {"ts": "101.000001", "user": "U2", "text": "later"},
                    {"ts": "100.1", "user": "U1", "text": "<@UBOT> start"},
                ],
                "response_metadata": {"next_cursor": "page2"},
            },
            "page2": {
                "messages": [
                    {
                        "ts": "100.3",
                        "user": "UBOT",
                        "bot_id": "BBOT",
                        "text": "abra is on it.",
                    },
                    {
                        "ts": "100.4",
                        "bot_id": "BOTHER",
                        "subtype": "bot_message",
                        "text": "noise",
                    },
                    {
                        "ts": "100.5",
                        "user": "U9",
                        "bot_id": "BOTHER",
                        "text": "app post",
                    },
                    {
                        "ts": "100.6",
                        "user": "U2",
                        "subtype": "channel_join",
                        "text": "joined",
                    },
                    {"ts": "100.7", "user": "U2", "text": ""},
                    {"ts": "bad", "user": "U2", "text": "bad ts"},
                    "junk",
                ],
                "response_metadata": {"next_cursor": ""},
            },
        }
        history = self.adapter.history("slack:C1:100.1")
        self.assertEqual(
            history,
            [
                runtime.Message("100.1", "U1", "@abra start"),
                runtime.Message("100.3", "abra", "abra is on it."),
                runtime.Message("101.000001", "U2", "later"),
            ],
        )
        calls = self.client.made("conversations_replies")
        self.assertEqual([c.get("cursor") for c in calls], [None, "page2"])
        self.assertEqual((calls[0]["channel"], calls[0]["ts"]), ("C1", "100.1"))

    def test_history_api_error_returns_empty_and_logs_code(self):
        self.client.failures["conversations_replies"] = ["missing_scope"]
        with self.assertLogs("abra.triggers", level="WARNING") as logs:
            self.assertEqual(self.adapter.history("slack:C1:100.1"), [])
        self.assertIn("missing_scope", "\n".join(logs.output))
        self.assertNotIn("secret", "\n".join(logs.output))

    def test_error_code_falls_back_to_type(self):
        self.assertEqual(slack.error_code(ApiError("not_in_channel")), "not_in_channel")
        self.assertEqual(slack.error_code(ApiError("Has Spaces and text")), "ApiError")
        self.assertEqual(slack.error_code(OSError("secret")), "OSError")

    def test_redact_masks_tokens_and_drops_tracebacks(self):
        import logging

        record = logging.LogRecord(
            "slack_sdk",
            logging.WARNING,
            "",
            0,
            "url %s",
            ("wss://x/?ticket=abc&app_id=1",),
            None,
        )
        try:
            raise ValueError("xoxb-123-456")
        except ValueError:
            record.exc_info = sys.exc_info()
        slack.Redact().filter(record)
        self.assertEqual(record.getMessage(), "url wss://x/?[redacted]&app_id=1")
        self.assertIsNone(record.exc_info)


class FakeApp:
    def __init__(self, client):
        self.client = client
        self.listeners = {}

    def event(self, name):
        def register(function):
            self.listeners[name] = function
            return function

        return register


class FakeSocket:
    def __init__(self, test, app):
        self.test = test
        self.app = app
        self.closed = False

    def connect(self):
        threading.Thread(target=self.test.drive, args=(self.app,), daemon=True).start()

    def close(self):
        self.closed = True


class SlackMainTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "home"
        (self.root / "bin").mkdir(parents=True)
        stub = self.root / "bin/abra"
        stub.write_text("#!" + sys.executable + "\n" + STUB)
        stub.chmod(0o755)
        (self.root / "stub.json").write_text(json.dumps({}))
        self.env = {
            "SLACK_BOT_TOKEN": "xoxb-1111-supersecretbot",
            "SLACK_APP_TOKEN": "xapp-1-supersecretapp",
        }

    def run_main(self, env, *extra):
        argv = [sys.executable, str(TRIGGERS / "slack.py"), "--root", str(self.root)]
        clean = {k: v for k, v in os.environ.items() if not k.startswith("SLACK_")}
        clean.update(env)
        return subprocess.run(
            argv + list(extra), env=clean, capture_output=True, text=True, timeout=30
        )

    def test_missing_or_invalid_tokens_exit_1_without_values(self):
        cases = [
            ({}, "slack_bot_token is not set"),
            (
                {"SLACK_BOT_TOKEN": self.env["SLACK_BOT_TOKEN"]},
                "slack_app_token is not set",
            ),
            (
                {"SLACK_BOT_TOKEN": "xapp-wrong-supersecret", "SLACK_APP_TOKEN": "x"},
                "slack_bot_token is not a valid xoxb- token",
            ),
            (
                {
                    "SLACK_BOT_TOKEN": self.env["SLACK_BOT_TOKEN"],
                    "SLACK_APP_TOKEN": "xoxb-supersecret",
                },
                "slack_app_token is not a valid xapp- token",
            ),
        ]
        for env, expected in cases:
            result = self.run_main(env)
            self.assertEqual(result.returncode, 1, env)
            self.assertIn(expected, result.stderr)
            self.assertNotIn("supersecret", result.stderr + result.stdout)
            self.assertNotIn("Traceback", result.stderr)

    @unittest.skipIf(importlib.util.find_spec("slack_bolt"), "slack_bolt is installed")
    def test_missing_slack_bolt_exits_1(self):
        result = self.run_main(self.env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("slack_bolt is not installed", result.stderr)
        self.assertNotIn("supersecret", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_bad_root_exits_1_before_connecting(self):
        result = self.run_main(self.env, "--root", str(self.root / "missing"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("root is not a directory", result.stderr)

    def drive(self, app):
        """socket thread: deliver events, wait for the turn, then send sigterm."""
        try:
            app.listeners["app_mention"](event=mention("<@UBOT> private words"))
            app.listeners["message"](event=message("hey <@UBOT> again", ts="100.3"))
            app.listeners["message"](event=message("top", ts="200.1", thread_ts=None))
            app.listeners["message"](event="garbage")
            deadline = time.time() + 20
            while time.time() < deadline:
                texts = [p["text"] for p in self.client.made("chat_postMessage")]
                if "result 1" in texts:
                    break
                time.sleep(0.05)
        finally:
            os.kill(os.getpid(), signal.SIGTERM)

    def test_main_end_to_end_with_fake_bolt(self):
        self.client = FakeClient()
        made = {}

        def connect(bot_token, app_token):
            self.assertEqual(
                (bot_token, app_token),
                (self.env["SLACK_BOT_TOKEN"], self.env["SLACK_APP_TOKEN"]),
            )
            made["app"] = FakeApp(self.client)
            made["socket"] = FakeSocket(self, made["app"])
            return made["app"], made["socket"]

        argv = ["--root", str(self.root), "--name", "helper"]
        with self.assertLogs("abra.triggers", level="INFO") as logs:
            code = slack.main(argv, self.env, connect)
        self.assertEqual(code, 0)
        self.assertTrue(made["socket"].closed)
        posts = self.client.made("chat_postMessage")
        self.assertTrue(
            posts[0]["text"].startswith(
                "helper is on it. this thread is now work item helper-"
            )
        )
        self.assertEqual([p["thread_ts"] for p in posts], ["100.1", "100.1"])
        self.assertEqual(posts[-1]["text"], "result 1")
        added = [f["name"] for f in self.client.made("reactions_add")]
        self.assertEqual(added, ["hourglass_flowing_sand", "eyes", "white_check_mark"])
        runs = (self.root / "runs.log").read_text().splitlines()
        self.assertEqual(len(runs), 1)
        record = json.loads(runs[0])
        self.assertEqual(record["argv"][:3], ["run", "--key", "slack:C1:100.1"])
        self.assertEqual(
            json.loads(record["--messages-file"]),
            [{"from": "U1", "text": "@helper private words"}],
        )
        store = json.loads((self.root / "data/triggers/slack.json").read_text())
        self.assertEqual(list(store["convs"]), ["slack:C1:100.1"])
        output = "\n".join(r.getMessage() for r in logs.records)
        for leaked in ("private words", "again", "supersecret", "xoxb", "xapp"):
            self.assertNotIn(leaked, output)
        for record in logs.records:
            self.assertEqual(record.msg, record.msg.lower())
        self.assertEqual(signal.getsignal(signal.SIGTERM), signal.SIG_DFL)


if __name__ == "__main__":
    unittest.main()
