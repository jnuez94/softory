"""Units of work (epic, story, task, bug, review) on top of plain coordination tasks.

A unit is an ordinary task whose tags carry ``unit:<kind>``, an optional
``parent:<ID>``, and for tasks and bugs one ``lane:<lane>``. A review unit
names the tasks it reviewed with ``for:<ID>`` tags, and a follow-up names its
source with ``from:<ID>``. These helpers are pure so they can be tested
without a database.
"""

from __future__ import annotations

import re
from typing import Any

from .errors import SoftoryError

UNITS = ("epic", "story", "task", "bug", "review")
LANES = ("frontend", "backend", "infra")
REVIEW_TAGS = ("arch", "ui", "security", "auth", "data", "deps")
ALLOWED_PARENTS = {"epic": (), "story": ("epic",), "task": ("story",), "bug": ("story", "epic"), "review": ()}
RESERVED_TAG_KEYS = ("unit", "parent", "lane", "for", "from")


def tags_of(task: dict[str, Any]) -> list[str]:
    """The task's tags as a clean list of tokens."""
    return [token.strip() for token in str(task.get("tags", "")).split(",") if token.strip()]


def tag_value(tags: list[str], key: str) -> str | None:
    """The value of the first ``key:value`` tag, or None."""
    prefix = key + ":"
    for tag in tags:
        if tag.startswith(prefix):
            return tag[len(prefix) :]
    return None


def tag_values(tags: list[str], key: str) -> list[str]:
    """Every value of ``key:value`` tags, in order."""
    prefix = key + ":"
    return [tag[len(prefix) :] for tag in tags if tag.startswith(prefix)]


def targets_of(task: dict[str, Any]) -> list[str]:
    """The tasks a review unit reviewed, from its ``for:`` tags."""
    return tag_values(tags_of(task), "for")


def unit_of(task: dict[str, Any], gates: dict[str, Any]) -> str | None:
    """The task's unit, from its ``unit:`` tag or else its ID prefix."""
    tagged = tag_value(tags_of(task), "unit")
    if tagged in UNITS:
        return tagged
    prefix = str(task.get("id", "")).split("-", 1)[0]
    for unit, spec in gates["units"].items():
        if spec["id_prefix"] == prefix:
            return unit
    return None


def parent_of(task: dict[str, Any]) -> str | None:
    return tag_value(tags_of(task), "parent")


def lane_of(task: dict[str, Any]) -> str | None:
    return tag_value(tags_of(task), "lane")


def next_id(prefix: str, existing_ids: list[str]) -> str:
    """The next free ``PREFIX-n`` after the highest one already used."""
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    numbers = [int(match.group(1)) for value in existing_ids if (match := pattern.match(value))]
    return f"{prefix}-{max(numbers, default=0) + 1}"


def build_tags(
    unit: str, parent: str | None, lane: str | None, extra: list[str],
    targets: list[str] | None = None, source: str | None = None,
) -> str:
    """Compose the tag string for a new unit, validating lanes and review tags."""
    if unit not in UNITS:
        raise SoftoryError(f"Unknown unit {unit!r}; use one of {', '.join(UNITS)}", "invalid_arguments")
    if unit in ("task", "bug") and lane not in LANES:
        raise SoftoryError(
            f"A {unit} needs --lane, one of {', '.join(LANES)}", "invalid_arguments"
        )
    if unit in ("epic", "story", "review") and lane:
        raise SoftoryError(f"A {unit} has no lane; its tasks do", "invalid_arguments")
    if unit == "review" and not targets:
        raise SoftoryError("A review needs --for with the task(s) it reviews", "invalid_arguments")
    if unit != "review" and targets:
        raise SoftoryError("Only a review takes --for", "invalid_arguments")
    tags = [f"unit:{unit}"]
    if parent:
        tags.append(f"parent:{parent}")
    if lane:
        tags.append(f"lane:{lane}")
    tags += [f"for:{target}" for target in dict.fromkeys(targets or [])]
    if source:
        tags.append(f"from:{source}")
    for tag in extra:
        if tag in tags:
            continue
        if ":" in tag and tag.split(":", 1)[0] in RESERVED_TAG_KEYS:
            raise SoftoryError(f"Set {tag.split(':')[0]} with its own option, not --tags", "invalid_arguments")
        if any(character.isspace() for character in tag) or "," in tag:
            raise SoftoryError(f"Invalid tag {tag!r}", "invalid_arguments")
        tags.append(tag)
    return ",".join(tags)


def check_parent(unit: str, parent_unit: str | None, parent_id: str | None) -> None:
    """Enforce the hierarchy: story under epic, task under story, bug under either."""
    if unit == "task" and not parent_id:
        raise SoftoryError("A task needs --parent STORY-n", "invalid_arguments")
    if parent_id is None:
        return
    if parent_unit not in ALLOWED_PARENTS[unit]:
        allowed = " or ".join(ALLOWED_PARENTS[unit]) or "nothing"
        raise SoftoryError(
            f"A {unit} can only sit under: {allowed}. {parent_id} is a {parent_unit or 'non-unit task'}.",
            "invalid_arguments",
        )


def children_by_parent(tasks: list[dict[str, Any]]) -> dict[str | None, list[dict[str, Any]]]:
    """Group tasks under their parent ID (None for top level), sorted by ID number."""
    grouped: dict[str | None, list[dict[str, Any]]] = {}
    for task in tasks:
        grouped.setdefault(parent_of(task), []).append(task)
    for siblings in grouped.values():
        siblings.sort(key=_id_sort_key)
    return grouped


def _id_sort_key(task: dict[str, Any]) -> tuple[str, int, str]:
    prefix, _, number = str(task["id"]).partition("-")
    return (prefix, int(number) if number.isdigit() else 0, str(task["id"]))
