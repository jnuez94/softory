"""The done-gate: what must be true before a unit of work may close.

``evaluate`` is pure. It takes the task as ``task show`` returns it, the
statuses of the tasks it depends on and of its children, and gates.json, and
returns every check with a pass/fail and a reason.

How it adapts to a project that already had a team:

- ``gates["stand_ins"]`` lists grants (see grants.py). A stand-in may review
  and close wherever its roles may. A grant that names tasks counts on those
  tasks only, and a grant with an end date lapses after it.
- A task with no unit (usually created before softory joined) falls under
  ``gates["legacy"]``. Its reviewer ``"*"`` means anyone but the builder.
- ``gates["waivers"]`` lets one review check pass on one task, by the owner.

Two rules keep the gate from asking the impossible:

- When the specialist a tag review names is the only builder (Toby wrote the
  threat model), the tag's ``if_builder`` roles review instead. A role-wide
  stand-in for the specialist doesn't count there; one scoped to the task does.
  If the specialist only helped build it, the backup doesn't apply.
- A review unit is a record of a review run. Its verdicts are its output,
  not a block on it: it closes once the reviewer's verdict is recorded and
  every change it asks for has a follow-up task. Its tags still need someone
  qualified: a ``security`` record stands on its own when Toby (or a stand-in)
  wrote it, and otherwise needs Toby to accept it. Without that, a builder could
  relabel their own security fix as a review and close it unreviewed.
"""

from __future__ import annotations

from typing import Any

from . import grants
from .units import CODE_EVIDENCE, follow_up_ids, tags_of, targets_of, unit_of

ANYONE = "*"
RECORD_STATUSES = ("review", "blocked", "todo")


