"""Design checks: UI build work waits for its design, and softory verify runs Impeccable's detector.

Both follow the design standard's gates. A todo ``ui`` or ``frontend`` task under a story whose
``lane:design`` task isn't done waits, as for the feasibility check: its builder isn't woken and
``queue`` says why. A todo ``ui`` task or bug with no finished story design behind it waits the same
way for Darwin's target on the unit itself: in Tablet, UI bugs and one-off UI tasks went straight to a
builder, Darwin saw them only at review, and the owner ruled twice that every UI change starts with
him. ``softory verify`` on a ``ui`` unit also scans the unit's own UI files with the
Impeccable detector when the project has the ``impeccable`` skill installed. Its error and warning
findings on lines the unit's own commits wrote fail the verify, so they block the close. Advisory
findings, and findings on lines the unit didn't change, are only counted.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .gate import with_stand_ins
from .install import SKILL_ROOTS
from .project import Project
from .units import lane_of, live_evidence, parent_of, resolution_of, tags_of, unit_of

LAUNCHER = "impeccable/scripts/impeccable"
#: What the detector reads (Impeccable's hook list), so a backend diff on a ui task scans nothing.
UI_SUFFIXES = (".tsx", ".jsx", ".html", ".vue", ".svelte", ".astro", ".css", ".scss", ".sass", ".less", ".ts", ".js")
SCAN_SECONDS = 300
MAX_LISTED = 10


def settings(charter: dict[str, Any]) -> dict[str, Any]:
    return {"wait_for_design": True, "detect": True, **(charter.get("design") or {})}


#: What ``held`` maps a unit to when it waits for a target on itself, not for a story's design task.
TARGET = "target"


def held(board: Any, charter: dict[str, Any]) -> dict[str, str]:
    """Todo UI build work that waits for design, mapped to the story's open design task, or to ``TARGET``
    for a ui task or bug that needs Darwin's target on the unit itself."""
    if not settings(charter)["wait_for_design"]:
        return {}
    waiting = {}
    for task in board.tasks:
        if task["status"] != "todo" or not _builds_ui(task):
            continue
        designs = _story_designs(board, task)
        open_design = [d["id"] for d in designs if d["status"] != "done"]
        if open_design:
            waiting[task["id"]] = open_design[0]
        elif not designs and _needs_target(board, task) and not target_of(board, task):
            waiting[task["id"]] = TARGET
    return waiting


def waits_for(what: str) -> str:
    """The queue's words for one of ``held``'s values."""
    return ("the designer's target: evidence of type design on the unit, saying how it should look and read"
            if what == TARGET else f"its story's design, {what}")


def targets_due(board: Any, charter: dict[str, Any], agent: str) -> list[str]:
    """The ui units waiting for a target that ``agent`` may give."""
    return sorted(i for i, what in held(board, charter).items()
                  if what == TARGET and agent in designers(board.gates, i))


def designers(gates: dict[str, Any], task_id: str | None = None) -> list[str]:
    """Who may say how UI should look: the ``ui`` tag's reviewers, their stand-ins, and whoever reviews
    in their place (the owner)."""
    ui = (gates.get("tag_reviews") or {}).get("ui") or {}
    roles = with_stand_ins(list(ui.get("reviewers") or []), gates, task_id)
    return [*roles, *(r for r in ui.get("if_builder") or [] if r not in roles)]


def target_of(board: Any, task: dict[str, Any]) -> str | None:
    """When the unit got its target, or None. A designer's evidence row of a target type is one; so is a
    unit a designer filed, because the report already says what it should look like.

    The name on a row is whatever ``--actor`` said, so a name alone releases nothing: the row, or the
    unit, counts only if the tracker's audit log shows it was written in a session of the role named
    (``board.in_session``). ``softory report`` and ``softory new`` write a designer's that way.
    """
    shown = board.show(task["id"])
    who = set(designers(board.gates, task["id"]))
    kinds = set((board.gates.get("ui_target") or {}).get("evidence_types") or [])
    rows = [str(r.get("created_at") or "") for r in live_evidence(shown.get("evidence") or [])
            if str(r.get("evidence_type", "")).lower() in kinds and r.get("added_by") in who
            and board.in_session("evidence", str(r.get("id")))]
    if rows:
        return max(rows)
    filed = shown.get("created_by") in who and board.in_session("task", task["id"])
    return str(shown.get("created_at") or "") if filed else None


def target_types(gates: dict[str, Any]) -> set[str]:
    return set((gates.get("ui_target") or {}).get("evidence_types") or [])


