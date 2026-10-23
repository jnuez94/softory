"""Commands agents use while working: start, new, tree, queue, reviewers, gate, close."""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Any

from . import gate as gate_rules
from . import lifecycle
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
    resolution_of,
    tag_value,
    tags_of,
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

    ``from`` files a follow-up: it inherits the source's story and lane and
    links back to the source. It doesn't hold the source open unless
    ``blocks_source`` says so. ``for`` names the tasks a review covers.
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
    if options.get("blocks_source") and source is None:
        raise SoftoryError("--blocks-source needs --from", "invalid_arguments")
    parent_unit = unit_of(coord.task(parent_id), gates) if parent_id else None
    check_parent(unit, parent_unit, parent_id)
    tags = build_tags(unit, parent_id, lane, _split(options.get("tags")), targets, source_id)

    assignee = options.get("assignee") or spec.get("default_assignee")
    if not assignee and lane:
        assignee = spec.get("default_assignee_by_lane", {}).get(lane)
    if not assignee and unit == "review":
        assignee = actor  # the reviewer holds their own review run
    if unit == "review":
        check_review_targets(coord, targets, {assignee, actor})
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
    if source is not None:
        coord.run("dependency", "add", "--task", task_id, "--depends-on", source_id, "--actor", actor,
                  "--type", "informs", "--rationale", f"{task_id} is a follow-up from {source_id}")
        result["follows_up"] = source_id
        if options.get("blocks_source") and source.get("status") != "done":
            coord.run("dependency", "add", "--task", source_id, "--depends-on", task_id, "--actor", actor,
                      "--type", "blocks", "--rationale", f"{source_id} can't close until its follow-up {task_id} does")
            result["blocks"] = source_id
    if unit == "story" and not parent_id:
        result["warning"] = "This story is not under an epic. Add --parent EPIC-n unless it stands alone."
    return result


def check_review_targets(coord: Coordination, targets: list[str], reviewers: set[str]) -> None:
    """A review covers existing work that its reviewer didn't build."""
    for target in targets:
        task = coord.task(target)  # a typo fails here, before anything is created
        own = sorted(gate_rules.builders(task) & reviewers)
        if own:
            raise SoftoryError(f"{', '.join(own)} built {target}, so a review of it by them isn't independent",
                               "not_independent")


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
        lines.append(f"{'  ' * depth}{task['id']} [{_shown_status(task)}] {task['title']} ({owners}{claim})")
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


def _shown_status(task: dict[str, Any]) -> str:
    resolution = resolution_of(task)
    if task["status"] != "done" or not resolution:
        return task["status"]
    if resolution == "superseded":
        replacement = tag_value(tags_of(task), "superseded-by")
        return f"done: superseded by {replacement}" if replacement else "done: superseded"
    return "done: won't do"


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
    return gate_rules.evaluate(task, gates, dependency_status, children,
                               actor or os.environ.get("SOFTORY_ROLE"), related_live(coord, task, gates))


