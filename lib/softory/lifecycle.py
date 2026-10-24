"""Ways a unit reaches done besides a plain close: dropped, or closed with its stack.

The scaffold moves a task to done only from review, and into review only
through a claim. ``move_to_done`` walks those steps for the acting role, so
a review record or a dropped task can close from todo or blocked.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import gate as gate_rules
from .coordination import Coordination
from .errors import SoftoryError
from .project import Project
from .units import stack_of, tags_of, unit_of


def update_tags(coord: Coordination, task: dict[str, Any], tags: list[str], actor: str) -> None:
    """Rewrite a task's tags. A task the actor holds needs its session; one held by someone else fails."""
    coord.run("task", "update", task["id"], "--tags", ",".join(tags), "--actor", actor,
              "--if-revision", str(task["revision"]), session=task.get("claimed_by") == actor)


def move_to_done(coord: Coordination, task_id: str, actor: str, note: str, because: str | None = None) -> None:
    """Take a task to done through the moves the scaffold allows.

    From todo or blocked that means a claim, which needs the actor's session.
    ``--no-assign`` keeps the claim from making the actor one of the builders.
    """
    task = coord.task(task_id)
    status = task["status"]
    if status == "in_progress" and task.get("claimed_by") != actor:
        raise SoftoryError(f"{task_id} is claimed by {task.get('claimed_by')}; they must release it first",
                           "task_already_claimed")
    if status in ("todo", "blocked"):
        coord.run("task", "claim", task_id, "--agent", actor, "--no-assign", "--if-revision", str(task["revision"]),
                  session=True)
        status = "in_progress"
    if status == "in_progress":
        coord.run("task", "release", task_id, "--to", "review", "--actor", actor,
                  "--if-revision", _revision(coord, task_id), session=True)
    extra = ["--because", because] if because else []
    coord.run("task", "status", task_id, "done", "--actor", actor, "--if-revision", _revision(coord, task_id),
              "--note", note, *extra)


def _revision(coord: Coordination, task_id: str) -> str:
    return str(coord.task(task_id)["revision"])


def drop(project: Project, coord: Coordination, task_id: str, reason: str, superseded_by: str | None,
         actor: str) -> dict[str, Any]:
    """Close a unit nobody will build, as won't do or superseded, with a recorded decision."""
    gates = project.gates()
    task = coord.task(task_id)
    if task["status"] == "done":
        raise SoftoryError(f"{task_id} is already done", "invalid_task_state")
    if not reason.strip():
        raise SoftoryError("Say why with --reason", "invalid_arguments")
    _, spec = gate_rules.spec_for(task, gates)
    listed = spec.get("dropper", ["owner"])
    allowed = set(gate_rules.with_stand_ins([d for d in listed if d != "assignee"], gates, task_id))
    if "assignee" in listed:
        allowed |= gate_rules.builders(task)
    if actor not in allowed:
        raise SoftoryError(f"Only {', '.join(sorted(allowed))} may drop {task_id}", "not_allowed")
    if superseded_by:
        if superseded_by == task_id:
            raise SoftoryError("A task can't supersede itself", "invalid_arguments")
        coord.task(superseded_by)  # must exist
    open_children = [c["id"] for c in coord.all_tasks("--tag", f"parent:{task_id}") if c["status"] != "done"]
    if open_children:
        raise SoftoryError(f"{task_id} still has open children: {', '.join(open_children)}. Close or drop them first.",
                           "children_open")
    if task["status"] == "in_progress" and task.get("claimed_by") != actor:
        raise SoftoryError(f"{task_id} is claimed by {task.get('claimed_by')}; they must release it first",
                           "task_already_claimed")

    kind = "superseded" if superseded_by else "wont-do"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    decision_id = f"SOFTORY-DROP-{task_id}-{stamp}"
    outcome = f"Superseded by {superseded_by}. " if superseded_by else "Won't do. "
    coord.run("decision", "add", "--id", decision_id, "--title", f"Drop {task_id}: {task['title']}"[:200],
              "--owner", actor, "--status", "accepted",
              "--context", f"{task_id} was {task['status']} and will not be built.",
              "--decision", outcome + reason)
    coord.run("evidence", "add", "--task", task_id, "--uri", f"decision:{decision_id}", "--type", "decision",
              "--actor", actor)
    tags = [t for t in tags_of(task) if not t.startswith(("resolution:", "superseded-by:"))]
    tags.append(f"resolution:{kind}")
    if superseded_by:
        tags.append(f"superseded-by:{superseded_by}")
    update_tags(coord, coord.task(task_id), tags, actor)
    move_to_done(coord, task_id, actor, f"dropped ({kind}): {reason}", because=f"decision:{decision_id}")
    parent = next((t.split(":", 1)[1] for t in tags if t.startswith("parent:")), None)
    result = {"dropped": task_id, "resolution": kind, "decision": decision_id}
    if superseded_by:
        result["superseded_by"] = superseded_by
    if parent:
        result["note"] = f"{parent} no longer waits for {task_id}."
    return result


