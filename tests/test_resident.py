"""exercise the resident runtime against a fake acp agent in temporary roots."""

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

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "triggers"))

import resident  # noqa: E402
import runtime  # noqa: E402

FAKE = TESTS / "fake_resident_agent.py"
CLI = TESTS.parent / "bin/abra"


class Adapter:
    name = "test"

    def __init__(self):
        self.events = []
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
        return []

    def wait(self, predicate, timeout=10):
        with self.changed:
            if not self.changed.wait_for(lambda: predicate(self), timeout):
                raise AssertionError("timed out waiting for adapter events")

    def replies(self, conv=None):
        return [e[2] for e in self.events if e[0] == "reply" and conv in (None, e[1])]

    def acks(self, msg_id):
        return [e[3] for e in self.events if e[0] == "ack" and e[2] == msg_id]


def event(kind, msg_id, text, conv="t:c1:1", sender="U1"):
    return runtime.Event(kind, conv, msg_id, sender, text)


class ResidentTests(unittest.TestCase):
    def setUp(self):
        # short paths keep the unix socket under the platform limit
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / "bin").mkdir()
        shutil.copy(CLI, self.root / "bin/abra")
        self.log = self.root / "agent.log"
        self.config_path = self.root / "agent.json"
        self.configure()
        self.adapter = Adapter()
        self.instances = []
        self.addCleanup(self.stop_all)

    def configure(self, **config):
        config.setdefault("log", str(self.log))
        self.config_path.write_text(json.dumps(config))

    def make(self, adapter=None, **options):
        options.setdefault("stop_timeout", 5)
        options.setdefault("kill_timeout", 2)
        options.setdefault("timeout", 20)
        options.setdefault("heartbeat", 0)
        instance = resident.Resident(
            adapter or self.adapter,
            self.root,
            [sys.executable, str(FAKE), str(self.config_path)],
            **options,
        )
        self.instances.append(instance)
        return instance

    def start(self, **options):
        instance = self.make(**options)
        instance.start()
        return instance

    def stop_all(self):
        for instance in self.instances:
            instance.stop()

    def received(self, method=None):
        if not self.log.exists():
            return []
        entries = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [e for e in entries if method is None or e.get("method") == method]

    def prompts(self):
        return [
            "".join(b["text"] for b in e["params"]["prompt"])
            for e in self.received("session/prompt")
        ]

    def wait_for(self, predicate, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        raise AssertionError("timed out")

    def work_id(self, instance, conv="t:c1:1"):
        return instance.convs[conv]["work_id"]

    def test_requires_agent_command(self):
        args = type("Args", (), {"root": str(self.root), "name": "abra"})
        with self.assertRaises(ValueError):
            runtime.from_args(self.adapter, args, {})
        instance = runtime.from_args(
            self.adapter,
            args,
            {
                "ABRA_AGENT_CMD": "agent --acp",
                "ABRA_AGENT_MODE": "1",
            },
        )
        self.assertIsInstance(instance, resident.Resident)
        self.assertEqual(instance.argv, ["agent", "--acp"])
        self.assertTrue(instance.agent_mode)

    def test_reply_tool_answers_and_framing(self):
        instance = self.start()
        instance.submit(event("start", "1", "please do-reply"))
        self.assertTrue(instance.wait_idle(10))
        work_id = self.work_id(instance)
        replies = self.adapter.replies("t:c1:1")
        self.assertEqual(
            replies[0],
            "abra is on it. this thread is now work item "
            + work_id
            + ". reply in this thread to add to it.",
        )
        self.assertEqual(replies[1:], ["re " + work_id])
        self.assertEqual(self.adapter.acks("1"), ["running"])
        text = self.prompts()[0]
        self.assertIn("runtime event: " + resident.BOOTSTRAP, text)
        self.assertIn("conversation: t:c1:1\nwork id: " + work_id + "\n", text)
        self.assertRegex(
            text,
            r'<untrusted-message msg_id="1" from="U1" nonce="([0-9a-f]{16})">\n'
            r"please do-reply\n</untrusted-message nonce="
            r'"\1">',
        )
        self.assertEqual(instance.convs["t:c1:1"]["pending"], [])
        new = self.received("session/new")[0]["params"]
        self.assertEqual(new["cwd"], str(self.root))
        bridge = new["mcpServers"][0]
        self.assertEqual(bridge["name"], "abra")
        self.assertEqual(bridge["args"], [str(resident.BRIDGE)])
        state = json.loads((self.root / "data/triggers/resident.json").read_text())
        self.assertTrue(state["session_id"].startswith("s-"))
        mode = os.stat(self.root / "data/triggers/resident.json").st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_batches_across_conversations_in_arrival_order(self):
        self.configure(steering=False, slow=0.6)
        instance = self.start()
        instance.submit(event("start", "1", "first do-slow"))
        self.wait_for(lambda: len(self.prompts()) == 1)
        instance.submit(event("start", "2", "from b", conv="t:b:1", sender="U2"))
        instance.submit(event("start", "3", "from c", conv="t:c:1", sender="U3"))
        instance.submit(event("message", "4", "more b", conv="t:b:1", sender="U2"))
        self.assertTrue(instance.wait_idle(10))
        prompts = self.prompts()
        self.assertEqual(len(prompts), 2)
        second = prompts[1]
        self.assertNotIn(resident.BOOTSTRAP, second)
        self.assertLess(second.index("conversation: t:b:1"), second.index("from c"))
        self.assertLess(second.index("from b"), second.index("more b"))
        self.assertLess(second.index("more b"), second.index("conversation: t:c:1"))
        self.assertIn("3 new messages", second)
        self.assertEqual(self.received("_session/steering"), [])

    def test_steering_injects_into_running_turn(self):
        instance = self.start()
        instance.submit(event("start", "1", "wait do-hold"))
        self.wait_for(lambda: len(self.prompts()) == 1)
        instance.submit(event("start", "2", "now do-reply", conv="t:b:1"))
        self.assertTrue(instance.wait_idle(10))
        steer = self.received("_session/steering")
        self.assertEqual(len(steer), 1)
        self.assertEqual(
            steer[0]["params"]["_meta"],
            {"steering": {"idleBehavior": "promptRequired"}},
        )
        self.assertIn("now do-reply", steer[0]["params"]["prompt"][0]["text"])
        self.assertEqual(len(self.prompts()), 1)
        self.assertEqual(self.adapter.acks("2"), ["running"])
        b = self.work_id(instance, "t:b:1")
        self.assertIn("re " + b, self.adapter.replies("t:b:1"))
        self.assertEqual(instance.convs["t:b:1"]["pending"], [])

    def steer_with(self, outcome):
        self.configure(steer_outcome=outcome, slow=0.6)
        instance = self.start()
        instance.submit(event("start", "1", "first do-slow"))
        self.wait_for(lambda: len(self.prompts()) == 1)
        instance.submit(event("start", "2", "second", conv="t:b:1"))
        self.assertTrue(instance.wait_idle(10))
        return instance

    def test_steering_prompt_required_falls_back_to_prompt(self):
        instance = self.steer_with("promptRequired")
        self.assertEqual(len(self.received("_session/steering")), 1)
        self.assertEqual(len(self.prompts()), 2)
        self.assertIn("second", self.prompts()[1])
        self.assertTrue(instance.steering)

    def test_steering_failed_queues_for_next_prompt(self):
        self.steer_with("failed")
        self.assertEqual(len(self.received("_session/steering")), 1)
        self.assertIn("second", self.prompts()[1])

    def test_steering_started_new_turn_counts_as_handled(self):
        instance = self.steer_with("startedNewTurn")
        self.assertEqual(len(self.prompts()), 1)
        self.assertEqual(self.adapter.acks("2"), ["running"])
        self.assertEqual(instance.convs["t:b:1"]["pending"], [])

    def test_steering_method_not_found_disables_steering(self):
        self.configure(steering=False, advertise=True, slow=0.6)
        instance = self.start()
        instance.submit(event("start", "1", "first do-slow"))
        self.wait_for(lambda: len(self.prompts()) == 1)
        instance.submit(event("start", "2", "second", conv="t:b:1"))
        self.assertTrue(instance.wait_idle(10))
        self.assertFalse(instance.steering)
        self.assertEqual(len(self.prompts()), 2)
        self.assertIn("second", self.prompts()[1])

    def test_free_text_fallback_for_single_conversation(self):
        instance = self.start()
        instance.submit(event("start", "1", "please do-silent"))
        self.assertTrue(instance.wait_idle(10))
        self.assertEqual(self.adapter.replies("t:c1:1")[1:], ["free text answer"])

    def test_no_fallback_across_conversations(self):
        self.configure(steering=False, slow=0.6)
        instance = self.start()
        instance.submit(event("start", "1", "first do-slow"))
        self.wait_for(lambda: len(self.prompts()) == 1)
        instance.submit(event("start", "2", "do-silent", conv="t:b:1"))
        instance.submit(event("start", "3", "do-silent", conv="t:c:1"))
        self.assertTrue(instance.wait_idle(10))
        self.assertEqual(len(self.adapter.replies("t:b:1")), 1)
        self.assertEqual(len(self.adapter.replies("t:c:1")), 1)

    def test_failure_and_refusal_post_error_text(self):
        instance = self.start()
        with self.assertLogs("abra.triggers", "INFO") as logs:
            instance.submit(event("start", "1", "please do-fail"))
            self.assertTrue(instance.wait_idle(10))
        self.assertEqual(
            self.adapter.replies("t:c1:1")[1:], [runtime.error_text("abra")]
        )
        self.assertEqual(self.adapter.acks("1"), ["running", "failed"])
        self.assertNotIn("secret", "\n".join(logs.output))
        instance.submit(event("message", "2", "please do-refuse"))
        self.assertTrue(instance.wait_idle(10))
        self.assertEqual(self.adapter.acks("2"), ["running", "failed"])
        self.assertEqual(instance.convs["t:c1:1"]["pending"], [])

    def test_permission_policy_allows_only_reply_tool(self):
        instance = self.start()
        instance.submit(event("start", "1", "do-permission"))
        self.assertTrue(instance.wait_idle(10))
        outcomes = [e for e in self.received() if "permission" in e][0]["permission"]
        self.assertEqual(
            outcomes,
            [
                {"outcome": "selected", "optionId": "a1"},
                {"outcome": "selected", "optionId": "r1"},
            ],
        )
        self.assertEqual(self.received("session/set_mode"), [])

    def test_agent_mode_sets_unattended_mode(self):
        self.configure(modes=["default", "plan", "bypassPermissions"])
        instance = self.start(agent_mode=True)
        instance.submit(event("start", "1", "hello"))
        self.assertTrue(instance.wait_idle(10))
        modes = self.received("session/set_mode")
        self.assertEqual(modes[0]["params"]["modeId"], "bypassPermissions")

    def test_pending_survives_crash_and_restart(self):
        instance = self.start()
        instance.submit(event("start", "1", "boom do-crash"))
        self.assertTrue(instance.crashed.wait(10))
        self.assertTrue(instance.wait_idle(1))
        instance.stop()
        stored = json.loads((self.root / "data/triggers/test.json").read_text())
        self.assertEqual(len(stored["convs"]["t:c1:1"]["pending"]), 1)
        self.log.unlink()
        again = Adapter()
        restarted = self.start(adapter=again)
        self.assertTrue(restarted.wait_idle(10))
        self.assertEqual(len(self.received("session/resume")), 1)
        self.assertEqual(self.received("session/new"), [])
        text = self.prompts()[0]
        self.assertIn(resident.RESTART, text)
        self.assertIn("boom do-crash", text)

    def test_resume_failure_starts_new_session(self):
        state = self.root / "data/triggers"
        state.mkdir(parents=True, mode=0o700)
        instance = self.make()
        runtime.write_private(
            state / "resident.json",
            {"version": 1, "agent": instance.digest, "session_id": "old-1"},
        )
        self.configure(fail_resume=True)
        instance.start()
        self.assertTrue(instance.wait_idle(10))
        self.assertEqual(len(self.received("session/resume")), 1)
        self.assertEqual(len(self.received("session/load")), 1)
        self.assertEqual(len(self.received("session/new")), 1)
        self.assertIn(resident.BOOTSTRAP, self.prompts()[0])

    def test_other_agent_command_does_not_resume(self):
        state = self.root / "data/triggers"
        state.mkdir(parents=True, mode=0o700)
        runtime.write_private(
            state / "resident.json",
            {"version": 1, "agent": "different", "session_id": "old-1"},
        )
        instance = self.start()
        self.assertTrue(instance.wait_idle(5))
        self.assertEqual(self.received("session/resume"), [])
        self.assertEqual(self.prompts(), [])

    def test_stop_closes_session_and_kills_agent(self):
        instance = self.start()
        instance.submit(event("start", "1", "hello"))
        self.assertTrue(instance.wait_idle(10))
        process = instance.client.proc
        instance.stop()
        self.assertEqual(len(self.received("session/close")), 1)
        self.assertIsNotNone(process.poll())
        self.assertFalse(instance.socket_path.exists())
        self.assertFalse((self.root / "data/triggers/bridge.json").exists())
        self.assertFalse(instance.submit(event("message", "2", "late")))

    def test_long_root_moves_socket_to_private_temp_dir(self):
        self.root = self.root / ("x" * 90)
        (self.root / "bin").mkdir(parents=True)
        shutil.copy(CLI, self.root / "bin/abra")
        instance = self.start()
        self.assertNotEqual(instance.socket_path.parent, self.root / "data/triggers")
        mode = os.stat(instance.socket_path.parent).st_mode & 0o777
        self.assertEqual(mode, 0o700)
        instance.submit(event("start", "1", "please do-shim"))
        self.assertTrue(instance.wait_idle(10))
        self.assertIn("shim " + self.work_id(instance), self.adapter.replies())
        directory = instance.socket_path.parent
        instance.stop()
        self.assertFalse(directory.exists())

    def test_bridge_end_to_end_through_shim(self):
        instance = self.start()
        instance.submit(event("start", "1", "please do-shim"))
        self.assertTrue(instance.wait_idle(10))
        work_id = self.work_id(instance)
        self.assertIn("shim " + work_id, self.adapter.replies("t:c1:1"))

    def test_job_is_delivered_as_runtime_event(self):
        pack = self.root / "specialty"
        (pack / "jobs").mkdir(parents=True)
        (pack / "specialty.json").write_text(
            json.dumps({"jobs": {"nightly": {"prompt": "jobs/nightly.md"}}})
        )
        (pack / "jobs/nightly.md").write_text("summarize the day\n")
        instance = self.start()
        result = subprocess.run(
            [sys.executable, str(self.root / "bin/abra"), "job", "nightly"],
            capture_output=True,
            text=True,
            timeout=30,
            env=dict(os.environ, ABRA_SPECIALTY_DIR=""),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("delivered to the resident runtime", result.stdout)
        self.wait_for(lambda: len(self.prompts()) == 1)
        self.assertTrue(instance.wait_idle(10))
        text = self.prompts()[0]
        self.assertIn("runtime event: scheduled job nightly", text)
        self.assertIn("summarize the day", text)
        unknown = subprocess.run(
            [sys.executable, str(self.root / "bin/abra"), "job", "missing"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(unknown.returncode, 1)

    def test_wakes_agent_that_does_not_wake_itself(self):
        self.configure(background=0.2)
        instance = self.start(wake_grace=0.3)
        instance.submit(event("start", "1", "go do-background"))
        self.wait_for(lambda: len(self.prompts()) == 2)
        self.assertIn(
            "runtime event: background work finished (1 tool calls)", self.prompts()[1]
        )
        time.sleep(1)
        self.assertEqual(len(self.prompts()), 2)
        self.assertEqual(instance.background, set())

    def test_no_wake_when_agent_wakes_itself(self):
        self.configure(background=0.2, wake=True)
        instance = self.start(wake_grace=0.5)
        instance.submit(event("start", "1", "go do-background"))
        self.wait_for(lambda: instance.background == set() and instance.finished == 0)
        time.sleep(1.2)
        self.assertEqual(len(self.prompts()), 1)
        self.assertIsNone(instance.wake_at)

    def test_heartbeat_only_with_tasks_in_flight(self):
        counts = []

        def busy():
            counts.append(2)
            return 2

        instance = self.start(heartbeat=0.3, inflight=busy)
        self.wait_for(lambda: len(self.prompts()) >= 1)
        self.assertIn(
            "runtime event: heartbeat: 2 tasks are in flight", self.prompts()[0]
        )
        instance.stop()
        self.log.unlink()
        (self.root / "data/triggers/resident.json").unlink()
        idle = self.start(heartbeat=0.2, inflight=lambda: 0)
        time.sleep(1)
        self.assertEqual(self.prompts(), [])
        self.assertIsNotNone(idle.beat_at)

    def test_inflight_count_from_tasks_cli(self):
        tasks = self.root / "bin/tasks"
        tasks.write_text("#!/bin/sh\necho 'count: 3'\necho 'tasks[3]{id}:'\n")
        tasks.chmod(0o755)
        instance = self.make()
        self.assertEqual(instance._inflight(), 3)
        tasks.write_text("#!/bin/sh\necho 'count: 3'\nexit 2\n")
        self.assertEqual(instance._inflight(), 0)
        tasks.unlink()
        self.assertEqual(instance._inflight(), 0)

    def test_idle_clear_checkpoints_then_starts_fresh(self):
        instance = self.start(idle_clear=0.3)
        instance.submit(event("start", "1", "hello"))
        self.wait_for(lambda: len(self.received("session/close")) == 1)
        self.assertIn("runtime event: " + resident.CHECKPOINT, self.prompts()[1])
        self.wait_for(lambda: instance.session is None)
        state = json.loads((self.root / "data/triggers/resident.json").read_text())
        self.assertIsNone(state["session_id"])
        instance.submit(event("message", "2", "back again"))
        self.wait_for(lambda: len(self.prompts()) == 3)
        self.assertEqual(len(self.received("session/new")), 2)
        self.assertIn(resident.BOOTSTRAP, self.prompts()[2])
        self.assertIn("back again", self.prompts()[2])

    def test_no_clear_while_background_work_runs(self):
        self.configure(background=5)
        instance = self.start(idle_clear=0.2)
        instance.submit(event("start", "1", "go do-background"))
        self.wait_for(lambda: instance.background == {"bg1"})
        time.sleep(1)
        self.assertEqual(len(self.prompts()), 1)
        self.assertEqual(self.received("session/close"), [])

    def test_rotation_after_max_age(self):
        state = self.root / "data/triggers"
        state.mkdir(parents=True, mode=0o700)
        instance = self.make(idle_clear=0, max_age=60, rotate_idle=0.2)
        runtime.write_private(
            state / "resident.json",
            {
                "version": 1,
                "agent": instance.digest,
                "session_id": "old-1",
                "started": "2000-01-01T00:00:00Z",
            },
        )
        instance.start()
        self.wait_for(lambda: len(self.received("session/close")) == 1)
        self.assertIn(resident.RESTART, self.prompts()[0])
        self.assertIn(resident.CHECKPOINT, self.prompts()[1])
        self.assertIsNone(instance.session)

    def test_stop_waits_for_running_turn(self):
        self.configure(slow=0.8)
        instance = self.start()
        instance.submit(event("start", "1", "work do-slow do-reply"))
        self.wait_for(lambda: len(self.prompts()) == 1)
        instance.stop()
        self.assertIn("re " + self.work_id(instance), self.adapter.replies())
        self.assertEqual(instance.convs["t:c1:1"]["pending"], [])

    def test_stop_timeout_keeps_messages_pending(self):
        instance = self.start(stop_timeout=0.3)
        instance.submit(event("start", "1", "wait do-hold"))
        self.wait_for(lambda: len(self.prompts()) == 1)
        process = instance.client.proc
        instance.stop()
        self.assertIsNotNone(process.poll())
        stored = json.loads((self.root / "data/triggers/test.json").read_text())
        self.assertEqual(len(stored["convs"]["t:c1:1"]["pending"]), 1)

    def test_stop_leaves_no_orphans(self):
        instance = self.start()
        instance.submit(event("start", "1", "do-spawn"))
        self.assertTrue(instance.wait_idle(10))
        pid = [e for e in self.received() if "spawned" in e][0]["spawned"]
        os.kill(pid, 0)
        instance.stop()

        def gone():
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            return False

        self.wait_for(gone)

    def run_cli(self, *texts):
        lines = "".join(
            json.dumps(
                {
                    "kind": "start" if index == 0 else "message",
                    "conv": "cli:demo:1",
                    "msg_id": str(index + 1),
                    "sender": "U1",
                    "text": text,
                }
            )
            + "\n"
            for index, text in enumerate(texts)
        )
        command = " ".join([sys.executable, str(FAKE), str(self.config_path)])
        return subprocess.run(
            [
                sys.executable,
                str(TESTS.parent / "triggers/cli.py"),
                "--root",
                str(self.root),
            ],
            input=lines,
            capture_output=True,
            text=True,
            timeout=60,
            env=dict(os.environ, ABRA_AGENT_CMD=command),
        )

    def test_cli_adapter_in_resident_mode(self):
        result = self.run_cli("hi do-reply", "again do-silent")
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        replies = [r["text"] for r in records if r["type"] == "reply"]
        self.assertEqual(len(replies), 2)
        self.assertTrue(replies[1].startswith("re abra-"))
        acks = [(r["msg_id"], r["state"]) for r in records if r["type"] == "ack"]
        self.assertEqual(acks, [("1", "running"), ("2", "running")])

    def test_cli_exits_non_zero_when_agent_crashes(self):
        result = self.run_cli("boom do-crash")
        self.assertEqual(result.returncode, 1)
        self.assertIn("the agent stopped", result.stderr)


if __name__ == "__main__":
    unittest.main()
