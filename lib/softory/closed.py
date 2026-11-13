"""The commit each unit closed at: what its gate, reviews, and secret scan approved.

Commit evidence can still be added to a done task, so ``softory ship`` and a production deploy never
read the newest evidence of closed work. They use the commit recorded here by ``softory close``.
A unit closed without a commit, or closed any other way, has no entry and doesn't ship.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from typing import Any

from .project import Project
from .units import resolution_of

#: The note every softory close leaves on a task; triage looks for done work without one.
CLOSE_NOTE = "closed through softory gate"


def through_gate(task: dict[str, Any]) -> bool:
    """Whether the task is done because ``softory close`` passed its gate: not dropped, not closed raw."""
    return (task.get("status") == "done" and not resolution_of(task)
            and str(task.get("notes") or "").startswith(CLOSE_NOTE))


def path(project: Project) -> Path:
    return project.state / "closed.json"


def commits(project: Project) -> dict[str, str]:
    """Unit id to the commit it closed at."""
    try:
        return {unit: row["commit"] for unit, row in json.loads(path(project).read_text(encoding="utf-8")).items()}
    except (OSError, json.JSONDecodeError):
        return {}


def record(project: Project, unit: str, commit: str | None, actor: str) -> None:
    """Called by softory close after the unit reached done. A reopened unit's next close replaces its entry."""
    try:
        data = json.loads(path(project).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data.pop(unit, None)
    if commit:
        data[unit] = {"commit": commit, "by": actor, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path(project).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
