"""For schedulers and the owner: should a role run now, and which roles have gone quiet?

Neither starts a session or a model, so the runner can call them every tick
for free.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from . import charter as charters
from . import decide, design, feasibility, grants, verify
from .coordination import Coordination
from .project import Project
from .runstate import allowed_tasks, is_paused
from .gate import latest_reviews
from .gate import spec_for as gate_spec
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
    running = _live(sessions, now)
    last_start = max((s["started_at"] for s in sessions if s.get("status") != "active"), default=None)
    since = last_start if since is None else since
    board = Board(project, coord)
    touched = {t["id"]: max([t["updated_at"], *(r["created_at"] for r in board.reviews.get(t["id"], []))])
               for t in board.tasks}
    charter = charters.load(project)
    for task_id, passed in feasibility.released(board, charter).items():  # a pass releases held work: that's news
        touched[task_id] = max(touched.get(task_id, ""), passed)
    for task_id, done in design.released(board, charter).items():  # so does a finished design
        touched[task_id] = max(touched.get(task_id, ""), done)
    for task_id, retried in decide.retried_at(project).items():  # so is an extra round past the review cap
        if task_id in touched:
            touched[task_id] = max(touched[task_id], retried)

    def changed(ids: list[str]) -> list[str]:
        return [i for i in ids if (since is None or touched.get(i, "") > since) and i not in capped]

    work = queue(project, coord, agent, board)
    caps = charter["task_caps"]
    rounds = review_rounds(board, int(caps.get("free_evidence_rounds", 1)))
    capped = {i for i, n in rounds.items() if n >= decide.cap_for(project, charter, i)}
    waits = feasibility.held(board, charter)  # todo tasks whose story hasn't passed its feasibility check
    waits |= set(design.held(board, charter))  # and UI build tasks whose story's design isn't done
    reasons = []
    hold = is_paused(project, agent)
    # The owner let this role work on a few tasks while the pause holds. Scope every list before anything
    # decides whether to run, so messages and other work wait for the full resume without hiding the retry.
    scope = allowed_tasks(project, agent) if hold else set()
    in_scope = (lambda ids: [i for i in ids if i in scope]) if scope else (lambda ids: ids)
    inbox = coord.run("inbox", "list", "--agent", agent, "--limit", "100")
    unread = inbox.get("messages", []) if isinstance(inbox, dict) else inbox
    if unread and not scope:
        reasons.append({"why": "unread messages", "count": len(unread)})
    if in_scope([t["id"] for t in work["ready_to_close"]]):
        reasons.append({"why": "ready to close", "ids": in_scope([t["id"] for t in work["ready_to_close"]])})
    accepting = set(board.gates["accepting_decisions"])
    sent_back = [t["id"] for t in board.tasks if t["status"] == "review" and agent in (t.get("assignees") or [])
                 and any(r.get("decision") not in accepting for r in latest_reviews({"reviews": board.reviews.get(t["id"], [])}).values())]
    tests = {t["id"]: verify.tests_state(project, charter, board.show(t["id"]), board.gates)
             for t in board.tasks if t["status"] == "review"} if charter["verify"]["command"] else {}
    # A reviewer waits until softory saw the tests pass; the builder is woken to run or fix them instead.
    untested = [t["id"] for t in board.tasks if t["status"] == "review" and agent in (t.get("assignees") or [])
                and tests.get(t["id"]) in ("not run", "failed", "setup failed") and t["id"] not in sent_back]
    reviews = [t["id"] for t in work["reviews_waiting"] if tests.get(t["id"], "n/a") in ("passed", "n/a")]
    batching = _batch_hold(charter, reviews, touched, now)
    waiting = {why: in_scope(ids) for why, ids in {
        "changes requested": sent_back,
        "tests not passed at the commit (run softory verify, fix if it fails)": untested,
        "reviews waiting": [] if batching else reviews,
        "claimed work changed": work["claimed"],
        "assigned work changed": [t["id"] for t in work["assigned"] if t["status"] != "blocked"
                                  and t["id"] not in waits],
    }.items()}
    unsettled: list[str] = []  # units at the review cap that Quinn may settle and hasn't yet
    if agent == "quinn":
        unsettled = in_scope([i for i in sorted(capped) if board.by_id.get(i, {}).get("status") not in (None, "done")
                              and decide.quinn_may_settle(project, charter, board.show(i))])
        stuck = [i for i in unsettled if since is None or touched.get(i, "") > since]
        if stuck:
            reasons.append({"why": "units at the review cap: settle each with softory settle (retry, split, or drop)",
                            "ids": stuck})
    for why, ids in waiting.items():
        if changed(ids):
            reasons.append({"why": why, "ids": changed(ids)})
    # Capped units wait for a settlement, so a run that missed one retries it like any other waiting work.
    everything = [i for ids in waiting.values() for i in ids if i not in capped] + unsettled
    stale = last_start is None or now - parse_time(last_start) >= timedelta(hours=retry_hours)
    if not reasons and everything and retry_hours > 0 and stale:
        reasons.append({"why": f"work waiting and no run in {retry_hours:g} hours", "ids": everything[:20]})
    if scope:
        hold = None
    ids = {i for r in reasons for i in r.get("ids", [])}
    escalate = sorted(i for i in ids if rounds.get(i, 0) >= caps["escalate_model_after"])
    result = {"agent": agent, "pending": bool(reasons) and not running and not hold, "since": since,
              "running": running, "reasons": reasons}
    if hold:
        result["paused"] = hold
    if scope:
        result["scoped_to"] = sorted(scope)
    if escalate:
        result["escalate"] = escalate
    if batching:
        result["batching"] = batching
    held = sorted(capped & {i for ids in waiting.values() for i in ids})
    if held:
        result["capped"] = held
    return result


def _live(sessions: list[dict[str, Any]], now: datetime) -> list[str]:
    """Sessions active and seen in the last 30 minutes."""
    return [s["id"] for s in sessions if s.get("status") == "active"
            and now - parse_time(s["last_seen_at"]) < timedelta(minutes=30)]


def active_sessions(coord: Coordination, agent: str) -> list[str]:
    """The role's live sessions, however they were started (the runner, an app, a terminal)."""
    sessions = coord.run("session", "list", "--agent", agent, "--status", "active", "--limit", "20")
    return _live(sessions, datetime.now(timezone.utc))


