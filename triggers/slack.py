#!/usr/bin/env python3
"""slack adapter: socket mode events in, thread replies and reaction markers out."""

import argparse
from collections import OrderedDict
import logging
import os
import re
import signal
import sys
import threading

import runtime

CHANNEL = re.compile(r"[CG][A-Z0-9]{1,31}")
DIRECT = re.compile(r"D[A-Z0-9]{1,31}")
USER = re.compile(r"[UW][A-Z0-9]{1,31}")
BOT = re.compile(r"B[A-Z0-9]{1,31}")
TS = re.compile(r"[0-9]{1,12}\.[0-9]{1,9}")
CONV = re.compile(r"slack:([CG][A-Z0-9]{1,31}):([0-9]{1,12}\.[0-9]{1,9})")
CODE = re.compile(r"[a-z0-9_]{1,64}")
TOKEN = re.compile(r"[A-Za-z0-9-]{10,256}")
SECRET = re.compile(r"xox[a-z]-[A-Za-z0-9-]+|xapp-[A-Za-z0-9-]+|ticket=[^&\s]+")
# user replies that carry a subtype but are still ordinary thread messages
ALLOWED = ("thread_broadcast", "file_share")
MARKERS = {
    "queued": "hourglass_flowing_sand",
    "running": "eyes",
    "done": "white_check_mark",
    "failed": "x",
}
CHUNK = 3900
MAX_PAGES = 100
MAX_MARKERS = 10000
UNKNOWN = object()
log = runtime.log


def chunks(text, size=CHUNK):
    """split text into posts of at most size chars, preferring newline boundaries."""
    parts = []
    while len(text) > size:
        cut = text.rfind("\n", 0, size + 1)
        if cut <= 0:
            cut = size
            # never split an escaped entity such as &amp;
            amp = text.rfind("&", max(0, cut - 4), cut)
            if amp > 0 and ";" not in text[amp:cut]:
                cut = amp
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    parts.append(text)
    return [part for part in parts if part.strip()]


