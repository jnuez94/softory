"""Decisions that don't stop the work: escalations that default on timeout, and Quinn settling stuck units.

Every escalation names a recommended option and whether it can be undone. If it can, the runner applies
the recommendation once ``decisions.default_after_hours`` pass with no answer, as a decision the owner
can still reverse with ``softory answer``. If it can't, it waits, and work that doesn't depend on it
carries on.

A unit at the review-round cap goes to Quinn, who splits it, drops it, or allows one more round (once per
unit). The owner sees what Quinn did in the digest. A unit Quinn built, or one already given its extra
round, goes to the owner as before.
"""

from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterator

from .coordination import Coordination
from .errors import SoftoryError
from .owner import record_decision
from .project import Project
from .runstate import state_dir

ACTIONS = ("retry", "split", "drop")
QUINN_EXTRA_ROUNDS = 1


def _load(project: Project, name: str) -> dict[str, Any]:
    try:
        return json.loads((state_dir(project) / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(project: Project, name: str, data: dict[str, Any]) -> None:
    (state_dir(project) / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@contextmanager
def _editing(project: Project, name: str) -> Iterator[dict[str, Any]]:
    """Read, change, and write one state file under an exclusive lock, so concurrent roles don't lose rows."""
    with (state_dir(project) / f"{name}.lock").open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = _load(project, name)
            try:
                yield data
            finally:  # keep what was already done, even if a later row failed
                _save(project, name, data)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- escalations that default -------------------------------------------------------------------

def note(project: Project, escalation_id: str, recommend: str, reversible: bool, raised_by: str,
         holds: list[str] | None = None) -> None:
    """Keep the escalation's recommendation, and the units it holds, beside it; the scaffold's record has
    no field for either."""
    with _editing(project, "escalations.json") as rows:
        rows[escalation_id] = {"recommend": recommend, "reversible": reversible, "raised_by": raised_by,
                               "at": _now().isoformat(timespec="seconds"), **({"holds": holds} if holds else {})}


def recommendations(project: Project) -> dict[str, dict[str, Any]]:
    return _load(project, "escalations.json")


def due_at(row: dict[str, Any], charter: dict[str, Any]) -> datetime | None:
    """When an undoable escalation defaults, or None if it waits for the owner."""
    hours = float((charter.get("decisions") or {}).get("default_after_hours") or 0)
    if not row.get("reversible") or hours <= 0:
        return None
    return datetime.fromisoformat(row["at"]) + timedelta(hours=hours)


def apply_due(project: Project, coord: Coordination, charter: dict[str, Any],
              clock: datetime | None = None) -> list[str]:
    """Apply every undoable escalation's recommendation once its time is up. The runner calls this each tick."""
    clock = clock or _now()
    owner = project.roster()["owner"]["id"]
    applied: list[str] = []
    with _editing(project, "escalations.json") as rows:
        _apply(coord, charter, clock, owner, rows, applied)
    return applied


def _apply(coord: Coordination, charter: dict[str, Any], clock: datetime, owner: str,
           rows: dict[str, Any], applied: list[str]) -> None:
    for escalation_id, row in rows.items():
        when = due_at(row, charter)
        if row.get("settled") or when is None or clock < when:
            continue
        shown = coord.call("escalation", "show", escalation_id)
        if not shown.get("ok") or shown["data"].get("status") != "open":
            row["settled"] = "answered"
            continue
        hours = float(charter["decisions"]["default_after_hours"])
        decision = record_decision(
            coord, owner, "DEFAULT", f"{escalation_id} defaulted: {row['recommend']}",
            f"No answer in {hours:g} hours, so the recommendation applies: {row['recommend']}. "
            f"The owner can reverse it with softory answer {escalation_id}.",
            str(shown["data"].get("issue") or ""), recorded_by=row["raised_by"])
        coord.run("escalation", "resolve", escalation_id, "--actor", row["raised_by"], "--if-status", "open",
                  "--resolution", f"No answer in {hours:g} hours; the recommendation applies: {row['recommend']}",
                  "--because", f"decision:{decision}")
        _tell(coord, owner, row["raised_by"], f"SOFTORY-DEFAULT-{escalation_id}",
              f"{escalation_id}: no answer in {hours:g} hours, so go ahead with your recommendation: "
              f"{row['recommend']}. Keep it easy to undo; the owner may still answer.")
        row.update(settled="defaulted", decision=decision)
        applied.append(escalation_id)


def answer(project: Project, coord: Coordination, escalation_id: str, text: str,
           confirm: Callable[[str], None]) -> dict[str, Any]:
    """The owner answers an escalation, or reverses one that defaulted. At a terminal."""
    shown = coord.call("escalation", "show", escalation_id)
    if not shown.get("ok"):
        raise SoftoryError(f"No escalation {escalation_id}", "not_found")
    row = recommendations(project).get(escalation_id, {})
    owner = project.roster()["owner"]["id"]
    raised_by = row.get("raised_by") or shown["data"].get("raised_by")
    confirm(f"Answer {escalation_id}: {text}")
    reversing = row.get("settled") == "defaulted"
    decision = record_decision(coord, owner, "ANSWER", f"{escalation_id}: {text}"[:200], text,
                               str(shown["data"].get("issue") or ""))
    if shown["data"].get("status") == "open":
        coord.run("escalation", "resolve", escalation_id, "--actor", owner, "--resolution", text,
                  "--because", f"decision:{decision}")
    _tell(coord, owner, raised_by, f"SOFTORY-ANSWER-{escalation_id}-{decision[-8:]}",
          f"The owner answered {escalation_id}" + (" and replaces the default" if reversing else "") + f": {text}")
    with _editing(project, "escalations.json") as rows:
        if escalation_id in rows:
            rows[escalation_id]["settled"] = "answered"
    return {"escalation": escalation_id, "decision": decision, "reversed_default": reversing}


def open_escalation(coord: Coordination, escalation_id: str) -> dict[str, Any]:
    """The escalation, if it still waits for an answer; an error that says why otherwise."""
    shown = coord.call("escalation", "show", escalation_id)
    if not shown.get("ok"):
        raise SoftoryError(f"No escalation {escalation_id}", "not_found")
    if shown["data"].get("status") not in ("open", "in_review"):
        raise SoftoryError(f"{escalation_id} is already {shown['data'].get('status')}; only the owner replaces an "
                           "answer, with softory answer", "conflict")
    return shown["data"]


def close_as_told(project: Project, coord: Coordination, escalation: dict[str, Any], text: str, decision: str,
                  recorded_by: str) -> None:
    """Close an open escalation with the answer the owner gave in chat, which ``recorded_by`` wrote down as
    ruling ``decision``. In Tablet an escalation the owner had answered in a session stayed open for days."""
    owner = project.roster()["owner"]["id"]
    escalation_id = escalation["id"]
    row = recommendations(project).get(escalation_id, {})
    coord.run("escalation", "resolve", escalation_id, "--actor", owner, "--resolution", text,
              "--because", f"decision:{decision}")
    _tell(coord, owner, row.get("raised_by") or escalation.get("raised_by"),
          f"SOFTORY-ANSWER-{escalation_id}-{decision[-8:]}",
          f"The owner answered {escalation_id} (recorded by {recorded_by}): {text}")
    with _editing(project, "escalations.json") as rows:
        if escalation_id in rows:
            rows[escalation_id]["settled"] = "answered"


def note_on_behalf(project: Project, row: dict[str, Any]) -> None:
    """Log what a role recorded as the owner's word that changed more than a record, for the owner's digest."""
    with (state_dir(project) / "on-behalf.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps({"at": _now().isoformat(timespec="seconds"), **row}) + "\n")


def recent_on_behalf(project: Project, hours: float = 24) -> list[dict[str, Any]]:
    return _recent(project, "on-behalf.jsonl", hours)


def _tell(coord: Coordination, sender: str, recipient: str | None, message_id: str, body: str) -> None:
    if recipient and not coord.call("message", "show", message_id).get("ok"):
        coord.call("message", "send", "--id", message_id, "--sender", sender, "--recipient", recipient,
                   "--body", body)


# ---- Quinn settles units at the review cap ------------------------------------------------------

def extra_rounds(project: Project, task_id: str) -> int:
    return int(_load(project, "settled.json").get(task_id, {}).get("extra", 0))


def retried_at(project: Project) -> dict[str, str]:
    """When each unit was last given an extra round: a retry is news for its builder."""
    return {task_id: entry["log"][-1]["at"] for task_id, entry in _load(project, "settled.json").items()
            if entry.get("log")}


def cap_for(project: Project, charter: dict[str, Any], task_id: str) -> int:
    return int(charter["task_caps"]["review_rounds"]) + extra_rounds(project, task_id)


def quinn_may_settle(project: Project, charter: dict[str, Any], task: dict[str, Any]) -> bool:
    from .gate import builders  # noqa: PLC0415 - gate is heavier than this module needs at import

    return (bool((charter.get("decisions") or {}).get("quinn_settles"))
            and "quinn" not in builders(task) and extra_rounds(project, task["id"]) < QUINN_EXTRA_ROUNDS)


def settle(project: Project, coord: Coordination, charter: dict[str, Any], task_id: str, action: str,
           reason: str, actor: str, into: list[str] | None = None) -> dict[str, Any]:
    """Quinn (or the owner) settles a unit stopped at the review cap: one more round, a split, or a drop."""
    from . import lifecycle, watch  # noqa: PLC0415 - both import the work board, which imports this module
    from .work import Board  # noqa: PLC0415

    if action not in ACTIONS:
        raise SoftoryError(f"Settle with one of {', '.join(ACTIONS)}", "invalid_arguments")
    if not reason.strip():
        raise SoftoryError("Say why with --reason", "invalid_arguments")
    owner = project.roster()["owner"]["id"]
    task = coord.task(task_id)
    if actor != owner and not (actor == "quinn" and quinn_may_settle(project, charter, task)):
        raise SoftoryError(f"Only the owner may settle {task_id} now: Quinn built it, already allowed its extra "
                           "round, or the charter turned quinn_settles off", "not_allowed")
    board = Board(project, coord)
    rounds = watch.review_rounds(board, int(charter["task_caps"].get("free_evidence_rounds", 1))).get(task_id, 0)
    if rounds < cap_for(project, charter, task_id):
        raise SoftoryError(f"{task_id} isn't at its review cap ({rounds} rounds)", "invalid_task_state")
    if action == "split" and not into:
        raise SoftoryError("Create the smaller units first, then name them with --into", "invalid_arguments")
    for unit_id in into or []:
        coord.task(unit_id)  # must exist
    result: dict[str, Any] = {"task": task_id, "action": action}
    if action == "retry":
        with _editing(project, "settled.json") as settled:  # check again under the lock: two retries race
            entry = settled.setdefault(task_id, {"extra": 0, "log": []})
            if actor != owner and entry["extra"] >= QUINN_EXTRA_ROUNDS:
                raise SoftoryError(f"{task_id} already had its extra round; only the owner may settle it now",
                                   "not_allowed")
            if rounds < int(charter["task_caps"]["review_rounds"]) + entry["extra"]:
                raise SoftoryError(f"{task_id} isn't at its review cap ({rounds} rounds)", "invalid_task_state")
            entry["extra"] += 1
            entry["log"].append({"by": actor, "at": _now().isoformat(timespec="seconds"), "reason": reason})
        result["decision"] = record_decision(coord, actor, "SETTLE", f"One more review round for {task_id}", reason,
                                             f"{task_id} had {rounds} rounds of requested changes.")
    else:
        why = (f"Split into {', '.join(into or [])}: " if action == "split" else "") + reason
        dropped = lifecycle.drop(project, coord, task_id, why, (into or [None])[0], actor)
        result["decision"] = dropped["decision"]
    _log(project, task_id, action, actor, reason)
    return result


def _log(project: Project, task_id: str, action: str, actor: str, reason: str) -> None:
    with (state_dir(project) / "settlements.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps({"at": _now().isoformat(timespec="seconds"), "task": task_id, "action": action,
                              "by": actor, "reason": reason}) + "\n")


def recent_settlements(project: Project, hours: float = 24) -> list[dict[str, Any]]:
    return _recent(project, "settlements.jsonl", hours)


def _recent(project: Project, name: str, hours: float) -> list[dict[str, Any]]:
    since = _now() - timedelta(hours=hours)
    try:
        lines = (state_dir(project) / name).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
            if datetime.fromisoformat(row["at"]) >= since:
                rows.append(row)
        except (ValueError, KeyError):
            continue
    return rows
