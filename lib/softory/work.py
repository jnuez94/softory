"""Commands agents use while working: start, new, tree, queue, pending, reviewers, gate."""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from . import gate as gate_rules
from .coordination import Coordination
from .errors import SoftoryError
from .project import Project
from .units import (
    build_tags,
    check_parent,
    children_by_parent,
    lane_of,
    next_id,
    parent_of,
    tags_of,
    targets_of,
    unit_of,
)


def actor_of(explicit: str | None) -> str:
    actor = explicit or os.environ.get("SOFTORY_ROLE")
    if not actor:
        raise SoftoryError("Name the acting role with --actor or start a session first", "invalid_arguments")
    return actor


def start(project: Project, coord: Coordination, role_id: str, harness: str | None, model: str) -> str:
    """Start an execution session for a role and return shell exports."""
    role = project.role(role_id)
    harness = harness or role.get("recommended_harness") or "unspecified"
    if not coord.agent_exists(role_id):
        raise SoftoryError(f"Agent {role_id!r} is not registered. Re-run the softory installer.", "not_found")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    session_id = f"{role_id}-{harness}-{stamp}-{secrets.token_hex(2)}"
    args = ["session", "start", "--id", session_id, "--agent", role_id, "--harness", harness]
    if model:
        args += ["--model", model]
    coord.run(*args)
    return f"export COORDINATION_SESSION={session_id}\nexport SOFTORY_ROLE={role_id}\n"


def end(coord: Coordination, session: str | None) -> dict[str, Any]:
    """End the session ``softory start`` opened, so its claims don't go stale."""
    session = session or os.environ.get("COORDINATION_SESSION")
    if not session:
        raise SoftoryError("No session to end: pass --session or set COORDINATION_SESSION", "invalid_arguments")
    coord.run("session", "end", session)
    return {"ended": session}


def new_unit(project: Project, coord: Coordination, unit: str, options: dict[str, Any]) -> dict[str, Any]:
    """Create an epic, story, task, bug, or review with softory's tags and links.

    ``from`` files a follow-up: it inherits the source's story and lane, and
    an open source task waits for it. ``for`` names the tasks a review covers.
    """
    gates = project.gates()
    spec = gates["units"][unit]
    actor = actor_of(options.get("actor"))
    targets = _split(options.get("for"))
    source_id = options.get("from")
    source = coord.task(source_id) if source_id else None
    parent_id = options.get("parent")
    lane = options.get("lane")
    if source is not None:
        parent_id = parent_id or _inherited_parent(source, gates, unit)
        lane = lane or (lane_of(source) if unit in ("task", "bug") else None)
    parent_unit = unit_of(coord.task(parent_id), gates) if parent_id else None
    check_parent(unit, parent_unit, parent_id)
    for target in targets:
        coord.task(target)  # a typo fails here, before anything is created
    tags = build_tags(unit, parent_id, lane, _split(options.get("tags")), targets, source_id)

    assignee = options.get("assignee") or spec.get("default_assignee")
    if not assignee and lane:
        assignee = spec.get("default_assignee_by_lane", {}).get(lane)
    if not assignee and unit == "review":
        assignee = actor  # the reviewer holds their own review run
    description = options.get("description")
    if description is None:
        template = "task" if unit == "bug" else unit
        description = project.factory_file(f"templates/{template}.md").read_text(encoding="utf-8")

    existing = [task["id"] for task in coord.all_tasks()]
    for _attempt in range(5):
        task_id = next_id(spec["id_prefix"], existing)
        args = ["task", "create", "--id", task_id, "--title", options["title"], "--actor", actor,
                "--tags", tags, "--description", description, "--priority", str(options.get("priority") or 3)]
        if options.get("acceptance"):
            args += ["--acceptance", options["acceptance"]]
        if assignee:
            args += ["--assignee", assignee]
        envelope = coord.call(*args)
        if envelope.get("ok"):
            break
        error = envelope.get("error") or {}
        taken = error.get("code") == "constraint_violation" and coord.call("task", "show", task_id).get("ok")
        if not taken:  # a real failure, not a race for the same ID
            raise SoftoryError(error.get("message", "task create failed"), error.get("code", "coordination_error"), error.get("details"))
        existing.append(task_id)
    else:
        raise SoftoryError("Could not allocate a free ID after 5 tries", "conflict")

    if parent_id:
        coord.run("dependency", "add", "--task", parent_id, "--depends-on", task_id,
                  "--actor", actor, "--type", "blocks", "--rationale", f"{task_id} is a child of {parent_id}")
    result: dict[str, Any] = {"id": task_id, "unit": unit, "tags": tags, "assignee": assignee, "parent": parent_id}
    if source is not None and source.get("status") != "done" and unit_of(source, gates) != "review":
        coord.run("dependency", "add", "--task", source_id, "--depends-on", task_id, "--actor", actor,
                  "--type", "blocks", "--rationale", f"{task_id} is a follow-up from {source_id}")
        result["blocks"] = source_id
    if unit == "story" and not parent_id:
        result["warning"] = "This story is not under an epic. Add --parent EPIC-n unless it stands alone."
    return result


