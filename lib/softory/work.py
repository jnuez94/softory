"""Commands agents use while working: start, new, tree, queue, reviewers, gate, close."""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Any, Callable

from . import charter, feasibility, lifecycle, runstate, sessions, verify, verifyenv
from . import design as design_rules
from . import gate as gate_rules
from .coordination import Coordination
from .errors import SoftoryError
from .project import Project
from .units import (
    build_tags,
    check_parent,
    children_by_parent,
    lane_of,
    live_evidence,
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
    session_id = open_session(project, coord, role_id, harness, model)
    return f"export COORDINATION_SESSION={session_id}\nexport SOFTORY_ROLE={role_id}\n"


def open_session(project: Project, coord: Coordination, role_id: str, harness: str | None, model: str) -> str:
    """Start a session for a role, remember it for commands whose shell lost the exports, and return its ID."""
    role = project.role(role_id)
    if not model or not harness:  # usage and reviews compare models, so a session always names one
        pick = (charter.load(project).get("models") or {}).get(role_id) or {}
        harness = harness or pick.get("harness")
        model = model or (pick.get("model") if (pick.get("harness") or harness) == harness else "") or ""
    harness = harness or role.get("recommended_harness") or "unspecified"
    if not coord.agent_exists(role_id):
        raise SoftoryError(f"Agent {role_id!r} is not registered. Re-run the softory installer.", "not_found")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    session_id = f"{role_id}-{harness}-{stamp}-{secrets.token_hex(2)}"
    args = ["session", "start", "--id", session_id, "--agent", role_id, "--harness", harness]
    if model:
        args += ["--model", model]
    coord.run(*args)
    runstate.note_start(project, role_id, session_id)
    sessions.remember(project, role_id, session_id)
    return session_id


def end(project: Project, coord: Coordination, session: str | None) -> dict[str, Any]:
    """End the session ``softory start`` opened, so its claims don't go stale."""
    session = session or coord.session
    if not session:
        raise SoftoryError("No session to end: pass --session or --actor, or set COORDINATION_SESSION",
                           "invalid_arguments")
    coord.run("session", "end", session)
    sessions.forget(project, session)
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
    if options.get("design") and unit != "story":
        raise SoftoryError("Only a story takes --design", "invalid_arguments")
    if unit == "bug" and not options.get("type"):
        raise SoftoryError("A bug needs --type: functional, or visual (it renders or looks wrong)", "invalid_arguments")
    found = options.get("found_at") or ("review" if unit == "bug" and source is not None else None)
    tags = build_tags(unit, parent_id, lane, _split(options.get("tags")), targets, source_id,
                      options.get("type"), found)

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
    if unit == "story" and options.get("design"):
        # Darwin's UX direction starts now, in the repo, instead of waiting for Quinn's breakdown.
        design = new_unit(project, coord, "task", {
            "title": f"Design: {options['title']}", "parent": task_id, "lane": "design", "actor": actor,
            "priority": options.get("priority"),
            "acceptance": "Flows, states, and acceptance notes for the story's UI, ready for Quinn's breakdown."})
        result["design_task"] = design["id"]
    missing = missing_design_files(project, unit, options)
    if missing:
        templates = project.factory_file("templates").relative_to(project.root)
        result["reminder"] = (f"{' and '.join(missing)} not written yet. The design standard needs them before "
                              f"UI work: templates are in {templates}/ (Greg writes PRODUCT.md, Darwin DESIGN.md).")
    return result


def missing_design_files(project: Project, unit: str, options: dict[str, Any]) -> list[str]:
    """PRODUCT.md matters from the first epic; both matter once a story has UI. A reminder, never a block."""
    if unit == "epic":
        wanted = ["docs/product/PRODUCT.md"]
    elif unit == "story" and options.get("design"):
        wanted = ["docs/product/PRODUCT.md", "docs/design/DESIGN.md"]
    else:
        return []
    return [path for path in wanted if not (project.root / path).is_file()]


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
        lines.append(f"{'  ' * depth}{task['id']} [{_shown_status(task)}{progress(task['id'], grouped)}] "
                     f"{task['title']} ({owners}{claim})")
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


def progress(task_id: str, grouped: dict[Any, list[dict[str, Any]]]) -> str:
    """', 3/5 done' for a unit with children, counted from them, since the scaffold keeps no parent state (S5)."""
    children = grouped.get(task_id, [])
    if not children:
        return ""
    done = sum(1 for c in children if c["status"] == "done")
    moving = sum(1 for c in children if c["status"] in ("in_progress", "review"))
    return f", {done}/{len(children)} done" + (f", {moving} moving" if moving else "")


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
                               actor or os.environ.get("SOFTORY_ROLE"), related_live(coord, task, gates),
                               objective_checks(project, task, gates))


def objective_checks(project: Project, task: dict[str, Any], gates: dict[str, Any]) -> list[dict[str, Any]]:
    """The charter's checks on the code itself: tests passed at the commit, and the diff stays in its lane."""
    unit, _ = gate_rules.spec_for(task, gates)
    return verify.checks(project, charter.load(project), task, unit, gates)


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
    return coord.all_rows("review", "list", "--task", task_id, "--order-by", "sequence:asc")


