"""shared trigger runtime: turns conversation events into bin/abra turns."""

from collections import namedtuple
from datetime import datetime, timezone
import fcntl
import json
import logging
import os
from pathlib import Path
import queue
import re
import secrets
import stat
import subprocess
import tempfile
import threading
import time
import uuid


KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,127}")
REQUESTER = re.compile(r"[A-Za-z0-9][A-Za-z0-9@:._ -]{0,127}")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,31}")
ADAPTER = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
WORK = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+){0,31}")
UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
BASE32 = "abcdefghijklmnopqrstuvwxyz234567"
MAX_TEXT = 32 * 1024
MAX_BATCH = 50
MAX_PENDING = 200
MAX_CONTEXT = 256 * 1024
BUSY = 75
DAY = 24 * 3600
STAMP = "%Y-%m-%dT%H:%M:%SZ"
STATES = ("queued", "running", "done", "failed")

Event = namedtuple("Event", "kind conv msg_id sender text")
Message = namedtuple("Message", "msg_id sender text")
log = logging.getLogger("abra.triggers")


def announcement(name, work_id, session_id):
    return (
        name
        + " is on it. this thread is now work item "
        + work_id
        + " (session "
        + session_id
        + "). reply in this thread to add to it."
    )


def resume_text(name, work_id, session_id):
    return name + " is resuming work item " + work_id + " (session " + session_id + ")."


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


def positive(value, label, high):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= high:
        raise ValueError(label + " must be an integer from 1 to " + str(high))
    return value


def take(pending):
    """the longest prefix of pending that fits one bin/abra messages file."""
    batch = []
    for message in pending[:MAX_BATCH]:
        candidate = batch + [message]
        if (
            len(encoded([{"from": m["sender"], "text": m["text"]} for m in candidate]))
            > MAX_TEXT
        ):
            break
        batch = candidate
    return batch


def clip(text):
    return text.encode("utf-8", "replace")[:MAX_TEXT].decode("utf-8", "ignore")


def context(history, work_id, exclude):
    """prior history for resurrection: first message plus the most recent that fit."""
    note = (
        "note: this conversation was archived and resumes in a new session. the"
        " task body and reports for work item "
        + work_id
        + " are in data/"
        + work_id
        + "/; read them before acting. the prior conversation follows.\n\n"
    ).encode("utf-8")
    entries = [
        ("[" + m.msg_id + "] " + m.sender + ":\n" + clip(m.text) + "\n\n").encode(
            "utf-8"
        )
        for m in history
        if m.msg_id not in exclude
    ]
    if not entries:
        return note
    budget = MAX_CONTEXT - len(note) - len(entries[0]) - 64
    recent = []
    for entry in reversed(entries[1:]):
        if len(entry) > budget:
            break
        recent.insert(0, entry)
        budget -= len(entry)
    omitted = len(entries) - 1 - len(recent)
    gap = []
    if omitted:
        gap = [("[" + str(omitted) + " messages omitted]\n\n").encode("utf-8")]
    return b"".join([note, entries[0]] + gap + recent)


