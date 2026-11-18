"""Stories and epics show as active while their children run (scaffold 1.4.2's ``task activate``, gap S5).

A claim is a one-hour lease, so a parent can't stay ``in_progress`` for the days its children take.
Each runner tick marks an open story or epic active once one of its children has started, and clears
the marker when none has (a child reopened, or the work was re-planned). ``done`` clears it too. The
marker is not a claim: nothing sweeps it, and it never stops the parent's closer.
"""

from __future__ import annotations

from typing import Any

from .coordination import Coordination
from .project import Project
from .units import tags_of, unit_of

STARTED = ("in_progress", "review", "blocked", "done")


def sync(project: Project, coord: Coordination, tasks: list[dict[str, Any]] | None = None) -> dict[str, list[str]]:
    """Mark or clear each open parent's active marker from its children. Returns what changed."""
    gates = project.gates()
    tasks = coord.all_tasks() if tasks is None else tasks
    children: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        for tag in tags_of(task):
            if tag.startswith("parent:"):
                children.setdefault(tag.split(":", 1)[1], []).append(task)
    owner = project.roster()["owner"]["id"]
    changed: dict[str, list[str]] = {"activated": [], "cleared": []}
    active: set[str] = set()
    # Stories first, so an epic counts a story that just became active.
    for task in sorted(tasks, key=lambda t: unit_of(t, gates) != "story"):
        if task["status"] == "done" or unit_of(task, gates) not in ("epic", "story"):
            continue
        started = any(c["status"] in STARTED or c["id"] in active for c in children.get(task["id"], []))
        if started:
            active.add(task["id"])
        if started == bool(task.get("active")):
            continue
        verb = "activate" if started else "deactivate"
        if coord.call("task", verb, task["id"], "--actor", owner).get("ok"):
            changed["activated" if started else "cleared"].append(task["id"])
    return changed
