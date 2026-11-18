"""What needs the owner, in one place: a daily digest, and pages for the few things that can't wait.

Urgent (paged at once, outside quiet hours): a unit closed without the gate,
and a role that hit today's budget. Everything else waits for the digest:
proposals, open escalations to the owner with their recommendations, defaults applied, units at the
review cap that Quinn can't settle and what Quinn settled, provisioning requests from feasibility checks,
unread messages to the owner, silent roles, and budget warnings. Each page
goes once a day per item. With no paging command, the digest still lands in
.coordination/softory/digest.md and in the owner's inbox.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any

from . import owner as owners
from . import clutter, decide, feasibility, team, usage, watch
from .coordination import Coordination
from .project import Project
from .runstate import all_runs, budget, paused, state_dir
from .gate import spec_for as gate_spec
from .ship import owner_items as ship_items
from .work import Board

QUINN_SETTLE_HOURS = 8  # a capped unit Quinn hasn't settled in this long reaches the owner too


def _hours_since(board: Board, task_id: str) -> float:
    """Hours since the unit last changed (an update or a review)."""
    stamps = [board.by_id[task_id]["updated_at"], *(r["created_at"] for r in board.reviews.get(task_id, []))]
    return (datetime.now(timezone.utc) - watch.parse_time(max(stamps))).total_seconds() / 3600


def items(project: Project, coord: Coordination, charter: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Everything waiting on the owner, split into urgent and digest items. Each has a stable key."""
    owner = project.roster()["owner"]["id"]
    urgent, later = [], []
    for row in team._closed_outside_softory(project, coord):  # noqa: SLF001 - the same check triage runs
        urgent.append({"key": f"bypass-{row['id']}", "text": f"{row['id']} reached done without softory's gate"})
    for role in charter["run"]["roles"]:
        use = budget(project, charter, role)
        if use["over"]:
            urgent.append({"key": f"budget-{role}", "text": f"{role} hit today's budget ({use['runs']} runs, "
                           f"{use['minutes']} min) and is paused until tomorrow"})
        elif use["warn"]:
            later.append({"key": f"budget-warn-{role}", "text": f"{role} has used {int(use['share'] * 100)}% of today's budget"})
    for proposal in owners.proposals(project):
        later.append({"key": f"prop-{proposal['id']}", "text": f"{proposal['id']} ({proposal['kind']}) from "
                      f"{proposal['proposed_by']}: {proposal['why'][:160]}. Run: softory approve {proposal['id']}"})
    names = owner_names(project, charter)
    recommended = decide.recommendations(project)
    for row in coord.all_rows("escalation", "list", "--status", "open"):
        if str(row.get("owner", "")).strip().lower() in names:
            later.append({"key": f"esc-{row['id']}", "text": f"{row['id']} from {row.get('raised_by')}: "
                          f"{_cut(row.get('issue'), 600)} Asks: {_cut(row.get('requested_decision'), 400)}"
                          + _default_note(recommended.get(row["id"]), charter, row["id"])})
    for row in recommended.values():
        if row.get("settled") == "defaulted" and row.get("decision"):
            later.append({"key": f"default-{row['decision']}", "text": f"Defaulted with no answer: {row['recommend']} "
                          f"({row['decision']}). Replace it with softory answer <ESC> \"...\""})
    board = Board(project, coord)
    for task_id, rounds in sorted(watch.review_rounds(board, int(charter['task_caps'].get('free_evidence_rounds', 1))).items()):
        task = board.by_id.get(task_id)
        if not task or task["status"] == "done" or rounds < decide.cap_for(project, charter, task_id):
            continue
        if decide.quinn_may_settle(project, charter, board.show(task_id)):
            if _hours_since(board, task_id) < QUINN_SETTLE_HOURS:
                continue  # Quinn settles it; the owner sees what he chose below
            later.append({"key": f"cap-{task_id}", "text": f"{task_id} has waited {QUINN_SETTLE_HOURS:g}+ hours at "
                          f"the review cap for Quinn to settle it. Settle it yourself if he hasn't: softory settle "
                          f"{task_id} retry|split|drop --actor owner ({task['title'][:80]})"})
            continue
        later.append({"key": f"cap-{task_id}", "text": f"{task_id} had {rounds} rounds of requested changes and "
                      f"stopped: softory settle {task_id} retry|split|drop --actor owner ({task['title'][:80]})"})
    for row in decide.recent_settlements(project):
        later.append({"key": f"settled-{row['task']}-{row['at']}", "text": f"{row['by']} settled {row['task']} "
                      f"({row['action']}): {_cut(row['reason'], 200)}"})
    for ask in feasibility.asks(board):  # one ask per missing thing, however many stories need it
        later.append({"key": f"needs-{ask['key']}", "text": f"Provisioning request: {ask['need']} (needed by "
                      f"{', '.join(ask['stories'])}). The team re-plans around it meanwhile; add it to the "
                      "charter's environment if you provide it"})
    churn = int((charter.get("waste") or {}).get("revision", 0) or 0)
    for task in board.tasks:
        spec = gate_spec(task, board.gates)[1]
        if churn and task["status"] != "done" and not spec.get("record") and int(task.get("revision") or 0) >= churn:
            later.append({"key": f"churn-{task['id']}", "text": f"{task['id']} has changed {task['revision']} times "
                          f"without closing, mostly claims and status moves: check whether a role is repairing its own "
                          f"tooling instead of the task ({task['title'][:80]})"})
    unread = coord.run("inbox", "list", "--agent", owner, "--limit", "20")
    unread = unread.get("messages", []) if isinstance(unread, dict) else unread
    if unread:
        later.append({"key": "inbox", "text": f"{len(unread)} unread message(s) to you: softory inbox --agent {owner}"})
    for row in watch.silent(project, coord)["silent"]:
        later.append({"key": f"silent-{row['agent']}", "text": f"{row['agent']} has had no run since "
                      f"{row['last_seen'] or 'ever'} with work waiting"})
    found = clutter.report(project)
    if not found["clean"]:
        later.append({"key": "clutter", "text": clutter.summary(found)})
    shipping = ship_items(project)
    urgent += shipping[0]
    later += shipping[1]
    for who, why in paused(project).items():
        if who == "allow":
            continue
        later.append({"key": f"paused-{who}", "text": f"{who} is paused: {why}. Resume with softory resume"})
    return {"urgent": urgent, "digest": later}


