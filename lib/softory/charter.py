"""The owner's charter: the settings unattended runs follow.

Defaults live in ``factory/governance/charter.json`` (protected). The owner
overrides them once, at a terminal, with ``softory charter approve <file>``;
the overrides go into local.json, which is hashed like the rest of the rules.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .coordination import Coordination
from .errors import SoftoryError
from .owner import _now, record_decision
from .project import Project
from .runstate import limits_for


def defaults(project: Project) -> dict[str, Any]:
    return project.load_json("governance/charter.json")


def load(project: Project) -> dict[str, Any]:
    """The charter in force: the defaults with the owner's approved overrides on top."""
    merged = merge(defaults(project), project.local().get("charter", {}).get("settings", {}))
    merged["approved"] = project.local().get("charter", {}).get("approved")
    return merged


def merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def unknown_keys(base: Any, overrides: Any, prefix: str = "") -> list[str]:
    """Override keys the defaults don't have. Lane names and model roles may be added."""
    if not isinstance(overrides, dict) or not isinstance(base, dict):
        return []
    open_maps = {"lanes", "models", "run.harnesses", "budget.roles"}
    found = []
    for key, value in overrides.items():
        path = f"{prefix}{key}"
        if key not in base:
            if prefix.rstrip(".") not in open_maps:
                found.append(path)
            continue
        found += unknown_keys(base[key], value, path + ".")
    return found


def approve(project: Project, coord: Coordination, path: Path, confirm: Any) -> dict[str, Any]:
    """Replace the owner's overrides with the file's, after a typed yes at a terminal, and record a decision."""
    try:
        overrides = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SoftoryError(f"Cannot read {path}: {error}", "invalid_arguments") from error
    if not isinstance(overrides, dict):
        raise SoftoryError("The charter file must hold one JSON object", "invalid_arguments")
    overrides.pop("approved", None)
    bad = unknown_keys(defaults(project), overrides)
    if bad:
        raise SoftoryError(f"Unknown charter settings: {', '.join(bad)}. `softory charter show` lists them.",
                           "invalid_arguments")
    merged = merge(defaults(project), overrides)
    problems = validate(project, merged)
    if problems:
        raise SoftoryError("; ".join(problems), "invalid_arguments")
    confirm("Charter for unattended runs:\n" + json.dumps(overrides, indent=2, sort_keys=True))
    owner = project.roster()["owner"]["id"]
    decision = record_decision(coord, owner, "charter", "Charter for unattended runs",
                               "The owner approved the charter softory's runner follows.",
                               json.dumps(overrides, sort_keys=True)[:4000])
    settings = project.local()
    settings["charter"] = {"settings": overrides, "approved": {"at": _now(), "decision": decision}}
    project.save_local(settings)
    return {"approved": True, "decision": decision, "charter": load(project)}


def validate(project: Project, charter: dict[str, Any]) -> list[str]:
    problems = []
    roles = set(project.role_ids())
    for role in charter["run"]["roles"]:
        if role not in roles:
            problems.append(f"run.roles names an unknown role {role!r}")
        elif role not in charter["models"]:
            problems.append(f"models has no entry for {role}")
    for role, choice in charter["models"].items():
        if role == "description":
            continue
        for pick in (choice, choice.get("escalate")):
            if pick and pick.get("harness") not in charter["run"]["harnesses"]:
                problems.append(f"models.{role} uses harness {pick.get('harness')!r}, which run.harnesses doesn't define")
    for role in ["", *(charter["budget"].get("roles") or {})]:
        limits = limits_for(charter, role)
        if min(limits["runs_per_role_per_day"], limits["minutes_per_role_per_day"], limits["minutes_per_run"]) <= 0:
            problems.append(f"budget values must be positive{' for ' + role if role else ''}")
    return problems


def model_for(charter: dict[str, Any], role: str, escalated: bool) -> dict[str, str]:
    choice = charter["models"].get(role) or {}
    pick = (choice.get("escalate") if escalated else None) or choice
    if not pick.get("harness"):
        raise SoftoryError(f"The charter names no harness for {role}", "configuration_error")
    return {"harness": pick["harness"], "model": pick.get("model", "")}
