"""How much coordination the delivered work cost, and how often each reviewer's requests led to a fix.

``softory usage --team`` reports both over a window of days, read from the
coordination records, so it counts every session whatever started it: the
runner, an app's scheduled check-in, or a person in a chat. Nothing here
writes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .coordination import Coordination
from .gate import spec_for
from .project import Project
from .units import CODE_EVIDENCE, live_evidence, resolution_of
from .work import Board


def _since(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()


def sessions_by_role(coord: Coordination, since: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in coord.all_rows("session", "list", "--where", f"started_at:ge={since}"):
        counts[row["agent_id"]] = counts.get(row["agent_id"], 0) + 1
    return counts


def overhead(coord: Coordination, board: Board, days: float = 7) -> dict[str, Any]:
    """Sessions and messages per task or bug delivered in the window. The 2026-10 Vault Radar figure was 45."""
    since = _since(days)
    sessions = sessions_by_role(coord, since)
    messages = len(coord.all_rows("message", "list", "--where", f"created_at:ge={since}"))
    delivered = [t["id"] for t in board.tasks if t["status"] == "done" and t["updated_at"] >= since
                 and not spec_for(t, board.gates)[1].get("record") and not resolution_of(t)
                 and spec_for(t, board.gates)[0] in ("task", "bug", "legacy")]
    total = sum(sessions.values())
    return {"days": days, "since": since, "delivered": len(delivered), "sessions": total, "messages": messages,
            "sessions_by_role": dict(sorted(sessions.items())),
            "sessions_per_delivered": round(total / len(delivered), 1) if delivered else None,
            "messages_per_delivered": round(messages / len(delivered), 1) if delivered else None}


def reviewers(board: Board, days: float = 14) -> dict[str, Any]:
    """Per reviewer: requests for changes in the window, and how many the builder answered with new code.

    A request that never led to a code change may still have been right (missing evidence, a question),
    but a reviewer whose rate sits far below the others is worth a look before trusting them unattended.
    """
    since = _since(days)
    accepting = set(board.gates["accepting_decisions"])
    stats: dict[str, dict[str, int]] = {}
    for task_id, rows in board.reviews.items():
        summary = board.by_id.get(task_id)
        if summary is None or spec_for(summary, board.gates)[1].get("record"):
            continue
        asked = [r for r in rows if r.get("decision") not in accepting and str(r.get("created_at")) >= since]
        if not asked:
            continue
        code_times = [str(e.get("created_at")) for e in live_evidence(board.show(task_id).get("evidence"))
                      if str(e.get("evidence_type", "")).lower() in CODE_EVIDENCE]
        for review in asked:
            who = review.get("reviewer_id") or review.get("reviewer") or "?"
            row = stats.setdefault(who, {"requested": 0, "followed_by_code": 0})
            row["requested"] += 1
            if any(t > str(review.get("created_at")) for t in code_times):
                row["followed_by_code"] += 1
    for row in stats.values():
        row["rate"] = round(row["followed_by_code"] / row["requested"], 2)
    return {"days": days, "since": since, "reviewers": dict(sorted(stats.items()))}


def team_report(project: Project, coord: Coordination, days: float = 7) -> dict[str, Any]:
    board = Board(project, coord)
    return {"overhead": overhead(coord, board, days), "reviews": reviewers(board, days * 2)}
