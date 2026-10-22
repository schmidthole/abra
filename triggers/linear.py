#!/usr/bin/env python3
"""linear adapter: polls linear-axi for todo issues assigned to the bot; comments out."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

import runtime

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
IDENTIFIER = re.compile(r"[A-Za-z0-9_]{1,16}-[0-9]{1,9}")
TEAM = re.compile(r"[A-Za-z0-9_]{1,16}")
STAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z"
)
CONV = re.compile(r"linear:([A-Za-z0-9_]{1,16}-[0-9]{1,9})")
PICKUP = re.compile(r"todo-(.+)")
CODE = re.compile(r"[A-Z][A-Z_]{0,39}")
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}")
API_KEY = re.compile(r"lin_api_[A-Za-z0-9_-]{8,256}")
SECRET = re.compile(r"lin_(?:api|oauth)_[A-Za-z0-9_-]+")
MENTION = re.compile(r"@(?=[A-Za-z0-9_.-])")
# child processes get only these variables plus linear_api_key
PASSED = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "NODE_EXTRA_CA_CERTS",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)
SETTINGS = (
    ("LINEAR_TODO_STATE", "todo", "Todo"),
    ("LINEAR_PROGRESS_STATE", "progress", "In Progress"),
    ("LINEAR_REVIEW_STATE", "review", "In Review"),
    ("LINEAR_BLOCKED_LABEL", "blocked", "abra-blocked"),
)
ISSUE_QUERY = (
    "query AbraIssue($id: String!) { issue(id: $id) { id identifier title"
    " description url state { name } assignee { id } creator { id } team { key }"
    " comments(first: 100) { nodes { id body createdAt user { id name } } } } }"
)
VIEWER_QUERY = "query AbraViewer { viewer { id } }"
POLL = 30
POLL_RANGE = (10, 3600)
LIMIT = "50"
TIMEOUT = 60
MAX_OUTPUT = 4 * 1024 * 1024
MAX_DESCRIPTION = 16000
CHUNK = 10000
ZERO_WIDTH = "​"
TRUNCATED = "\n\n[truncated by the linear trigger]"
log = runtime.log


def same(name, other):
    """linear-axi resolves state names case-insensitively and returns them canonical."""
    return isinstance(name, str) and name.casefold() == other.casefold()


def moment(stamp):
    """a validated linear timestamp as an aware datetime."""
    base, _, fraction = stamp.rstrip("Z").partition(".")
    value = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return value + timedelta(microseconds=int(fraction.ljust(6, "0") or 0))


class LinearError(Exception):
    """a failed linear-axi call; str() is a code, never api or issue text."""


def neutralize(text):
    """break @mentions with a zero-width space; markdown and links stay as written."""
    return MENTION.sub("@" + ZERO_WIDTH, text)


def chunks(text, size=CHUNK):
    """split text into comments of at most size chars, preferring newline boundaries."""
    parts = []
    while len(text) > size:
        cut = text.rfind("\n", 0, size + 1)
        if cut <= 0:
            cut = size
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    parts.append(text)
    return [part for part in parts if part.strip()]


def fit(sender, text):
    """cut text from the end until the runtime accepts it as one message."""
    limit = runtime.MAX_TEXT - 64
    while len(runtime.encoded([{"from": sender, "text": text}])) > limit:
        over = len(runtime.encoded([{"from": sender, "text": text}])) - limit
        keep = max(0, len(text) - over - len(TRUNCATED))
        text = text[:keep].rstrip() + TRUNCATED
        if keep == 0:
            break
    return text


class LinearAdapter:
    """maps todo issues to runtime events; every linear call runs linear-axi."""

    name = "linear"

    def __init__(self, bot, command, env, teams=(), timeout=TIMEOUT, **names):
        self.bot = bot
        self.command = command
        self.env = env
        self.teams = tuple(teams)
        self.timeout = timeout
        self.todo = names.get("todo", "Todo")
        self.progress = names.get("progress", "In Progress")
        self.blocked = names.get("blocked", "abra-blocked")
        self.viewer = None

    # linear-axi

    def run(self, *args):
        """one linear-axi call with --json; returns the parsed object or raises."""
        argv = [self.command] + list(args) + ["--json"]
        with tempfile.TemporaryFile() as out:
            try:
                result = subprocess.run(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=subprocess.DEVNULL,
                    env=self.env,
                    timeout=self.timeout,
                )
            except subprocess.TimeoutExpired:
                raise LinearError("timeout") from None
            except OSError as error:
                raise LinearError(type(error).__name__) from None
            out.seek(0)
            data = out.read(MAX_OUTPUT + 1)
        if len(data) > MAX_OUTPUT:
            raise LinearError("output too large")
        try:
            value = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError):
            value = None
        if result.returncode:
            code = value.get("code") if isinstance(value, dict) else None
            if isinstance(code, str) and CODE.fullmatch(code):
                raise LinearError(
                    code.lower() + " (exit " + str(result.returncode) + ")"
                )
            raise LinearError("exit " + str(result.returncode))
        if not isinstance(value, dict):
            raise LinearError("invalid output")
        return value

    def call(self, what, *args):
        """run, logging a failure by code; returns none on failure."""
        try:
            return self.run(*args)
        except LinearError as error:
            log.warning("linear-axi %s failed: %s", what, error)
            return None

    def fetch(self, identifier):
        """the issue with comments through the graphql escape hatch, or none."""
        variables = json.dumps({"id": identifier})
        data = self.call(
            "issue fetch", "api", "--query=" + ISSUE_QUERY, "--variables=" + variables
        )
        issue = (data.get("data") or {}).get("issue") if data else None
        if not isinstance(issue, dict) or issue.get("identifier") != identifier:
            if data is not None:
                log.warning("linear issue %s was not returned", identifier)
            return None
        return issue

    def identify(self):
        """learn the bot user id through linear-axi; fails closed."""
        try:
            data = self.run("api", "--query=" + VIEWER_QUERY)
        except LinearError as error:
            raise ValueError("linear-axi could not identify the bot: " + str(error))
        viewer = (data.get("data") or {}).get("viewer") or {}
        if not isinstance(viewer.get("id"), str) or not UUID.fullmatch(viewer["id"]):
            raise ValueError("linear-axi did not return a valid bot user id")
        self.viewer = viewer["id"]
        log.info("connected to linear as user %s", self.viewer)

    def check(self):
        """list todo issues once per team at startup, so a bad setup fails closed."""
        for team in self.teams or (None,):
            try:
                self.run(*self.listing(team, "1"))
            except LinearError as error:
                if str(error).startswith("validation_error") and team is None:
                    raise ValueError(
                        "linear-axi could not resolve the todo state across teams"
                        " (ambiguous); set linear_teams"
                    )
                raise ValueError("linear-axi could not list todo issues: " + str(error))

    def listing(self, team, limit=LIMIT):
        args = ["issue", "list", "--assignee", "me", "--state", self.todo]
        args += ["--fields", "id,identifier,team,updatedAt", "--limit", limit]
        return args + (["--team", team] if team else [])

    # intake

    def poll(self, instance, stop=lambda: False):
        """one poll: claim and submit every todo issue assigned to the bot."""
        if self.viewer is None:
            raise ValueError("identify must run before poll")
        seen = 0
        for team in self.teams or (None,):
            data = self.call("issue list", *self.listing(team))
            issues = data.get("issues") if data else None
            # an empty list is reported as a sentence, not an array
            for item in issues if isinstance(issues, list) else []:
                if stop():
                    return seen
                seen += 1
                try:
                    self.pickup(instance, item)
                except Exception as error:
                    log.error("linear pickup failed: %s", type(error).__name__)
        return seen

    def pickup(self, instance, item):
        """claim one listed issue, then submit it; a failed claim skips it."""
        if not isinstance(item, dict):
            return
        identifier, team, stamp = (
            item.get(k) for k in ("identifier", "team", "updatedAt")
        )
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            log.warning("ignoring a linear issue with an invalid identifier")
            return
        if not isinstance(stamp, str) or not STAMP.fullmatch(stamp):
            log.warning("ignoring linear issue %s: invalid updated time", identifier)
            return
        if self.teams and team not in self.teams:
            log.info("ignoring linear issue %s: team not allowed", identifier)
            return
        conv, msg_id = "linear:" + identifier, "todo-" + stamp
        with instance.lock:
            entry = instance.convs.get(conv)
            known = entry and (
                msg_id == entry["last_msg_id"]
                or msg_id in {m["msg_id"] for m in entry["pending"]}
            )
            last = entry["last_msg_id"] if entry else None
        if known:
            log.info("ignoring linear issue %s: pickup already submitted", identifier)
            return
        issue = self.fetch(identifier)
        if issue is None:
            return
        if not self.claimable(issue):
            log.info("skipping linear issue %s: no longer todo for the bot", identifier)
            return
        claimed = self.call("issue state", "issue", "state", identifier, self.progress)
        status = ((claimed or {}).get("issue") or {}).get("status")
        if not same(status, self.progress) and not self.confirm(identifier):
            return
        log.info("claimed linear issue %s", identifier)
        match = PICKUP.fullmatch(last) if isinstance(last, str) else None
        if match and not STAMP.fullmatch(match.group(1)):
            match = None
        creator = (issue.get("creator") or {}).get("id")
        sender = (
            creator
            if isinstance(creator, str) and UUID.fullmatch(creator)
            else "unknown"
        )
        text = fit(sender, self.compose(issue, match.group(1) if match else None))
        event = runtime.Event("start", conv, msg_id, sender, text)
        if not instance.submit(event):
            log.error("could not submit linear issue %s; handing it back", identifier)
            self.give_up(identifier)

    def claimable(self, issue):
        state = (issue.get("state") or {}).get("name")
        assignee = (issue.get("assignee") or {}).get("id")
        team = (issue.get("team") or {}).get("key")
        allowed = not self.teams or team in self.teams
        return same(state, self.todo) and assignee == self.viewer and allowed

    def confirm(self, identifier):
        """after an unconfirmed claim, read the issue back; never strand it."""
        issue = self.fetch(identifier)
        if issue is None:
            log.warning(
                "could not confirm the claim of %s; handing it back", identifier
            )
            self.give_up(identifier)
            return False
        state = (issue.get("state") or {}).get("name")
        assigned = (issue.get("assignee") or {}).get("id") == self.viewer
        if assigned and same(state, self.progress):
            return True
        if assigned and not same(state, self.todo):
            log.warning(
                "claim of %s left an unexpected state; handing it back", identifier
            )
            self.give_up(identifier)
        else:
            log.warning("could not claim linear issue %s; skipping it", identifier)
        return False

    def comments(self, issue):
        nodes = (issue.get("comments") or {}).get("nodes")
        items = []
        for node in nodes if isinstance(nodes, list) else []:
            if not isinstance(node, dict):
                continue
            ident, body, stamp = (node.get(k) for k in ("id", "body", "createdAt"))
            if not isinstance(ident, str) or not runtime.KEY.fullmatch(ident):
                continue
            if not isinstance(body, str) or not body.strip():
                continue
            if not isinstance(stamp, str) or not STAMP.fullmatch(stamp):
                continue
            user = node.get("user") or {}
            items.append(
                (moment(stamp), ident, user.get("id"), user.get("name"), body, stamp)
            )
        return sorted(items, key=lambda item: item[:2])

    def compose(self, issue, since):
        """message text for a pickup; since is the previous pickup's time, if any."""
        title = issue.get("title") if isinstance(issue.get("title"), str) else ""
        url = issue.get("url") if isinstance(issue.get("url"), str) else ""
        description = issue.get("description")
        description = description if isinstance(description, str) else ""
        if len(description) > MAX_DESCRIPTION:
            description = description[:MAX_DESCRIPTION] + TRUNCATED
        lines = ["linear issue " + issue["identifier"] + ": " + title, "url: " + url]
        if since:
            lines.append(
                "resumed: the issue was assigned back to the bot and set to todo."
            )
        lines += ["", "description:", description.strip() or "(none)"]
        comments = [
            c
            for c in self.comments(issue)
            if c[2] != self.viewer and (since is None or c[0] > moment(since))
        ]
        heading = "new comments since the last pickup:" if since else "comments:"
        if comments:
            lines += ["", heading]
        for _, _, _, name, body, stamp in comments:
            author = name if isinstance(name, str) and name.strip() else "unknown"
            lines += ["", "comment by " + author + " at " + stamp + ":", body.strip()]
        return "\n".join(lines)

    def give_up(self, identifier):
        """fixed error comment (best effort), then the cannot-complete hand-back."""
        try:
            self.reply("linear:" + identifier, self.error_text(self.bot))
        except Exception as error:
            log.warning("error comment failed: %s", type(error).__name__)
        self.hand_back(identifier)

    def hand_back(self, identifier):
        """cannot-complete hand-back: blocked label, then reassign to the creator."""
        self.call("label add", "issue", "label", "add", identifier, self.blocked)
        issue = self.fetch(identifier)
        creator = ((issue or {}).get("creator") or {}).get("id")
        target = (
            creator if isinstance(creator, str) and UUID.fullmatch(creator) else "none"
        )
        if self.call("issue assign", "issue", "assign", identifier, target) is not None:
            log.info("handed linear issue %s back to its creator", identifier)

    # runtime output

    @staticmethod
    def split(conv):
        match = CONV.fullmatch(conv) if isinstance(conv, str) else None
        if not match:
            raise ValueError("not a linear conversation key")
        return match.group(1)

    def announcement(self, name, work_id):
        return (
            name
            + " is on it. this issue is now work item "
            + work_id
            + ". to add to it later, comment here, then assign the issue back to the"
            " bot and set it to " + self.todo + "."
        )

    def error_text(self, name):
        return (
            name + " hit an error on this issue and handed it back. to retry, comment"
            " here, then assign the issue back to the bot and set it to "
            + self.todo
            + "."
        )

    def reply(self, conv, text):
        identifier = self.split(conv)
        for part in chunks(neutralize(text)):
            args = ("issue", "comment", identifier, "--body=" + part)
            if self.call("issue comment", *args) is None:
                return

    def ack(self, conv, msg_id, state):
        identifier = self.split(conv)
        if state == "failed":
            self.hand_back(identifier)
        # running needs nothing: the claim already set the in-progress state

    def history(self, conv):
        identifier = self.split(conv)
        issue = self.fetch(identifier)
        if issue is None:
            return []
        messages = []
        description = issue.get("description")
        creator = (issue.get("creator") or {}).get("id")
        if isinstance(description, str) and description.strip():
            sender = (
                creator
                if isinstance(creator, str) and UUID.fullmatch(creator)
                else "unknown"
            )
            messages.append(runtime.Message("description", sender, description))
        for _, ident, user, _, body, _ in self.comments(issue):
            if user == self.viewer:
                sender = self.bot
            elif isinstance(user, str) and UUID.fullmatch(user):
                sender = user
            else:
                sender = "unknown"
            messages.append(runtime.Message(ident, sender, body))
        return messages


