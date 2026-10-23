"""Feedback on softory itself, from the agents that use it.

Agents append one JSON line per note to a hidden local file, so they can
report friction (an unclear rule, a wrong default, a missing command) without
leaving their task or needing the network. Whoever maintains softory reads
the file and turns the notes into fixes.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from . import __version__
from .errors import SoftoryError
from .project import Project

KINDS = ("friction", "bug", "idea")
MAX_NOTE = 2000


def path(project: Project):
    return project.bundle / "feedback.jsonl"


def add(project: Project, note: str, kind: str, task: str | None, actor: str | None) -> dict[str, Any]:
    note = (note or "").strip()
    if not note:
        raise SoftoryError("Say what happened and what you expected", "invalid_arguments")
    if len(note) > MAX_NOTE:
        raise SoftoryError(f"Keep a note under {MAX_NOTE} characters", "invalid_arguments")
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "role": actor or os.environ.get("SOFTORY_ROLE") or "unknown",
        "session": os.environ.get("COORDINATION_SESSION"),
        "task": task,
        "kind": kind,
        "note": note,
        "softory_version": __version__,
    }
    # One write per line in append mode, so notes from parallel agents don't interleave.
    with path(project).open("a", encoding="utf-8") as log:
        log.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"recorded": True, "file": str(path(project).relative_to(project.root)), "count": len(entries(project))}


def entries(project: Project) -> list[dict[str, Any]]:
    if not path(project).is_file():
        return []
    found = []
    for line in path(project).read_text(encoding="utf-8").splitlines():
        try:
            found.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a torn line never hides the rest
    return found
