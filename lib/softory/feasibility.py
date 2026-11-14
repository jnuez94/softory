"""The feasibility check: before a story's tasks start, a fresh run reads the plan against what the team can reach.

Tablet's three open escalations shared a cause: the plan assumed real provider sign-in and an unlocked Mac,
and nobody checked that against the environment before the work started. So once a story has tasks, the
runner starts a Quinn run on a different model (``feasibility.harness`` and ``model``). It reads only the
story, its tasks, the charter's vision and out-of-scope list, and the declared ``environment``, and records
``softory feasible STORY-n --pass`` or ``--needs "<what's missing>"`` (repeatable).

A pass lets the story's todo tasks start. Needs becomes a provisioning request in the owner's digest, and
Greg and Quinn re-plan around what is reachable (fakes, headless checks); any change to the story or its
tasks after that runs the check again.

A verdict records a hash of what it read (the charter's vision, scope, and environment; the titles, acceptance,
and descriptions of the story and its tasks). A pass
holds only while the plan still hashes the same, so a new task or a new requirement after a pass is checked again
before it starts.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from . import charter as charters
from .coordination import Coordination
from .errors import SoftoryError
from .project import Project
from .units import live_evidence, parent_of, unit_of

#: The role whose fresh run gives the verdict.
CHECKER = "quinn"
MARK = "softory-feasibility:"
MAX_NEED = 200


def latest(story: dict[str, Any]) -> dict[str, Any] | None:
    """The story's newest feasibility record: {'verdict': 'pass'|'needs', 'needs': [...], 'plan': hash, 'at': ...}."""
    for row in reversed(live_evidence(story.get("evidence"))):
        uri = str(row.get("uri", ""))
        if uri.startswith(MARK):
            body = uri[len(MARK):]
            head, _, rest = body.partition(":")
            verdict, _, plan = head.partition("@")  # records from before plan hashes carry none
            return {"verdict": verdict, "needs": [n for n in rest.split(" | ") if n] if rest else [],
                    "plan": plan or None, "at": row.get("created_at") or ""}
    return None


def plan_hash(show: Callable[[str], dict[str, Any]], story_id: str, child_ids: list[str],
              charter: dict[str, Any]) -> str:
    """A short fingerprint of what the check reads: the charter's vision, scope, and environment, and the story's
    and every task's title, acceptance, and description.

    Status moves (a claim, a review, a close) don't change it, so work in progress doesn't re-run the check; a new
    task, changed requirements, or a changed environment (the owner provided what was missing) do.
    """
    parts: list[Any] = [_scope(charter)]
    for unit_id in [story_id, *sorted(child_ids)]:
        unit = show(unit_id)
        parts.append([unit_id, unit.get("title") or "", _acceptance(unit), " ".join(str(unit.get("description") or "").split())])
    return hashlib.sha256(json.dumps(parts).encode("utf-8")).hexdigest()[:12]


def _scope(charter: dict[str, Any]) -> list[Any]:
    environment = {k: v for k, v in (charter.get("environment") or {}).items() if k != "description"}
    return [charter.get("vision") or "", charter.get("out_of_scope") or [], environment]


def _current(board: Any, story_id: str, charter: dict[str, Any]) -> str:
    return plan_hash(board.show, story_id, [t["id"] for t in board.children.get(story_id, [])], charter)


def required(charter: dict[str, Any]) -> bool:
    return bool((charter.get("feasibility") or {}).get("required"))


def _open_children(board: Any, story_id: str) -> list[dict[str, Any]]:
    return [t for t in board.children.get(story_id, []) if t["status"] != "done"]


def due(board: Any, charter: dict[str, Any]) -> list[str]:
    """Stories whose plan should be checked now: tasks exist, and no check covers the current plan."""
    if not required(charter):
        return []
    found = []
    for summary in board.tasks:
        if unit_of(summary, board.gates) != "story":
            continue  # a done story still counts when new work was filed under it
        children = _open_children(board, summary["id"])
        if not any(t["status"] == "todo" for t in children):
            continue  # nothing waits to start: no tasks yet, or all already moving
        record = latest(board.show(summary["id"]))
        if record is None or record["plan"] != _current(board, summary["id"], charter):
            found.append(summary["id"])  # never checked, or the plan changed since its verdict: check again
    return found


def due_rows(board: Any, charter: dict[str, Any]) -> list[dict[str, Any]]:
    """Each due check with the plan it would read and the plan the last verdict covered, for Quinn's queue."""
    rows = []
    for story in due(board, charter):
        last = latest(board.show(story)) or {}
        rows.append({"story": story, "plan": _current(board, story, charter), "checked_plan": last.get("plan"),
                     "last_verdict": last.get("verdict"), "run": f"softory run-check {story}"})
    return rows


def held(board: Any, charter: dict[str, Any]) -> set[str]:
    """Todo tasks that wait for their story's feasibility pass."""
    if not required(charter):
        return set()
    waiting = set()
    verdicts: dict[str, bool] = {}
    for task in board.tasks:
        story = parent_of(task)
        if task["status"] != "todo" or not story or story not in board.by_id:
            continue
        if unit_of(board.by_id[story], board.gates) != "story":
            continue
        if story not in verdicts:  # a pass counts only for the plan it checked
            record = latest(board.show(story))
            verdicts[story] = bool(record and record["verdict"] == "pass" and record["plan"] == _current(board, story, charter))
        if not verdicts[story]:
            waiting.add(task["id"])
    return waiting


