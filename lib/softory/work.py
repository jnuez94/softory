"""Commands agents use while working: start, new, tree, queue, reviewers, gate."""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Any

from . import gate as gate_rules
from .coordination import Coordination
from .errors import SoftoryError
from .project import Project
from .units import (
    build_tags,
    check_parent,
    children_by_parent,
    next_id,
    parent_of,
    unit_of,
)


def _actor(explicit: str | None) -> str:
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


def new_unit(project: Project, coord: Coordination, unit: str, options: dict[str, Any]) -> dict[str, Any]:
    """Create an epic, story, task, or bug with softory's tags and parent link."""
    gates = project.gates()
    spec = gates["units"][unit]
    actor = _actor(options.get("actor"))
    parent_id = options.get("parent")
    parent_unit = None
    if parent_id:
        parent_unit = unit_of(coord.task(parent_id), gates)
    check_parent(unit, parent_unit, parent_id)
    extra = [t.strip() for t in (options.get("tags") or "").split(",") if t.strip()]
    tags = build_tags(unit, parent_id, options.get("lane"), extra)

    assignee = options.get("assignee") or spec.get("default_assignee")
    if not assignee and options.get("lane"):
        assignee = spec.get("default_assignee_by_lane", {}).get(options["lane"])
    description = options.get("description")
    if description is None:
        description = (project.factory_file(f"templates/{'task' if unit == 'bug' else unit}.md")).read_text(encoding="utf-8")

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
    return {"id": task_id, "unit": unit, "tags": tags, "assignee": assignee, "parent": parent_id}


def tree(project: Project, coord: Coordination, root_id: str | None) -> str:
    """Render the epic > story > task hierarchy as indented text."""
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
        for task in grouped.get(None, []):
            render(task, 0)
        orphans = [t for t in tasks if parent_of(t) and parent_of(t) not in by_id]
        for task in orphans:
            render(task, 0)
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
    return gate_rules.evaluate(task, gates, dependency_status, children, actor or os.environ.get("SOFTORY_ROLE"))


def close(project: Project, coord: Coordination, task_id: str, actor: str | None) -> dict[str, Any]:
    """Run the gate and, only if it passes, move the unit to done."""
    actor = _actor(actor)
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
        eligible = [r for r in requirement["reviewers"] if not (requirement.get("not_self") and r in built_by)]
        rows.append({
            "why": requirement["why"],
            "source": requirement["source"],
            "reviewers": eligible,
            "latest": {r: latest[r]["decision"] for r in eligible if r in latest},
        })
    return {"id": task_id, "builders": sorted(built_by), "requirements": rows}


def queue(project: Project, coord: Coordination, agent: str | None) -> dict[str, Any]:
    """The acting role's claimed work, assigned work, and pending reviews."""
    agent = _actor(agent)
    gates = project.gates()
    open_statuses = ["--status", "todo", "--status", "in_progress", "--status", "blocked"]
    mine = coord.all_tasks("--assignee", agent, *open_statuses)
    claimed = [t["id"] for t in mine if t.get("claimed_by") == agent]
    assigned = [
        {"id": t["id"], "status": t["status"], "priority": t["priority"], "title": t["title"]}
        for t in sorted(mine, key=lambda t: (t["priority"], t["id"]))
        if t.get("claimed_by") != agent
    ]
    to_review = []
    for summary in coord.all_tasks("--status", "review"):
        task = coord.task(summary["id"])
        latest = gate_rules.latest_reviews(task)
        built_by = gate_rules.builders(task)
        for requirement in gate_rules.required_reviews(task, gates):
            if agent in requirement["reviewers"] and not (requirement.get("not_self") and agent in built_by):
                if latest.get(agent, {}).get("decision") not in gates["accepting_decisions"]:
                    to_review.append({"id": task["id"], "why": requirement["why"], "title": task["title"]})
                break
    return {"agent": agent, "claimed": claimed, "reviews_waiting": to_review, "assigned": assigned}
