"""For schedulers and the owner: should a role run now, and which roles have gone quiet?

Neither starts a session or a model, so a scheduler can call them every few
minutes for free: ``softory pending greg && codex exec ...`` and
``softory silent --notify``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import charter as charters
from . import grants
from .coordination import Coordination
from .project import Project
from .runstate import is_paused
from .gate import latest_reviews
from .work import Board, actor_of, queue


def pending(project: Project, coord: Coordination, agent: str | None, since: str | None = None,
            retry_hours: float = 4.0) -> dict[str, Any]:
    """Whether a role has anything to do.

    Work counts when it changed after the role's last finished session
    started; unread messages and units ready to close always count. So that
    a crashed or cut-short run can't strand work, any waiting work counts
    again once ``retry_hours`` pass without a run (0 turns that off). A role
    that is already running (a session seen in the last 30 minutes) is not
    started again.
    """
    agent = actor_of(agent)
    sessions = coord.run("session", "list", "--agent", agent, "--order-by", "started_at:desc", "--limit", "20")
    now = datetime.now(timezone.utc)
    running = [s["id"] for s in sessions if s.get("status") == "active"
               and now - parse_time(s["last_seen_at"]) < timedelta(minutes=30)]
    last_start = max((s["started_at"] for s in sessions if s.get("status") != "active"), default=None)
    since = last_start if since is None else since
    board = Board(project, coord)
    touched = {t["id"]: max([t["updated_at"], *(r["created_at"] for r in board.reviews.get(t["id"], []))])
               for t in board.tasks}

    def changed(ids: list[str]) -> list[str]:
        return [i for i in ids if (since is None or touched.get(i, "") > since) and i not in capped]

    work = queue(project, coord, agent, board)
    rounds = review_rounds(board)
    caps = charters.load(project)["task_caps"]
    capped = {i for i, n in rounds.items() if n >= caps["review_rounds"]}
    reasons = []
    inbox = coord.run("inbox", "list", "--agent", agent, "--limit", "100")
    unread = inbox.get("messages", []) if isinstance(inbox, dict) else inbox
    if unread:
        reasons.append({"why": "unread messages", "count": len(unread)})
    if work["ready_to_close"]:
        reasons.append({"why": "ready to close", "ids": [t["id"] for t in work["ready_to_close"]]})
    accepting = set(board.gates["accepting_decisions"])
    sent_back = [t["id"] for t in board.tasks if t["status"] == "review" and agent in (t.get("assignees") or [])
                 and any(r.get("decision") not in accepting for r in latest_reviews({"reviews": board.reviews.get(t["id"], [])}).values())]
    waiting = {
        "changes requested": sent_back,
        "reviews waiting": [t["id"] for t in work["reviews_waiting"]],
        "claimed work changed": work["claimed"],
        "assigned work changed": [t["id"] for t in work["assigned"] if t["status"] != "blocked"],
    }
    for why, ids in waiting.items():
        if changed(ids):
            reasons.append({"why": why, "ids": changed(ids)})
    everything = [i for ids in waiting.values() for i in ids if i not in capped]
    stale = last_start is None or now - parse_time(last_start) >= timedelta(hours=retry_hours)
    if not reasons and everything and retry_hours > 0 and stale:
        reasons.append({"why": f"work waiting and no run in {retry_hours:g} hours", "ids": everything[:20]})
    hold = is_paused(project, agent)
    ids = {i for r in reasons for i in r.get("ids", [])}
    escalate = sorted(i for i in ids if rounds.get(i, 0) >= caps["escalate_model_after"])
    result = {"agent": agent, "pending": bool(reasons) and not running and not hold, "since": since,
              "running": running, "reasons": reasons}
    if hold:
        result["paused"] = hold
    if escalate:
        result["escalate"] = escalate
    held = sorted(capped & {i for ids in waiting.values() for i in ids})
    if held:
        result["capped"] = held
    return result


def review_rounds(board: Board) -> dict[str, int]:
    """How many reviews asked for changes on each task: a task past the charter's cap waits for the owner."""
    accepting = set(board.gates["accepting_decisions"])
    return {task_id: n for task_id, rows in board.reviews.items()
            if (n := sum(1 for r in rows if r.get("decision") not in accepting))}


def silent(project: Project, coord: Coordination, hours: float = 12.0, notify: bool = False,
           sender: str = "owner") -> dict[str, Any]:
    """Roles with work waiting and no session seen for ``hours`` (or ever).

    ``notify`` messages the owner once a day per silent role, so a scheduler
    can run this hourly without repeating itself.
    """
    board = Board(project, coord)
    now = datetime.now(timezone.utc)
    roster = project.roster()
    agents = [role["id"] for role in roster["roles"]]
    agents += [g["agent"] for g in project.stand_ins() if grants.is_active(g) and g["agent"] not in agents]
    quiet = []
    for agent in dict.fromkeys(agents):
        work = queue(project, coord, agent, board)
        waiting = {
            "ready_to_close": len(work["ready_to_close"]),
            "reviews_waiting": len(work["reviews_waiting"]),
            "claimed": len(work["claimed"]),
            "assigned": len([t for t in work["assigned"] if t["status"] != "blocked"]),
        }
        if not any(waiting.values()):
            continue
        seen = last_seen(coord, agent)
        if seen is not None and now - parse_time(seen) < timedelta(hours=hours):
            continue
        quiet.append({"agent": agent, "last_seen": seen,
                      "hours_silent": None if seen is None else round((now - parse_time(seen)).total_seconds() / 3600, 1),
                      "waiting": {k: v for k, v in waiting.items() if v}})
    notified = []
    if notify:
        owner = roster["owner"]["id"]
        day = now.strftime("%Y%m%d")
        for row in quiet:
            message_id = f"SOFTORY-SILENT-{row['agent']}-{day}"
            if coord.call("message", "show", message_id).get("ok"):
                continue  # already told the owner today
            since = f"since {row['last_seen']}" if row["last_seen"] else "ever"
            waiting = ", ".join(f"{count} {kind.replace('_', ' ')}" for kind, count in row["waiting"].items())
            coord.run("message", "send", "--id", message_id, "--sender", sender, "--recipient", owner,
                      "--body", f"{row['agent']} has had no session {since}, with work waiting: {waiting}. "
                                f"Check its schedule, or reassign the work.")
            notified.append(row["agent"])
    return {"hours": hours, "silent": quiet, "notified": notified}


def last_seen(coord: Coordination, agent: str) -> str | None:
    """When the agent's most recent session was last seen or ended."""
    sessions = coord.run("session", "list", "--agent", agent, "--order-by", "last_seen_at:desc", "--limit", "5")
    stamps = [s.get(key) for s in sessions for key in ("last_seen_at", "ended_at") if s.get(key)]
    return max(stamps, default=None)


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
