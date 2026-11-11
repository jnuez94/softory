"""Ways a unit reaches done besides a plain close: dropped, or closed with its stack.

The scaffold moves a task to done only from review, and into review only
through a claim. ``move_to_done`` walks those steps for the acting role, so
a review record or a dropped task can close from todo or blocked.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import gate as gate_rules
from . import policy
from .coordination import Coordination
from .errors import SoftoryError
from .owner import record_decision
from .project import Project
from .units import WITHDRAWN, stack_of, tags_of, unit_of

#: The note every softory close leaves on a task; triage looks for done work without one.
CLOSE_NOTE = "closed through softory gate"
DROP_NOTE = "dropped ("


def closed_by_softory(task: dict[str, Any]) -> bool:
    """Whether a done task's note is one softory's close or drop wrote."""
    note = task.get("notes") or ""
    return note.startswith(CLOSE_NOTE) or note.startswith(DROP_NOTE)


def update_tags(coord: Coordination, task: dict[str, Any], tags: list[str], actor: str) -> None:
    """Rewrite a task's tags. A task the actor holds needs its session; one held by someone else fails."""
    coord.run("task", "update", task["id"], "--tags", ",".join(tags), "--actor", actor,
              "--if-revision", str(task["revision"]), session=task.get("claimed_by") == actor)


def handoff(project: Project, coord: Coordination, task_id: str, actor: str, note: str = "") -> dict[str, Any]:
    """Move a claimed unit to review, once it has what reviewers need: evidence and, for a ui unit, its
    rendered check against the design reference. Both used to show only at close, after a review round."""
    task = coord.task(task_id)
    if task["status"] != "in_progress" or task.get("claimed_by") != actor:
        raise SoftoryError(f"{task_id} isn't in progress under your claim ({task['status']}, "
                           f"claimed by {task.get('claimed_by') or 'nobody'})", "invalid_task_state")
    ready_for_review(project, task)
    extra = ["--note", note] if note else []
    coord.run("task", "release", task_id, "--to", "review", "--actor", actor, "--if-revision",
              str(task["revision"]), *extra, session=True)
    return {"task": task_id, "status": "review", "next": f"softory reviewers {task_id}, then message each one"}


def ready_for_review(project: Project, task: dict[str, Any]) -> None:
    """Refuse a unit reviewers would get nothing to review on: no evidence, or a ui unit with no reference check
    (an owner's waiver of that check counts). ``softory handoff`` and ``softory coord task release`` both ask."""
    from .units import live_evidence  # noqa: PLC0415

    if not live_evidence(task.get("evidence")):
        raise SoftoryError(f"{task['id']} has no evidence: record the commit with softory commit first",
                           "evidence_required")
    reference = gate_rules.ui_reference_check(task, project.gates())
    if reference and not reference["pass"]:
        raise SoftoryError(f"{task['id']}: {reference['detail']}", "ui_reference_missing")
    left = left_behind(project, task)
    if left:
        listed = ", ".join(left[:5]) + (f" and {len(left) - 5} more" if len(left) > 5 else "")
        raise SoftoryError(f"{task['id']}: untracked files appeared in the main checkout during this claim ({listed}). "
                           f"Commit what belongs in the repository, file a report with softory report {task['id']} "
                           f"<file>, and delete the rest: keep the process simple", "untracked_files")


def left_behind(project: Project, task: dict[str, Any]) -> list[str]:
    """Untracked files in the main checkout changed since the unit was claimed: what this run left lying around.
    Off when the charter's simplify.clean_handoff is false."""
    from . import charter as charters  # noqa: PLC0415
    from .clutter import untracked_files  # noqa: PLC0415

    if not (charters.load(project).get("simplify") or {}).get("clean_handoff", True) or not task.get("claimed_at"):
        return []
    try:
        since = datetime.fromisoformat(str(task["claimed_at"]).replace("Z", "+00:00"))
    except ValueError:
        return []
    since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
    root = project.root.resolve()
    found = []
    for relative in untracked_files(root):
        try:
            if datetime.fromtimestamp((root / relative).stat().st_mtime, timezone.utc) >= since:
                found.append(relative)
        except OSError:
            continue
    return found


