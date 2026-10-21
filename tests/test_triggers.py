"""exercise the trigger runtime against a stub bin/abra in temporary roots."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock


TRIGGERS = Path(__file__).resolve().parents[1] / "triggers"
sys.path.insert(0, str(TRIGGERS))

import runtime  # noqa: E402

STUB = textwrap.dedent(
    """\
    import fcntl, json, os, sys, time
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    config = json.loads((root / "stub.json").read_text())
    args = sys.argv[1:]
    record = {"argv": args, "start": time.time()}
    for flag in ("--messages-file", "--context-file"):
        if flag in args:
            path = args[args.index(flag) + 1]
            record[flag] = open(path, encoding="utf-8").read()
            record[flag + "-mode"] = os.stat(path).st_mode & 0o777
    with open(root / "calls.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        log = root / "calls.log"
        count = len(log.read_text().splitlines()) if log.exists() else 0
        with open(log, "a") as handle:
            handle.write(json.dumps({"index": count, "start": True}) + "\\n")
    if args[:2] == ["sessions", "prune"]:
        record["end"] = time.time()
        with open(root / "prune.log", "a") as handle:
            handle.write(json.dumps(record) + "\\n")
        print("old:1")
        sys.exit(0)
    time.sleep(config.get("sleep", 0))
    record["end"] = time.time()
    with open(root / "runs.log", "a") as handle:
        handle.write(json.dumps(record) + "\\n")
    codes = config.get("codes", [])
    runs = len((root / "runs.log").read_text().splitlines())
    code = codes[runs - 1] if runs - 1 < len(codes) else 0
    if code:
        print("traceback secret-stderr-detail", file=sys.stderr)
        print("partial secret-stdout")
        sys.exit(code)
    print("result " + str(runs))
    """
)


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

    def wait(self, predicate, timeout=10):
        with self.changed:
            self.assert_true(self.changed.wait_for(lambda: predicate(self), timeout))

    @staticmethod
    def assert_true(value):
        if not value:
            raise AssertionError("timed out waiting for adapter events")

    def replies(self, conv=None):
        return [e[2] for e in self.events if e[0] == "reply" and conv in (None, e[1])]

    def acks(self, msg_id):
        return [e[3] for e in self.events if e[0] == "ack" and e[2] == msg_id]


def event(kind, msg_id, text="hello", conv="t:c1:1", sender="U1"):
    return runtime.Event(kind, conv, msg_id, sender, text)


class TriggerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "home"
        (self.root / "bin").mkdir(parents=True)
        stub = self.root / "bin/abra"
        stub.write_text("#!" + sys.executable + "\n" + STUB)
        stub.chmod(0o755)
        self.configure()
        self.runtimes = []
        self.addCleanup(self.stop_all)

    def configure(self, **config):
        (self.root / "stub.json").write_text(json.dumps(config))

    def stop_all(self):
        for instance in self.runtimes:
            if instance.threads:
                instance.stop()

    def start(self, adapter=None, **options):
        adapter = adapter or Adapter()
        options.setdefault("backoff", lambda attempt: 0.01)
        instance = runtime.Runtime(adapter, self.root, name="abra", **options)
        self.runtimes.append(instance)
        instance.start()
        return adapter, instance

    def runs(self):
        path = self.root / "runs.log"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def prunes(self):
        path = self.root / "prune.log"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

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
            session_id="11111111-1111-4111-8111-111111111111",
            created=stamp,
            last_used=stamp,
            last_msg_id="m1",
            archived=False,
            pending=[],
        )
        entry.update(fields)
        return entry

    def test_start_announces_before_run_with_work_and_session_ids(self):
        adapter, instance = self.start()
        self.assertTrue(instance.submit(event("start", "m1")))
        self.assertTrue(instance.wait_idle(10))
        first = adapter.events[0]
        self.assertEqual(first[0], "reply")
        match = re.fullmatch(
            r"abra is on it\. this thread is now work item (abra-[a-z2-7]{4}) \(session"
            r" ([0-9a-f-]{36})\)\. reply in this thread to add to it\.",
            first[2],
        )
        self.assertIsNotNone(match, first[2])
        work_id, session_id = match.groups()
        self.assertRegex(session_id, runtime.UUID.pattern)
        self.assertEqual(adapter.events[1], ("ack", "t:c1:1", "m1", "queued"))
        self.assertEqual(adapter.acks("m1"), ["queued", "running", "done"])
        self.assertEqual(adapter.replies()[-1], "result 1")
        argv = self.runs()[0]["argv"]
        self.assertEqual(argv[:3], ["run", "--key", "t:c1:1"])
        self.assertEqual(argv[argv.index("--work-id") + 1], work_id)
        self.assertEqual(argv[argv.index("--session-id") + 1], session_id)
        self.assertNotIn("--context-file", argv)
        self.assertEqual(
            json.loads(self.runs()[0]["--messages-file"]),
            [{"from": "U1", "text": "hello"}],
        )
        self.assertEqual(self.runs()[0]["--messages-file-mode"], 0o600)
        instance.submit(event("message", "m2"))
        self.assertTrue(instance.wait_idle(10))
        argv = self.runs()[1]["argv"]
        self.assertNotIn("--session-id", argv)
        self.assertEqual(argv[argv.index("--work-id") + 1], work_id)

    def test_messages_during_a_turn_batch_into_one_next_turn(self):
        self.configure(sleep=0.4)
        adapter, instance = self.start()
        instance.submit(event("start", "m1"))
        adapter.wait(lambda a: "running" in a.acks("m1"))
        for index, msg_id in enumerate(("m2", "m3", "m4")):
            instance.submit(event("message", msg_id, "text " + str(index), sender="U2"))
            self.assertEqual(adapter.acks(msg_id), ["queued"])
        self.assertTrue(instance.wait_idle(10))
        runs = self.runs()
        self.assertEqual(len(runs), 2)
        self.assertEqual(
            json.loads(runs[1]["--messages-file"]),
            [{"from": "U2", "text": "text " + str(i)} for i in range(3)],
        )
        for msg_id in ("m2", "m3", "m4"):
            self.assertEqual(adapter.acks(msg_id), ["queued", "running", "done"])

    def test_busy_requeues_with_backoff_and_no_failed_ack(self):
        self.configure(codes=[75, 75, 0])
        delays = []
        adapter, instance = self.start(
            backoff=lambda attempt: delays.append(attempt) or 0.01
        )
        instance.submit(event("start", "m1"))
        self.assertTrue(instance.wait_idle(10))
        self.assertEqual(delays, [0, 1])
        self.assertEqual(len(self.runs()), 3)
        self.assertEqual(
            adapter.acks("m1"),
            ["queued", "running", "queued", "running", "queued", "running", "done"],
        )
        self.assertEqual(adapter.replies()[1:], ["result 3"])
        self.assertIn("--session-id", self.runs()[2]["argv"])

    def test_error_posts_fixed_reply_without_stderr_or_stdout(self):
        for code in (1, 2, 9):
            self.configure(codes=[code])
            (self.root / "runs.log").unlink(missing_ok=True)
            adapter, instance = self.start()
            conv = "t:err:" + str(code)
            instance.submit(event("start", "m1", conv=conv))
            self.assertTrue(instance.wait_idle(10))
            self.assertEqual(adapter.acks("m1"), ["queued", "running", "failed"])
            self.assertEqual(
                adapter.replies()[1:],
                ["abra hit an error on this turn. reply here to try again."],
            )
            for text in adapter.replies():
                self.assertNotIn("secret", text)
            self.assertEqual(self.store()["convs"][conv]["pending"], [])
            instance.stop()

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
        self.assertEqual(len(self.runs()), 2)
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

    def test_one_turn_per_conv_and_concurrency_up_to_worker_cap(self):
        self.configure(sleep=0.3)
        adapter, instance = self.start(workers=2)
        for conv in ("a", "b", "c"):
            instance.submit(event("start", conv + "1", conv="t:" + conv + ":1"))
        adapter.wait(lambda a: "running" in a.acks("a1"))
        instance.submit(event("message", "a2", conv="t:a:1"))
        self.assertTrue(instance.wait_idle(10))
        runs = self.runs()
        self.assertEqual(len(runs), 4)
        spans = [(r["start"], r["end"], r["argv"][2]) for r in runs]
        peak = max(sum(s <= start < e for s, e, _ in spans) for start, _, _ in spans)
        self.assertEqual(peak, 2)
        mine = sorted(s[:2] for s in spans if s[2] == "t:a:1")
        self.assertLessEqual(mine[0][1], mine[1][0])

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
        self.assertEqual(list((path.parent / "tmp").iterdir()), [])
        entry = self.store()["convs"]["t:c1:1"]
        for field in ("work_id", "session_id", "created", "last_used"):
            self.assertIsInstance(entry[field], str)
        self.assertEqual(entry["last_msg_id"], "m2")
        self.assertIs(entry["archived"], False)

    def test_second_runtime_on_same_store_refused(self):
        self.start()
        with self.assertRaises(ValueError):
            self.start()

    def test_pending_persists_across_restart(self):
        self.configure(codes=[75])
        adapter, instance = self.start(backoff=lambda attempt: 3600)
        instance.submit(event("start", "m1"))
        adapter.wait(
            lambda a: a.acks("m1")[-1:] == ["queued"] and len(a.acks("m1")) == 3
        )
        instance.stop()
        self.assertEqual(len(self.store()["convs"]["t:c1:1"]["pending"]), 1)
        adapter, instance = self.start()
        self.assertTrue(instance.wait_idle(10))
        self.assertEqual(adapter.acks("m1"), ["queued", "running", "done"])
        self.assertEqual(adapter.replies(), ["result 2"])
        self.assertIn("--session-id", self.runs()[1]["argv"])
        self.assertEqual(self.store()["convs"]["t:c1:1"]["pending"], [])

    def test_archive_marks_conv_and_prunes_with_configured_days(self):
        self.write_store(
            {"t:old:1": self.entry(days_ago=31), "t:new:1": self.entry(days_ago=1)}
        )
        adapter, instance = self.start(archive_days=30)
        convs = self.store()["convs"]
        self.assertTrue(convs["t:old:1"]["archived"])
        self.assertIsNone(convs["t:old:1"]["session_id"])
        self.assertEqual(convs["t:old:1"]["work_id"], "abra-wxyz")
        self.assertFalse(convs["t:new:1"]["archived"])
        self.assertEqual(
            [p["argv"] for p in self.prunes()],
            [["sessions", "prune", "--older-than", "30"]],
        )
        self.assertEqual(self.runs(), [])

    def test_resurrection_passes_trimmed_context_and_posts_resume_text(self):
        big = "y" * 20000
        history = [runtime.Message("h0", "U1", "first message")]
        history += [runtime.Message("h" + str(i), "U2", big) for i in range(1, 40)]
        history += [runtime.Message("b1", "abra", "bot said this")]
        history += [runtime.Message("m9", "U3", "new message")]
        self.write_store({"t:c1:1": self.entry(days_ago=100, last_msg_id="h39")})
        adapter = Adapter({"t:c1:1": history})
        adapter, instance = self.start(adapter)
        self.assertTrue(self.store()["convs"]["t:c1:1"]["archived"])
        instance.submit(event("message", "m9", "new message", sender="U3"))
        self.assertTrue(instance.wait_idle(10))
        resume = adapter.events[0]
        self.assertEqual(resume[0], "reply")
        match = re.fullmatch(
            r"abra is resuming work item abra-wxyz \(session ([0-9a-f-]{36})\)\.",
            resume[2],
        )
        self.assertIsNotNone(match, resume[2])
        self.assertNotEqual(match.group(1), "11111111-1111-4111-8111-111111111111")
        run = self.runs()[0]
        argv = run["argv"]
        self.assertEqual(argv[argv.index("--session-id") + 1], match.group(1))
        self.assertEqual(argv[argv.index("--work-id") + 1], "abra-wxyz")
        prior = run["--context-file"]
        self.assertEqual(run["--context-file-mode"], 0o600)
        self.assertLessEqual(len(prior.encode("utf-8")), 256 * 1024)
        self.assertIn("data/abra-wxyz/", prior)
        self.assertIn("[h0] U1:\nfirst message", prior)
        self.assertIn("[h39] U2:", prior)
        self.assertIn("[b1] abra:\nbot said this", prior)
        self.assertNotIn("[h1] U2:", prior)
        self.assertIn("messages omitted", prior)
        self.assertNotIn("new message", prior)
        self.assertEqual(adapter.replies()[-1], "result 1")
        instance.submit(event("message", "m10"))
        self.assertTrue(instance.wait_idle(10))
        argv = self.runs()[1]["argv"]
        self.assertNotIn("--context-file", argv)
        self.assertNotIn("--session-id", argv)

    def test_failed_resurrection_turn_keeps_context_without_session_id(self):
        self.configure(codes=[1, 0])
        history = [runtime.Message("h0", "U1", "first message")]
        self.write_store({"t:c1:1": self.entry(days_ago=100, last_msg_id="h0")})
        adapter, instance = self.start(Adapter({"t:c1:1": history}))
        instance.submit(event("message", "m1"))
        self.assertTrue(instance.wait_idle(10))
        self.assertEqual(adapter.acks("m1"), ["queued", "running", "failed"])
        instance.submit(event("message", "m2"))
        self.assertTrue(instance.wait_idle(10))
        first, second = [run["argv"] for run in self.runs()]
        self.assertIn("--session-id", first)
        self.assertIn("--context-file", first)
        self.assertIn("--context-file", second)
        self.assertNotIn("--session-id", second)
        self.assertIn("first message", self.runs()[1]["--context-file"])
        self.assertFalse(self.store()["convs"]["t:c1:1"]["resumed"])
        instance.submit(event("message", "m3"))
        self.assertTrue(instance.wait_idle(10))
        self.assertNotIn("--context-file", self.runs()[2]["argv"])

    def test_pending_cap_drops_and_acks_failed(self):
        self.configure(sleep=0.4)
        with mock.patch.object(runtime, "MAX_PENDING", 2):
            adapter, instance = self.start()
            instance.submit(event("start", "m1"))
            adapter.wait(lambda a: "running" in a.acks("m1"))
            self.assertTrue(instance.submit(event("message", "m2")))
            with self.assertLogs("abra.triggers", level="WARNING") as logs:
                self.assertFalse(
                    instance.submit(event("message", "m3", "secret words"))
                )
            self.assertEqual(adapter.acks("m3"), ["failed"])
            self.assertNotIn("secret", "\n".join(logs.output))
            self.assertTrue(instance.wait_idle(10))
        self.assertEqual(len(self.runs()), 2)
        self.assertEqual(
            json.loads(self.runs()[1]["--messages-file"]),
            [{"from": "U1", "text": "hello"}],
        )
        self.assertEqual(self.store()["convs"]["t:c1:1"]["last_msg_id"], "m2")

    def test_redelivered_message_on_archived_conv_does_not_resurrect(self):
        self.write_store({"t:c1:1": self.entry(days_ago=100, last_msg_id="h0")})
        adapter, instance = self.start()
        self.assertFalse(instance.submit(event("message", "h0")))
        self.assertEqual(adapter.events, [])
        entry = self.store()["convs"]["t:c1:1"]
        self.assertTrue(entry["archived"])
        self.assertIsNone(entry["session_id"])
        self.assertEqual(self.runs(), [])

    def test_temporary_files_cleaned_on_write_failure_and_startup(self):
        scratch = self.root / "data/triggers/tmp"
        scratch.mkdir(parents=True)
        scratch.parent.chmod(0o755)
        scratch.chmod(0o755)
        (scratch / "leftover").write_text("old message")
        adapter, instance = self.start()
        self.assertEqual(list(scratch.iterdir()), [])
        self.assertEqual(scratch.stat().st_mode & 0o777, 0o700)
        self.assertEqual(scratch.parent.stat().st_mode & 0o777, 0o700)
        lock = self.root / "data/triggers/test.lock"
        self.assertEqual(lock.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(TypeError):
            instance._temporary("not bytes")
        self.assertEqual(list(scratch.iterdir()), [])

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
                "t:stale:1": self.entry(days_ago=2),
            }
        )
        adapter = Adapter({"t:c1:1": history, "t:stale:1": history})
        adapter, instance = self.start(adapter)
        self.assertTrue(instance.wait_idle(10))
        runs = self.runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["argv"][2], "t:c1:1")
        self.assertEqual(
            json.loads(runs[0]["--messages-file"]),
            [
                {"from": "U2", "text": "missed one"},
                {"from": "U3", "text": "missed two"},
            ],
        )
        self.assertNotIn("--session-id", runs[0]["argv"])
        self.assertEqual(self.store()["convs"]["t:c1:1"]["last_msg_id"], "m3")

    def test_logs_never_contain_message_text(self):
        self.configure(codes=[1])
        with self.assertLogs("abra.triggers", level="INFO") as logs:
            adapter, instance = self.start()
            instance.submit(event("start", "m1", "private words here"))
            self.assertTrue(instance.wait_idle(10))
        output = "\n".join(record.getMessage() for record in logs.records)
        self.assertIn("t:c1:1", output)
        self.assertNotIn("private words", output)
        self.assertNotIn("secret", output)
        for record in logs.records:
            self.assertEqual(record.msg, record.msg.lower())

    def test_invalid_config_rejected(self):
        adapter = Adapter()
        cases = [
            dict(archive_days=0),
            dict(archive_days=-1),
            dict(archive_days=True),
            dict(workers=0),
            dict(workers=-2),
            dict(catchup_hours=-1),
            dict(name="bad\nname"),
        ]
        for case in cases:
            with self.assertRaises(ValueError, msg=case):
                runtime.Runtime(adapter, self.root, **case)
        with self.assertRaises(ValueError):
            runtime.Runtime(adapter, self.root / "missing")
        (self.root / "bin/abra").unlink()
        with self.assertRaises(ValueError):
            runtime.Runtime(adapter, self.root)

    def test_corrupt_store_fails_closed(self):
        directory = self.root / "data/triggers"
        directory.mkdir(parents=True)
        (directory / "test.json").write_text("[" * 100000)
        with self.assertRaises(ValueError):
            self.start()

    def test_env_settings(self):
        class Args:
            root = str(self.root)
            name = "Bot One"

        instance = runtime.from_args(
            Adapter(), Args, {"ABRA_ARCHIVE_DAYS": "7", "ABRA_TRIGGER_WORKERS": "3"}
        )
        self.assertEqual((instance.archive_days, instance.workers), (7, 3))
        self.assertEqual(instance.slug, "bot-one")
        for env in ({"ABRA_ARCHIVE_DAYS": "0"}, {"ABRA_TRIGGER_WORKERS": "x"}):
            with self.assertRaises(ValueError):
                runtime.from_args(Adapter(), Args, env)

    def test_cli_adapter_end_to_end(self):
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
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(records[0]["type"], "reply")
        self.assertTrue(records[0]["text"].startswith("helper is on it."))
        self.assertIn("work item helper-", records[0]["text"])
        acks = [r["state"] for r in records if r["type"] == "ack"]
        self.assertEqual(acks, ["queued", "running", "done"])
        self.assertEqual(
            records[-2], {"type": "reply", "conv": "t:x:1", "text": "result 1"}
        )
        self.assertIn("ignoring invalid event on line 2", result.stderr)
        self.assertNotIn("do it", result.stderr)
        self.assertTrue((self.root / "data/triggers/cli.json").exists())
        missing = subprocess.run(
            [
                sys.executable,
                str(TRIGGERS / "cli.py"),
                "--root",
                str(self.root / "nope"),
            ],
            input="",
            capture_output=True,
            text=True,
        )
        self.assertEqual(missing.returncode, 1)
        self.assertNotIn("Traceback", missing.stderr)


if __name__ == "__main__":
    unittest.main()
