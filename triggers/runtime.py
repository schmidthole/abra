"""shared trigger runtime base: event intake, the conversation store, catch-up, and
bridge replies. the resident backend in resident.py runs the agent session."""

from collections import deque, namedtuple
from datetime import datetime, timezone
import fcntl
import json
import logging
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time

KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,127}")
REQUESTER = re.compile(r"[A-Za-z0-9][A-Za-z0-9@:._ -]{0,127}")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,31}")
ADAPTER = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
WORK = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+){0,31}")
TOOL_USE = re.compile(r"[A-Za-z0-9_-]{1,128}")
BASE32 = "abcdefghijklmnopqrstuvwxyz234567"
MAX_TEXT = 32 * 1024
MAX_BATCH = 50
MAX_PENDING = 200
MAX_CONTEXT = 256 * 1024
REPLY_LIMIT = 20
REPLY_WINDOW = 60
DAY = 24 * 3600
STAMP = "%Y-%m-%dT%H:%M:%SZ"

Event = namedtuple("Event", "kind conv msg_id sender text")
Message = namedtuple("Message", "msg_id sender text")
log = logging.getLogger("abra.triggers")


def announcement(name, work_id):
    return (
        name
        + " is on it. this thread is now work item "
        + work_id
        + ". reply in this thread to add to it."
    )


def error_text(name):
    return name + " hit an error on this turn. reply here to try again."


def now():
    return datetime.now(timezone.utc).strftime(STAMP)


def seconds(stamp):
    """parse a stored timestamp; missing or unparsable counts as the epoch."""
    try:
        moment = datetime.strptime(stamp, STAMP).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return 0.0
    return moment.timestamp()


def encoded(messages):
    return json.dumps(messages, ensure_ascii=False).encode("utf-8")


def valid_message(msg_id, sender, text):
    """return the bin/abra message for valid input, else raise valueerror."""
    if not isinstance(msg_id, str) or not KEY.fullmatch(msg_id):
        raise ValueError("invalid msg id")
    if not isinstance(sender, str) or not REQUESTER.fullmatch(sender):
        raise ValueError("invalid sender")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty or non-text message")
    try:
        size = len(encoded([{"from": sender, "text": text}]))
    except UnicodeEncodeError:
        raise ValueError("message is not valid unicode") from None
    if size > MAX_TEXT:
        raise ValueError("message exceeds " + str(MAX_TEXT) + " bytes")
    return dict(msg_id=msg_id, sender=sender, text=text)


def clip(text):
    return text.encode("utf-8", "replace")[:MAX_TEXT].decode("utf-8", "ignore")


