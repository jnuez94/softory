"""Records agents write that need more care than a raw coordination call: commits, corrections, escalations.

``softory commit`` records the commit a unit delivered by its full hash, with
its base kept apart, so verify and the gate never mistake one for the other.
``softory supersede`` retracts a wrong evidence row without deleting it: the
row and its audit stay, and softory reads past it. ``softory escalate``
raises an escalation the owner can read at a glance: one plain question, a
length limit, and no words run together.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from typing import Any

from . import ops
from .coordination import Coordination
from .errors import SoftoryError
from .gitlocal import git
from .owner import record_decision
from .project import Project
from .work import actor_of

COMMANDS = ("commit", "supersede", "escalate")
ISSUE_LIMIT = 600
ASK_LIMIT = 300
# "contain9", "runnerusage0", "atthe186": a word fused with a number reads as noise to the owner.
_HASH = re.compile(r"^[0-9a-f]{7,40}$")  # commit hashes are fine
_FUSED = re.compile(r"\b(?:[a-z]{3,}\d+[a-z]*|\d+[a-z]{4,})\b")


def add_parsers(sub: Any) -> None:
    p = sub.add_parser("commit", help="Record the commit a unit delivered, by full hash, with its base kept apart")
    p.add_argument("id")
    p.add_argument("sha")
    p.add_argument("--base", help="The commit it was built on, if reviewers need it")
    p.add_argument("--actor")
    p = sub.add_parser("supersede", help="Retract a wrong evidence row; it stays in the audit, and softory reads past it")
    p.add_argument("id", help="The task the evidence is on")
    p.add_argument("evidence", help="The evidence row's number, from task show")
    p.add_argument("--reason", required=True)
    p.add_argument("--actor")
    p = sub.add_parser("escalate", help="Ask the owner one plain question, checked so it reads at a glance")
    p.add_argument("--issue", required=True, help=f"What happened, in plain sentences (up to {ISSUE_LIMIT} characters)")
    p.add_argument("--ask", required=True, help=f"The one question for the owner (up to {ASK_LIMIT} characters)")
    p.add_argument("--tasks", help="Related task IDs, comma-separated")
    p.add_argument("--owner", help="Who decides; default the project owner")
    p.add_argument("--actor")


def dispatch(args: argparse.Namespace, project: Project, coord: Coordination) -> int:
    actor = actor_of(args.actor)
    if args.command == "commit":
        result = commit(project, coord, args.id, args.sha, args.base, actor)
    elif args.command == "supersede":
        result = supersede(project, coord, args.id, args.evidence, args.reason, actor)
    else:
        result = escalate(project, coord, args.issue, args.ask, args.tasks, args.owner, actor)
    print(ops.dumps(result), end="")
    return 0


def commit(project: Project, coord: Coordination, task_id: str, sha: str, base: str | None,
           actor: str) -> dict[str, Any]:
    head = _full(project, sha)
    uri = f"commit:{head}" + (f";base={_full(project, base)}" if base else "")
    coord.run("evidence", "add", "--task", task_id, "--uri", uri, "--type", "commit", "--actor", actor)
    return {"task": task_id, "commit": head, "uri": uri}


def _full(project: Project, sha: str) -> str:
    found = git(project.root, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
    if found.returncode != 0:
        raise SoftoryError(f"{sha} is not a commit in this repository", "not_found")
    return found.stdout.strip()


def supersede(project: Project, coord: Coordination, task_id: str, evidence_id: str, reason: str,
              actor: str) -> dict[str, Any]:
    """Only whoever added the row, Quinn, or the owner may retract it, and the reason becomes a decision."""
    task = coord.task(task_id)
    row = next((e for e in task.get("evidence") or [] if str(e.get("id")) == str(evidence_id)), None)
    if row is None:
        raise SoftoryError(f"{task_id} has no evidence row {evidence_id}", "not_found")
    owner = project.roster()["owner"]["id"]
    if actor not in (row.get("added_by"), "quinn", owner):
        raise SoftoryError(f"Only {row.get('added_by')}, quinn, or the owner may supersede evidence {evidence_id}",
                           "not_allowed")
    if not reason.strip():
        raise SoftoryError("Say why with --reason", "invalid_arguments")
    decision = record_decision(coord, actor, "SUPERSEDE", f"Supersede evidence {evidence_id} on {task_id}",
                               f"Evidence {evidence_id} ({row.get('evidence_type')}: {row.get('uri')}) no longer counts.",
                               reason)
    coord.run("evidence", "add", "--task", task_id, "--uri", f"softory-supersedes:{evidence_id}:{decision}",
              "--type", "note", "--actor", actor)
    return {"task": task_id, "superseded": evidence_id, "decision": decision,
            "note": "The row and its audit stay; the gate and verify read past it."}


def text_problems(issue: str, ask: str) -> list[str]:
    """Why an escalation would be hard for the owner to read. Empty when it reads fine."""
    problems = []
    if len(issue) > ISSUE_LIMIT:
        problems.append(f"--issue is {len(issue)} characters; keep it under {ISSUE_LIMIT} and link a file for detail")
    if len(ask) > ASK_LIMIT:
        problems.append(f"--ask is {len(ask)} characters; keep it under {ASK_LIMIT}")
    if ask.count("?") != 1:
        problems.append("--ask must be exactly one question, ending in a question mark")
    fused = sorted({w for w in _FUSED.findall(f"{issue} {ask}".lower()) if not _HASH.match(w)})
    if fused:
        problems.append(f"put spaces between words and numbers: {', '.join(fused[:5])}")
    return problems


def escalate(project: Project, coord: Coordination, issue: str, ask: str, tasks: str | None, owner: str | None,
             actor: str) -> dict[str, Any]:
    problems = text_problems(issue.strip(), ask.strip())
    if problems:
        raise SoftoryError("Rewrite the escalation so the owner can read it at a glance: " + "; ".join(problems),
                           "invalid_arguments")
    decider = owner or project.roster()["owner"]["id"]
    escalation_id = f"ESC-{actor.upper()}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    args = ["escalation", "add", "--id", escalation_id, "--raised-by", actor, "--owner", decider,
            "--issue", issue.strip(), "--requested-decision", ask.strip()]
    if tasks:
        args += ["--related-tasks", tasks]
    coord.run(*args)
    return {"escalation": escalation_id, "owner": decider}