def _batch_hold(charter: dict[str, Any], reviews: list[str], touched: dict[str, str],
                now: datetime) -> dict[str, Any] | None:
    """Why waiting reviews are held for a fuller batch, or None when a reviewer should wake now."""
    rule = charter.get("review_batch") or {}
    least, wait = int(rule.get("min") or 1), float(rule.get("max_wait_minutes") or 0)
    if not reviews or len(reviews) >= least:
        return None
    oldest = min(parse_time(touched[i]) for i in reviews if touched.get(i)) if any(touched.get(i) for i in reviews) else now
    waited = (now - oldest).total_seconds() / 60
    if waited >= wait:
        return None
    return {"ids": reviews, "until": f"{least} reviews or {wait:g} min ({waited:.0f} so far)"}


def review_rounds(board: Board, free_evidence_rounds: int = 1) -> dict[str, int]:
    """How many reviews asked for changes on each unit: one past the charter's cap waits for the owner.

    A review record's verdicts are its output, so records never count. A request whose every item is
    labelled ``evidence:`` (the work is right, the proof is missing) is free, up to
    ``free_evidence_rounds`` per unit, so a missing screenshot doesn't send a task to the owner.
    """
    accepting = set(board.gates["accepting_decisions"])
    counts = {}
    for task_id, rows in board.reviews.items():
        task = board.by_id.get(task_id)
        if task is not None and gate_spec(task, board.gates)[1].get("record"):
            continue
        asked = [r for r in rows if r.get("decision") not in accepting]
        free = min(free_evidence_rounds, sum(1 for r in asked if evidence_only(r)))
        if len(asked) - free:
            counts[task_id] = len(asked) - free
    return counts


def evidence_only(review: dict[str, Any]) -> bool:
    """True when every requested change is labelled ``evidence:``."""
    items = [i.strip(" -*\t") for i in re.split(r"[\n;]+", str(review.get("required_changes") or "")) if i.strip(" -*\t")]
    return bool(items) and all(i.lower().startswith("evidence:") for i in items)


def silent(project: Project, coord: Coordination, hours: float = 12.0) -> dict[str, Any]:
    """Roles with work waiting and no session seen for ``hours`` (or ever). The digest reports them."""
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
    return {"hours": hours, "silent": quiet}


def last_seen(coord: Coordination, agent: str) -> str | None:
    """When the agent's most recent session was last seen or ended."""
    sessions = coord.run("session", "list", "--agent", agent, "--order-by", "last_seen_at:desc", "--limit", "5")
    stamps = [s.get(key) for s in sessions for key in ("last_seen_at", "ended_at") if s.get(key)]
    return max(stamps, default=None)


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
