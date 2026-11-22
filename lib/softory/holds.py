"""Units held off every queue until the owner answers.

From Tablet, where work waiting on the owner kept waking roles (TASK-59 to TASK-71):
``softory escalate --holds TASK-n,...`` holds the named units while the escalation is open. The answer, or
the default when an undoable escalation times out, releases them, and their builders wake on it.

A held unit leaves the queue, ready-to-close and pending, and ``softory queue`` lists it under ``held`` with why.
Nothing changes on the tracker: the unit keeps its status and claim, so lifting a hold is free.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import decide
from .coordination import Coordination
from .errors import SoftoryError
from .project import Project

#: A hold released longer ago than this is no longer news: its builders woke long ago.
RELEASE_DAYS = 30


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
    return found


def released(project: Project, coord: Coordination) -> dict[str, str]:
    """When each unit's hold ended, for units whose hold has ended: their builders wake on it."""
    found: dict[str, str] = {}
    rows = _escalation_rows(project)
    for escalation_id, state in _escalation_states(project, coord).items():
        if state.get("status") != "open":
            for unit in rows[escalation_id]["holds"]:
                found[unit] = max(found.get(unit, ""), str(state.get("updated_at") or ""))
    return found


def check_units(coord: Coordination, ids: list[str]) -> list[str]:
    """The named units, each checked to exist."""
    for unit in ids:
        if not coord.call("task", "show", unit).get("ok"):
            raise SoftoryError(f"No unit {unit}", "not_found")
    return ids