class Redact(logging.Filter):
    """defense in depth: mask linear key-like values and drop tracebacks."""

    def filter(self, record):
        message = record.getMessage()
        clean = SECRET.sub("[redacted]", message)
        if clean != message:
            record.msg, record.args = clean, None
        record.exc_info = record.exc_text = None
        return True


def settings(env):
    """adapter settings from env; raises valueerror naming the variable only."""
    key = env.get("LINEAR_API_KEY", "")
    if not key:
        raise ValueError("linear_api_key is not set")
    if not API_KEY.fullmatch(key):
        raise ValueError("linear_api_key is not a valid lin_api_ key")
    value = env.get("LINEAR_POLL_SECONDS", "") or str(POLL)
    low, high = POLL_RANGE
    if not re.fullmatch(r"[0-9]{1,5}", value) or not low <= int(value) <= high:
        raise ValueError(
            "linear_poll_seconds must be " + str(low) + " to " + str(high) + " seconds"
        )
    teams = [t.strip() for t in env.get("LINEAR_TEAMS", "").split(",") if t.strip()]
    if not all(TEAM.fullmatch(team) for team in teams):
        raise ValueError("linear_teams must be comma-separated team keys")
    names = {}
    for variable, field, default in SETTINGS:
        name = env.get(variable, "") or default
        if not LABEL.fullmatch(name):
            raise ValueError(variable.lower() + " must match " + LABEL.pattern)
        names[field] = name
    passed = {k: env[k] for k in PASSED if k in env}
    passed["LINEAR_API_KEY"] = key
    command = shutil.which("linear-axi", path=passed.get("PATH", os.defpath))
    if not command:
        raise ValueError("linear-axi is not installed or not on path")
    return dict(
        command=command, env=passed, teams=teams, interval=int(value), names=names
    )


