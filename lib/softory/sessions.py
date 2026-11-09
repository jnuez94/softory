"""Each role's open session, kept in a file so the operating loop doesn't depend on the harness's shell.

``softory start`` prints shell exports, but a harness may run every command in a fresh shell (Claude Code
does), so ``COORDINATION_SESSION`` is gone by the next command. Softory remembers the session it opened
for each role and falls back to it when a command names the role (``--actor`` or ``$SOFTORY_ROLE``) and
no session. ``softory end`` forgets it. An ended session is never used.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .project import Project


def _path(project: Project, role: str) -> Path:
    return project.state / "sessions" / f"{role}.json"


def remember(project: Project, role: str, session: str) -> None:
    path = _path(project, role)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"session": session}) + "\n", encoding="utf-8")


def recall(project: Project, role: str | None, is_open: Callable[[str], bool]) -> str | None:
    """The role's remembered session, if it is still open."""
    if not role:
        return None
    try:
        session = json.loads(_path(project, role).read_text(encoding="utf-8")).get("session")
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
    return session if session and is_open(session) else None


def forget(project: Project, session: str) -> None:
    """Drop the file that remembers ``session``, whichever role it was."""
    folder = project.state / "sessions"
    for path in folder.glob("*.json") if folder.is_dir() else []:
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("session") == session:
                path.unlink()
        except (OSError, json.JSONDecodeError, AttributeError):
            continue


def open_check(coord: Any) -> Callable[[str], bool]:
    """A test for whether the database still holds ``session`` as active."""
    def is_open(session: str) -> bool:
        shown = coord.call("session", "show", session)
        return bool(shown.get("ok")) and (shown.get("data") or {}).get("status") == "active"
    return is_open
