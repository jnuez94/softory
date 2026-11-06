"""Design checks: UI build work waits for its design, and softory verify runs Impeccable's detector.

Both follow the design standard's gates. A todo ``ui`` or ``frontend`` task under a story whose
``lane:design`` task isn't done waits, as for the feasibility check: its builder isn't woken and
``queue`` says why. ``softory verify`` on a ``ui`` unit also scans the unit's own UI files with the
Impeccable detector when the project has the ``impeccable`` skill installed. Its error and warning
findings fail the verify, so they block the close; advisory findings are only counted.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .install import SKILL_ROOTS
from .project import Project
from .units import lane_of, parent_of, tags_of, unit_of

LAUNCHER = "impeccable/scripts/impeccable"
#: What the detector reads (Impeccable's hook list), so a backend diff on a ui task scans nothing.
UI_SUFFIXES = (".tsx", ".jsx", ".html", ".vue", ".svelte", ".astro", ".css", ".scss", ".sass", ".less", ".ts", ".js")
SCAN_SECONDS = 300
MAX_LISTED = 10


def settings(charter: dict[str, Any]) -> dict[str, Any]:
    return {"wait_for_design": True, "detect": True, **(charter.get("design") or {})}


def held(board: Any, charter: dict[str, Any]) -> dict[str, str]:
    """Todo UI build tasks whose story's design task isn't done yet, mapped to that design task."""
    if not settings(charter)["wait_for_design"]:
        return {}
    waiting = {}
    for task in board.tasks:
        story = parent_of(task)
        if task["status"] != "todo" or not story or lane_of(task) == "design":
            continue
        if "ui" not in tags_of(task) and lane_of(task) != "frontend":
            continue
        open_design = [d["id"] for d in board.children.get(story, [])
                       if lane_of(d) == "design" and d["status"] != "done" and unit_of(d, board.gates) == "task"]
        if open_design:
            waiting[task["id"]] = open_design[0]
    return waiting


def detector(project: Project) -> Path | None:
    """The installed Impeccable launcher, or None when the skill isn't installed."""
    for root in SKILL_ROOTS:
        launcher = project.root / root / LAUNCHER
        if launcher.is_file():
            return launcher
    return None


def applies(project: Project, charter: dict[str, Any], task: dict[str, Any]) -> bool:
    return settings(charter)["detect"] and "ui" in tags_of(task) and detector(project) is not None


def ui_files(files: list[str] | None) -> list[str]:
    return [f for f in files or [] if f.endswith(UI_SUFFIXES)]


def scan(launcher: Path, tree: Path, files: list[str]) -> dict[str, Any]:
    """Run the detector on ``files`` in ``tree``. Passes when nothing but advisory findings remain."""
    present = [f for f in files if (tree / f).is_file()]  # a deleted file has nothing to scan
    if not present:
        return {"passed": True, "scanned": 0, "blocking": [], "advisory": 0, "detail": "no UI files changed"}
    try:
        done = subprocess.run([str(launcher), "detect", "--json", *present], cwd=tree, capture_output=True,
                              text=True, timeout=SCAN_SECONDS, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return _broken(len(present), f"the detector didn't run: {error}")
    if done.returncode not in (0, 2):  # 2 means findings; anything else means a file couldn't be scanned
        return _broken(len(present), f"the detector exited {done.returncode}: {done.stderr.strip()[:300]}")
    try:
        findings = json.loads(done.stdout or "[]")
    except json.JSONDecodeError:
        return _broken(len(present), "the detector's output wasn't JSON")
    if isinstance(findings, dict):
        findings = findings.get("findings") or []
    advisory = [f for f in findings if f.get("advisory") is True or f.get("severity") == "advisory"]
    blocking = [f for f in findings if f not in advisory]
    listed = [f"{f.get('file')}:{f.get('line')} {f.get('antipattern') or f.get('id')} ({f.get('severity', 'warning')})"
              for f in blocking[:MAX_LISTED]]
    detail = (f"{len(blocking)} finding(s) to fix: " + "; ".join(listed) if blocking
              else f"{len(present)} UI file(s) clean") + (f", {len(advisory)} advisory" if advisory else "")
    return {"passed": not blocking, "scanned": len(present), "blocking": listed, "advisory": len(advisory),
            "detail": detail}


def _broken(count: int, why: str) -> dict[str, Any]:
    return {"passed": False, "scanned": count, "blocking": [], "advisory": 0, "detail": why}