def related_live(coord: Coordination, task: dict[str, Any], gates: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """What a review record's checks need: its reviewed tasks, its follow-ups, and the reviews on its targets."""
    targets, follow_ups = gate_rules.related_ids(task, gates)
    tasks: dict[str, Any] = {}
    for task_id in dict.fromkeys(targets + follow_ups):
        envelope = coord.call("task", "show", task_id)
        tasks[task_id] = envelope["data"] if envelope.get("ok") else None
    return {"tasks": tasks, "reviews": {t: reviews_of(coord, t) for t in targets if tasks.get(t)}}


def reviews_of(coord: Coordination, task_id: str) -> list[dict[str, Any]]:
    """Every review of one task, oldest first."""
    return coord.all_rows("review", "list", "--task", task_id, "--order-by", "created_at:asc", "--order-by", "id:asc")


def all_reviews(coord: Coordination) -> dict[str, list[dict[str, Any]]]:
    """Every review, grouped by task, oldest first (the order latest_reviews expects)."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for review in coord.all_rows("review", "list", "--order-by", "created_at:asc", "--order-by", "id:asc"):
        grouped.setdefault(review.get("task_id") or "", []).append(review)
    return grouped


def close(project: Project, coord: Coordination, task_id: str, actor: str | None, stack: bool = False) -> dict[str, Any]:
    """Run the gate and, only if it passes, move the unit to done.

    A review record may close from todo or blocked; softory makes the moves
    the scaffold needs, in the closer's session. ``stack`` closes the unit's
    whole stack together, or none of it.
    """
    actor = actor_of(actor)
    if stack:
        return lifecycle.close_stack(project, coord, task_id, actor)
    report = gate(project, coord, task_id, actor)
    if not report["pass"]:
        return {"closed": False, "gate": report}
    lifecycle.move_to_done(coord, task_id, actor, "closed through softory gate")
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
        row = {
            "why": requirement["why"],
            "source": requirement["source"],
            "reviewers": ["anyone but the builder"] if anyone else candidates,
            "latest": {r: latest[r]["decision"] for r in candidates if r in latest},
        }
        if requirement.get("note"):
            row["note"] = requirement["note"]
        rows.append(row)
    result: dict[str, Any] = {"id": task_id, "builders": sorted(built_by), "requirements": rows}
    if gate_rules.spec_for(task, gates)[1].get("record"):
        result["note"] = ("A review record is not reviewed again, unless a tag on it needs a reviewer its own reviewer "
                          "isn't. softory gate shows what it needs to close.")
    return result


class Board:
    """One read of every task and review, with ``task show`` cached, for commands that scan the project."""

    def __init__(self, project: Project, coord: Coordination, tasks: list[dict[str, Any]] | None = None,
                 reviews: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.project = project
        self.coord = coord
        self.gates = project.gates()
        self.tasks = coord.all_tasks() if tasks is None else tasks
        self.by_id = {t["id"]: t for t in self.tasks}
        self.reviews = all_reviews(coord) if reviews is None else reviews
        self.children = children_by_parent(self.tasks)
        self._shown: dict[str, dict[str, Any]] = {}

    def show(self, task_id: str) -> dict[str, Any]:
        if task_id not in self._shown:
            self._shown[task_id] = self.coord.task(task_id)
        return self._shown[task_id]

    def related(self, task: dict[str, Any]) -> dict[str, dict[str, Any]]:
        targets, follow_ups = gate_rules.related_ids(task, self.gates)
        return {"tasks": {i: self.by_id.get(i) for i in dict.fromkeys(targets + follow_ups)},
                "reviews": {t: self.reviews.get(t, []) for t in targets}}

    def evaluate(self, task_id: str, actor: str) -> dict[str, Any]:
        task = self.show(task_id)
        statuses = {dep["depends_on_task_id"]: self.by_id.get(dep["depends_on_task_id"], {}).get("status", "")
                    for dep in task.get("dependencies") or []}
        return gate_rules.evaluate(task, self.gates, statuses, self.children.get(task_id, []), actor, self.related(task))


def queue(project: Project, coord: Coordination, agent: str | None, board: Board | None = None) -> dict[str, Any]:
    """The acting role's claimed work, what it may close now, pending reviews, and assigned work."""
    agent = actor_of(agent)
    board = board or Board(project, coord)
    gates = board.gates
    mine = [t for t in board.tasks if agent in (t.get("assignees") or []) and t["status"] in ("todo", "in_progress", "blocked")]
    claimed = [t["id"] for t in mine if t.get("claimed_by") == agent]
    assigned = [
        {"id": t["id"], "status": t["status"], "priority": t["priority"], "title": t["title"]}
        for t in sorted(mine, key=lambda t: (t["priority"], t["id"]))
        if t.get("claimed_by") != agent
    ]
    to_review = []
    for summary in board.tasks:
        unit, spec = gate_rules.spec_for(summary, gates)
        if unit in (None, "legacy"):
            continue  # older tasks keep the project's own review routing
        if spec.get("record"):  # a record needs a sign-off only for a tag its reviewer can't give
            if summary["status"] not in gate_rules.RECORD_STATUSES or not any(
                    tag in gates["tag_reviews"] for tag in tags_of(summary)):
                continue
        elif summary["status"] != "review":
            continue
        task = board.show(summary["id"])
        latest = gate_rules.latest_reviews(task)
        built_by = gate_rules.builders(task)
        for requirement in gate_rules.required_reviews(task, gates):
            if gate_rules.may_review(requirement, agent, built_by):
                if latest.get(agent, {}).get("decision") not in gates["accepting_decisions"]:
                    to_review.append({"id": task["id"], "why": requirement["why"], "title": task["title"]})
                break
    return {"agent": agent, "claimed": claimed, "ready_to_close": ready_to_close(board, agent),
            "reviews_waiting": to_review, "assigned": assigned}


def ready_to_close(board: Board, agent: str) -> list[dict[str, Any]]:
    """Units that pass the gate and that ``agent`` may close."""
    gates = board.gates
    accepting = set(gates["accepting_decisions"])
    ready = []
    for summary in board.tasks:
        unit, spec = gate_rules.spec_for(summary, gates)
        record = bool(spec.get("record"))
        closable = ("review", *gate_rules.RECORD_STATUSES) if record else ("review",)
        if summary["status"] not in closable or not int(summary.get("evidence_count") or 0):
            continue
        if agent not in gate_rules.closers(summary, gates):
            continue
        latest = gate_rules.latest_reviews({"reviews": board.reviews.get(summary["id"], [])})
        if not record:
            if any(r.get("decision") not in accepting for r in latest.values()):
                continue  # someone wants changes; no need to ask the CLI
            needs_reviews = bool(spec.get("required_reviews")) or (
                spec.get("tag_reviews", True) and any(tag in gates["tag_reviews"] for tag in tags_of(summary)))
            if needs_reviews and not latest:
                continue  # nobody has reviewed it yet
        if board.evaluate(summary["id"], agent)["pass"]:
            ready.append({"id": summary["id"], "unit": unit, "title": summary["title"]})
    return ready