def escape(text):
    """neutralize slack control sequences: broadcasts, mentions, and links."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def order(ts):
    seconds, _, fraction = ts.partition(".")
    return int(seconds), int(fraction.ljust(9, "0"))


def error_code(error):
    """the slack error code of an api failure, else the exception type; never text."""
    response = getattr(error, "response", None)
    try:
        value = response.get("error") if response is not None else None
    except Exception:
        value = None
    if isinstance(value, str) and CODE.fullmatch(value):
        return value
    return type(error).__name__


class SlackAdapter:
    """maps slack events to runtime events; all slack calls go through client."""

    name = "slack"

    def __init__(self, client, bot):
        self.client = client
        self.bot = bot
        self.user_id = None
        self.bot_id = None
        self.mention = None
        self.lock = threading.Lock()
        self.markers = OrderedDict()

    def identify(self):
        """learn the bot user id from auth.test; fails closed."""
        response = self._call("auth_test")
        user_id = response.get("user_id") if response is not None else None
        bot_id = response.get("bot_id") if response is not None else None
        if not isinstance(user_id, str) or not USER.fullmatch(user_id):
            raise ValueError("slack auth.test did not return a valid bot user id")
        self.user_id = user_id
        self.bot_id = (
            bot_id if isinstance(bot_id, str) and BOT.fullmatch(bot_id) else None
        )
        self.mention = re.compile("<@" + user_id + r"(?:\|[^>]*)?>")
        log.info("connected to slack as %s", user_id)

    def _call(self, method, tolerate=(), **fields):
        """one api call; failures are logged by code and return none."""
        try:
            return getattr(self.client, method)(**fields)
        except Exception as error:
            code = error_code(error)
            if code not in tolerate:
                log.warning("slack %s failed: %s", method, code)
            return None

    def _sender(self, item):
        """sender for a slack message, or a reason string when it is ignored."""
        if item.get("user") == self.user_id or (
            self.bot_id and item.get("bot_id") == self.bot_id
        ):
            return None, "own post"
        if item.get("bot_id") or item.get("subtype") == "bot_message":
            return None, "bot post"
        subtype = item.get("subtype")
        if subtype is not None and subtype not in ALLOWED:
            return None, "subtype"
        user = item.get("user")
        if not isinstance(user, str) or not USER.fullmatch(user):
            return None, "invalid user"
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            return None, "empty text"
        return user, None

    def _ignore(self, conv, msg_id, reason):
        log.info("ignoring slack event %s in %s: %s", msg_id, conv, reason)
        return None

    def intake(self, event, mention):
        """runtime event for an app_mention (mention) or message event, else none."""
        if self.mention is None:
            raise ValueError("identify must run before intake")
        if not isinstance(event, dict):
            return self._ignore(None, None, "not an object")
        channel, ts, thread = (event.get(k) for k in ("channel", "ts", "thread_ts"))
        if isinstance(channel, str) and DIRECT.fullmatch(channel):
            return self._ignore(None, None, "direct or group message")
        if not isinstance(channel, str) or not CHANNEL.fullmatch(channel):
            return self._ignore(None, None, "invalid channel")
        if not isinstance(ts, str) or not TS.fullmatch(ts):
            return self._ignore(None, None, "invalid ts")
        if thread is not None and (
            not isinstance(thread, str) or not TS.fullmatch(thread)
        ):
            return self._ignore(None, ts, "invalid thread ts")
        conv = "slack:" + channel + ":" + (thread or ts)
        user, reason = self._sender(event)
        if reason:
            return self._ignore(conv, ts, reason)
        text = event["text"]
        channel_type = event.get("channel_type")
        if channel_type in ("im", "mpim"):
            return self._ignore(conv, ts, "direct or group message")
        if not mention:
            if channel_type not in ("channel", "group"):
                return self._ignore(conv, ts, "not a channel message")
            if thread is None or thread == ts:
                return self._ignore(conv, ts, "top-level message")
            if self.mention.search(text):
                return self._ignore(conv, ts, "mention handled by app_mention")
        with self.lock:
            # a message seen at intake has no marker yet
            self.markers.setdefault((channel, ts), None)
            self._trim()
        kind = "start" if mention else "message"
        return runtime.Event(kind, conv, ts, user, self.rewrite(text))

    def rewrite(self, text):
        return self.mention.sub("@" + self.bot, text)

    def _trim(self):
        while len(self.markers) > MAX_MARKERS:
            self.markers.popitem(last=False)

    @staticmethod
    def split(conv):
        match = CONV.fullmatch(conv) if isinstance(conv, str) else None
        if not match:
            raise ValueError("not a slack conversation key")
        return match.groups()

    # runtime output

    def reply(self, conv, text):
        channel, thread = self.split(conv)
        for part in chunks(escape(text)):
            response = self._call(
                "chat_postMessage",
                channel=channel,
                thread_ts=thread,
                text=part,
                unfurl_links=False,
                unfurl_media=False,
            )
            if response is None:
                return

    def ack(self, conv, msg_id, state):
        channel, _ = self.split(conv)
        if not isinstance(msg_id, str) or not TS.fullmatch(msg_id):
            raise ValueError("not a slack message ts")
        marker = MARKERS[state]
        key = (channel, msg_id)
        with self.lock:
            previous = self.markers.pop(key, UNKNOWN)
            self.markers[key] = state
            self._trim()
        if previous == state:
            return
        if previous is UNKNOWN:
            # after a restart the old marker is unknown, so clear every other one
            stale = [name for name in MARKERS.values() if name != marker]
        else:
            stale = [MARKERS[previous]] if previous else []
        self._call(
            "reactions_add",
            tolerate=("already_reacted",),
            channel=channel,
            timestamp=msg_id,
            name=marker,
        )
        for name in stale:
            self._call(
                "reactions_remove",
                tolerate=("no_reaction",),
                channel=channel,
                timestamp=msg_id,
                name=name,
            )

    def history(self, conv):
        channel, thread = self.split(conv)
        seen = {}
        cursor = None
        for _ in range(MAX_PAGES):
            fields = dict(channel=channel, ts=thread, limit=200)
            if cursor:
                fields["cursor"] = cursor
            response = self._call("conversations_replies", **fields)
            if response is None:
                return []
            messages = response.get("messages")
            for item in messages if isinstance(messages, list) else []:
                message = self._history_item(item)
                if message:
                    seen[message.msg_id] = message
            metadata = response.get("response_metadata")
            cursor = metadata.get("next_cursor") if isinstance(metadata, dict) else None
            if not isinstance(cursor, str) or not cursor:
                break
        else:
            log.warning("history for %s truncated at %d pages", conv, MAX_PAGES)
        return [seen[ts] for ts in sorted(seen, key=order)]

    def _history_item(self, item):
        if not isinstance(item, dict):
            return None
        ts, text = item.get("ts"), item.get("text")
        if not isinstance(ts, str) or not TS.fullmatch(ts):
            return None
        user, reason = self._sender(item)
        if reason == "own post" and isinstance(text, str) and text.strip():
            return runtime.Message(ts, self.bot, self.rewrite(text))
        if reason:
            return None
        return runtime.Message(ts, user, self.rewrite(text))


class Redact(logging.Filter):
    """defense in depth for library log lines: drop tracebacks, mask credentials."""

    def filter(self, record):
        message = record.getMessage()
        clean = SECRET.sub("[redacted]", message)
        if clean != message:
            record.msg, record.args = clean, None
        record.exc_info = record.exc_text = None
        return True


def build(bot_token, app_token):
    """the real bolt app and socket mode handler; slack_bolt is imported only here."""
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler
    from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

    app = App(token=bot_token)
    app.client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=2))
    return app, SocketModeHandler(app, app_token)


def tokens(env):
    """bot and app tokens from env; raises valueerror naming the variable only."""
    values = []
    for variable, prefix in (
        ("SLACK_BOT_TOKEN", "xoxb-"),
        ("SLACK_APP_TOKEN", "xapp-"),
    ):
        value = env.get(variable, "")
        if not value:
            raise ValueError(variable.lower() + " is not set")
        if not value.startswith(prefix) or not TOKEN.fullmatch(value):
            raise ValueError(variable.lower() + " is not a valid " + prefix + " token")
        values.append(value)
    return values


def main(argv=None, env=None, connect=build):
    parser = argparse.ArgumentParser(description=__doc__)
    runtime.add_arguments(parser)
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("triggers: %(message)s"))
    handler.addFilter(Redact())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    for name in ("slack_bolt", "slack_sdk"):
        logging.getLogger(name).setLevel(logging.WARNING)
    adapter = SlackAdapter(None, args.name)
    try:
        bot_token, app_token = tokens(env)
        instance = runtime.from_args(adapter, args, env)
    except ValueError as error:
        log.error("error: %s", error)
        return 1
    try:
        app, socket = connect(bot_token, app_token)
    except ImportError:
        log.error(
            "error: slack_bolt is not installed;"
            " pip install -r triggers/requirements-slack.txt"
        )
        return 1
    except Exception as error:
        log.error(
            "error: could not create the slack app (check slack_bot_token): %s",
            error_code(error),
        )
        return 1
    adapter.client = app.client
    try:
        adapter.identify()
        instance.start()
    except (ValueError, OSError) as error:
        log.error("error: %s", error)
        return 1

    def listener(mention):
        def handle(event):
            try:
                item = adapter.intake(event, mention)
                if item:
                    instance.submit(item)
            except Exception as error:
                log.error("slack event handling failed: %s", type(error).__name__)

        return handle

    app.event("app_mention")(listener(True))
    app.event("message")(listener(False))
    done = threading.Event()
    previous = {}
    for number in (signal.SIGINT, signal.SIGTERM):
        previous[number] = signal.signal(number, lambda *_: done.set())
    try:
        socket.connect()
        log.info("listening for slack events as %s", args.name)
        while not done.wait(1):
            if instance.crashed.is_set():
                break
        log.info("shutting down; pending messages stay stored")
    except Exception as error:
        log.error("slack connection failed: %s", error_code(error))
        return 1
    finally:
        for number, action in previous.items():
            signal.signal(number, action)
        try:
            socket.close()
        except Exception as error:
            log.warning("could not close slack connection: %s", error_code(error))
        instance.stop()
    if instance.crashed.is_set():
        log.error("error: the agent stopped; pending messages stay stored")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
