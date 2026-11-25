"""Stand-in grants and gate waivers: the owner's per-project exceptions.

Both live in local.json, and only the owner adds them, at a terminal
(``softory standin add`` or ``softory approve``). These helpers are pure.

A grant lets an existing agent act for softory roles. It can name tasks, so
it applies to those tasks only, and an end date (inclusive), after which it
lapses on its own.

A waiver lets one named gate check pass on one task, with the owner's reason. It covers the commit the
unit had delivered when it was asked for, and one close: Tablet's owner approved a waiver for one reviewed
commit, and softory would have honoured it for any later commit, or after the task was opened again.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Checks a waiver may cover. The rest are what make a close a close: the
# record exists, has evidence, is in review, is closed by the right person,
# its blockers are done, and the rules haven't been edited.
WAIVABLE_PREFIXES = ("review:",)
WAIVABLE_CHECKS = ("ui_reference", "no_open_rejections", "findings_tracked", "verdicts_recorded", "independent", "verified",
                   "lane_paths", "process_paths", "no_secrets", "rollback_plan", "staged")


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def normalize_stand_ins(raw: Any) -> list[dict[str, Any]]:
    """Grants as a list. Reads softory 0.1/0.2's ``{agent: [roles]}`` too."""
    if isinstance(raw, dict):
        return [_grant(agent, roles) for agent, roles in sorted(raw.items())]
    return [_grant(g["agent"], g.get("roles") or [], g.get("tasks"), g.get("until"), g.get("decision"))
            for g in raw or []]


def _grant(agent: str, roles: list[str], tasks: list[str] | None = None, until: str | None = None,
           decision: str | None = None) -> dict[str, Any]:
    return {"agent": agent, "roles": sorted(set(roles)), "tasks": sorted(set(tasks or [])),
            "until": until or None, "decision": decision}


def is_active(grant: dict[str, Any], on: str | None = None) -> bool:
    return not grant.get("until") or (on or today()) <= grant["until"]


def stand_ins_for(
    roles: list[str], grants: list[dict[str, Any]], task_id: str | None = None,
    on: str | None = None, scoped_only: bool = False,
) -> list[str]:
    """Agents whose active grants cover one of ``roles`` on ``task_id``.

    A grant that names tasks covers only those. ``scoped_only`` leaves out
    role-wide grants: they don't reach a specialist's own work.
    """
    agents: list[str] = []
    for grant in grants:
        if not is_active(grant, on) or not set(grant["roles"]) & set(roles):
            continue
        if grant["tasks"] and task_id not in grant["tasks"]:
            continue
        if scoped_only and not grant["tasks"]:
            continue
        if grant["agent"] not in agents and grant["agent"] not in roles:
            agents.append(grant["agent"])
    return sorted(agents)


def describe(grant: dict[str, Any]) -> str:
    """One line for instructions and listings."""
    text = f"`{grant['agent']}` stands in for {', '.join(f'`{r}`' for r in grant['roles'])}"
    if grant["tasks"]:
        text += f" on {', '.join(grant['tasks'])} only"
    if grant.get("until"):
        text += f", until {grant['until']}"
    return text + "."


def normalize_waivers(raw: Any) -> list[dict[str, Any]]:
    """Waivers as stored. ``commit`` is what the unit had delivered when the waiver was proposed ("" when
    nothing yet). One approved before softory 0.6.13 names none, and so covers nothing."""
    return [{"task": w["task"], "check": w["check"], "reason": w.get("reason", ""), "decision": w.get("decision"),
             "commit": w.get("commit"), "approved_at": w.get("approved_at")} for w in raw or []]


def waivable(check: str) -> bool:
    return check in WAIVABLE_CHECKS or check.startswith(WAIVABLE_PREFIXES)


def waiver_for(task_id: str, check: str, waivers: list[dict[str, Any]], commit: str | None = None,
               closed_at: str | None = None) -> tuple[dict[str, Any] | None, str]:
    """The waiver that lets ``check`` pass on the task as it stands, or None and why the one on file doesn't.

    ``commit`` is what the unit delivers now. ``closed_at`` is when a unit that is open again last closed:
    a waiver approved before that close was used by it.
    """
    if not waivable(check):
        return None, ""
    lapsed = ""
    for waiver in reversed(waivers):  # the newest first: a fresh approval replaces a lapsed one
        if waiver["task"] != task_id or waiver["check"] != check:
            continue
        name = waiver.get("decision") or "no decision id"
        if waiver.get("commit") is None:
            lapsed = lapsed or f"the owner's waiver ({name}) names no commit, so it covers none: propose it again"
        elif waiver["commit"] != (commit or ""):
            lapsed = lapsed or (f"the owner's waiver ({name}) covers {waiver['commit'][:12] or 'the unit before it had a commit'}"
                                f", not {(commit or '')[:12] or 'a unit with no commit'}: another commit needs its own")
        elif closed_at and str(waiver.get("approved_at") or "") <= closed_at:
            lapsed = lapsed or f"the owner's waiver ({name}) was used when the unit closed at {closed_at}"
        else:
            return waiver, ""
    return None, lapsed