def _plan_of(coord: Coordination, story_id: str, charter: dict[str, Any]) -> str:
    children = [t["id"] for t in coord.all_tasks("--tag", f"parent:{story_id}")]
    return plan_hash(coord.task, story_id, children, charter)


def released(board: Any, charter: dict[str, Any]) -> dict[str, str]:
    """When each todo task's story passed its check, for tasks that pass releases: their builders wake on it."""
    if not required(charter):
        return {}
    found: dict[str, str] = {}
    passes: dict[str, str | None] = {}
    for task in board.tasks:
        story = parent_of(task)
        if task["status"] != "todo" or not story or story not in board.by_id:
            continue
        if story not in passes:
            record = latest(board.show(story))
            ok = record and record["verdict"] == "pass" and record["plan"] == _current(board, story, charter)
            passes[story] = record["at"] if ok else None
        if passes[story]:
            found[task["id"]] = passes[story]
    return found


def record(project: Project, coord: Coordination, story_id: str, passed: bool, needs: list[str],
           actor: str, plan: str | None = None) -> dict[str, Any]:
    """Record the check's verdict on the story, for the plan it read. Needs tells Greg and Quinn to re-plan.

    ``plan`` is the hash the check's prompt named; without it the verdict covers the plan as it is now.
    """
    story = coord.task(story_id)
    if unit_of(story, project.gates()) != "story":
        raise SoftoryError(f"{story_id} is not a story", "invalid_arguments")
    needs = [" ".join(n.split())[:MAX_NEED] for n in needs if n.strip()]
    if passed == bool(needs):
        raise SoftoryError("Give either --pass or one --needs per missing thing", "invalid_arguments")
    plan = (plan or "").strip() or _plan_of(coord, story_id, charters.load(project))
    uri = MARK + ("pass" if passed else "needs") + f"@{plan}" + ("" if passed else ":" + " | ".join(needs))
    coord.run("evidence", "add", "--task", story_id, "--uri", uri, "--type", "review", "--actor", actor)
    result: dict[str, Any] = {"story": story_id, "verdict": "pass" if passed else "needs", "needs": needs,
                              "plan": plan}
    if not passed:
        owner = project.roster()["owner"]["id"]
        body = (f"{story_id} can't be built as planned with what the environment declares. Missing: "
                f"{'; '.join(needs)}. Re-plan it around what is reachable (a fake provider, a headless check) "
                f"so it keeps moving; the owner sees the provisioning request in the digest. Any change to the "
                f"story or its tasks runs the check again.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        for role in ("greg", "quinn"):
            coord.run("message", "send", "--id", f"SOFTORY-FEASIBILITY-{story_id}-{role}-{stamp}", "--sender", owner,
                      "--recipient", role, "--task", story_id, "--body", body)
        result["told"] = ["greg", "quinn"]
    return result


def requests(board: Any) -> list[dict[str, Any]]:
    """Open stories whose latest check found something missing: the owner's provisioning requests."""
    rows = []
    for summary in board.tasks:
        if unit_of(summary, board.gates) != "story":
            continue
        if summary["status"] == "done" and not any(t["status"] == "todo" for t in _open_children(board, summary["id"])):
            continue
        found = latest(board.show(summary["id"]))
        if found and found["verdict"] == "needs":
            rows.append({"story": summary["id"], "title": summary["title"], "needs": found["needs"]})
    return rows


def prompt(project: Project, coord: Coordination, charter: dict[str, Any], story_id: str) -> str:
    """Everything the check may read, and nothing else: the plan, the scope, and the environment."""
    story = coord.task(story_id)
    plan_id = _plan_of(coord, story_id, charter)  # the verdict names this, so a change while it runs is checked again
    tasks = [t for t in coord.all_tasks("--tag", f"parent:{story_id}") if t["status"] != "done"]
    environment = {k: v for k, v in (charter.get("environment") or {}).items() if k != "description"}
    plan = [f"{story_id}: {story['title']}", f"Acceptance: {_acceptance(story) or '(none)'}",
            f"Description: {' '.join(str(story.get('description') or '').split())}", "Tasks:"]
    for summary in tasks:  # each task's own requirements: that is where accounts and devices hide
        task = coord.task(summary["id"])
        plan.append(f"- {task['id']} [{task['status']}] {task['title']}")
        for label, text in (("Acceptance", _acceptance(task)), ("Description", task.get("description"))):
            text = " ".join(str(text or "").split())
            if text:
                plan.append(f"  {label}: {text}")  # whole: the pass covers every word the hash does
    return (
        "You are Quinn (quinn) running softory's feasibility check, on a different model from the one that "
        "planned this work. Your session is already open; pass --actor quinn to softory commands. Read only what is "
        "below; change no files and no tasks. Decide whether the team can do every step of this plan with "
        "only what the environment declares: networks, accounts, devices, and whether a desktop session is "
        "unlocked. Anything the plan assumes that isn't declared is missing, including sign-ins, paid tiers, "
        "private consoles, and checks that need a person at the machine. Then run exactly one of:\n"
        f"  .agents/softory/bin/softory feasible {story_id} --plan {plan_id} --pass\n"
        f"  .agents/softory/bin/softory feasible {story_id} --plan {plan_id} --needs \"<one missing thing>\" [--needs ...]\n"
        "\n"
        f"Vision: {charter.get('vision') or '(not set)'}\n"
        f"Out of scope: {json.dumps(charter.get('out_of_scope') or [])}\n"
        f"Environment: {json.dumps(environment)}\n\n" + "\n".join(plan)
    )


def _acceptance(task: dict[str, Any]) -> str:
    return " ".join(str(task.get("acceptance_criteria") or task.get("acceptance") or "").split())
