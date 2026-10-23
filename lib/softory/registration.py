"""Register the owner and the six roles as agents in the coordination database."""

from __future__ import annotations

from typing import Any

from .coordination import Coordination


def _lines(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values)


def register_roster(coord: Coordination, roster: dict[str, Any], options: dict[str, Any]) -> list[str]:
    """Add every roster entry that isn't registered yet. Returns the IDs added.

    Existing agents are left alone: the 1.4 CLI can update an agent's name and
    role but not its profile text, so a re-install never rewrites history.
    """
    owner = dict(roster["owner"])
    owner["name"] = options.get("owner_name") or owner["name"]
    added: list[str] = []
    for entry in [owner, *roster["roles"]]:
        if coord.agent_exists(entry["id"]):
            continue
        args = [
            "agent", "add",
            "--id", entry["id"],
            "--name", entry["name"],
            "--role", entry["title"],
            "--actor-type", entry.get("actor_type", "ai"),
            "--responsibilities", _lines(entry.get("responsibilities", [])),
            "--decision-authority", _lines(entry.get("decision_authority", [])),
            "--review-authority", _lines(entry.get("review_authority", [])),
            "--escalation-rules", _lines(entry.get("escalation_rules", [])),
            "--unavailable-for", _lines(entry.get("unavailable_for", [])),
        ]
        if entry.get("goal"):
            args += ["--goal", entry["goal"]]
        if entry.get("operating_style"):
            args += ["--operating-style", _lines(entry["operating_style"])]
        if entry["id"] != owner["id"]:
            args += ["--actor", owner["id"]]
        coord.run(*args)
        added.append(entry["id"])
    return added
