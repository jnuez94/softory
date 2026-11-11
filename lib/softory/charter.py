"""The owner's charter: the settings unattended runs follow.

Defaults live in ``factory/governance/charter.json`` (protected). The owner
overrides them once, at a terminal, with ``softory charter approve <file>``;
the overrides go into local.json, which is hashed like the rest of the rules.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from .coordination import Coordination
from .deploy import problems as deploy_problems
from .errors import SoftoryError
from .owner import _now, record_decision
from .project import Project
from .runstate import limits_for


def defaults(project: Project) -> dict[str, Any]:
    return project.load_json("governance/charter.json")


def load(project: Project) -> dict[str, Any]:
    """The charter in force: the defaults with the owner's approved overrides on top."""
    saved = project.local().get("charter", {})
    merged = merge(defaults(project), saved.get("settings", {}))
    merged["approved"] = saved.get("approved")
    merged["merge"]["since"] = saved.get("merge_since")  # when softory began merging; older work stays the owner's
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
    open_maps = {"lanes", "models", "run.harnesses", "run.attended", "budget.roles", "prices"}
    found = []
    for key, value in overrides.items():
        path = f"{prefix}{key}"
        if key not in base:
            if prefix.rstrip(".") not in open_maps:
                found.append(path)
            continue
        found += unknown_keys(base[key], value, path + ".")
    return found


def approve(project: Project, coord: Coordination, path: Path, confirm: Any, layer: bool = False) -> dict[str, Any]:
    """Replace the owner's overrides with the file's, after a typed yes at a terminal, and record a decision.

    With ``layer`` the file's settings go on top of the current overrides instead of replacing them, so
    several small changes don't each need a full file. The prompt shows only what changes.
    """
    try:
        overrides = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SoftoryError(f"Cannot read {path}: {error}", "invalid_arguments") from error
    if not isinstance(overrides, dict):
        raise SoftoryError("The charter file must hold one JSON object", "invalid_arguments")
    overrides.pop("approved", None)
    current = project.local().get("charter", {}).get("settings", {})
    if layer:
        overrides = merge(current, overrides)
    bad = unknown_keys(defaults(project), overrides)
    if bad:
        raise SoftoryError(f"Unknown charter settings: {', '.join(bad)}. `softory charter show` lists them.",
                           "invalid_arguments")
    merged = merge(defaults(project), overrides)
    problems = validate(project, merged)
    if problems:
        raise SoftoryError("; ".join(problems), "invalid_arguments")
    changes = diff(merge(defaults(project), current), merged)
    already = project.local().get("charter", {}).get("approved")
    if not changes and already:
        return {"approved": False, "note": "Nothing changes; the charter in force already says this."}
    confirm("Charter changes:\n" + "\n".join(changes) if changes else "Approve the default charter, unchanged?")
    owner = project.roster()["owner"]["id"]
    decision = record_decision(coord, owner, "charter", "Charter for unattended runs",
                               "The owner approved the charter softory's runner follows.",
                               json.dumps(overrides, sort_keys=True)[:4000])
    settings = project.local()
    before = merge(defaults(project), current)["merge"].get("by")
    since = settings.get("charter", {}).get("merge_since")
    if merged["merge"].get("by") != "softory":
        since = None
    elif before != "softory" or not since:
        since = _now()
    settings["charter"] = {"settings": overrides, "approved": {"at": _now(), "decision": decision}, "merge_since": since}
    project.save_local(settings)
    return {"approved": True, "decision": decision, "changed": changes, "charter": load(project)}


def diff(before: Any, after: Any, prefix: str = "") -> list[str]:
    """One line per setting that changes, as ``path: old -> new``."""
    if isinstance(before, dict) and isinstance(after, dict):
        lines = []
        for key in sorted(set(before) | set(after)):
            if key == "description":
                continue
            lines += diff(before.get(key), after.get(key), f"{prefix}{key}.")
        return lines
    if before == after:
        return []
    return [f"{prefix.rstrip('.')}: {json.dumps(before)} -> {json.dumps(after)}"]


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
    mode = charter["run"].get("mode", "unattended")
    if mode not in ("unattended", "attended"):
        problems.append(f"run.mode is {mode!r}: use unattended or attended")
    elif mode == "attended":
        used = {pick.get("harness") for r, c in charter["models"].items() if r != "description"
                for pick in (c, c.get("escalate")) if pick}
        for harness in sorted(h for h in used if h and h not in (charter["run"].get("attended") or {})):
            problems.append(f"run.mode is attended, but run.attended has no interactive command for {harness}")
    merging = (charter.get("merge") or {}).get("by", "owner")
    if merging not in ("owner", "softory"):
        problems.append(f"merge.by is {merging!r}: use owner or softory")
    elif merging == "softory" and not charter["verify"].get("command"):
        problems.append("merge.by softory needs verify.command: softory merges only what it saw pass")
    problems += deploy_problems(charter)
    for pattern in (charter.get("secrets") or {}).get("allow") or []:
        try:
            re.compile(pattern)
        except re.error as error:
            problems.append(f"secrets.allow has an invalid pattern {pattern!r}: {error}")
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


def effort_for(charter: dict[str, Any], role: str, job: str) -> str:
    """Reasoning effort for a build or review run: the role's own setting, else the charter's for that job."""
    own = (charter["models"].get(role) or {}).get("effort")
    if isinstance(own, dict):
        own = own.get(job)
    return str(own or (charter.get("effort") or {}).get(job) or "")