class Runtime:
    """intake and store for one adapter; resident.Resident adds the agent session."""

    def __init__(self, adapter, root, name="abra", catchup_hours=24):
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise ValueError("name must match " + NAME.pattern)
        if isinstance(catchup_hours, bool) or not isinstance(catchup_hours, int):
            raise ValueError("catchup_hours must be an integer")
        if catchup_hours < 0:
            raise ValueError("catchup_hours must not be negative")
        adapter_name = getattr(adapter, "name", None)
        if not isinstance(adapter_name, str) or not ADAPTER.fullmatch(adapter_name):
            raise ValueError("adapter name must match " + ADAPTER.pattern)
        self.root = Path(root).resolve()
        self.abra = self.root / "bin/abra"
        if not self.root.is_dir():
            raise ValueError("root is not a directory")
        if not self.abra.is_file() or not os.access(self.abra, os.X_OK):
            raise ValueError("root has no executable bin/abra")
        self.adapter = adapter
        self.name = name
        self.slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        self.catchup_hours = catchup_hours
        self.directory = self.root / "data/triggers"
        self.path = self.directory / (adapter_name + ".json")
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.stopping = threading.Event()
        self.crashed = threading.Event()
        self.convs = {}
        self.holder = None
        self.replies = {}
        self.replied = set()

    # lifecycle

    def _open(self):
        """private directories, the instance lock, stale temp files, and the store."""
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        descriptor = os.open(
            self.path.with_suffix(".lock"),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        holder = os.fdopen(descriptor, "a")
        try:
            fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder.close()
            raise ValueError("another runtime already owns " + self.path.name)
        self.holder = holder
        # only this runtime's temp files: other adapters may share the root
        stale = list(self.directory.glob("." + self.path.name + "*.tmp"))
        stale += list(self.directory.glob(".resident.json*.tmp"))
        stale += list(self.directory.glob(".bridge.json*.tmp"))
        for path in stale:
            path.unlink()
        if stale:
            log.info("removed %d stale temporary files", len(stale))
        with self.lock:
            self.convs = self._load()
        log.info("starting %s with %d conversations", self.path.name, len(self.convs))

    # intake

    def submit(self, event):
        """accept one event from the adapter; returns true when it was queued."""
        try:
            if not isinstance(event, Event):
                raise ValueError("not an event")
            if event.kind not in ("start", "message"):
                raise ValueError("invalid kind")
            if not isinstance(event.conv, str) or not KEY.fullmatch(event.conv):
                raise ValueError("invalid conversation key")
            message = valid_message(event.msg_id, event.sender, event.text)
        except ValueError as error:
            log.warning("ignoring invalid event: %s", error)
            return False
        conv = event.conv
        try:
            with self.lock:
                entry = self.convs.get(conv)
                if entry is None:
                    if event.kind != "start":
                        log.info(
                            "ignoring message %s for unknown conversation %s",
                            event.msg_id,
                            conv,
                        )
                        return False
                    entry = self._create(conv)
                return self._enqueue(conv, entry, message)
        except OSError as error:
            log.error("could not store event for %s: %s", conv, type(error).__name__)
            return False

    def _create(self, conv):
        work_id = self._mint()
        stamp = now()
        entry = dict(
            work_id=work_id,
            created=stamp,
            last_used=stamp,
            last_msg_id=None,
            pending=[],
        )
        self.convs[conv] = entry
        try:
            self._save()
        except OSError:
            del self.convs[conv]
            raise
        log.info("started %s as work item %s", conv, work_id)
        self._reply(conv, announcement(self.name, work_id))
        return entry

    def _mint(self):
        taken = {entry["work_id"] for entry in self.convs.values()}
        while True:
            suffix = "".join(secrets.choice(BASE32) for _ in range(4))
            work_id = self.slug + "-" + suffix
            if work_id not in taken and not (self.root / "data" / work_id).exists():
                return work_id

    def _duplicate(self, conv, entry, msg_id):
        pending = {m["msg_id"] for m in entry["pending"]}
        if msg_id in pending or msg_id == entry["last_msg_id"]:
            log.info("ignoring duplicate message %s for %s", msg_id, conv)
            return True
        return False

    def _enqueue(self, conv, entry, message):
        if self._duplicate(conv, entry, message["msg_id"]):
            return False
        if len(entry["pending"]) >= MAX_PENDING:
            log.warning(
                "dropping message %s for %s: %d messages already pending",
                message["msg_id"],
                conv,
                MAX_PENDING,
            )
            self._ack(conv, message["msg_id"], "failed")
            return False
        previous = entry["last_msg_id"]
        entry["pending"].append(message)
        entry["last_msg_id"] = message["msg_id"]
        try:
            self._save()
        except OSError:
            entry["pending"].pop()
            entry["last_msg_id"] = previous
            raise
        log.info(
            "queued message %s from %s for %s",
            message["msg_id"],
            message["sender"],
            conv,
        )
        self._schedule(conv)
        return True

    def _schedule(self, conv):
        """queue a conversation's pending messages; the backend implements it."""
        raise NotImplementedError

    # catch-up

    def _catch_up(self):
        cutoff = time.time() - self.catchup_hours * 3600
        with self.lock:
            for conv, entry in list(self.convs.items()):
                if seconds(entry["last_used"]) < cutoff:
                    continue
                history = self._history(conv)
                ids = [item.msg_id for item in history]
                if entry["last_msg_id"] not in ids:
                    log.warning(
                        "cannot find last message for %s; skipping catch-up", conv
                    )
                    continue
                count = 0
                for item in history[ids.index(entry["last_msg_id"]) + 1 :]:
                    if item.sender == self.name:
                        continue
                    try:
                        message = valid_message(item.msg_id, item.sender, item.text)
                    except ValueError as error:
                        log.warning("skipping missed message for %s: %s", conv, error)
                        continue
                    count += self._enqueue(conv, entry, message)
                if count:
                    log.info("caught up %d missed messages for %s", count, conv)

    # bridge requests from the agent's reply tool

    def bridge(self, request):
        """answer one authenticated bridge request; valueerror rejects it."""
        if request.get("op") != "reply":
            raise ValueError("unknown op")
        work_id = request.get("work_id")
        text = request.get("text")
        use = request.get("tool_use_id")
        use = use if isinstance(use, str) and TOOL_USE.fullmatch(use) else "none"
        if not isinstance(work_id, str) or not WORK.fullmatch(work_id):
            raise ValueError("invalid work id")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be non-empty")
        try:
            size = len(text.encode("utf-8"))
        except UnicodeEncodeError:
            raise ValueError("text is not valid unicode") from None
        if size > MAX_TEXT:
            raise ValueError("text exceeds " + str(MAX_TEXT) + " bytes")
        with self.lock:
            conv = next(
                (c for c, e in self.convs.items() if e["work_id"] == work_id), None
            )
            if conv is None:
                log.warning("bridge reply for unknown work item (tool use %s)", use)
                raise ValueError("unknown work id")
            recent = self.replies.setdefault(conv, deque())
            moment = time.monotonic()
            while recent and moment - recent[0] > REPLY_WINDOW:
                recent.popleft()
            if len(recent) >= REPLY_LIMIT:
                log.warning("bridge reply rate limited for %s (tool use %s)", conv, use)
                raise ValueError("rate limited; wait before replying again")
            recent.append(moment)
            self.replied.add(conv)
        log.info(
            "bridge reply for %s in %s: %d bytes (tool use %s)",
            work_id,
            conv,
            size,
            use,
        )
        self._reply(conv, text)
        return {"ok": True}

    # adapter calls never raise into the runtime

    def _reply(self, conv, text):
        try:
            self.adapter.reply(conv, text)
        except Exception as error:
            log.error("adapter reply failed for %s: %s", conv, type(error).__name__)

    def _ack(self, conv, msg_id, state):
        try:
            self.adapter.ack(conv, msg_id, state)
        except Exception as error:
            log.error("adapter ack failed for %s: %s", conv, type(error).__name__)

    def _history(self, conv):
        try:
            items = list(self.adapter.history(conv))
        except Exception as error:
            log.error("adapter history failed for %s: %s", conv, type(error).__name__)
            return []
        return [
            item
            for item in items
            if isinstance(getattr(item, "msg_id", None), str)
            and isinstance(getattr(item, "sender", None), str)
            and isinstance(getattr(item, "text", None), str)
        ]

    # store

    def _load(self):
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, RecursionError):
            raise ValueError(self.path.name + " is not valid json") from None
        if not isinstance(data, dict) or not isinstance(data.get("convs"), dict):
            raise ValueError(self.path.name + " must hold a convs object")
        convs = {}
        for conv, entry in data["convs"].items():
            if (
                not KEY.fullmatch(conv)
                or not isinstance(entry, dict)
                or not isinstance(entry.get("work_id"), str)
                or not WORK.fullmatch(entry["work_id"])
            ):
                log.warning("dropping invalid stored conversation")
                continue
            pending = []
            for item in entry.get("pending") or []:
                try:
                    pending.append(
                        valid_message(item["msg_id"], item["sender"], item["text"])
                    )
                except (ValueError, KeyError, TypeError):
                    log.warning("dropping invalid pending message for %s", conv)
            # one-shot era fields (session_id, archived, fresh, resumed) are dropped
            last_msg_id = entry.get("last_msg_id")
            convs[conv] = dict(
                work_id=entry["work_id"],
                created=str(entry.get("created", "")),
                last_used=str(entry.get("last_used", "")),
                last_msg_id=last_msg_id if isinstance(last_msg_id, str) else None,
                pending=pending,
            )
        return convs

    def _save(self):
        """atomic 0600 write; caller holds self.lock."""
        write_private(self.path, {"version": 1, "convs": self.convs})


def write_private(path, value):
    """atomically replace path with json, readable only by the owner."""
    data = json.dumps(value, indent=2, ensure_ascii=False)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix="." + path.name, suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(data + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def add_arguments(parser):
    parser.add_argument("--root", required=True, help="abra instance root")
    parser.add_argument("--name", default="abra", help="bot name, default abra")


def from_args(adapter, args, env, **options):
    """build the resident runtime from --root/--name and the environment."""
    import resident

    return resident.from_env(adapter, args, env, **options)
