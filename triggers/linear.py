#!/usr/bin/env python3
"""linear adapter: polls linear-axi for todo issues assigned to the bot; comments out."""

import argparse
import base64
from datetime import datetime, timedelta, timezone
import http.client
import json
import logging
import os
import re
import shutil
import signal
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

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
CLIENT = re.compile(r"[A-Za-z0-9_-]{8,256}")
TOKEN = re.compile(r"[A-Za-z0-9_.~+/=-]{16,4096}")
# app mode: oauth client credentials for a linear agent app (actor=app)
TOKEN_URL = "https://api.linear.app/oauth/token"
SCOPES = (
    "read",
    "write",
    "issues:create",
    "comments:create",
    "app:assignable",
    "app:mentionable",
)
DEFAULT_SCOPES = "read,write,app:assignable"
TOKEN_TIMEOUT = 30
MAX_TOKEN_RESPONSE = 64 * 1024
MIN_LIFETIME = 2 * 3600
MAX_LIFETIME = 366 * 24 * 3600
RENEW_MARGIN = 24 * 3600
# credential inputs never reach the agent as given; it gets only what it needs
CREDENTIALS = (
    "LINEAR_API_KEY",
    "LINEAR_CLIENT_ID",
    "LINEAR_CLIENT_SECRET",
    "LINEAR_ACCESS_TOKEN",
)
# child processes get only these variables plus the linear key or token
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
    " description url state { name } assignee { id } delegate { id } creator { id }"
    " team { key }"
    " comments(first: 100) { nodes { id body createdAt user { id name } } } } }"
)
VIEWER_QUERY = "query AbraViewer { viewer { id } }"
# query.agentSessions takes no filter, so match the issue and app user here
SESSIONS_QUERY = (
    "query AbraSessions { agentSessions(first: 50, orderBy: updatedAt)"
    " { nodes { id status appUser { id } issue { id } } } }"
)
THOUGHT_MUTATION = (
    "mutation AbraThought($input: AgentActivityCreateInput!)"
    " { agentActivityCreate(input: $input) { success } }"
)
OPEN_SESSIONS = ("pending", "active", "awaitingInput", "stale")
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

    def __init__(
        self, bot, command, env, teams=(), timeout=TIMEOUT, actor="user", **names
    ):
        self.bot = bot
        self.actor = actor
        self.command = command
        self.env = env
        self.teams = tuple(teams)
        self.timeout = timeout
        self.todo = names.get("todo", "Todo")
        self.progress = names.get("progress", "In Progress")
        self.blocked = names.get("blocked", "abra-blocked")
        self.viewer = None
        # app mode: set when the token is near expiry or rejected
        self.renew = threading.Event()
        self.stopper = lambda: None

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
                if code == "AUTH_ERROR" and self.actor == "app":
                    self.expire("linear rejected the app token")
                raise LinearError(
                    code.lower() + " (exit " + str(result.returncode) + ")"
                )
            raise LinearError("exit " + str(result.returncode))
        if not isinstance(value, dict):
            raise LinearError("invalid output")
        return value

    def expire(self, why):
        """app mode: stop gracefully so the supervisor restarts with a fresh token."""
        if not self.renew.is_set():
            log.warning("%s; stopping so the supervisor mints a fresh token", why)
            self.renew.set()
            self.stopper()

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
        who = "--delegate" if self.actor == "app" else "--assignee"
        args = ["issue", "list", who, "me", "--state", self.todo]
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
        if self.actor == "app":
            self.think(issue)
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

    def mine(self, issue):
        """the issue is with the bot: its delegate in app mode, else its assignee."""
        field = "delegate" if self.actor == "app" else "assignee"
        return (issue.get(field) or {}).get("id") == self.viewer

    def claimable(self, issue):
        state = (issue.get("state") or {}).get("name")
        team = (issue.get("team") or {}).get("key")
        allowed = not self.teams or team in self.teams
        return same(state, self.todo) and self.mine(issue) and allowed

    def think(self, issue):
        """best effort: a thought on the bot's agent session, so it is not unresponsive."""
        try:
            data = self.call("agent sessions", "api", "--query=" + SESSIONS_QUERY)
            nodes = (((data or {}).get("data") or {}).get("agentSessions") or {}).get(
                "nodes"
            )
            session = None
            for node in nodes if isinstance(nodes, list) else []:
                if (
                    isinstance(node, dict)
                    and (node.get("issue") or {}).get("id") == issue.get("id")
                    and (node.get("appUser") or {}).get("id") == self.viewer
                    and node.get("status") in OPEN_SESSIONS
                    and isinstance(node.get("id"), str)
                    and UUID.fullmatch(node["id"])
                ):
                    session = node["id"]
                    break
            if session is None:
                log.info("no open agent session for %s", issue["identifier"])
                return
            content = {
                "type": "thought",
                "body": self.bot + " picked up this issue and is working on it.",
            }
            variables = {"input": {"agentSessionId": session, "content": content}}
            data = self.call(
                "agent activity",
                "api",
                "--query=" + THOUGHT_MUTATION,
                "--variables=" + json.dumps(variables),
            )
            result = ((data or {}).get("data") or {}).get("agentActivityCreate") or {}
            if result.get("success") is True:
                log.info(
                    "posted a thought to the agent session for %s", issue["identifier"]
                )
        except Exception as error:
            log.warning("agent session update failed: %s", type(error).__name__)

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
        assigned = self.mine(issue)
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
        known = isinstance(creator, str) and UUID.fullmatch(creator)
        if self.actor == "app":
            # the human assignee stays; the creator gets an unassigned issue
            if issue is not None and not (issue.get("assignee") or {}).get("id"):
                if known:
                    self.call("issue assign", "issue", "assign", identifier, creator)
            args = ("issue", "update", identifier, "--delegate", "none")
            if self.call("issue delegate", *args) is not None:
                log.info("handed linear issue %s back: delegate cleared", identifier)
            else:
                log.error("could not clear the delegate of linear issue %s", identifier)
            return
        target = creator if known else "none"
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
    """defense in depth: mask linear key-like and known secret values, drop tracebacks."""

    def __init__(self):
        super().__init__()
        self.values = []

    def filter(self, record):
        message = record.getMessage()
        clean = SECRET.sub("[redacted]", message)
        for value in self.values:
            clean = clean.replace(value, "[redacted]")
        if clean != message:
            record.msg, record.args = clean, None
        record.exc_info = record.exc_text = None
        return True


