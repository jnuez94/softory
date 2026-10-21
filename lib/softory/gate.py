"""The done-gate: what must be true before a unit of work may close.

``evaluate`` is pure. It takes the task as ``task show`` returns it, the
statuses of the tasks it depends on and of its children, and gates.json, and
returns every check with a pass/fail and a reason.

Two things adapt the gate to a project that already had a team:

- ``gates["stand_ins"]`` maps an agent to the roles it stands in for. A
  stand-in may review and close wherever one of those roles may.
- A task with no unit (usually created before softory joined) falls under
  ``gates["legacy"]``. Its reviewer ``"*"`` means anyone but the builder.
"""

from __future__ import annotations

from typing import Any

from .units import tags_of, unit_of


ANYONE = "*"


def spec_for(task: dict[str, Any], gates: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """The task's unit and its gate spec. A task with no unit uses the legacy spec."""
    unit = unit_of(task, gates)
    if unit:
        return unit, gates["units"][unit]
    if "legacy" in gates:
        return "legacy", gates["legacy"]
    return None, {}


def with_stand_ins(roles: list[str], gates: dict[str, Any]) -> list[str]:
    """``roles`` plus every agent standing in for one of them."""
    extra = [agent for agent, covers in (gates.get("stand_ins") or {}).items()
             if agent not in roles and set(covers) & set(roles)]
    return [*roles, *sorted(extra)]


def required_reviews(task: dict[str, Any], gates: dict[str, Any]) -> list[dict[str, Any]]:
    """Every review requirement for the task, from its unit and its tags."""
    unit, spec = spec_for(task, gates)
    requirements: list[dict[str, Any]] = []
    for entry in spec.get("required_reviews", []):
        requirements.append({**entry, "source": f"unit:{unit}"})
    for tag in tags_of(task):
        if tag in gates["tag_reviews"]:
            entry = gates["tag_reviews"][tag]
            requirements.append({**entry, "source": f"tag:{tag}", "not_self": True})
    for requirement in requirements:
        requirement["reviewers"] = with_stand_ins(list(requirement["reviewers"]), gates)
    return requirements


def eligible(requirement: dict[str, Any], built_by: set[str], latest: dict[str, dict[str, Any]]) -> list[str]:
    """Who can satisfy the requirement. For ``*`` that is whoever has reviewed."""
    pool = list(latest) if ANYONE in requirement["reviewers"] else requirement["reviewers"]
    return [r for r in pool if not (requirement.get("not_self") and r in built_by)]


def may_review(requirement: dict[str, Any], agent: str, built_by: set[str]) -> bool:
    if requirement.get("not_self") and agent in built_by:
        return False
    return agent in requirement["reviewers"] or ANYONE in requirement["reviewers"]


def builders(task: dict[str, Any]) -> set[str]:
    """Who built the task: its assignees and any current claim holder."""
    people = set(task.get("assignees") or [])
    if task.get("claimed_by"):
        people.add(task["claimed_by"])
    return people


def latest_reviews(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Each reviewer's most recent review, in the CLI's (created_at, id) order."""
    latest: dict[str, dict[str, Any]] = {}
    for review in task.get("reviews") or []:
        latest[review.get("reviewer_id") or review["reviewer"]] = review
    return latest


def evaluate(
    task: dict[str, Any],
    gates: dict[str, Any],
    dependency_status: dict[str, str],
    children: list[dict[str, Any]],
    actor: str | None = None,
) -> dict[str, Any]:
    """Run every gate check. ``dependency_status`` maps task ID to status."""
    checks: list[dict[str, Any]] = []
    unit, spec = spec_for(task, gates)
    accepting = set(gates["accepting_decisions"])
    latest = latest_reviews(task)
    built_by = builders(task)

    unit_detail = {None: "no unit:* tag or known ID prefix", "legacy": "no unit tag, so the legacy rule applies"}
    checks.append(_check("unit", unit is not None, unit_detail.get(unit, f"unit is {unit}")))
    checks.append(_check("status", task.get("status") == "review", f"status is {task.get('status')}; it must be review"))
    evidence = int(task.get("evidence_count") or 0)
    checks.append(_check("evidence", evidence > 0, f"{evidence} evidence row(s)"))

    open_deps = [
        dep["depends_on_task_id"]
        for dep in task.get("dependencies") or []
        if dep.get("dependency_type") == "blocks"
        and dep.get("status") == "active"
        and dependency_status.get(dep["depends_on_task_id"]) != "done"
    ]
    checks.append(_check("blocks_resolved", not open_deps, "open: " + ", ".join(open_deps) if open_deps else "no open blocking dependencies"))

    if spec.get("children_must_be_done"):
        undone = [child["id"] for child in children if child.get("status") != "done"]
        checks.append(_check("children_done", not undone, "not done: " + ", ".join(undone) if undone else f"{len(children)} child unit(s) done"))

    for requirement in required_reviews(task, gates):
        candidates = eligible(requirement, built_by, latest)
        passed_by = [r for r in candidates if latest.get(r, {}).get("decision") in accepting]
        named = ANYONE not in requirement["reviewers"] and " or ".join(candidates)
        detail = (
            f"accepted by {', '.join(passed_by)}"
            if passed_by
            else f"needs an accepted review from {named or 'someone other than the builder'}"
        )
        checks.append(_check(f"review:{requirement['source']}", bool(passed_by), f"{requirement['why']}: {detail}"))

    blocking = sorted(r for r, review in latest.items() if review.get("decision") not in accepting)
    checks.append(_check("no_open_rejections", not blocking, "latest review requests changes from: " + ", ".join(blocking) if blocking else "no reviewer is requesting changes"))

    if actor is not None:
        closers = spec.get("closer", [])
        named = with_stand_ins([c for c in closers if c != "assignee"], gates)
        allowed = (built_by if "assignee" in closers else set()) | set(named)
        checks.append(_check("closer", actor in allowed, f"{actor} may close" if actor in allowed else f"only {', '.join(sorted(allowed)) or 'the assignee'} may close"))

    return {"id": task.get("id"), "unit": unit, "pass": all(c["pass"] for c in checks), "checks": checks}


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"check": name, "pass": bool(passed), "detail": detail}