def _split(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _inherited_parent(source: dict[str, Any], gates: dict[str, Any], unit: str) -> str | None:
    """Where a follow-up sits: under the source if it can hold one, else beside it."""
    source_unit = unit_of(source, gates)
    if source_unit == "story" or (source_unit == "epic" and unit in ("story", "bug")):
        return source["id"]
    return parent_of(source)


def tree(project: Project, coord: Coordination, root_id: str | None, show_all: bool = False) -> str:
    """Render the epic > story > task hierarchy as indented text."""
    gates = project.gates()
    tasks = coord.all_tasks()
    grouped = children_by_parent(tasks)
    by_id = {task["id"]: task for task in tasks}
    lines: list[str] = []

    def render(task: dict[str, Any], depth: int) -> None:
        owners = ",".join(task.get("assignees") or []) or "unassigned"
        claim = f" claimed:{task['claimed_by']}" if task.get("claimed_by") else ""
        lines.append(f"{'  ' * depth}{task['id']} [{task['status']}] {task['title']} ({owners}{claim})")
        for child in grouped.get(task["id"], []):
            render(child, depth + 1)

    if root_id:
        if root_id not in by_id:
            raise SoftoryError(f"No task {root_id}", "not_found")
        render(by_id[root_id], 0)
    else:
        top = grouped.get(None, []) + [t for t in tasks if parent_of(t) and parent_of(t) not in by_id]
        older = [t for t in top if unit_of(t, gates) is None]
        reviews = [t for t in top if unit_of(t, gates) == "review"]
        shown = top if show_all else [t for t in top if t not in older and t not in reviews]
        epics = [t for t in shown if unit_of(t, gates) == "epic"]
        loose = [t for t in shown if t not in epics]
        for task in epics:
            render(task, 0)
        if loose:
            lines.append("Not under an epic:")
            for task in loose:
                render(task, 1)
        if older and not show_all:
            lines.append(f"({len(older)} task(s) without a unit not shown; add --all to list them)")
        if reviews and not show_all:
            lines.append(f"({len(reviews)} review run(s) not shown; add --all to list them)")
    return "\n".join(lines) + ("\n" if lines else "(no work yet)\n")


def gate(project: Project, coord: Coordination, task_id: str, actor: str | None) -> dict[str, Any]:
    """Evaluate the done-gate for one unit."""
    gates = project.gates()
    task = coord.task(task_id)
    dependency_status = {
        dep["depends_on_task_id"]: coord.task(dep["depends_on_task_id"])["status"]
        for dep in task.get("dependencies") or []
        if dep.get("dependency_type") == "blocks" and dep.get("status") == "active"
    }
    children = coord.all_tasks("--tag", f"parent:{task_id}")
    targets = {target: _reviews_of(coord, target) for target in _targets_needing_verdicts(task, gates)}
    return gate_rules.evaluate(task, gates, dependency_status, children,
                               actor or os.environ.get("SOFTORY_ROLE"), targets)


def _targets_needing_verdicts(task: dict[str, Any], gates: dict[str, Any]) -> list[str]:
    _, spec = gate_rules.spec_for(task, gates)
    return targets_of(task) if spec.get("verdicts_on_targets") else []


def _reviews_of(coord: Coordination, task_id: str) -> list[dict[str, Any]]:
    envelope = coord.call("review", "list", "--task", task_id, "--order-by", "created_at:asc",
                          "--order-by", "id:asc", "--limit", "500")
    return (envelope.get("data") or []) if envelope.get("ok") else []


def all_reviews(coord: Coordination) -> dict[str, list[dict[str, Any]]]:
    """Every review, grouped by task, oldest first (the order latest_reviews expects)."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for review in coord.all_rows("review", "list", "--order-by", "created_at:asc", "--order-by", "id:asc"):
        grouped.setdefault(review.get("task_id") or "", []).append(review)
    return grouped


def close(project: Project, coord: Coordination, task_id: str, actor: str | None) -> dict[str, Any]:
    """Run the gate and, only if it passes, move the unit to done."""
    actor = actor_of(actor)
    report = gate(project, coord, task_id, actor)
    if not report["pass"]:
        return {"closed": False, "gate": report}
    revision = str(coord.task(task_id)["revision"])
    coord.run("task", "status", task_id, "done", "--actor", actor, "--if-revision", revision,
              "--note", "closed through softory gate")
    return {"closed": True, "id": task_id, "gate": report}


def reviewers(project: Project, coord: Coordination, task_id: str) -> dict[str, Any]:
    """Who must review the unit, and where each requirement stands."""
    gates = project.gates()
    task = coord.task(task_id)
    latest = gate_rules.latest_reviews(task)
    built_by = gate_rules.builders(task)
    rows = []
    for requirement in gate_rules.required_reviews(task, gates):
        candidates = gate_rules.eligible(requirement, built_by, latest)
        anyone = gate_rules.ANYONE in requirement["reviewers"]
        rows.append({
            "why": requirement["why"],
            "source": requirement["source"],
            "reviewers": ["anyone but the builder"] if anyone else candidates,
            "latest": {r: latest[r]["decision"] for r in candidates if r in latest},
        })
    return {"id": task_id, "builders": sorted(built_by), "requirements": rows}


def queue(project: Project, coord: Coordination, agent: str | None,
          tasks: list[dict[str, Any]] | None = None,
          reviews: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """The acting role's claimed work, what it may close now, pending reviews, and assigned work."""
    agent = actor_of(agent)
    gates = project.gates()
    tasks = coord.all_tasks() if tasks is None else tasks
    mine = [t for t in tasks if agent in (t.get("assignees") or []) and t["status"] in ("todo", "in_progress", "blocked")]
    claimed = [t["id"] for t in mine if t.get("claimed_by") == agent]
    assigned = [
        {"id": t["id"], "status": t["status"], "priority": t["priority"], "title": t["title"]}
        for t in sorted(mine, key=lambda t: (t["priority"], t["id"]))
        if t.get("claimed_by") != agent
    ]
    to_review = []
    for summary in tasks:
        if summary["status"] != "review" or unit_of(summary, gates) is None:
            continue  # older tasks keep the project's own review routing
        task = coord.task(summary["id"])
        latest = gate_rules.latest_reviews(task)
        built_by = gate_rules.builders(task)
        for requirement in gate_rules.required_reviews(task, gates):
            if gate_rules.may_review(requirement, agent, built_by):
                if latest.get(agent, {}).get("decision") not in gates["accepting_decisions"]:
                    to_review.append({"id": task["id"], "why": requirement["why"], "title": task["title"]})
                break
    reviews = all_reviews(coord) if reviews is None else reviews
    return {"agent": agent, "claimed": claimed, "ready_to_close": ready_to_close(project, coord, agent, tasks, reviews),
            "reviews_waiting": to_review, "assigned": assigned}


def ready_to_close(project: Project, coord: Coordination, agent: str, tasks: list[dict[str, Any]],
                   reviews: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Tasks in review that pass the gate and that ``agent`` may close."""
    gates = project.gates()
    statuses = {t["id"]: t["status"] for t in tasks}
    children = children_by_parent(tasks)
    accepting = set(gates["accepting_decisions"])
    ready = []
    for summary in tasks:
        if summary["status"] != "review" or not int(summary.get("evidence_count") or 0):
            continue
        unit, spec = gate_rules.spec_for(summary, gates)
        closers = spec.get("closer", [])
        named = gate_rules.with_stand_ins([c for c in closers if c != "assignee"], gates)
        if agent not in named and not ("assignee" in closers and agent in gate_rules.builders(summary)):
            continue
        latest = gate_rules.latest_reviews({"reviews": reviews.get(summary["id"], [])})
        if any(r.get("decision") not in accepting for r in latest.values()):
            continue  # someone wants changes; no need to ask the CLI
        needs_reviews = bool(spec.get("required_reviews")) or (
            spec.get("tag_reviews", True) and any(tag in gates["tag_reviews"] for tag in tags_of(summary)))
        if needs_reviews and not latest:
            continue  # nobody has reviewed it yet
        task = coord.task(summary["id"])
        targets = {t: reviews.get(t, []) for t in _targets_needing_verdicts(task, gates)}
        dependency_status = {dep["depends_on_task_id"]: statuses.get(dep["depends_on_task_id"], "")
                             for dep in task.get("dependencies") or []}
        report = gate_rules.evaluate(task, gates, dependency_status, children.get(task["id"], []), agent, targets)
        if report["pass"]:
            ready.append({"id": task["id"], "unit": unit, "title": task["title"]})
    return ready


def pending(project: Project, coord: Coordination, agent: str | None, since: str | None = None) -> dict[str, Any]:
    """Whether a role has anything to do, without starting a session or a model.

    Put it in front of a scheduled run so an idle role costs no tokens:
    ``softory pending greg && codex exec ...``. Work counts when it changed
    after the role's last finished session started; unread messages and
    tasks ready to close always count. A role that is already running
    (a session seen in the last 30 minutes) is not started again.
    """
    agent = actor_of(agent)
    sessions = coord.run("session", "list", "--agent", agent, "--order-by", "started_at:desc", "--limit", "20")
    now = datetime.now(timezone.utc)
    running = [s["id"] for s in sessions if s.get("status") == "active"
               and now - _parse_time(s["last_seen_at"]) < timedelta(minutes=30)]
    if since is None:
        finished = [s["started_at"] for s in sessions if s.get("status") != "active"]
        since = max(finished, default=None)
    tasks = coord.all_tasks()
    reviews = all_reviews(coord)
    touched = {t["id"]: max([t["updated_at"], *(r["created_at"] for r in reviews.get(t["id"], []))]) for t in tasks}

    def changed(ids: list[str]) -> list[str]:
        return [i for i in ids if since is None or touched.get(i, "") > since]

    work = queue(project, coord, agent, tasks, reviews)
    reasons = []
    inbox = coord.run("inbox", "list", "--agent", agent, "--limit", "100")
    unread = inbox.get("messages", []) if isinstance(inbox, dict) else inbox
    if unread:
        reasons.append({"why": "unread messages", "count": len(unread)})
    if work["ready_to_close"]:
        reasons.append({"why": "ready to close", "ids": [t["id"] for t in work["ready_to_close"]]})
    for why, ids in (
        ("reviews waiting", changed([t["id"] for t in work["reviews_waiting"]])),
        ("claimed work changed", changed(work["claimed"])),
        ("assigned work changed", changed([t["id"] for t in work["assigned"] if t["status"] != "blocked"])),
    ):
        if ids:
            reasons.append({"why": why, "ids": ids})
    return {"agent": agent, "pending": bool(reasons) and not running, "since": since,
            "running": running, "reasons": reasons}


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