def scopes(env):
    """app token scopes from linear_app_scopes, checked against an allowlist."""
    value = env.get("LINEAR_APP_SCOPES", "") or DEFAULT_SCOPES
    items = [s.strip() for s in value.split(",") if s.strip()]
    if "admin" in items:
        raise ValueError("linear_app_scopes must not include admin")
    if not items or not all(s in SCOPES for s in items):
        raise ValueError(
            "linear_app_scopes must be comma-separated from: " + ",".join(SCOPES)
        )
    return ",".join(dict.fromkeys(items))


def credentials(env):
    """the actor (app or user) and its credentials; errors name variables only."""
    key, client, secret = (
        env.get(name, "")
        for name in ("LINEAR_API_KEY", "LINEAR_CLIENT_ID", "LINEAR_CLIENT_SECRET")
    )
    if key and (client or secret):
        raise ValueError(
            "set either linear_api_key or linear_client_id and linear_client_secret,"
            " not both"
        )
    if client or secret:
        if not (client and secret):
            raise ValueError(
                "app mode needs both linear_client_id and linear_client_secret"
            )
        for name, value in (
            ("linear_client_id", client),
            ("linear_client_secret", secret),
        ):
            if not CLIENT.fullmatch(value):
                raise ValueError(name + " is malformed")
        return "app", dict(client=client, secret=secret, scopes=scopes(env))
    if not key:
        raise ValueError(
            "linear_api_key is not set (or set linear_client_id and"
            " linear_client_secret)"
        )
    if not API_KEY.fullmatch(key):
        raise ValueError("linear_api_key is not a valid lin_api_ key")
    return "user", dict(key=key)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """never follow a redirect, so client credentials go only to the token url."""

    def redirect_request(self, *args, **kwargs):
        return None


def unique(pairs):
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate key")
    return dict(pairs)


def reject(name):
    raise ValueError("non-standard json constant")


