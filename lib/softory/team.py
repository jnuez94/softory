"""Triage: finished work left open, work closed outside softory, stale sessions, and silent roles."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import gate as gate_rules
from . import lifecycle, watch, work
from .coordination import Coordination
from .project import Project


def triage(project: Project, coord: Coordination) -> dict[str, Any]:
    """Open tasks whose latest reviews already accept them.

    In a project with history, many "todo" tasks are finished work nobody
    closed. This lists them so they get closed instead of rebuilt.
    """
    gates = project.gates()
    ready, accepted_but_open = [], []
    statuses = ("todo", "in_progress", "blocked", "review")
    open_tasks = coord.all_tasks(*[arg for status in statuses for arg in ("--status", status)])
    reviews = work.all_reviews(coord)  # one listing instead of a task show per open task
    for task in open_tasks:
        latest = gate_rules.latest_reviews({"reviews": reviews.get(task["id"], [])})
        accepted = sorted(r for r, review in latest.items() if review.get("decision") in gates["accepting_decisions"])
        if not accepted:
            continue
        rejecting = sorted(work.open_requests(project, gates, task, reviews.get(task["id"], []),
                                              lambda task=task: coord.task(task["id"])))
        row = {"id": task["id"], "status": task["status"], "title": task["title"],
               "assignees": task.get("assignees") or [], "accepted_by": accepted, "changes_requested_by": rejecting}
        (ready if task["status"] == "review" and not rejecting else accepted_but_open).append(row)
    return {
        "ready_to_close": ready,
        "accepted_but_open": accepted_but_open,
        "closed_outside_softory": _closed_outside_softory(project, coord),
        "sessions": _session_report(project, coord),
        "silent_roles": watch.silent(project, coord)["silent"],
        "next": ("Run softory gate on each ready task. For the others, check the code: close finished work, drop "
                 "work nobody will build (softory drop), or say what is left. End silent sessions; restart sessions older than the install; tell the owner "
                 "about silent roles and anything closed outside softory."),
    }


def _closed_outside_softory(project: Project, coord: Coordination) -> list[dict[str, Any]]:
    """Units done since softory was installed without softory's close or drop note: someone ran
    ``task status done`` directly, which the scaffold allows and the gate never saw."""
    manifest = project.manifest()
    since = manifest.get("first_installed_at") or manifest.get("installed_at") or ""
    return [{"id": t["id"], "title": t["title"], "updated_at": t["updated_at"], "notes": t.get("notes") or ""}
            for t in coord.all_tasks("--status", "done")
            if t.get("updated_at", "") >= since and not lifecycle.closed_by_softory(t)]


def _session_report(project: Project, coord: Coordination) -> dict[str, list[dict[str, str]]]:
    """Active sessions nobody has seen for a day, and ones running rules older than this install."""
    now = datetime.now(timezone.utc)
    installed = str(project.manifest().get("installed_at") or "")
    silent, before_install = [], []
    for session in coord.all_rows("session", "list", "--status", "active"):
        row = {"id": session["id"], "agent": session["agent_id"], "started_at": session["started_at"],
               "last_seen_at": session["last_seen_at"]}
        if now - watch.parse_time(session["last_seen_at"]) > timedelta(hours=24):
            silent.append(row)
        elif installed and session["started_at"] < installed:
            before_install.append(row)
    return {"silent": silent, "started_before_install": before_install}

