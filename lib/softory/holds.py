"""Units held off every queue until something outside the work happens.

Two kinds, both from Tablet, where work waiting on the owner kept waking roles (TASK-59 to TASK-71):

- ``softory escalate --holds TASK-n,...`` holds the named units while the escalation is open. The answer, or
  the default when an undoable escalation times out, releases them, and their builders wake on it.
- ``softory defer <ID> --decision <id>`` hides a unit on the strength of an owner's decision (an answer, or a
  ruling recorded with ``softory ruling``), until ``--until`` passes or someone runs ``softory defer <ID> --lift``.

A held unit leaves the queue, ready-to-close and pending, and ``softory queue`` lists it under ``held`` with why.
Nothing changes on the tracker: the unit keeps its status and claim, so lifting a hold is free.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import decide
from .coordination import Coordination
from .errors import SoftoryError
from .project import Project

#: A hold released longer ago than this is no longer news: its builders woke long ago.
RELEASE_DAYS = 30


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _escalation_rows(project: Project) -> dict[str, dict[str, Any]]:
    return {e: row for e, row in decide.recommendations(project).items() if row.get("holds")}


def _escalation_states(project: Project, coord: Coordination) -> dict[str, dict[str, Any]]:
    """Each holding escalation that is open, however old, or that changed in the last ``RELEASE_DAYS``
    -> its status and when it last changed. Two list calls, whatever the history."""
    rows = _escalation_rows(project)
    if not rows:
        return {}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RELEASE_DAYS)).isoformat(timespec="seconds")
    found = coord.all_rows("escalation", "list", "--status", "open")
    found += coord.all_rows("escalation", "list", "--updated-since", cutoff)
    return {str(e["id"]): e for e in found if str(e.get("id")) in rows}


def held(project: Project, coord: Coordination) -> dict[str, str]:
    """Every held unit -> why, in words a role can act on."""
    found: dict[str, str] = {}
    rows = _escalation_rows(project)
    for escalation_id, state in _escalation_states(project, coord).items():
        if state.get("status") == "open":
            for unit in rows[escalation_id]["holds"]:
                found[unit] = f"waits for the owner's answer to {escalation_id}"
    today = _today().isoformat()
    for unit, row in deferred(project).items():
        if not row.get("lifted") and (not row.get("until") or row["until"] >= today):
            until = f" until {row['until']}" if row.get("until") else ""
            found.setdefault(unit, f"deferred{until} by {row['decision']}")
    return found


def released(project: Project, coord: Coordination) -> dict[str, str]:
    """When each unit's hold ended, for units whose hold has ended: their builders wake on it."""
    found: dict[str, str] = {}
    rows = _escalation_rows(project)
    for escalation_id, state in _escalation_states(project, coord).items():
        if state.get("status") != "open":
            for unit in rows[escalation_id]["holds"]:
                found[unit] = max(found.get(unit, ""), str(state.get("updated_at") or ""))
    for unit, row in deferred(project).items():
        if row.get("lifted"):
            found[unit] = max(found.get(unit, ""), row["lifted"])
        elif row.get("until") and row["until"] < _today().isoformat():
            day_after = date.fromisoformat(row["until"]) + timedelta(days=1)
            found[unit] = max(found.get(unit, ""), f"{day_after.isoformat()}T00:00:00+00:00")
    return found


def check_units(coord: Coordination, ids: list[str]) -> list[str]:
    """The named units, each checked to exist."""
    for unit in ids:
        if not coord.call("task", "show", unit).get("ok"):
            raise SoftoryError(f"No unit {unit}", "not_found")
    return ids


# ---- deferrals ----------------------------------------------------------------------------------

def deferred(project: Project) -> dict[str, dict[str, Any]]:
    return decide._load(project, "deferred.json")  # noqa: SLF001 - the same locked state files


def defer(project: Project, coord: Coordination, unit: str, decision: str, until: str | None,
          actor: str) -> dict[str, Any]:
    """Hide ``unit`` from every queue, citing a decision the owner owns."""
    check_units(coord, [unit])
    shown = coord.call("decision", "show", decision)
    owner = project.roster()["owner"]["id"]
    if not shown.get("ok"):
        raise SoftoryError(f"No decision {decision}. Record the owner's word first with softory ruling", "not_found")
    if shown["data"].get("owner_id") != owner:
        raise SoftoryError(f"{decision} isn't the owner's decision; only the owner defers work", "not_allowed")
    if until:
        try:
            if date.fromisoformat(until) < _today():
                raise SoftoryError("--until is in the past", "invalid_arguments")
        except ValueError as error:
            raise SoftoryError("--until takes a date, YYYY-MM-DD", "invalid_arguments") from error
    row = {"decision": decision, "by": actor, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "until": until or ""}
    with decide._editing(project, "deferred.json") as rows:  # noqa: SLF001
        rows[unit] = row
    return {"unit": unit, **row, "note": "It leaves every queue until then; softory defer --lift brings it back."}


def lift(project: Project, unit: str, actor: str) -> dict[str, Any]:
    with decide._editing(project, "deferred.json") as rows:  # noqa: SLF001
        row = rows.get(unit)
        if not row or row.get("lifted"):
            raise SoftoryError(f"{unit} isn't deferred", "invalid_task_state")
        row.update(lifted=datetime.now(timezone.utc).isoformat(timespec="seconds"), lifted_by=actor)
    return {"unit": unit, "lifted": row["lifted"], "note": "Its builders wake on their next tick."}
