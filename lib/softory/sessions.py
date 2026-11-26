"""Each role's open session, kept in a file so the operating loop doesn't depend on the harness's shell.

``softory start`` prints shell exports, but a harness may run every command in a fresh shell (Claude Code
does), so ``COORDINATION_SESSION`` is gone by the next command. Softory remembers the session it opened
for each role and falls back to it when a command names the role (``--actor`` or ``$SOFTORY_ROLE``) and
no session. ``softory end`` forgets it. An ended session is never used.

A role can hold two sessions for a while: Quinn's own, and the feasibility check Quinn starts from it
with ``softory run-check``. The newer one is remembered while it runs, and the one before it comes
back when it ends.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from .project import Project


def _path(project: Project, role: str) -> Path:
    return project.state / "sessions" / f"{role}.json"


def _read(path: Path) -> dict[str, Any]:
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return found if isinstance(found, dict) else {}


def remember(project: Project, role: str, session: str) -> None:
    """Remember ``session`` as the role's current one, keeping those it was opened beside."""
    path = _path(project, role)
    path.parent.mkdir(parents=True, exist_ok=True)
    was = _read(path)
    earlier = [s for s in [*(was.get("earlier") or []), was.get("session")] if s and s != session]
    path.write_text(json.dumps({"session": session, **({"earlier": earlier} if earlier else {})}) + "\n",
                    encoding="utf-8")


def recall(project: Project, role: str | None, is_open: Callable[[str], bool]) -> str | None:
    """The role's remembered session, if it is still open."""
    if not role:
        return None
    session = _read(_path(project, role)).get("session")
    return session if session and is_open(session) else None


def own(project: Project, coord: Any, role: str) -> str | None:
    """An open session the tracker holds as ``role``'s: the one this command runs in, or the one softory
    remembers for the role. A record written in it carries the session in the tracker's audit log, and
    the tracker refuses a session that isn't the writer's, so softory can tell who wrote it. A caller
    whose ``SOFTORY_ROLE`` names someone else gets none: naming a role is not being it."""
    if os.environ.get("SOFTORY_ROLE") not in (None, "", role):
        return None
    for session in dict.fromkeys(s for s in (coord.session, _read(_path(project, role)).get("session")) if s):
        shown = coord.call("session", "show", session)
        found = shown.get("data") or {}
        if shown.get("ok") and found.get("status") == "active" and found.get("agent_id") == role:
            return session
    return None


def forget(project: Project, session: str) -> None:
    """Stop remembering ``session``, whichever role it was. The session it was opened beside, if any,
    is the role's current one again: a feasibility check that ends hands Quinn's own session back."""
    folder = project.state / "sessions"
    for path in folder.glob("*.json") if folder.is_dir() else []:
        was = _read(path)
        earlier = [s for s in was.get("earlier") or [] if s != session]
        current = was.get("session")
        if current == session:
            current = earlier.pop() if earlier else None
        elif session not in (was.get("earlier") or []):
            continue
        try:
            if current:
                path.write_text(json.dumps({"session": current, **({"earlier": earlier} if earlier else {})}) + "\n",
                                encoding="utf-8")
            else:
                path.unlink()
        except OSError:
            continue


def open_check(coord: Any) -> Callable[[str], bool]:
    """A test for whether the database still holds ``session`` as active."""
    def is_open(session: str) -> bool:
        shown = coord.call("session", "show", session)
        return bool(shown.get("ok")) and (shown.get("data") or {}).get("status") == "active"
    return is_open
