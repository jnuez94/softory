"""Stand-in grants and gate waivers: the owner's per-project exceptions.

Both live in local.json, and only the owner adds them, at a terminal
(``softory standin add`` or ``softory approve``). These helpers are pure.

A grant lets an existing agent act for softory roles. It can name tasks, so
it applies to those tasks only, and an end date (inclusive), after which it
lapses on its own.

A waiver lets one named gate check pass on one task, with the owner's reason.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Checks a waiver may cover. The rest are what make a close a close: the
# record exists, has evidence, is in review, is closed by the right person,
# its blockers are done, and the rules haven't been edited.
WAIVABLE_PREFIXES = ("review:",)
WAIVABLE_CHECKS = ("no_open_rejections", "findings_tracked", "verdicts_recorded", "independent")


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
    return [{"task": w["task"], "check": w["check"], "reason": w.get("reason", ""), "decision": w.get("decision")}
            for w in raw or []]


def waivable(check: str) -> bool:
    return check in WAIVABLE_CHECKS or check.startswith(WAIVABLE_PREFIXES)


def waiver_for(task_id: str, check: str, waivers: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not waivable(check):
        return None
    for waiver in waivers:
        if waiver["task"] == task_id and waiver["check"] == check:
            return waiver
    return None
