"""Local state for unattended runs: the pause switch and the run log the budget counts.

All of it lives in .agents/softory/run/, hidden from git like the rest of softory.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .project import Project


def state_dir(project: Project) -> Path:
    path = project.bundle / "run"
    path.mkdir(parents=True, exist_ok=True)
    return path


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---- pause ------------------------------------------------------------------------------------

def paused(project: Project) -> dict[str, Any]:
    try:
        return json.loads((state_dir(project) / "paused.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def is_paused(project: Project, role: str) -> str | None:
    """Why ``role`` is paused, or None."""
    state = paused(project)
    return state.get("all") or state.get(role)


def pause(project: Project, role: str | None, reason: str, actor: str) -> dict[str, Any]:
    """Anyone may stop the runner; it fails safe."""
    state = paused(project)
    state[role or "all"] = f"{reason} ({actor}, {now().isoformat(timespec='seconds')})"
    (state_dir(project) / "paused.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return {"paused": state}


def resume(project: Project, role: str | None, confirm: Any) -> dict[str, Any]:
    """Only the owner, at a terminal, starts it again."""
    state = paused(project)
    key = role or "all"
    if key not in state:
        return {"paused": state, "note": f"{key} wasn't paused"}
    confirm(f"Resume unattended runs for {key}? Paused because: {state[key]}")
    state.pop(key)
    (state_dir(project) / "paused.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return {"paused": state}


# ---- budget -----------------------------------------------------------------------------------

def runs_today(project: Project, role: str) -> list[dict[str, Any]]:
    day = now().date().isoformat()
    path = state_dir(project) / "runs.jsonl"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("role") == role and str(row.get("started", "")).startswith(day):
            rows.append(row)
    return rows


def budget(project: Project, charter: dict[str, Any], role: str) -> dict[str, Any]:
    """Today's use against the charter's caps, as fractions of each."""
    rows = runs_today(project, role)
    limits = limits_for(charter, role)
    used = {"runs": len(rows), "minutes": round(sum(r.get("minutes", 0) for r in rows), 1),
            "usd": round(sum(r.get("usd") or 0 for r in rows), 2),
            "tokens": {k: sum(r.get(f"{k}_tokens") or 0 for r in rows) for k in ("input", "cached", "output")}}
    shares = [used["runs"] / limits["runs_per_role_per_day"], used["minutes"] / limits["minutes_per_role_per_day"]]
    if float(limits.get("usd_per_role_per_day") or 0) > 0:
        shares.append(used["usd"] / float(limits["usd_per_role_per_day"]))
    share = max(shares)
    return {**used, "share": round(share, 2), "over": share >= 1, "warn": share >= limits["warn_at"]}


def limits_for(charter: dict[str, Any], role: str) -> dict[str, Any]:
    """The budget caps for one role: the defaults, with that role's overrides on top."""
    base = {k: v for k, v in charter["budget"].items() if k not in ("roles", "description")}
    return {**base, **((charter["budget"].get("roles") or {}).get(role) or {})}
