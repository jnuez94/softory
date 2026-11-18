"""A daily copy of the coordination database, made by the scaffold's own ``backup`` command.

Once softory merges and ships on its own, the database is the record of what shipped and why, so the
runner copies it once a day into ``.coordination/backups`` and keeps the charter's ``backups.keep_days``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .coordination import Coordination
from .errors import SoftoryError
from .project import Project

PREFIX = "softory-daily-"


def daily(project: Project, coord: Coordination, charter: dict[str, Any], today: datetime | None = None) -> str | None:
    """Make today's backup if there isn't one, and remove those past keep_days. Returns the new file, if any."""
    keep = int((charter.get("backups") or {}).get("keep_days", 7) or 0)
    if keep <= 0:
        return None
    today = today or datetime.now(timezone.utc)
    folder = project.root / ".coordination" / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{PREFIX}{today.strftime('%Y-%m-%d')}.sqlite3"
    made = None
    if not target.exists():
        try:
            coord.run("backup", "--output", str(target), "--actor", project.roster()["owner"]["id"])
            made = str(target)
        except SoftoryError:
            return None  # the next tick tries again
    oldest = (today - timedelta(days=keep)).strftime("%Y-%m-%d")
    for old in folder.glob(f"{PREFIX}*.sqlite3"):
        if old.name[len(PREFIX):len(PREFIX) + 10] <= oldest:
            old.unlink(missing_ok=True)
    return made