def move_to_done(coord: Coordination, task_id: str, actor: str, note: str, because: str | None = None,
                 dropping: bool = False, gate: dict[str, Any] | None = None) -> None:
    """Take a task to done through the moves the scaffold allows.

    From todo or blocked that means a claim, which needs the actor's session.
    ``--no-assign`` keeps the claim from making the actor one of the builders.
    Under strict closure (policy.py) finished dependencies are resolved first, and every dependency of
    dropped work. When softory's ``gate`` passed but the scaffold's single-review rule doesn't fit (Greg
    accepts the story he owns; changes requested with follow-ups filed), the gate's verdict is recorded
    as a decision and cited.
    """
    task = coord.task(task_id)
    status = task["status"]
    if status == "in_progress" and task.get("claimed_by") != actor:
        raise SoftoryError(f"{task_id} is claimed by {task.get('claimed_by')}; they must release it first",
                           "task_already_claimed")
    policy.resolve_dependencies(coord, task, actor, everything=dropping)
    if status in ("todo", "blocked"):
        coord.run("task", "claim", task_id, "--agent", actor, "--no-assign", "--if-revision", _revision(coord, task_id),
                  session=True)
        status = "in_progress"
    if status == "in_progress":
        coord.run("task", "release", task_id, "--to", "review", "--actor", actor,
                  "--if-revision", _revision(coord, task_id), session=True)
    extra = ["--because", because] if because else []
    done = coord.call("task", "status", task_id, "done", "--actor", actor, "--if-revision", _revision(coord, task_id),
                      "--note", note, *extra)
    error = done.get("error") or {}
    if not done.get("ok") and error.get("code") == "closure_requires_review" and gate and not because:
        decision = record_decision(coord, actor, "GATE", f"{task_id} passed softory's gate"[:200],
                                   f"Close {task_id}: softory's gate passed, which stands in for the scaffold's "
                                   "single accepted review.", _gate_summary(gate, error))
        done = coord.call("task", "status", task_id, "done", "--actor", actor,
                          "--if-revision", _revision(coord, task_id), "--note", note, "--because", f"decision:{decision}")
        error = done.get("error") or {}
    if not done.get("ok"):
        raise SoftoryError(error.get("message", "task status failed"), error.get("code", "coordination_error"),
                           error.get("details"))


def _gate_summary(gate: dict[str, Any], error: dict[str, Any]) -> str:
    reason = (error.get("details") or {}).get("reason", "")
    passed = "; ".join(f"{c['check']}: {c['detail']}" for c in gate.get("checks") or [] if c["check"].startswith("review"))
    return f"The scaffold refused ({reason or error.get('message', '')}). Reviews: {passed}"[:4000]


def _revision(coord: Coordination, task_id: str) -> str:
    return str(coord.task(task_id)["revision"])


def drop(project: Project, coord: Coordination, task_id: str, reason: str, superseded_by: str | None,
         actor: str, withdrawn: bool = False) -> dict[str, Any]:
    """Close a unit nobody will build, as won't do or superseded, with a recorded decision."""
    gates = project.gates()
    task = coord.task(task_id)
    if task["status"] == "done":
        raise SoftoryError(f"{task_id} is already done", "invalid_task_state")
    if not reason.strip():
        raise SoftoryError("Say why with --reason", "invalid_arguments")
    unit, spec = gate_rules.spec_for(task, gates)
    if withdrawn and unit != "bug":
        raise SoftoryError("Only a bug is withdrawn; drop other units as won't do or superseded", "invalid_arguments")
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
    if withdrawn:
        tags = [t for t in tags if not t.startswith("finding:")] + [f"finding:{WITHDRAWN}"]
    if superseded_by:
        tags.append(f"superseded-by:{superseded_by}")
    update_tags(coord, coord.task(task_id), tags, actor)
    move_to_done(coord, task_id, actor, f"{DROP_NOTE}{kind}): {reason}", because=f"decision:{decision_id}",
                 dropping=True)
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
    for lower, upper in zip(tasks, tasks[1:]):  # "built on", which never blocks a claim (scaffold 1.4.2)
        if not any(d.get("depends_on_task_id") == lower["id"] and d.get("dependency_type") in ("informs", "blocks")
                   for d in upper.get("dependencies") or []):
            coord.run("dependency", "add", "--task", upper["id"], "--depends-on", lower["id"], "--type", "informs",
                      "--actor", actor, "--rationale", f"{upper['id']} is built on {lower['id']} (stack {name})")
    members = [t["id"] for t in coord.all_tasks("--tag", f"stack:{name}")]
    return {"stack": name, "members": members,
            "next": f"When every member is in review with its own reviews, close them together: softory close {ids[-1]} --stack"}


def close_stack(project: Project, coord: Coordination, task_id: str, actor: str) -> dict[str, Any]:
    """Close every open member of the task's stack, or none of them.

    Each member must pass its own gate, objective checks included (tests at its commit,
    its lane), when the other members count as done. Members close bottom first: a member
    closes after every member it waits on.
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
    objective = {i: work.objective_checks(project, t, gates) for i, t in members.items()}

    passing = set(members)
    while True:
        reports = {}
        for member_id, task in members.items():
            deps = {dep["depends_on_task_id"]: "done" if dep["depends_on_task_id"] in passing
                    else statuses.get(dep["depends_on_task_id"], "")
                    for dep in task.get("dependencies") or []}
            reports[member_id] = gate_rules.evaluate(task, gates, deps, children[member_id], actor, related[member_id],
                                                     objective[member_id])
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
            move_to_done(coord, member_id, actor, f"{CLOSE_NOTE} with stack {name}", gate=reports[member_id])
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
