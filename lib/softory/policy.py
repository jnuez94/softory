"""The scaffold's own enforcement, turned on: strict closure and strict dependencies (scaffold 1.4.2).

Softory's gate decides what may close, but a raw ``task status done`` used to skip it. With these
lines in ``.coordination/config.yml`` the scaffold itself refuses a close without an accepted review
from someone other than a builder, with an open ``blocks`` dependency, or a claim on blocked work.
Three things in softory close legitimately without a review of their own, and the policies let them:

- a review record (``unit:review``): its verdicts are its output, so its tag exempts it;
- dropped work, which cites the drop decision with ``--because decision:<ID>``;
- a unit whose softory gate passed but whose newest review isn't the scaffold's single accepted
  review (Greg accepting the story he owns, or a request for changes whose follow-ups are filed).
  ``softory close`` records the gate's verdict as a decision and cites it.

Stacked work uses ``informs`` dependencies, which never block a claim.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .coordination import Coordination
from .errors import SoftoryError

POLICY = {
    "closure_policy": "strict",
    "closure_review_waiver": "decision",
    "closure_exempt_tags": "unit:review",
    "dependency_policy": "strict",
}
_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):[ \t]*(.*)$")


def config_path(root: Path) -> Path:
    return root / ".coordination" / "config.yml"


def apply(root: Path) -> list[str]:
    """Write the policy lines into the scaffold's config, keeping every other line. Returns what changed."""
    path = config_path(root)
    if not path.is_file():
        raise SoftoryError(f"{path} is missing; the scaffold installer writes it", "configuration_error")
    found = _values(path.read_text(encoding="utf-8").splitlines())
    remove(root)
    kept = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([*kept, *(f"{key}: {value}" for key, value in POLICY.items())]) + "\n",
                    encoding="utf-8")
    return [f"{key}: {found.get(key, 'unset')} -> {value}" for key, value in POLICY.items() if found.get(key) != value]


def remove(root: Path) -> None:
    """Take the policy lines back out, so a project that keeps the scaffold after softory runs it as before."""
    path = config_path(root)
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
        kept = [line for line in lines if not ((m := _LINE.match(line.strip())) and m.group(1) in POLICY)]
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def problems(root: Path) -> list[str]:
    """Policy lines that are missing or changed. The gate fails closed on any (config_intact)."""
    path = config_path(root)
    if not path.is_file():
        return []  # not installed yet
    found = _values(path.read_text(encoding="utf-8").splitlines())
    return [f"{key} is {found.get(key, 'unset')}, not {value}" for key, value in POLICY.items()
            if found.get(key) != value]


def _values(lines: list[str]) -> dict[str, str]:
    values = {}
    for line in lines:
        match = _LINE.match(line.strip())
        if match and match.group(1) in POLICY:
            values[match.group(1)] = match.group(2).strip()
    return values


def resolve_dependencies(coord: Coordination, task: dict[str, Any], actor: str, everything: bool = False) -> list[str]:
    """Resolve the task's active ``blocks`` and ``review_required`` dependencies on finished work, so strict
    closure accepts what softory's gate already checked. ``everything`` resolves the rest too: dropped
    work waits on nothing. Returns the tasks it no longer waits on."""
    resolved = []
    for dep in task.get("dependencies") or []:
        kind, other = dep.get("dependency_type"), dep.get("depends_on_task_id")
        if kind not in ("blocks", "review_required") or dep.get("status") != "active":
            continue
        if not everything and coord.task(other).get("status") != "done":
            continue
        coord.run("dependency", "resolve", "--task", task["id"], "--depends-on", other, "--type", kind,
                  "--actor", actor)
        resolved.append(other)
    return resolved