def stack(project: Project, coord: Coordination, ids: list[str], actor: str) -> dict[str, Any]:
    """Group work built on top of other work, bottom first, so it can close together."""
    if len(ids) < 2 or len(set(ids)) != len(ids):
        raise SoftoryError("Name two or more different units, bottom of the stack first", "invalid_arguments")
    gates = project.gates()
    tasks = [coord.task(i) for i in ids]
    name = next((stack_of(t) for t in tasks if stack_of(t)), None) or ids[0]
    for task in tasks:
        _, spec = gate_rules.spec_for(task, gates)
        if spec.get("record") or unit_of(task, gates) in ("epic", "story"):
            raise SoftoryError(f"{task['id']} is not code work; only tasks and bugs stack", "invalid_arguments")
        if task["status"] == "done":
            raise SoftoryError(f"{task['id']} is already done", "invalid_task_state")
        current = stack_of(task)
        if current and current != name:
            raise SoftoryError(f"{task['id']} is already in stack {current}", "conflict")
    for task in tasks:
        if not stack_of(task):
            update_tags(coord, task, [*tags_of(task), f"stack:{name}"], actor)
    members = [t["id"] for t in coord.all_tasks("--tag", f"stack:{name}")]
    return {"stack": name, "members": members,
            "next": f"When every member is in review with its own reviews, close them together: softory close {ids[-1]} --stack"}


def close_stack(project: Project, coord: Coordination, task_id: str, actor: str) -> dict[str, Any]:
    """Close every open member of the task's stack, or none of them.

    Each member must pass its own gate when the other members count as done.
    Members close bottom first: a member closes after every member it waits on.
    """
    from . import work  # work imports this module

    gates = project.gates()
    name = stack_of(coord.task(task_id))
    if not name:
        raise SoftoryError(f"{task_id} is not in a stack; add it with softory stack", "invalid_arguments")
    everything = coord.all_tasks()
    statuses = {t["id"]: t["status"] for t in everything}
    members = {t["id"]: coord.task(t["id"]) for t in everything if stack_of(t) == name and t["status"] != "done"}
    children = {i: [t for t in everything if f"parent:{i}" in tags_of(t)] for i in members}
    related = {i: work.related_live(coord, t, gates) for i, t in members.items()}

    passing = set(members)
    while True:
        reports = {}
        for member_id, task in members.items():
            deps = {dep["depends_on_task_id"]: "done" if dep["depends_on_task_id"] in passing
                    else statuses.get(dep["depends_on_task_id"], "")
                    for dep in task.get("dependencies") or []}
            reports[member_id] = gate_rules.evaluate(task, gates, deps, children[member_id], actor, related[member_id])
        now = {i for i, report in reports.items() if report["pass"]}
        if now == passing:
            break
        passing = now
    if passing != set(members):
        failing = sorted(set(members) - passing)
        return {"closed": False, "stack": name, "failing": failing, "gates": [reports[i] for i in failing]}

    order = _bottom_first(members)
    closed = []
    for member_id in order:
        try:
            move_to_done(coord, member_id, actor, f"closed through softory gate with stack {name}")
        except SoftoryError as error:
            return {"closed": False, "stack": name, "closed_before_error": closed, "error": error.message}
        closed.append(member_id)
    return {"closed": True, "stack": name, "order": closed}


def _bottom_first(members: dict[str, dict[str, Any]]) -> list[str]:
    """Members in an order where each comes after every member it waits on."""
    waits = {i: {dep["depends_on_task_id"] for dep in t.get("dependencies") or []
                 if dep.get("dependency_type") == "blocks" and dep.get("status") == "active"
                 and dep["depends_on_task_id"] in members}
             for i, t in members.items()}
    order: list[str] = []
    while waits:
        ready = sorted(i for i, deps in waits.items() if not deps - set(order))
        if not ready:
            raise SoftoryError("Stack members wait on each other in a cycle: " + ", ".join(sorted(waits)), "conflict")
        order += ready
        for i in ready:
            del waits[i]
    return order