def serve(adapter, instance, interval, done):
    """poll now and then every interval seconds until done or the agent stops."""
    following = time.monotonic()
    while not done.is_set() and not instance.crashed.is_set():
        if time.monotonic() >= following:
            count = adapter.poll(instance, done.is_set)
            if count:
                log.info("polled linear: %d todo issues", count)
            following = time.monotonic() + interval
        done.wait(min(1.0, max(0.0, following - time.monotonic())))


def main(argv=None, env=None):
    parser = argparse.ArgumentParser(description=__doc__)
    runtime.add_arguments(parser)
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("triggers: %(message)s"))
    handler.addFilter(Redact())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    try:
        config = settings(env)
        names = config["names"]
        names.pop("review")
        adapter = LinearAdapter(
            args.name, config["command"], config["env"], config["teams"], **names
        )
        instance = runtime.from_args(adapter, args, env)
        adapter.identify()
        adapter.check()
        instance.start()
    except (ValueError, OSError) as error:
        log.error("error: %s", error)
        return 1
    done = threading.Event()
    previous = {}
    for number in (signal.SIGINT, signal.SIGTERM):
        previous[number] = signal.signal(number, lambda *_: done.set())
    try:
        log.info(
            "polling linear every %d seconds for %d teams as %s",
            config["interval"],
            len(config["teams"]),
            args.name,
        )
        serve(adapter, instance, config["interval"], done)
        log.info("shutting down; pending messages stay stored")
    finally:
        for number, action in previous.items():
            signal.signal(number, action)
        instance.stop()
    if instance.crashed.is_set():
        log.error("error: the agent stopped; pending messages stay stored")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
