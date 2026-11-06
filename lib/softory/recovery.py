"""Recovery: free the claims of runs that died, so their work isn't stranded until someone notices.

A run can't last longer than its role's ``minutes_per_run``, so a session silent for twice the longest of
those (at least an hour) is gone: the Mac slept, the harness crashed, or the run timed out. Each runner
tick sweeps those sessions with the scaffold's reaper, which ends them and blocks what they claimed, and
then puts that work back to ``todo`` so its owner's next run picks it up. A role paused by its budget
starts again on its own when the next day's budget begins, since the budget counts today's runs only.
"""

from __future__ import annotations

from typing import Any

from .coordination import Coordination
from .project import Project
from .runstate import limits_for

REASON = "softory runner: the session went silent past its run limit (crash, timeout, or the Mac slept)"


def stale_after_minutes(charter: dict[str, Any]) -> int:
    longest = max((float(limits_for(charter, role)["minutes_per_run"]) for role in charter["run"]["roles"]),
                  default=30)
    return int(max(60, 2 * longest))


def sweep(project: Project, coord: Coordination, charter: dict[str, Any]) -> list[str]:
    """End silent sessions and return their claimed tasks to todo. Returns the task IDs it reopened."""
    owner = project.roster()["owner"]["id"]
    swept = coord.call("session", "sweep", "--actor", owner, "--reason", REASON,
                       "--stale-after-seconds", str(stale_after_minutes(charter) * 60))
    if not swept.get("ok"):
        return []
    reopened = []
    for session in swept["data"].get("recovered_sessions") or []:
        for task in session.get("recovered_tasks") or []:
            moved = coord.call("task", "status", task["id"], "todo", "--actor", owner,
                               "--if-revision", str(task["revision"]),
                               "--note", f"Reopened after {session['id']} went silent; claim it fresh.")
            if moved.get("ok"):
                reopened.append(task["id"])
    return reopened