def all_reviews(coord: Coordination) -> dict[str, list[dict[str, Any]]]:
    """Every review, grouped by task, oldest first (the order latest_reviews expects)."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for review in coord.all_rows("review", "list", "--order-by", "sequence:asc"):
        grouped.setdefault(review.get("task_id") or "", []).append(review)
    return grouped


def close(project: Project, coord: Coordination, task_id: str, actor: str | None, stack: bool = False) -> dict[str, Any]:
    """Run the gate and, only if it passes, move the unit to done.

    A review record may close from todo or blocked; softory makes the moves
    the scaffold needs, in the closer's session. ``stack`` closes the unit's
    whole stack together, or none of it.
    """
    actor = actor_of(actor)
    scope = runstate.scope_for(project, actor)
    if scope is not None and task_id not in scope:
        raise SoftoryError(f"{actor} is paused and may work only on {', '.join(sorted(scope))}; "
                           f"{task_id} waits for the owner's resume", "paused")
    if stack:
        return lifecycle.close_stack(project, coord, task_id, actor)
    report = gate(project, coord, task_id, actor)
    if not report["pass"]:
        return {"closed": False, "gate": report}
    lifecycle.move_to_done(coord, task_id, actor, lifecycle.CLOSE_NOTE)
    return {"closed": True, "id": task_id, "gate": report}


def close_ready(project: Project, coord: Coordination, actor: str | None) -> dict[str, Any]:
    """Close, one by one through the gate, every unit ``actor`` may close that passes now.

    For clearing a backlog of finished work in one go, such as older tasks whose reviews accepted them.
    """
    actor = actor_of(actor)
    found = ready_to_close(Board(project, coord), actor)
    scope = runstate.scope_for(project, actor)
    found = [row for row in found if scope is None or row["id"] in scope]
    closed, held = [], []
    for row in found:
        result = close(project, coord, row["id"], actor)
        (closed if result["closed"] else held).append(row["id"])
    return {"closed": closed, "closed_count": len(closed), "held": held}


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
        return gate_rules.evaluate(task, self.gates, statuses, self.children.get(task_id, []), actor,
                                   self.related(task), objective_checks(self.project, task, self.gates))


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
            if not gate_rules.may_review(requirement, agent, built_by):
                continue
            owed = review_owed(task, requirement, agent, built_by, latest, set(gates["accepting_decisions"]),
                               lambda e, r: _audit_id(coord, "evidence", e) > _audit_id(coord, "review", r))
            if owed is None:
                continue  # another listed reviewer already covered it; maybe the next requirement is the agent's
            if owed:
                to_review.append({"id": task["id"], "why": requirement["why"], "title": task["title"]})
            break
    ready = ready_to_close(board, agent)
    scope = runstate.scope_for(project, agent)
    if scope is not None:  # paused, with the owner's leave to work on these tasks only
        claimed = [i for i in claimed if i in scope]
        ready = [r for r in ready if r["id"] in scope]
        to_review = [r for r in to_review if r["id"] in scope]
        assigned = [a for a in assigned if a["id"] in scope]
    settings = charter.load(project)
    waits = feasibility.held(board, settings)
    designs = design_rules.held(board, settings)
    for row in assigned:
        if row["id"] in waits:
            row["waits_for"] = "its story's feasibility check"
        elif row["id"] in designs:
            row["waits_for"] = f"its story's design, {designs[row['id']]}"
    result = {"agent": agent, "claimed": claimed, "ready_to_close": ready, "reviews_waiting": to_review,
              "assigned": assigned, "verify_queue": verifyenv.waiting(project)}
    if scope is not None:
        result["scoped_to"] = sorted(scope)
    return result


def review_owed(task: dict[str, Any], requirement: dict[str, Any], agent: str, built_by: set[str],
                latest: dict[str, dict[str, Any]], accepting: set[str],
                came_after: Callable[[str, str], bool] | None = None) -> bool | None:
    """Whether ``agent`` owes ``task`` a review for ``requirement``: True, False (nothing to do now),
    or None (someone else satisfied the requirement, so it isn't the agent's).

    A reviewer who asked for changes owes a new pass only once new evidence lands after that request;
    until then the builder has the move. Timestamps are whole seconds, so evidence in the same second as
    the review is ordered by ``came_after(evidence_id, review_id)`` (the audit log); without it, a tie
    counts as new, since an extra pass costs less than a review nobody is woken for.
    """
    mine = latest.get(agent)
    if mine and mine.get("decision") in accepting:
        return False
    if mine:
        asked = str(mine.get("created_at") or "")
        rows = task.get("evidence") or []
        retractions = [r for r in rows if str(r.get("uri", "")).startswith("softory-supersedes:")]
        for row in [*live_evidence(rows), *retractions]:  # retracting a wrong row answers a request too
            stamp = str(row.get("created_at") or "9")
            if stamp > asked or (stamp == asked and (came_after is None
                                                     or came_after(str(row.get("id")), str(mine.get("id"))))):
                return True
        return False
    covered = any(latest.get(r, {}).get("decision") in accepting
                  for r in gate_rules.eligible(requirement, built_by, latest) if r != agent)
    return None if covered else True


def _audit_id(coord: Coordination, kind: str, object_id: str) -> int:
    """The audit row that recorded an evidence row or review: the order things happened in, to the row."""
    rows = coord.call("audit", "list", "--object-type", kind, "--object-id", object_id, "--limit", "1")
    found = (rows.get("data") or []) if rows.get("ok") else []
    return int(found[0]["id"]) if found else 0


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
