"""The prompt an unattended run starts with: the rules first, then the work.

The rules part is the same for a role on every run, so the provider's prompt
cache can reuse it; what changes goes last. The work part carries what an
agent would otherwise spend its first turns looking up: each waiting unit's
title, acceptance criteria, the changes its reviewers asked for, and the
files its commit touched.
"""

from __future__ import annotations

from typing import Any

from . import verify
from .coordination import Coordination
from .gate import latest_reviews
from .project import Project
from .units import parent_of
from .work import Board

REVIEW_REASONS = {"reviews waiting", "ready to close", "unread messages"}
MAX_UNITS = 5
MAX_TEXT = 300
MAX_FILES = 10


def job_of(wanted: dict[str, Any]) -> str:
    """'review' when the role only has reviews, closes, or messages waiting; otherwise 'build'."""
    whys = {r["why"] for r in wanted["reasons"]}
    return "review" if whys and whys <= REVIEW_REASONS else "build"


def build(project: Project, coord: Coordination, charter: dict[str, Any], role: str, pick: dict[str, str],
          wanted: dict[str, Any], job: str) -> str:
    name = project.role(role)["name"]
    rule = ("Clear every waiting review in this one run, then close what is ready. Build nothing."
            if job == "review" else
            "Do any waiting reviews and closes first, then finish one unit and stop.")
    stable = (f"You are {name} ({role}) in a softory project, running unattended: nobody is watching. "
              f"Start with: eval \"$(.agents/softory/bin/softory start {role} --harness {pick['harness']} "
              f"--model {pick['model']})\". Follow the softory-operating-loop skill. "
              f"{rule} If you need the owner, raise an escalation with --owner owner and move on; never wait "
              f"for an answer. End with softory end. The details below were current when this run started; "
              f"look up more only when you need it.")
    lines = ["", "Waiting for you:"]
    for reason in wanted["reasons"]:
        ids = reason.get("ids") or []
        lines.append(f"- {reason['why']}" + (f": {', '.join(ids[:8])}" if ids else ""))
    ids = list(dict.fromkeys(i for r in wanted["reasons"] for i in r.get("ids") or []))[:MAX_UNITS]
    if ids:
        board = Board(project, coord)
        lines += ["", "The units:"]
        lines += [_unit(project, charter, board, i) for i in ids if i in board.by_id]
    return stable + "\n" + "\n".join(lines)


def _unit(project: Project, charter: dict[str, Any], board: Board, task_id: str) -> str:
    task = board.show(task_id)
    head = [task.get("status", "")]
    if parent_of(task):
        head.append(f"parent {parent_of(task)}")
    parts = [f"- {task_id} [{', '.join(head)}] {task.get('title', '')}"]
    if task.get("acceptance"):
        parts.append(f"  Acceptance: {_trim(task['acceptance'])}")
    accepting = set(board.gates["accepting_decisions"])
    asked = [f"{who}: {_trim(r.get('required_changes') or r.get('decision', ''))}"
             for who, r in latest_reviews({"reviews": board.reviews.get(task_id, [])}).items()
             if r.get("decision") not in accepting]
    if asked:
        parts.append(f"  Changes asked: {' | '.join(asked)}")
    sha = verify.commit_of(project.root, task)
    if sha:
        files = verify.changed_files(project.root, charter["git"]["base"], sha) or []
        more = f" (+{len(files) - MAX_FILES} more)" if len(files) > MAX_FILES else ""
        parts.append(f"  Commit {sha[:12]}" + (f", changes: {', '.join(files[:MAX_FILES])}{more}" if files else ""))
    return "\n".join(parts)


def _trim(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1] + "…"
