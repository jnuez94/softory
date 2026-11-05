"""Local state for unattended runs: the pause switch and the run log the budget counts.

All of it lives in .agents/softory/run/, hidden from git like the rest of softory.
"""

from __future__ import annotations

import json
import os
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


def allowed_tasks(project: Project, role: str) -> set[str]:
    """Tasks a paused role may still work on, from the owner's scoped resumes."""
    return {grant["task"] for grant in paused(project).get("allow") or []
            if role in grant.get("roles", []) or "*" in grant.get("roles", [])}


def pause(project: Project, role: str | None, reason: str, actor: str) -> dict[str, Any]:
    """Anyone may stop the runner; it fails safe."""
    state = paused(project)
    state[role or "all"] = f"{reason} ({actor}, {now().isoformat(timespec='seconds')})"
    # A new stop beats any earlier scoped resume it covers: pausing everyone revokes every grant, pausing one
    # role revokes the grants that name it (or every role). The owner grants again after this pause if needed.
    grants = [g for g in state.get("allow") or [] if role and role not in g.get("roles", []) and "*" not in g.get("roles", [])]
    if grants:
        state["allow"] = grants
    else:
        state.pop("allow", None)
    (state_dir(project) / "paused.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return {"paused": state}


def resume(project: Project, role: str | None, confirm: Any, task: str | None = None,
           roles: list[str] | None = None) -> dict[str, Any]:
    """Only the owner, at a terminal, starts it again.

    With ``task`` the pause stays, and only ``roles`` (default: every role) may work on that one task,
    so the owner can restart one piece of work after a stop without restarting everything.
    """
    state = paused(project)
    if task:
        named = roles or ["*"]
        confirm(f"While the pause holds, let {', '.join(named)} work on {task} only?")
        state.setdefault("allow", []).append({"task": task, "roles": named, "at": now().isoformat(timespec="seconds")})
        (state_dir(project) / "paused.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        return {"paused": state}
    key = role or "all"
    if key not in state:
        return {"paused": state, "note": f"{key} wasn't paused"}
    confirm(f"Resume unattended runs for {key}? Paused because: {state[key]}")
    state.pop(key)
    if not any(k for k in state if k != "allow"):
        state.pop("allow", None)  # nothing paused, so the scoped resumes have done their job
    (state_dir(project) / "paused.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return {"paused": state}


def scope_for(project: Project, role: str) -> set[str] | None:
    """The only tasks ``role`` may touch while a pause holds with a scoped resume, or None when unrestricted.

    A pause with no scoped resume doesn't restrict commands: it only stops the runner from starting the role.
    """
    if not is_paused(project, role):
        return None
    return allowed_tasks(project, role) or None


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


# ---- who dispatched a session ----------------------------------------------------------------

RUNNER_ENV = "SOFTORY_RUNNER"


def note_start(project: Project, role: str, session: str) -> None:
    """Log a session the runner didn't start, so doctor can say another scheduler is still dispatching."""
    if os.environ.get(RUNNER_ENV) or _runner_holds(project, role):
        return
    row = {"at": now().isoformat(timespec="seconds"), "role": role, "session": session}
    with (state_dir(project) / "manual-starts.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(row) + "\n")


def _runner_holds(project: Project, role: str) -> bool:
    """A harness may not pass the runner's environment down, so a live run-role for the role counts too."""
    try:
        os.kill(int((state_dir(project) / f"{role}.pid").read_text(encoding="utf-8").strip()), 0)
        return True
    except (OSError, ValueError):
        return False


def manual_starts(project: Project, hours: float = 24) -> list[dict[str, Any]]:
    """Sessions started outside the runner in the last ``hours``."""
    since = now().timestamp() - hours * 3600
    rows = []
    try:
        lines = (state_dir(project) / "manual-starts.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            row = json.loads(line)
            if datetime.fromisoformat(row["at"]).timestamp() >= since:
                rows.append(row)
        except (ValueError, KeyError, TypeError):
            continue
    return rows
