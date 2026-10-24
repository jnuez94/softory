"""What needs the owner, in one place: a daily digest, and pages for the few things that can't wait.

Urgent (paged at once, outside quiet hours): a unit closed without the gate,
and a role that hit today's budget. Everything else waits for the digest:
proposals, open escalations to the owner, tasks past their review-round cap,
unread messages to the owner, silent roles, and budget warnings. Each page
goes once a day per item. With no paging command, the digest still lands in
.agents/softory/run/digest.md and in the owner's inbox.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from typing import Any

from . import owner as owners
from . import team, watch
from .coordination import Coordination
from .project import Project
from .runstate import budget, paused, state_dir
from .work import Board


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
    for row in coord.all_rows("escalation", "list", "--status", "open"):
        if row.get("owner") == owner:
            later.append({"key": f"esc-{row['id']}", "text": f"{row['id']} from {row.get('raised_by')}: "
                          f"{str(row.get('issue'))[:160]} Asks: {str(row.get('requested_decision'))[:160]}"})
    board = Board(project, coord)
    cap = charter["task_caps"]["review_rounds"]
    for task_id, rounds in sorted(watch.review_rounds(board).items()):
        task = board.by_id.get(task_id)
        if task and task["status"] != "done" and rounds >= cap:
            later.append({"key": f"cap-{task_id}", "text": f"{task_id} had {rounds} rounds of requested changes and "
                          f"stopped: reassign, split, or drop it ({task['title'][:80]})"})
    unread = coord.run("inbox", "list", "--agent", owner, "--limit", "20")
    unread = unread.get("messages", []) if isinstance(unread, dict) else unread
    if unread:
        later.append({"key": "inbox", "text": f"{len(unread)} unread message(s) to you: softory inbox --agent {owner}"})
    for row in watch.silent(project, coord)["silent"]:
        later.append({"key": f"silent-{row['agent']}", "text": f"{row['agent']} has had no run since "
                      f"{row['last_seen'] or 'ever'} with work waiting"})
    for who, why in paused(project).items():
        later.append({"key": f"paused-{who}", "text": f"{who} is paused: {why}. Resume with softory resume"})
    return {"urgent": urgent, "digest": later}


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
    path.write_text(render(found), encoding="utf-8")
    return {**found, "file": str(path)}


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