def spec_for(task: dict[str, Any], gates: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """The task's unit and its gate spec. A task with no unit uses the legacy spec."""
    unit = unit_of(task, gates)
    if unit:
        return unit, gates["units"][unit]
    if "legacy" in gates:
        return "legacy", gates["legacy"]
    return None, {}


def with_stand_ins(roles: list[str], gates: dict[str, Any], task_id: str | None = None,
                   scoped_only: bool = False) -> list[str]:
    """``roles`` plus every agent standing in for one of them on ``task_id``."""
    grant_list = grants.normalize_stand_ins(gates.get("stand_ins"))
    extra = grants.stand_ins_for(roles, grant_list, task_id, gates.get("today"), scoped_only)
    return [*roles, *(agent for agent in extra if agent not in roles)]


def required_reviews(task: dict[str, Any], gates: dict[str, Any]) -> list[dict[str, Any]]:
    """Every review requirement for the task, from its unit and its tags."""
    unit, spec = spec_for(task, gates)
    if spec.get("record"):
        return record_requirements(task, gates)
    requirements: list[dict[str, Any]] = []
    for entry in spec.get("required_reviews", []):
        requirements.append({**entry, "source": f"unit:{unit}"})
    if spec.get("tag_reviews", True) and not spec.get("record"):
        for tag in tags_of(task):
            if tag in gates["tag_reviews"]:
                entry = gates["tag_reviews"][tag]
                requirements.append({**entry, "source": f"tag:{tag}", "not_self": True})
    built_by = builders(task)
    task_id = task.get("id")
    for requirement in requirements:
        named = list(requirement["reviewers"])
        backup = requirement.get("if_builder")
        specialist_built = bool(backup) and requirement.get("not_self") and ANYONE not in named
        if specialist_built and built_by and built_by <= set(named):
            requirement["why"] += f" ({', '.join(named)} built it, so {' or '.join(backup)} reviews)"
            reviewers = with_stand_ins(list(backup), gates, task_id)
            reviewers += [a for a in with_stand_ins(named, gates, task_id, scoped_only=True)
                          if a not in named and a not in reviewers]
        else:
            reviewers = with_stand_ins(named, gates, task_id)
            co_built = sorted(built_by & set(named)) if specialist_built else []
            if co_built:
                requirement["note"] = (f"{', '.join(co_built)} helped build it, so the backup reviewer doesn't apply; "
                                       f"take {', '.join(co_built)} off the task, or ask the owner for a stand-in on it")
        requirement["reviewers"] = reviewers
    return requirements


def record_requirements(task: dict[str, Any], gates: dict[str, Any]) -> list[dict[str, Any]]:
    """The sign-offs a review record needs: one per tag its own reviewer isn't qualified to give."""
    built_by = builders(task)
    requirements = []
    for tag in tags_of(task):
        if tag not in gates["tag_reviews"]:
            continue
        entry = gates["tag_reviews"][tag]
        reviewers = with_stand_ins(list(entry["reviewers"]), gates, task.get("id"))
        if built_by & set(reviewers):
            continue  # the record's own reviewer gives this review
        who = ", ".join(sorted(built_by)) or "its reviewer"
        requirements.append({
            "reviewers": reviewers, "source": f"tag:{tag}", "not_self": True,
            "why": f"{entry['why']} ({who} can't give it, so a {tag} reviewer signs off this record)",
        })
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


def closers(task: dict[str, Any], gates: dict[str, Any]) -> set[str]:
    """Who may close the task: its spec's closers, their stand-ins, and the builders if ``assignee`` is listed."""
    _, spec = spec_for(task, gates)
    listed = spec.get("closer", [])
    named = with_stand_ins([c for c in listed if c != "assignee"], gates, task.get("id"))
    return (builders(task) if "assignee" in listed else set()) | set(named)


def latest_reviews(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Each reviewer's most recent review, in the CLI's (created_at, id) order."""
    latest: dict[str, dict[str, Any]] = {}
    for review in task.get("reviews") or []:
        latest[review.get("reviewer_id") or review["reviewer"]] = review
    return latest


def related_ids(task: dict[str, Any], gates: dict[str, Any]) -> tuple[list[str], list[str]]:
    """What a record's checks need looked up: its reviewed tasks and its follow-ups."""
    _, spec = spec_for(task, gates)
    if not spec.get("record"):
        return [], []
    follow_ups = [i for review in task.get("reviews") or [] for i in follow_up_ids(review.get("follow_up_tasks"))]
    return targets_of(task), list(dict.fromkeys(follow_ups))


def evaluate(
    task: dict[str, Any],
    gates: dict[str, Any],
    dependency_status: dict[str, str],
    children: list[dict[str, Any]],
    actor: str | None = None,
    related: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run every gate check. ``dependency_status`` maps task ID to status.

    ``related`` is only needed for a review record: ``tasks`` maps each ID from
    ``related_ids`` to its summary (None if it doesn't exist), and ``reviews``
    maps each reviewed task to its reviews, oldest first.
    """
    checks: list[dict[str, Any]] = []
    unit, spec = spec_for(task, gates)
    record = bool(spec.get("record"))
    accepting = set(gates["accepting_decisions"])
    latest = latest_reviews(task)
    built_by = builders(task)

    integrity = gates.get("integrity")
    if integrity is not None:
        changed = integrity.get("changed") or []
        checks.append(_check("config_intact", not changed,
                             "changed since the owner installed softory: " + ", ".join(changed)
                             + ". Rules change only through a softory release or softory approve." if changed
                             else "softory's rules are as installed"))
    unit_detail = {None: "no unit:* tag or known ID prefix", "legacy": "no unit tag, so the legacy rule applies"}
    checks.append(_check("unit", unit is not None, unit_detail.get(unit, f"unit is {unit}")))
    checks.append(_status_check(task, record, actor))
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

    if record:
        checks += _record_checks(task, built_by, latest, accepting, related or {})
    for requirement in required_reviews(task, gates):
        candidates = eligible(requirement, built_by, latest)
        passed_by = [r for r in candidates if latest.get(r, {}).get("decision") in accepting]
        named = ANYONE not in requirement["reviewers"] and " or ".join(candidates)
        detail = (
            f"accepted by {', '.join(passed_by)}"
            if passed_by
            else f"needs an accepted review from {named or 'someone other than the builder'}"
        )
        if not passed_by and requirement.get("note"):
            detail += f" ({requirement['note']})"
        checks.append(_check(f"review:{requirement['source']}", bool(passed_by), f"{requirement['why']}: {detail}"))
    if not record:
        blocking = sorted(r for r, review in latest.items() if review.get("decision") not in accepting)
        checks.append(_check("no_open_rejections", not blocking, "latest review requests changes from: " + ", ".join(blocking) if blocking else "no reviewer is requesting changes"))

    if actor is not None:
        allowed = closers(task, gates)
        checks.append(_check("closer", actor in allowed, f"{actor} may close" if actor in allowed else f"only {', '.join(sorted(allowed)) or 'the assignee'} may close"))

    checks = [_waive(task.get("id", ""), check, gates) for check in checks]
    return {"id": task.get("id"), "unit": unit, "pass": all(c["pass"] for c in checks), "checks": checks}


def _status_check(task: dict[str, Any], record: bool, actor: str | None) -> dict[str, Any]:
    status = task.get("status")
    if not record:
        return _check("status", status == "review", f"status is {status}; it must be review")
    # A record can close from blocked or todo too: nothing is waiting on code.
    held_by_actor = status == "in_progress" and (actor is None or task.get("claimed_by") == actor)
    if status in RECORD_STATUSES or held_by_actor:
        detail = "status is review" if status == "review" else f"status is {status}; softory close moves the record on to done"
        return _check("status", True, detail)
    return _check("status", False, f"status is {status}; a record closes from review, blocked, todo, or your own claim")


def _record_checks(task: dict[str, Any], built_by: set[str], latest: dict[str, dict[str, Any]],
                   accepting: set[str], related: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """A review record: holds reports, reviews others' work, has a verdict, and tracks every finding."""
    tasks = related.get("tasks") or {}
    target_reviews = related.get("reviews") or {}
    targets = targets_of(task)
    checks = []

    code = sorted({str(e.get("evidence_type")) for e in task.get("evidence") or []
                   if str(e.get("evidence_type", "")).lower() in CODE_EVIDENCE})
    checks.append(_check("record_only", not code,
                         f"has {', '.join(code)} evidence; a review record holds reports, so build code in a task or bug"
                         if code else "holds reports, not code"))

    overlap = [t for t in targets if tasks.get(t) and builders(tasks[t]) & built_by]
    if not targets:
        checks.append(_check("independent", False, "names no reviewed task; it needs for:<ID> tags"))
    else:
        checks.append(_check("independent", not overlap,
                             f"{', '.join(sorted(built_by))} also built {', '.join(overlap)}, so this isn't an independent review"
                             if overlap else f"reviews {', '.join(targets)}, built by others"))

    who = lambda review: review.get("reviewer_id") or review.get("reviewer")  # noqa: E731
    own = [r for r in task.get("reviews") or [] if who(r) in built_by]
    missing = [t for t in targets if not any(who(r) in built_by for r in target_reviews.get(t, []))]
    if own:
        checks.append(_check("verdicts_recorded", True, f"verdict on this record: {own[-1]['decision']}"))
    elif targets and not missing:
        checks.append(_check("verdicts_recorded", True, "verdict recorded on " + ", ".join(targets)))
    else:
        checks.append(_check("verdicts_recorded", False,
                             f"no verdict from {', '.join(sorted(built_by)) or 'the reviewer'}: record one on this record, "
                             f"or on each reviewed task ({', '.join(missing) or 'none named'})"))

    untracked = []
    for reviewer, review in sorted(latest.items()):
        if review.get("decision") in accepting:
            continue
        ids = follow_up_ids(review.get("follow_up_tasks"))
        absent = [i for i in ids if tasks.get(i) is None]
        if not ids:
            untracked.append(f"{reviewer} requests changes with no follow-up task")
        elif absent:
            untracked.append(f"{reviewer}'s follow-ups don't exist: {', '.join(absent)}")
    checks.append(_check("findings_tracked", not untracked,
                         "; ".join(untracked) + ". File each change with softory new bug --from, and list it in --follow-up-tasks"
                         if untracked else "every requested change has a follow-up task"))
    return checks


def _waive(task_id: str, check: dict[str, Any], gates: dict[str, Any]) -> dict[str, Any]:
    if check["pass"]:
        return check
    waiver = grants.waiver_for(task_id, check["check"], gates.get("waivers") or [])
    if waiver is None:
        return check
    return _check(check["check"], True,
                  f"waived by the owner ({waiver.get('decision') or 'no decision id'}): {waiver['reason']}. "
                  f"Without the waiver: {check['detail']}")


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"check": name, "pass": bool(passed), "detail": detail}