def mint(client, secret, scope, timeout=TOKEN_TIMEOUT):
    """an app token by the client_credentials grant: (token, lifetime seconds).

    tls is always verified; errors name the failure, never the response body.
    """
    body = urllib.parse.urlencode(
        {"grant_type": "client_credentials", "scope": scope}
    ).encode("ascii")
    basic = base64.b64encode((client + ":" + secret).encode("ascii")).decode("ascii")
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": "Basic " + basic,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context), NoRedirect()
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            data = response.read(MAX_TOKEN_RESPONSE + 1)
    except urllib.error.HTTPError as error:
        error.close()
        raise ValueError("linear token endpoint returned http " + str(error.code))
    except (OSError, http.client.HTTPException) as error:
        raise ValueError(
            "could not reach the linear token endpoint ("
            + type(error).__name__.lower()
            + ")"
        )
    if len(data) > MAX_TOKEN_RESPONSE:
        raise ValueError("linear token response is too large")
    try:
        value = json.loads(
            data.decode("utf-8"), object_pairs_hook=unique, parse_constant=reject
        )
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise ValueError("linear token response is not valid json")
    if not isinstance(value, dict):
        raise ValueError("linear token response is not an object")
    token, kind, lifetime = (
        value.get(k) for k in ("access_token", "token_type", "expires_in")
    )
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise ValueError("linear token response has no valid access_token")
    if not isinstance(kind, str) or kind.casefold() != "bearer":
        raise ValueError("linear token response is not a bearer token")
    if (
        not isinstance(lifetime, int)
        or isinstance(lifetime, bool)
        or not MIN_LIFETIME <= lifetime <= MAX_LIFETIME
    ):
        raise ValueError("linear token response has an invalid expires_in")
    return token, lifetime


def agent_env(env, actor, child):
    """the agent's env: no credential inputs, only the key or token, plus the actor."""
    result = {k: v for k, v in env.items() if k not in CREDENTIALS}
    result.update({k: child[k] for k in CREDENTIALS if k in child})
    result["LINEAR_ACTOR"] = actor
    return result


def settings(env):
    """adapter settings from env; raises valueerror naming the variable only."""
    actor, auth = credentials(env)
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
    if actor == "user":
        passed["LINEAR_API_KEY"] = auth["key"]
    command = shutil.which("linear-axi", path=passed.get("PATH", os.defpath))
    if not command:
        raise ValueError("linear-axi is not installed or not on path")
    return dict(
        command=command,
        env=passed,
        teams=teams,
        interval=int(value),
        names=names,
        actor=actor,
        auth=auth,
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
    redact = Redact()
    handler.addFilter(redact)
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    renew_at = None
    try:
        config = settings(env)
        actor, auth = config["actor"], config.pop("auth")
        if actor == "app":
            redact.values.append(auth["secret"])
            token, lifetime = mint(auth["client"], auth["secret"], auth["scopes"])
            redact.values.append(token)
            renew_at = time.monotonic() + lifetime - min(RENEW_MARGIN, lifetime // 2)
            config["env"]["LINEAR_ACCESS_TOKEN"] = token
            log.info("minted a linear app token for %d hours", lifetime // 3600)
        names = config["names"]
        names.pop("review")
        adapter = LinearAdapter(
            args.name,
            config["command"],
            config["env"],
            config["teams"],
            actor=actor,
            **names,
        )
        instance = runtime.from_args(
            adapter, args, agent_env(env, actor, config["env"])
        )
        adapter.identify()
        adapter.check()
        instance.start()
    except (ValueError, OSError) as error:
        log.error("error: %s", error)
        return 1
    done = threading.Event()
    adapter.stopper = done.set
    timer = None
    if renew_at is not None:
        timer = threading.Timer(
            max(0.0, renew_at - time.monotonic()),
            adapter.expire,
            ("the linear app token is near expiry",),
        )
        timer.daemon = True
        timer.start()
    previous = {}
    for number in (signal.SIGINT, signal.SIGTERM):
        previous[number] = signal.signal(number, lambda *_: done.set())
    try:
        log.info(
            "polling linear every %d seconds for %d teams as %s (%s actor)",
            config["interval"],
            len(config["teams"]),
            args.name,
            actor,
        )
        serve(adapter, instance, config["interval"], done)
        log.info("shutting down; pending messages stay stored")
    finally:
        if timer is not None:
            timer.cancel()
        for number, action in previous.items():
            signal.signal(number, action)
        instance.stop()
    if instance.crashed.is_set():
        log.error("error: the agent stopped; pending messages stay stored")
        return 1
    if adapter.renew.is_set():
        log.error("error: the linear app token needs renewal; restart to mint one")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
