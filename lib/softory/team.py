"""Joining a project that already has a team: adopting older tasks, and triage.

Adopting retags a task created before softory so it joins an epic or story
and the full gate, or marks a review run as a review record. Triage finds
finished work left open, review runs to adopt, stale sessions, and silent
roles. Stand-ins, the other half of joining a team, are the owner's: owner.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import gate as gate_rules
from . import watch, work
from .coordination import Coordination
from .errors import SoftoryError
from .project import Project
from .units import CODE_EVIDENCE, build_tags, check_parent, tags_of, unit_of


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
    skipped: list[str] = []
    targets = [t.strip() for t in (options.get("for") or "").split(",") if t.strip()]
    if unit == "review":
        targets, skipped = _review_targets(project, coord, task, actor, targets)
    elif targets:
        raise SoftoryError("Only a review takes --for", "invalid_arguments")
    extra = [t.strip() for t in (options.get("tags") or "").split(",") if t.strip()]
    tags = build_tags(unit, parent_id, options.get("lane"), extra, targets).split(",")
    tags += [t for t in tags_of(task) if t not in tags]
    coord.run("task", "update", task_id, "--tags", ",".join(tags), "--actor", actor, "--if-revision", str(task["revision"]),
              session=task.get("claimed_by") == actor)
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
    if skipped:
        result["not_targets"] = skipped
    accepted = _accepted_by(task, gates)
    if accepted and unit != "review":
        result["warning"] = (f"{', '.join(accepted)} already accepted this task. Check the code before building it; "
                             "it may be done and only need closing.")
    if unit == "review":
        result["next"] = f"softory gate {task_id}, then softory close {task_id}"
        sign_offs = gate_rules.record_requirements(coord.task(task_id), gates)
        if sign_offs:
            result["needs"] = [f"{r['why']}: {' or '.join(r['reviewers'])}" for r in sign_offs]
    return result


def _review_targets(project: Project, coord: Coordination, task: dict[str, Any], actor: str,
                    named: list[str]) -> tuple[list[str], list[str]]:
    """Check a task may become a review record, and settle what it reviewed.

    Only its reviewer (an assignee) or the owner may mark it, it must hold no
    code, and its reviewer must not have built what it reviewed. Without
    ``--for``, the tasks it links to with ``informs`` are the targets, less
    other review runs and the reviewer's own work.
    """
    owner = project.roster()["owner"]["id"]
    reviewers = gate_rules.builders(task)
    if actor not in reviewers and actor != owner:
        raise SoftoryError(f"Only {', '.join(sorted(reviewers)) or 'its reviewer'} or the owner may mark "
                           f"{task['id']} as a review run", "not_allowed")
    code = sorted({str(e.get("evidence_type")) for e in task.get("evidence") or []
                   if str(e.get("evidence_type", "")).lower() in CODE_EVIDENCE})
    if code:
        raise SoftoryError(f"{task['id']} has {', '.join(code)} evidence, so it delivered code; adopt it as a task or bug",
                           "not_a_review")
    if task["id"] in named:
        raise SoftoryError("A review cannot be for itself", "invalid_arguments")
    if named:
        work.check_review_targets(coord, named, reviewers)
        return named, []
    targets, skipped = [], []
    for dep in task.get("dependencies") or []:
        if dep.get("dependency_type") != "informs" or dep.get("status") != "active":
            continue
        linked = coord.task(dep["depends_on_task_id"])
        if gate_rules.builders(linked) & reviewers or _looks_like_review_run(linked) or "unit:review" in tags_of(linked):
            skipped.append(linked["id"])
        else:
            targets.append(linked["id"])
    if not targets:
        raise SoftoryError(f"Say what {task['id']} reviewed with --for <IDs>; it links to no task built by someone else",
                           "invalid_arguments")
    return targets, skipped


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
        {"id": t["id"], "status": t["status"], "title": t["title"], "assignees": t.get("assignees") or [],
         "adopt": f"softory adopt {t['id']} --unit review"}
        for t in open_tasks if unit_of(t, gates) is None and _looks_like_review_run(t)
    ]
    return {
        "ready_to_close": ready,
        "accepted_but_open": accepted_but_open,
        "review_runs": review_runs,
        "sessions": _session_report(project, coord),
        "silent_roles": watch.silent(project, coord)["silent"],
        "next": ("Run softory gate on each ready task. For the others, check the code: close finished work, drop "
                 "work nobody will build (softory drop), or say what is left. Each review run's reviewer runs its "
                 "adopt command (it finds what the run reviewed from its informs links, or add --for), then "
                 "softory close <ID>. End silent sessions; restart sessions older than the install; tell the owner "
                 "about silent roles."),
    }


REVIEW_RUN_TAGS = ("review", "code-review", "independent-review", "security-review")


def _looks_like_review_run(task: dict[str, Any]) -> bool:
    """A guess for triage only: tagged or named as a review, and not a fix."""
    words = task["id"].upper().split("-")
    tagged = any(tag in REVIEW_RUN_TAGS for tag in tags_of(task))
    return (tagged or "REVIEW" in words) and "FIX" not in words


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