class Runtime:
    """one runtime per adapter process; many may run against different roots."""

    def __init__(
        self,
        adapter,
        root,
        name="abra",
        archive_days=90,
        workers=2,
        catchup_hours=24,
        backoff=None,
    ):
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise ValueError("name must match " + NAME.pattern)
        self.archive_days = positive(archive_days, "archive_days", 3650)
        self.workers = positive(workers, "workers", 64)
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
        self.backoff = backoff or (lambda attempt: min(300, 5 * 2**attempt))
        self.directory = self.root / "data/triggers"
        self.path = self.directory / (adapter_name + ".json")
        self.scratch = self.directory / "tmp" / adapter_name
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.stopping = threading.Event()
        self.ready = queue.Queue()
        self.convs = {}
        self.scheduled = set()
        self.retries = {}
        self.timers = {}
        self.threads = []
        self.holder = None

    # lifecycle

    def start(self):
        # refuse symlinked or non-directory temp dirs before any chmod or sweep
        for directory in (self.directory / "tmp", self.scratch):
            try:
                mode = os.lstat(directory).st_mode
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(mode):
                raise ValueError(
                    str(directory.relative_to(self.root))
                    + " must be a real directory, not a symlink or file"
                )
        for directory in (self.directory, self.directory / "tmp", self.scratch):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)
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
        # only this adapter's temp files: other adapters may share the root
        stale = [path for path in self.scratch.iterdir() if path.is_file()]
        stale += list(self.directory.glob("." + self.path.name + "*.tmp"))
        for path in stale:
            path.unlink()
        if stale:
            log.info("removed %d stale temporary files", len(stale))
        with self.lock:
            self.convs = self._load()
        log.info("starting %s with %d conversations", self.path.name, len(self.convs))
        self.archive()
        with self.lock:
            for conv, entry in self.convs.items():
                for message in entry["pending"]:
                    self._ack(conv, message["msg_id"], "queued")
                if entry["pending"]:
                    self._schedule(conv)
        self._catch_up()
        for _ in range(self.workers):
            thread = threading.Thread(target=self._work, daemon=True)
            thread.start()
            self.threads.append(thread)
        thread = threading.Thread(target=self._archive_loop, daemon=True)
        thread.start()
        self.threads.append(thread)

    def stop(self):
        """stop intake scheduling, let running turns finish, keep pending stored."""
        self.stopping.set()
        with self.lock:
            for conv, timer in self.timers.items():
                timer.cancel()
                self.scheduled.discard(conv)
            self.timers.clear()
            self.changed.notify_all()
        for _ in range(self.workers):
            self.ready.put(None)
        for thread in self.threads:
            thread.join()
        self.threads = []
        if self.holder:
            self.holder.close()
            self.holder = None
        log.info("stopped %s", self.path.name)

    def wait_idle(self, timeout=None):
        """block until no conversation has queued or running work."""
        with self.changed:
            return self.changed.wait_for(lambda: not self.scheduled, timeout)

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
                elif entry["archived"]:
                    if self._duplicate(conv, entry, message["msg_id"]):
                        return False
                    self._resurrect(conv, entry)
                return self._enqueue(conv, entry, message)
        except OSError as error:
            log.error("could not store event for %s: %s", conv, type(error).__name__)
            return False

    def _create(self, conv):
        work_id = self._mint()
        session_id = str(uuid.uuid4())
        stamp = now()
        entry = dict(
            work_id=work_id,
            session_id=session_id,
            created=stamp,
            last_used=stamp,
            last_msg_id=None,
            archived=False,
            fresh=True,
            resumed=False,
            pending=[],
        )
        self.convs[conv] = entry
        try:
            self._save()
        except OSError:
            del self.convs[conv]
            raise
        log.info("started %s as work item %s", conv, work_id)
        self._reply(conv, announcement(self.name, work_id, session_id))
        return entry

    def _mint(self):
        taken = {entry["work_id"] for entry in self.convs.values()}
        while True:
            suffix = "".join(secrets.choice(BASE32) for _ in range(4))
            work_id = self.slug + "-" + suffix
            if work_id not in taken and not (self.root / "data" / work_id).exists():
                return work_id

    def _resurrect(self, conv, entry):
        entry.update(
            session_id=str(uuid.uuid4()),
            archived=False,
            fresh=True,
            resumed=True,
            last_used=now(),
        )
        self._save()
        log.info("resurrecting %s as work item %s", conv, entry["work_id"])
        self._reply(conv, resume_text(self.name, entry["work_id"], entry["session_id"]))

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
        self._ack(conv, message["msg_id"], "queued")
        self._schedule(conv)
        return True

    def _schedule(self, conv):
        if conv not in self.scheduled:
            self.scheduled.add(conv)
            self.ready.put(conv)

    # turns

    def _work(self):
        while True:
            conv = self.ready.get()
            if conv is None:
                return
            if self.stopping.is_set():
                self._finish(conv)
                continue
            try:
                self._turn(conv)
            except Exception as error:
                log.error("turn crashed for %s: %s", conv, type(error).__name__)
                self._finish(conv)

    def _turn(self, conv):
        with self.lock:
            entry = self.convs[conv]
            batch = take(entry["pending"])
            work_id = entry["work_id"]
            session_id = entry["session_id"] if entry["fresh"] else None
            resumed = entry["resumed"]
        if not batch:
            self._finish(conv)
            return
        ids = [m["msg_id"] for m in batch]
        for msg_id in ids:
            self._ack(conv, msg_id, "running")
        prior = self._context(conv, work_id, set(ids)) if resumed else None
        log.info("running %d messages for %s as %s", len(batch), conv, work_id)
        code, output = self._run(conv, batch, work_id, session_id, prior)
        if code == BUSY:
            for msg_id in ids:
                self._ack(conv, msg_id, "queued")
            with self.lock:
                attempt = self.retries.get(conv, 0)
                self.retries[conv] = attempt + 1
                if self.stopping.is_set():
                    self.scheduled.discard(conv)
                    self.changed.notify_all()
                    return
                delay = self.backoff(attempt)
                timer = threading.Timer(delay, self._retry, [conv])
                timer.daemon = True
                self.timers[conv] = timer
                timer.start()
            log.info("abra busy for %s; retrying in %ss", conv, delay)
            return
        with self.lock:
            self.retries.pop(conv, None)
            done = set(ids)
            entry["pending"] = [m for m in entry["pending"] if m["msg_id"] not in done]
            # resumed stays set until a turn succeeds; bin/abra ignores the context
            # once a session is stored. fresh clears because bin/abra rejects
            # --session-id when the key already has a session.
            entry.update(fresh=False, last_used=now())
            if code == 0:
                entry["resumed"] = False
            self._save()
        if code == 0:
            log.info("finished turn for %s", conv)
            if output.strip():
                self._reply(conv, output.strip())
            state = "done"
        else:
            log.warning("turn failed for %s with exit code %s", conv, code)
            self._reply(conv, error_text(self.name))
            state = "failed"
        for msg_id in ids:
            self._ack(conv, msg_id, state)
        self._finish(conv)

    def _retry(self, conv):
        with self.lock:
            self.timers.pop(conv, None)
            if not self.stopping.is_set():
                self.ready.put(conv)

    def _finish(self, conv):
        with self.lock:
            entry = self.convs.get(conv)
            if entry and entry["pending"] and not self.stopping.is_set():
                self.ready.put(conv)
            else:
                self.scheduled.discard(conv)
                self.changed.notify_all()

    def _temporary(self, data):
        descriptor, path = tempfile.mkstemp(dir=self.scratch)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
        except BaseException:
            os.unlink(path)
            raise
        return path

    def _run(self, conv, batch, work_id, session_id, prior):
        """one bin/abra turn; returns (exit code, stdout). stderr is never captured."""
        paths = []
        try:
            messages = [{"from": m["sender"], "text": m["text"]} for m in batch]
            paths.append(self._temporary(encoded(messages)))
            argv = [str(self.abra), "run", "--key", conv, "--messages-file", paths[0]]
            argv += ["--work-id", work_id]
            if session_id:
                argv += ["--session-id", session_id]
            if prior is not None:
                paths.append(self._temporary(prior))
                argv += ["--context-file", paths[1]]
            result = subprocess.run(
                argv,
                cwd=self.root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
            )
            return result.returncode, result.stdout
        except OSError as error:
            log.error("could not run bin/abra for %s: %s", conv, type(error).__name__)
            return 1, ""
        finally:
            for path in paths:
                try:
                    os.unlink(path)
                except OSError:
                    log.warning("could not remove a temporary file for %s", conv)

    def _context(self, conv, work_id, exclude):
        history = []
        for item in self._history(conv):
            msg_id = item.msg_id if KEY.fullmatch(item.msg_id) else "unknown"
            sender = item.sender if REQUESTER.fullmatch(item.sender) else "unknown"
            history.append(Message(msg_id, sender, item.text))
        log.info(
            "built resurrection context for %s from %d messages", conv, len(history)
        )
        return context(history, work_id, exclude)

    # archive and catch-up

    def archive(self):
        """archive idle conversations and prune their bin/abra sessions."""
        cutoff = time.time() - self.archive_days * DAY
        with self.lock:
            count = 0
            for conv, entry in self.convs.items():
                idle = conv not in self.scheduled and not entry["pending"]
                if (
                    not entry["archived"]
                    and idle
                    and seconds(entry["last_used"]) < cutoff
                ):
                    entry.update(archived=True, session_id=None)
                    log.info("archived %s (work item %s)", conv, entry["work_id"])
                    count += 1
            if count:
                self._save()
        argv = [str(self.abra), "sessions", "prune", "--older-than"]
        try:
            result = subprocess.run(
                argv + [str(self.archive_days)],
                cwd=self.root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as error:
            log.error("could not run session prune: %s", type(error).__name__)
            return
        if result.returncode:
            log.warning("session prune exited with code %d", result.returncode)
        else:
            log.info("pruned %d sessions", len(result.stdout.split()))

    def _archive_loop(self):
        while not self.stopping.wait(DAY):
            try:
                self.archive()
            except Exception as error:
                log.error("archive pass failed: %s", type(error).__name__)

    def _catch_up(self):
        cutoff = time.time() - self.catchup_hours * 3600
        with self.lock:
            for conv, entry in list(self.convs.items()):
                if entry["archived"] or seconds(entry["last_used"]) < cutoff:
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
            session_id = entry.get("session_id")
            last_msg_id = entry.get("last_msg_id")
            convs[conv] = dict(
                work_id=entry["work_id"],
                session_id=(
                    session_id
                    if isinstance(session_id, str) and UUID.fullmatch(session_id)
                    else None
                ),
                created=str(entry.get("created", "")),
                last_used=str(entry.get("last_used", "")),
                last_msg_id=last_msg_id if isinstance(last_msg_id, str) else None,
                archived=entry.get("archived") is True,
                fresh=entry.get("fresh") is True,
                resumed=entry.get("resumed") is True,
                pending=pending,
            )
        return convs

    def _save(self):
        """atomic 0600 write; caller holds self.lock."""
        data = json.dumps(
            {"version": 1, "convs": self.convs}, indent=2, ensure_ascii=False
        )
        descriptor, temporary = tempfile.mkstemp(
            dir=self.directory, prefix="." + self.path.name, suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(data + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
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
    """build a runtime from --root/--name and abra_archive_days/abra_trigger_workers."""
    settings = {}
    for variable, key in (
        ("ABRA_ARCHIVE_DAYS", "archive_days"),
        ("ABRA_TRIGGER_WORKERS", "workers"),
    ):
        value = env.get(variable, "")
        if value:
            if not re.fullmatch(r"[0-9]{1,4}", value):
                raise ValueError(variable.lower() + " must be a positive integer")
            settings[key] = int(value)
    settings.update(options)
    return Runtime(adapter, args.root, name=args.name, **settings)
