"""Inbox and message helpers, and full listings past the CLI's 500-row page."""

from __future__ import annotations

from typing import Any

from .coordination import Coordination
from .errors import SoftoryError
from .work import actor_of


def inbox(coord: Coordination, agent: str | None, limit: int = 20, mark_read: int | None = None) -> dict[str, Any]:
    """Unread messages, oldest first, and the number to mark them read with.

    ``mark_read`` takes the ``read_through`` number from an earlier listing,
    so messages that arrived since are left unread.
    """
    agent = actor_of(agent)
    if mark_read is not None:
        coord.run("inbox", "mark-read", "--agent", agent, "--cursor", str(mark_read))
        return {"agent": agent, "marked_read_through": mark_read}
    data = coord.run("inbox", "list", "--agent", agent, "--limit", str(limit))
    messages = data.get("messages", [])
    more = len(messages) >= limit
    read_through = messages[-1]["audit_id"] if more else data["head"]
    result: dict[str, Any] = {"agent": agent, "unread": len(messages), "messages": messages, "read_through": read_through}
    if messages:
        result["next"] = f"After acting on these: softory inbox --mark-read {read_through}"
    if more:
        result["more"] = f"More than {limit} unread; mark these read, then list again"
    return result


def message(coord: Coordination, message_id: str) -> dict[str, Any]:
    """One message by its ID (the ``id`` field, not ``audit_id``)."""
    return coord.run("message", "show", message_id)


def all_rows(coord: Coordination, args: list[str]) -> list[dict[str, Any]]:
    """Every row of a coordination list command, following pages past 500."""
    if len(args) < 2 or args[1] != "list":
        raise SoftoryError("Usage: softory all <entity> list [filters], e.g. softory all task list --status todo",
                           "invalid_arguments")
    if any(arg.startswith(("--limit", "--offset")) for arg in args):
        raise SoftoryError("softory all pages for you; leave out --limit and --offset", "invalid_arguments")
    return coord.all_rows(*args)
