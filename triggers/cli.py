#!/usr/bin/env python3
"""reference trigger adapter: json-lines events on stdin, replies and acks on stdout."""

import argparse
import json
import logging
import os
import signal
import sys
import threading

import runtime


class LinesAdapter:
    """serves history from the events and replies this process has seen."""

    name = "cli"

    def __init__(self, bot, out):
        self.bot = bot
        self.out = out
        self.lock = threading.Lock()
        self.seen = {}
        self.posts = 0

    def emit(self, record):
        with self.lock:
            self.out.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.out.flush()

    def remember(self, conv, msg_id, sender, text):
        with self.lock:
            self.seen.setdefault(conv, []).append(runtime.Message(msg_id, sender, text))

    def reply(self, conv, text):
        with self.lock:
            self.posts += 1
            msg_id = "bot-" + str(self.posts)
        self.remember(conv, msg_id, self.bot, text)
        self.emit({"type": "reply", "conv": conv, "text": text})

    def ack(self, conv, msg_id, state):
        self.emit({"type": "ack", "conv": conv, "msg_id": msg_id, "state": state})

    def history(self, conv):
        with self.lock:
            return list(self.seen.get(conv, []))


def parse(line):
    """one json-lines event, or none when the line is not a valid event object."""
    try:
        record = json.loads(line)
    except (ValueError, RecursionError):
        return None
    if not isinstance(record, dict):
        return None
    fields = [record.get(field) for field in runtime.Event._fields]
    if not all(isinstance(value, str) for value in fields):
        return None
    return runtime.Event(*fields)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    runtime.add_arguments(parser)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="triggers: %(message)s", stream=sys.stderr
    )
    adapter = LinesAdapter(args.name, sys.stdout)
    try:
        instance = runtime.from_args(adapter, args, os.environ)
        instance.start()
    except (ValueError, OSError) as error:
        runtime.log.error("error: %s", error)
        return 1

    def terminate(signum, frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        for number, line in enumerate(sys.stdin, 1):
            if not line.strip():
                continue
            event = parse(line)
            if event is None:
                runtime.log.warning("ignoring invalid event on line %d", number)
                continue
            adapter.remember(event.conv, event.msg_id, event.sender, event.text)
            instance.submit(event)
            if instance.crashed.is_set():
                break
        instance.wait_idle()
    except KeyboardInterrupt:
        runtime.log.info("interrupted; pending messages stay stored")
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        instance.stop()
        signal.signal(signal.SIGTERM, previous)
    if instance.crashed.is_set():
        runtime.log.error("error: the agent stopped; pending messages stay stored")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