def claim_refusal(board: Any, charter: dict[str, Any], task_id: str, agent: str) -> str | None:
    """Why ``agent`` may not claim the unit yet, or None. The design is a prerequisite, not a hint for the
    scheduler: a builder already running could claim a waiting unit, which also took it off the
    designer's list. A designer may claim a unit that waits for a target, since their build is the design."""
    what = held(board, charter).get(task_id)
    if not what or (what == TARGET and agent in designers(board.gates, task_id)):
        return None
    return f"{task_id} waits for {waits_for(what)}. Its builder claims it after that."


def _builds_ui(task: dict[str, Any]) -> bool:
    return lane_of(task) != "design" and ("ui" in tags_of(task) or lane_of(task) == "frontend")


def _story_designs(board: Any, task: dict[str, Any]) -> list[dict[str, Any]]:
    """The story's design tasks that stand. A dropped one is done in the tracker and designed nothing, so
    it doesn't count: the story's ui units then need a target each, as in a story filed without design."""
    story = parent_of(task)
    return [d for d in board.children.get(story, []) if lane_of(d) == "design"
            and unit_of(d, board.gates) == "task" and not resolution_of(d)] if story else []


def _needs_target(board: Any, task: dict[str, Any]) -> bool:
    """A ui task or bug somebody other than a designer builds. A designer's own ui work is the design."""
    tags = set((board.gates.get("ui_target") or {}).get("tags") or [])
    if unit_of(task, board.gates) not in ("task", "bug") or not tags & set(tags_of(task)):
        return False
    return not set(task.get("assignees") or []) & set(designers(board.gates, task["id"]))


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


def scan(launcher: Path, tree: Path, files: list[str],
         lines: dict[str, set[int] | None] | None = None) -> dict[str, Any]:
    """Run the detector on ``files`` in ``tree``. Passes when nothing but advisory findings remain.

    ``lines`` names, per file, the lines the unit changed: a finding on any other line was there before
    the unit, so it is counted and doesn't block. Without it, or for a finding with no line, every line counts.
    """
    present = [f for f in files if (tree / f).is_file()]  # a deleted file has nothing to scan
    if not present:
        return {"passed": True, "scanned": 0, "blocking": [], "advisory": 0, "unchanged": 0,
                "detail": "no UI files changed"}
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
    older = [f for f in blocking if _unchanged(f, tree, lines)]
    blocking = [f for f in blocking if f not in older]
    listed = [f"{f.get('file')}:{f.get('line')} {f.get('antipattern') or f.get('id')} ({f.get('severity', 'warning')})"
              for f in blocking[:MAX_LISTED]]
    detail = (f"{len(blocking)} finding(s) to fix: " + "; ".join(listed) if blocking
              else f"{len(present)} UI file(s) clean") + (f", {len(advisory)} advisory" if advisory else "")
    if older:
        detail += f", {len(older)} on lines this unit didn't change"
    return {"passed": not blocking, "scanned": len(present), "blocking": listed, "advisory": len(advisory),
            "unchanged": len(older), "detail": detail}


def _unchanged(finding: dict[str, Any], tree: Path, lines: dict[str, set[int] | None] | None) -> bool:
    """True when the finding sits on a line the unit's commits didn't write."""
    if lines is None or not isinstance(finding.get("line"), int):
        return False
    name = str(finding.get("file") or "")
    if name.startswith(str(tree)):
        name = str(Path(name).relative_to(tree))
    mine = lines.get(name.removeprefix("./"))
    return mine is not None and finding["line"] not in mine


def _broken(count: int, why: str) -> dict[str, Any]:
    return {"passed": False, "scanned": count, "blocking": [], "advisory": 0, "unchanged": 0, "detail": why}


def unscanned(why: str) -> dict[str, Any]:
    """A failed result for a unit softory couldn't scan at all."""
    return _broken(0, why)


def released(board: Any, charter: dict[str, Any]) -> dict[str, str]:
    """When design stopped holding each todo UI unit (its story's design finished, or it got its target): a
    release is news, so the builder wakes on it even if it last looked while the hold was on."""
    if not settings(charter)["wait_for_design"]:
        return {}
    found = {}
    for task in board.tasks:
        if task["status"] != "todo" or not _builds_ui(task):
            continue
        designs = _story_designs(board, task)
        if designs and all(d["status"] == "done" for d in designs):
            found[task["id"]] = max(str(d.get("updated_at") or "") for d in designs)
        elif not designs and _needs_target(board, task):
            at = target_of(board, task)
            if at:
                found[task["id"]] = at
    return found
