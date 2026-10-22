"""exercise the trigger runtime's intake, store, and catch-up against a fake acp agent."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

TESTS = Path(__file__).resolve().parent
TRIGGERS = TESTS.parent / "triggers"
sys.path.insert(0, str(TRIGGERS))

import resident  # noqa: E402
import runtime  # noqa: E402

FAKE = TESTS / "fake_resident_agent.py"


class Adapter:
    name = "test"

    def __init__(self, history=None):
        self.events = []
        self.histories = history or {}
        self.changed = threading.Condition()

    def record(self, *event):
        with self.changed:
            self.events.append(event)
            self.changed.notify_all()

    def reply(self, conv, text):
        self.record("reply", conv, text)

    def ack(self, conv, msg_id, state):
        self.record("ack", conv, msg_id, state)

    def history(self, conv):
        return list(self.histories.get(conv, []))

    def replies(self, conv=None):
        return [e[2] for e in self.events if e[0] == "reply" and conv in (None, e[1])]

    def acks(self, msg_id):
        return [e[3] for e in self.events if e[0] == "ack" and e[2] == msg_id]


def event(kind, msg_id, text="hello", conv="t:c1:1", sender="U1"):
    return runtime.Event(kind, conv, msg_id, sender, text)


class TriggerTests(unittest.TestCase):
    def setUp(self):
        # short paths keep the unix socket under the platform limit
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / "home"
        (self.root / "bin").mkdir(parents=True)
        shutil.copy(TESTS.parent / "bin/abra", self.root / "bin/abra")
        self.log = Path(self.temporary.name) / "agent.log"
        self.config = Path(self.temporary.name) / "agent.json"
        self.config.write_text(json.dumps({"log": str(self.log)}))
        self.command = [sys.executable, str(FAKE), str(self.config)]
        self.runtimes = []
        self.addCleanup(self.stop_all)

    def stop_all(self):
        for instance in self.runtimes:
            instance.stop()

    def make(self, adapter=None, **options):
        options.setdefault("heartbeat", 0)
        options.setdefault("stop_timeout", 5)
        options.setdefault("kill_timeout", 2)
        instance = resident.Resident(
            adapter or Adapter(), self.root, self.command, **options
        )
        self.runtimes.append(instance)
        return instance

    def start(self, adapter=None, **options):
        adapter = adapter or Adapter()
        instance = self.make(adapter, **options)
        instance.start()
        return adapter, instance

    def prompts(self):
        if not self.log.exists():
            return []
        entries = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [
            "".join(b["text"] for b in e["params"]["prompt"])
            for e in entries
            if e.get("method") == "session/prompt"
        ]

    def store(self):
        return json.loads((self.root / "data/triggers/test.json").read_text())

    def write_store(self, convs):
        directory = self.root / "data/triggers"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "test.json").write_text(json.dumps({"convs": convs}))

    def entry(self, days_ago=0, **fields):
        stamp = time.strftime(
            runtime.STAMP, time.gmtime(time.time() - days_ago * runtime.DAY)
        )
        entry = dict(
            work_id="abra-wxyz",
            created=stamp,
            last_used=stamp,
            last_msg_id="m1",
            pending=[],
        )
        entry.update(fields)
        return entry

    def test_unknown_conv_message_ignored_and_known_start_is_message(self):
        adapter, instance = self.start()
        self.assertFalse(instance.submit(event("message", "m0", conv="t:other:1")))
        self.assertEqual(adapter.events, [])
        instance.submit(event("start", "m1"))
        self.assertTrue(instance.wait_idle(10))
        self.assertTrue(instance.submit(event("start", "m2")))
        self.assertTrue(instance.wait_idle(10))
        announcements = [r for r in adapter.replies() if "is on it" in r]
        self.assertEqual(len(announcements), 1)
        self.assertEqual(len(self.store()["convs"]), 1)
        self.assertEqual(len(self.prompts()), 2)
        self.assertFalse(instance.submit(event("message", "m2")))

    def test_invalid_events_rejected(self):
        adapter, instance = self.start()
        cases = [
            event("start", "m1", conv="../escape"),
            event("start", "m1", conv="has space"),
            event("start", "m1", conv="k" * 129),
            event("start", "m1", sender="a\nb"),
            event("start", "m1", sender=""),
            event("start", "bad id"),
            event("start", "m1", text="   "),
            event("start", "m1", text="x" * (32 * 1024)),
            event("start", "m1", text="\ud800"),
            event("stop", "m1"),
            ("start", "t:c1:1", "m1", "U1", "x"),
        ]
        for case in cases:
            self.assertFalse(instance.submit(case), case)
        self.assertEqual(adapter.events, [])
        self.assertFalse((self.root / "data/triggers/test.json").exists())

    def test_store_is_private_and_atomic(self):
        adapter, instance = self.start()
        instance.submit(event("start", "m1"))
        self.assertTrue(instance.wait_idle(10))
        path = self.root / "data/triggers/test.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        before = path.read_text()
        with mock.patch.object(runtime.os, "replace", side_effect=OSError):
            self.assertFalse(instance.submit(event("message", "m2")))
        self.assertEqual(path.read_text(), before)
        self.assertEqual(instance.convs["t:c1:1"]["pending"], [])
        self.assertTrue(instance.submit(event("message", "m2")))
        self.assertTrue(instance.wait_idle(10))
        leftovers = [p.name for p in path.parent.iterdir() if p.suffix == ".tmp"]
        self.assertEqual(leftovers, [])
        entry = self.store()["convs"]["t:c1:1"]
        self.assertEqual(
            sorted(entry), ["created", "last_msg_id", "last_used", "pending", "work_id"]
        )
        self.assertEqual(entry["last_msg_id"], "m2")

    def assert_first_survives(self, first, refused):
        handoff = self.root / "data/triggers/bridge.json"
        inflight = self.root / "data/triggers/.resident.jsonlive.tmp"
        inflight.write_text("in flight")
        before = handoff.read_text()
        with self.assertRaises(ValueError) as caught:
            self.start(refused)
        self.assertEqual(handoff.read_text(), before)
        self.assertTrue(inflight.exists())
        self.assertTrue(first.socket_path.exists())
        first.submit(event("start", "m1"))
        self.assertTrue(first.wait_idle(10))
        return str(caught.exception)

    def test_second_runtime_on_same_store_refused(self):
        _, first = self.start()
        self.assert_first_survives(first, Adapter())

    def test_second_adapter_on_same_root_refused(self):
        _, first = self.start()

        class Other(Adapter):
            name = "other"

        message = self.assert_first_survives(first, Other())
        self.assertIn("another resident runtime", message)

    def test_pending_cap_drops_and_acks_failed(self):
        with mock.patch.object(runtime, "MAX_PENDING", 2):
            adapter, instance = self.start()
            instance.submit(event("start", "m1", "wait do-hold"))
            self.assertTrue(instance.submit(event("message", "m2")))
            with self.assertLogs("abra.triggers", level="WARNING") as logs:
                self.assertFalse(
                    instance.submit(event("message", "m3", "secret words"))
                )
            self.assertEqual(adapter.acks("m3"), ["failed"])
            self.assertNotIn("secret", "\n".join(logs.output))
        self.assertEqual(self.store()["convs"]["t:c1:1"]["last_msg_id"], "m2")

    def test_stale_temporary_files_removed_and_modes_fixed(self):
        directory = self.root / "data/triggers"
        directory.mkdir(parents=True)
        directory.chmod(0o755)
        for name in (".test.jsonabc.tmp", ".resident.jsonx.tmp", ".bridge.jsony.tmp"):
            (directory / name).write_text("old")
        lock = directory / "test.lock"
        lock.write_text("")
        lock.chmod(0o644)
        self.start()
        self.assertEqual(
            sorted(p.name for p in directory.iterdir() if p.suffix == ".tmp"), []
        )
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(lock.stat().st_mode & 0o777, 0o600)

    def test_symlinked_triggers_directory_is_allowed(self):
        volume = Path(self.temporary.name) / "volume"
        volume.mkdir()
        (self.root / "data").mkdir()
        (self.root / "data/triggers").symlink_to(volume)
        adapter, instance = self.start()
        instance.submit(event("start", "m1"))
        self.assertTrue(instance.wait_idle(10))
        self.assertTrue((volume / "test.json").exists())
        self.assertEqual(volume.stat().st_mode & 0o777, 0o700)

    def test_startup_sweep_leaves_other_adapters_temp_files(self):
        directory = self.root / "data/triggers"
        directory.mkdir(parents=True)
        theirs = directory / ".other.jsonxyz.tmp"
        theirs.write_text("old store")
        self.start()
        self.assertTrue(theirs.exists())

    def test_legacy_one_shot_store_loads(self):
        legacy = self.entry(
            session_id="11111111-1111-4111-8111-111111111111",
            archived=True,
            fresh=True,
            resumed=True,
            pending=[{"msg_id": "m2", "sender": "U1", "text": "left over"}],
        )
        self.write_store({"t:c1:1": legacy})
        adapter, instance = self.start()
        self.assertTrue(instance.wait_idle(10))
        self.assertIn("left over", self.prompts()[0])
        entry = self.store()["convs"]["t:c1:1"]
        self.assertNotIn("archived", entry)
        self.assertNotIn("session_id", entry)
        self.assertEqual(entry["pending"], [])
        self.assertTrue(instance.submit(event("message", "m3")))

    def test_catch_up_queues_missed_history_after_restart(self):
        history = [
            runtime.Message("m1", "U1", "seen"),
            runtime.Message("m2", "U2", "missed one"),
            runtime.Message("b1", "abra", "bot reply"),
            runtime.Message("m3", "U3", "missed two"),
        ]
        self.write_store(
            {
                "t:c1:1": self.entry(),
                "t:stale:1": self.entry(days_ago=2, work_id="abra-old1"),
            }
        )
        adapter = Adapter({"t:c1:1": history, "t:stale:1": history})
        adapter, instance = self.start(adapter)
        self.assertTrue(instance.wait_idle(10))
        prompts = self.prompts()
        self.assertEqual(len(prompts), 1)
        self.assertIn("conversation: t:c1:1", prompts[0])
        self.assertNotIn("t:stale:1", prompts[0])
        self.assertLess(prompts[0].index("missed one"), prompts[0].index("missed two"))
        self.assertNotIn("bot reply", prompts[0])
        self.assertEqual(self.store()["convs"]["t:c1:1"]["last_msg_id"], "m3")

    def test_logs_never_contain_message_text(self):
        with self.assertLogs("abra.triggers", level="INFO") as logs:
            adapter, instance = self.start()
            instance.submit(event("start", "m1", "private words do-fail"))
            self.assertTrue(instance.wait_idle(10))
        output = "\n".join(record.getMessage() for record in logs.records)
        self.assertIn("t:c1:1", output)
        self.assertNotIn("private words", output)
        self.assertNotIn("secret", output)
        for record in logs.records:
            self.assertEqual(record.msg, record.msg.lower())

    def test_invalid_config_rejected(self):
        adapter = Adapter()
        for case in (dict(catchup_hours=-1), dict(name="bad\nname")):
            with self.assertRaises(ValueError, msg=case):
                resident.Resident(adapter, self.root, self.command, **case)
        for command in ("", "   ", [], [""]):
            with self.assertRaises(ValueError):
                resident.Resident(adapter, self.root, command)
        with self.assertRaises(ValueError):
            resident.Resident(adapter, self.root / "missing", self.command)
        (self.root / "bin/abra").unlink()
        with self.assertRaises(ValueError):
            resident.Resident(adapter, self.root, self.command)

    def test_corrupt_store_fails_closed(self):
        directory = self.root / "data/triggers"
        directory.mkdir(parents=True)
        (directory / "test.json").write_text("[" * 100000)
        with self.assertRaises(ValueError):
            self.start()
        self.assertFalse((directory / "bridge.json").exists())

    def test_env_settings(self):
        class Args:
            root = str(self.root)
            name = "Bot One"

        env = {
            "ABRA_AGENT_CMD": "agent --acp",
            "ABRA_WAKE_GRACE": "5",
            "ABRA_HEARTBEAT": "0",
            "ABRA_IDLE_CLEAR": "60",
            "ABRA_MAX_SESSION_AGE": "3600",
        }
        instance = runtime.from_args(Adapter(), Args, env)
        self.assertEqual(instance.slug, "bot-one")
        self.assertEqual(
            (
                instance.wake_grace,
                instance.heartbeat,
                instance.idle_clear,
                instance.max_age,
            ),
            (5, 0, 60, 3600),
        )
        self.assertFalse(instance.agent_mode)
        for bad in ({}, {"ABRA_AGENT_CMD": "x", "ABRA_IDLE_CLEAR": "-1"}):
            with self.assertRaises(ValueError):
                runtime.from_args(Adapter(), Args, bad)

    def test_cli_adapter_rejects_bad_input_and_root(self):
        lines = [
            {
                "kind": "message",
                "conv": "t:x:1",
                "msg_id": "m0",
                "sender": "U1",
                "text": "ignored",
            },
            "not json",
            {
                "kind": "start",
                "conv": "t:x:1",
                "msg_id": "m1",
                "sender": "U1",
                "text": "do it",
            },
        ]
        stdin = "\n".join(l if isinstance(l, str) else json.dumps(l) for l in lines)
        env = dict(os.environ, ABRA_AGENT_CMD=" ".join(self.command))
        result = subprocess.run(
            [
                sys.executable,
                str(TRIGGERS / "cli.py"),
                "--root",
                str(self.root),
                "--name",
                "helper",
            ],
            input=stdin + "\n",
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(records[0]["text"].startswith("helper is on it."))
        self.assertIn("work item helper-", records[0]["text"])
        acks = [r["state"] for r in records if r["type"] == "ack"]
        self.assertEqual(acks, ["running"])
        self.assertIn("ignoring invalid event on line 2", result.stderr)
        self.assertNotIn("do it", result.stderr)
        self.assertTrue((self.root / "data/triggers/cli.json").exists())
        missing = subprocess.run(
            [sys.executable, str(TRIGGERS / "cli.py"), "--root", str(self.root / "no")],
            input="",
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(missing.returncode, 1)
        self.assertNotIn("Traceback", missing.stderr)


if __name__ == "__main__":
    unittest.main()
