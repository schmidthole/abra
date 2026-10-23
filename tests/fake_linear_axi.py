"""stub linear-axi for linear adapter tests: no network, state in a json file.

tests copy this file next to a state.json as an executable named linear-axi. it
implements the subset the adapter uses, with linear-axi's --json output shapes,
and appends every call to calls.jsonl beside it. state.json holds "viewer" (the
bot user id), "issues" keyed by identifier, and "fail": a list of command names
("issue state", "issue list", "api", ...) that exit 1 with an api error.
"apply_fail" lists commands that apply their change and then exit 1, and
"ambiguous" makes a todo listing without --team fail as linear-axi does when
several teams share the state name. state names resolve case-insensitively to
their canonical form, as in linear-axi. "auth_fail" lists commands that exit 1
with AUTH_ERROR ("api issue", "api sessions", and "api activity" name one
graphql call), as does setting both credentials, as in linear-axi. app mode authenticates with LINEAR_ACCESS_TOKEN: issues carry a
"delegate", "sessions" holds agent sessions, and thoughts land in "activities".
"""

import fcntl
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
STATE = HERE / "state.json"
CALLS = HERE / "calls.jsonl"
STATES = ("Todo", "In Progress", "In Review", "Done")


def emit(value, code=0):
    sys.stdout.write(json.dumps(value, indent=2) + "\n")
    sys.exit(code)


def error(message, code, exit_code=1):
    emit({"error": message, "code": code}, exit_code)


def flag(args, name):
    for index, arg in enumerate(args):
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
        if arg == name and index + 1 < len(args):
            return args[index + 1]
    return None


def canonical(name):
    for known in STATES:
        if known.lower() == (name or "").lower():
            return known
    error("Workflow state not found: " + str(name), "NOT_FOUND")


def bump(state, issue):
    state["clock"] = state.get("clock", 0) + 1
    issue["updatedAt"] = "2026-10-22T12:%02d:%02d.000Z" % divmod(state["clock"], 60)


def handle(state, args):
    viewer = state["viewer"]
    issues = state["issues"]
    command = " ".join(args[:2]) if args[0] == "issue" else args[0]
    if command in state.get("fail", []):
        error("Linear API error: stub failure for secret issue words", "API_ERROR")
    if command in state.get("auth_fail", []):
        error("Authentication failed", "AUTH_ERROR")
    if args[0] == "api":
        query = flag(args, "--query") or ""
        kind = "sessions" if "agentSessions" in query else "issue"
        kind = "activity" if "agentActivityCreate" in query else kind
        if "viewer" not in query and "api " + kind in state.get("auth_fail", []):
            error("Authentication failed: permission denied", "AUTH_ERROR")
        if "agentSessions" in query:
            emit({"data": {"agentSessions": {"nodes": state.get("sessions", [])}}})
        if "agentActivityCreate" in query:
            variables = json.loads(flag(args, "--variables") or "{}")
            state.setdefault("activities", []).append(variables["input"])
            emit({"data": {"agentActivityCreate": {"success": True}}})
        if "viewer" in query:
            emit({"data": {"viewer": {"id": viewer}}})
        ident = json.loads(flag(args, "--variables") or "{}").get("id")
        issue = issues.get(ident)
        if issue is None:
            error("Linear API error: Entity not found", "API_ERROR")
        data = {
            "id": issue["id"],
            "identifier": ident,
            "title": issue["title"],
            "description": issue.get("description"),
            "url": "https://linear.app/acme/issue/" + ident,
            "state": {"name": issue["state"]},
            "assignee": {"id": issue["assignee"]} if issue.get("assignee") else None,
            "delegate": {"id": issue["delegate"]} if issue.get("delegate") else None,
            "creator": {"id": issue["creator"]} if issue.get("creator") else None,
            "team": {"key": issue["team"]},
            "comments": {"nodes": issue.get("comments", [])},
        }
        emit({"data": {"issue": data}})
    if command == "issue list":
        state_name, team = canonical(flag(args, "--state")), flag(args, "--team")
        field = "delegate" if flag(args, "--delegate") == "me" else "assignee"
        if state.get("ambiguous") and team is None:
            error("Ambiguous workflow state: " + state_name, "VALIDATION_ERROR", 2)
        found = [
            {
                "id": issue["id"],
                "identifier": ident,
                "team": issue["team"],
                "updatedAt": issue["updatedAt"],
            }
            for ident, issue in sorted(issues.items())
            if issue.get(field) == viewer
            and issue["state"] == state_name
            and (team is None or issue["team"] == team)
        ]
        if not found:
            emit({"count": 0, "issues": "0 issues found", "help": []})
        emit({"count": len(found), "issues": found})
    issue = issues.get(args[3] if command == "issue label" else args[2])
    if issue is None:
        error("Issue not found", "NOT_FOUND")
    if command == "issue state":
        issue["state"] = canonical(args[3])
        bump(state, issue)
        if command in state.get("apply_fail", []):
            error("Linear API request timed out", "NETWORK_ERROR")
        emit({"result": "issue state updated", "issue": {"status": issue["state"]}})
    if command == "issue assign":
        issue["assignee"] = None if args[3] == "none" else args[3]
        bump(state, issue)
        emit({"result": "issue assigned", "issue": {"assignee": args[3]}})
    if command == "issue update":
        delegate = flag(args, "--delegate")
        issue["delegate"] = {"none": None, "me": viewer}.get(delegate, delegate)
        bump(state, issue)
        emit({"result": "issue updated", "issue": {"delegate": issue["delegate"]}})
    if command == "issue label":
        issue.setdefault("labels", []).append(args[4])
        emit({"result": "label added", "issue": {"labels": issue["labels"]}})
    if command == "issue comment":
        body = flag(args, "--body")
        state["clock"] = state.get("clock", 0) + 1
        comment = {
            "id": "c-bot-%d" % state["clock"],
            "body": body,
            "createdAt": "2026-10-22T13:%02d:%02d.000Z" % divmod(state["clock"], 60),
            "user": {"id": viewer, "name": "abra bot"},
        }
        issue.setdefault("comments", []).append(comment)
        emit({"result": "comment created", "comment": {"id": comment["id"]}})
    error("unsupported stub command", "VALIDATION_ERROR", 2)


def main():
    args = sys.argv[1:]
    with open(HERE / "state.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with open(CALLS, "a") as log:
            entry = {
                "args": args,
                "key": os.environ.get("LINEAR_API_KEY"),
                "token": os.environ.get("LINEAR_ACCESS_TOKEN"),
                "env": sorted(os.environ),
            }
            log.write(json.dumps(entry) + "\n")
        if args[-1:] != ["--json"]:
            error("stub requires --json", "VALIDATION_ERROR", 2)
        args = args[:-1]
        key, token = (
            os.environ.get(name) for name in ("LINEAR_API_KEY", "LINEAR_ACCESS_TOKEN")
        )
        if key and token:
            error("Both LINEAR_API_KEY and LINEAR_ACCESS_TOKEN are set", "AUTH_ERROR")
        if not (key or token):
            error("LINEAR_API_KEY is not set", "AUTH_ERROR")
        state = json.loads(STATE.read_text())
        try:
            handle(state, args)
        except SystemExit:
            # atomic, so readers never see a half-written file
            temporary = STATE.with_suffix(".tmp")
            temporary.write_text(json.dumps(state, indent=2))
            os.replace(temporary, STATE)
            raise


if __name__ == "__main__":
    main()
