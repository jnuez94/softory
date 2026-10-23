"""Joining a project that already has a team: stand-ins and adopting older tasks.

A stand-in is an existing agent the owner names to act for a softory role, for
example a project's own reviewer covering Jade and Gold. Adopting retags a task
created before softory so it joins an epic or story and the full gate.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import gate as gate_rules
from . import ops, work
from .coordination import Coordination
from .errors import SoftoryError
from .project import Project
from .units import build_tags, check_parent, tags_of, unit_of


def stand_ins(project: Project) -> dict[str, list[str]]:
    return dict(project.local().get("stand_ins", {}))


def add_stand_in(project: Project, coord: Coordination, agent: str, roles: list[str], actor: str) -> dict[str, Any]:
    """Let ``agent`` review and close wherever ``roles`` may, and record why."""
    known = {role["id"] for role in project.roster()["roles"]}
    unknown = sorted(set(roles) - known)
    if not roles or unknown:
        raise SoftoryError(f"Unknown role(s): {', '.join(unknown) or '(none given)'}. Roles: {', '.join(sorted(known))}",
                           "invalid_arguments")
    if agent in roles:
        raise SoftoryError(f"{agent} cannot stand in for itself", "invalid_arguments")
    if not coord.agent_exists(agent):
        raise SoftoryError(f"Agent {agent!r} is not registered in the coordination database", "not_found")
    settings = project.local()
    covers = sorted(set(settings.get("stand_ins", {}).get(agent, [])) | set(roles))
    decision = _record(coord, actor, f"{agent} stands in for {', '.join(covers)}",
                       f"{agent} may review and close wherever {', '.join(covers)} may, within that role's boundaries.")
    settings.setdefault("stand_ins", {})[agent] = covers
    project.save_local(settings)
    return {"agent": agent, "stands_in_for": covers, "decision": decision, "regenerated": ops.sync(project)}


def remove_stand_in(project: Project, coord: Coordination, agent: str, actor: str) -> dict[str, Any]:
    settings = project.local()
    if agent not in settings.get("stand_ins", {}):
        raise SoftoryError(f"{agent} is not a stand-in", "not_found")
    decision = _record(coord, actor, f"{agent} no longer stands in", f"{agent} stops acting for any softory role.")
    del settings["stand_ins"][agent]
    project.save_local(settings)
    return {"removed": agent, "decision": decision, "regenerated": ops.sync(project)}


def adopt(project: Project, coord: Coordination, task_id: str, unit: str, options: dict[str, Any]) -> dict[str, Any]:
    """Bring a task without a unit into the hierarchy, keeping its ID and history."""
    gates = project.gates()
    actor = options["actor"]
    task = coord.task(task_id)
    if unit_of(task, gates) is not None:
        raise SoftoryError(f"{task_id} is already a unit", "invalid_arguments")
    parent_id = options.get("parent")
    parent_unit = unit_of(coord.task(parent_id), gates) if parent_id else None
    check_parent(unit, parent_unit, parent_id)
    targets = [t.strip() for t in (options.get("for") or "").split(",") if t.strip()]
    if task_id in targets:
        raise SoftoryError("A review cannot be for itself", "invalid_arguments")
    for target in targets:
        coord.task(target)  # a typo fails here, before anything changes
    extra = [t.strip() for t in (options.get("tags") or "").split(",") if t.strip()]
    tags = build_tags(unit, parent_id, options.get("lane"), extra, targets).split(",")
    tags += [t for t in tags_of(task) if t not in tags]
    coord.run("task", "update", task_id, "--tags", ",".join(tags), "--actor", actor, "--if-revision", str(task["revision"]))
    if parent_id:
        coord.run("dependency", "add", "--task", parent_id, "--depends-on", task_id, "--actor", actor,
                  "--type", "blocks", "--rationale", f"{task_id} was adopted into {parent_id}")
    assignee = options.get("assignee")
    if assignee:  # reassign: the new builder in, everyone else out
        changes = [] if assignee in (task.get("assignees") or []) else [("--add", assignee)]
        changes += [("--remove", other) for other in task.get("assignees") or [] if other != assignee]
        for flag, agent in changes:
            revision = str(coord.task(task_id)["revision"])
            coord.run("task", "assign", task_id, "--actor", actor, flag, agent, "--if-revision", revision)
    result = {"id": task_id, "unit": unit, "tags": ",".join(tags), "parent": parent_id,
              "assignees": coord.task(task_id).get("assignees")}
    accepted = _accepted_by(task, gates)
    if accepted:
        result["warning"] = (f"{', '.join(accepted)} already accepted this task. Check the code before building it; "
                             "it may be done and only need closing.")
    return result


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
        rejecting = sorted(r for r, review in latest.items() if review.get("decision") not in gates["accepting_decisions"])
        row = {"id": task["id"], "status": task["status"], "title": task["title"],
               "assignees": task.get("assignees") or [], "accepted_by": accepted, "changes_requested_by": rejecting}
        (ready if task["status"] == "review" and not rejecting else accepted_but_open).append(row)
    review_runs = [
        {"id": t["id"], "status": t["status"], "title": t["title"], "assignees": t.get("assignees") or []}
        for t in open_tasks if unit_of(t, gates) is None and _looks_like_review_run(t)
    ]
    return {
        "ready_to_close": ready,
        "accepted_but_open": accepted_but_open,
        "review_runs": review_runs,
        "sessions": _session_report(project, coord),
        "next": ("Run softory gate on each ready task. For the others, check the code: close finished work, or say "
                 "what is left. For each review run, its reviewer runs softory adopt <ID> --unit review --for "
                 "<reviewed IDs>, then softory close <ID>. End silent sessions; restart sessions older than the install."),
    }


def _looks_like_review_run(task: dict[str, Any]) -> bool:
    """A guess for triage only: tagged or named as a review, and not a fix."""
    words = task["id"].upper().split("-")
    return ("review" in tags_of(task) or "REVIEW" in words) and "FIX" not in words


def _session_report(project: Project, coord: Coordination) -> dict[str, list[dict[str, str]]]:
    """Active sessions nobody has seen for a day, and ones running rules older than this install."""
    now = datetime.now(timezone.utc)
    installed = str(project.manifest().get("installed_at") or "")
    silent, before_install = [], []
    for session in coord.all_rows("session", "list", "--status", "active"):
        row = {"id": session["id"], "agent": session["agent_id"], "started_at": session["started_at"],
               "last_seen_at": session["last_seen_at"]}
        seen = datetime.fromisoformat(session["last_seen_at"].replace("Z", "+00:00"))
        if now - (seen if seen.tzinfo else seen.replace(tzinfo=timezone.utc)) > timedelta(hours=24):
            silent.append(row)
        elif installed and session["started_at"] < installed:
            before_install.append(row)
    return {"silent": silent, "started_before_install": before_install}


def _accepted_by(task: dict[str, Any], gates: dict[str, Any]) -> list[str]:
    latest = gate_rules.latest_reviews(task)
    return sorted(r for r, review in latest.items() if review.get("decision") in gates["accepting_decisions"])


def _record(coord: Coordination, owner: str, title: str, decision: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    decision_id = f"SOFTORY-DEC-STANDIN-{stamp}"
    coord.run("decision", "add", "--id", decision_id, "--title", title, "--owner", owner, "--status", "accepted",
              "--context", "The owner named a stand-in under softory's flex rule (boundaries.md).",
              "--decision", decision)
    return decision_id