def _default_note(row: dict[str, Any] | None, charter: dict[str, Any], escalation_id: str) -> str:
    if not row:
        return ""
    when = decide.due_at(row, charter)
    if when is None:
        return f" Recommends: {_cut(row['recommend'], 200)} (can't be undone, so it waits for you)."
    return (f" Recommends: {_cut(row['recommend'], 200)}; applies {when.strftime('%d %b %H:%M')} UTC unless you "
            f"run softory answer {escalation_id} \"...\".")


def owner_names(project: Project, charter: dict[str, Any]) -> set[str]:
    """Every way records name the owner: the roster ID and name, plus the charter's owner_aliases, any case."""
    owner = project.roster()["owner"]
    names = [owner["id"], owner.get("name"), *(charter.get("owner_aliases") or [])]
    return {str(n).strip().lower() for n in names if n}


def _cut(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def render(found: dict[str, list[dict[str, Any]]]) -> str:
    lines = ["# Softory digest", ""]
    for title, rows in (("Urgent", found["urgent"]), ("For you", found["digest"])):
        if rows:
            lines += [f"## {title}", "", *(f"- {row['text']}" for row in rows), ""]
    if len(lines) == 2:
        lines.append("Nothing needs you.")
    return "\n".join(lines) + "\n"


def build(project: Project, coord: Coordination, charter: dict[str, Any]) -> dict[str, Any]:
    found = items(project, coord, charter)
    path = state_dir(project) / "digest.md"
    spent = week(project, coord)
    path.write_text(render(found) + _week_lines(spent), encoding="utf-8")
    return {**found, "week": spent, "file": str(path)}


def week(project: Project, coord: Coordination, days: float = 7) -> dict[str, Any]:
    """What the runner spent over ``days`` and what it bought: units closed, and runs that changed nothing."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    return usage.week(all_runs(project), len(closed_since(coord, since)), days)


def closed_since(coord: Coordination, since: str) -> set[str]:
    """Units moved to done at or after ``since``, from the audit log. A done task's ``updated_at`` also moves
    when someone edits it, which would count old work as delivered."""
    rows = coord.all_rows("audit", "list", "--object-type", "task", "--action", "status")
    return {str(r["object_id"]) for r in rows
            if str(r.get("created_at", "")) >= since and "-> done;" in f"{r.get('detail', '')};"}


def _week_lines(spent: dict[str, Any]) -> str:
    if not spent["runs"]:
        return ""
    idle = "not measured yet" if spent["idle_share"] is None else (
        f"{int(spent['idle_share'] * 100)}% changed nothing (${spent['idle_usd']:g})")
    per = "no units closed" if spent["usd_per_closed"] is None else f"${spent['usd_per_closed']:g} per closed unit"
    return (f"\n## Last {spent['days']:g} days\n\n- {spent['runs']} runs, ${spent['usd']:g}: {per}, "
            f"{spent['closed']} closed\n- Runs: {idle}\n")


def page_due(project: Project, coord: Coordination, charter: dict[str, Any], clock: datetime | None = None,
             force_digest: bool = False) -> list[str]:
    """Page what is due now: new urgent items outside quiet hours, and the digest once a day."""
    clock = clock or datetime.now()
    found = build(project, coord, charter)
    sent = _sent(project)
    day = clock.date().isoformat()
    paging = charter["paging"]
    out = []
    if not _quiet(clock, paging.get("quiet_hours")):
        fresh = [row for row in found["urgent"] if sent.get(row["key"]) != day]
        if fresh:
            _page(project, coord, charter, "Softory: needs you now", "; ".join(r["text"] for r in fresh), found["file"])
            sent.update({row["key"]: day for row in fresh})
            out += [row["key"] for row in fresh]
    due = force_digest or (clock.hour >= int(paging.get("digest_hour", 8)) and sent.get("digest") != day)
    if due and (found["digest"] or found["urgent"]):
        count = len(found["digest"]) + len(found["urgent"])
        _page(project, coord, charter, f"Softory digest: {count} item(s)",
              "; ".join(r["text"] for r in (found["urgent"] + found["digest"])[:5]), found["file"], digest_day=day)
        sent["digest"] = day
        out.append("digest")
    (state_dir(project) / "pages.json").write_text(json.dumps(sent, indent=2) + "\n", encoding="utf-8")
    return out


def _quiet(clock: datetime, hours: list[int] | None) -> bool:
    if not hours or len(hours) != 2:
        return False
    start, end = int(hours[0]), int(hours[1])
    return start <= clock.hour or clock.hour < end if start > end else start <= clock.hour < end


def _sent(project: Project) -> dict[str, str]:
    try:
        return json.loads((state_dir(project) / "pages.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _page(project: Project, coord: Coordination, charter: dict[str, Any], title: str, body: str, file: str,
          digest_day: str | None = None) -> None:
    owner = project.roster()["owner"]["id"]
    if digest_day:
        message_id = f"SOFTORY-DIGEST-{digest_day.replace('-', '')}"
        if not coord.call("message", "show", message_id).get("ok"):
            coord.call("message", "send", "--id", message_id, "--sender", owner, "--recipient", owner,
                       "--body", f"{title}. {body[:1500]} Full list: {file}")
    command = charter["paging"].get("command")
    if command:
        env = {**os.environ, "SOFTORY_TITLE": title, "SOFTORY_MESSAGE": body[:900], "SOFTORY_DIGEST": file}
        subprocess.run(command, shell=True, cwd=project.root, env=env, timeout=60, check=False,  # noqa: S602 - owner's command
                       capture_output=True)
