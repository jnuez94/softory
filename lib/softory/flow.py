"""How fast, how heavy, and how costly the team's process is: what Sage's check-in measures.

``softory flow`` reads what softory already keeps (the audit log, the runs log, the state folder, the
checkout) and reports, over a window: time to delivery, review rounds, runs, minutes, and tokens per
delivered unit, the share of runs that changed nothing, and the disk the process holds. ``--record`` keeps
a snapshot, and the next report compares with it, so Sage sees whether a simplification paid off.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from . import clutter
from .coordination import Coordination
from .project import Project
from .runstate import all_runs, manual_starts, state_dir
from .gate import spec_for
from .units import resolution_of, tags_of
from .work import Board

#: The numbers a snapshot keeps and a report compares. Lower is better for every one of them.
COMPARED = ("lead_hours", "rounds", "runs_per_unit", "minutes_per_unit", "tokens_per_unit", "usd_per_unit",
            "idle_share", "process_mib", "untracked", "archives")


def report(project: Project, coord: Coordination, days: float = 7, record: bool = False) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat(timespec="seconds")
    board = Board(project, coord)
    done_at = {i: at for i, at in _done_at(coord, since).items() if _delivered(board, i)}
    lead = [_hours(board.by_id[i].get("created_at"), at) for i, at in done_at.items() if i in board.by_id]
    lead = [h for h in lead if h is not None]
    from .watch import review_rounds  # noqa: PLC0415 - watch imports this module

    rounds = review_rounds(board, 1)
    runs = [r for r in all_runs(project) if str(r.get("started", "")) >= since]
    measured = [r for r in runs if r.get("changes") is not None]
    closed = len(done_at)
    found = clutter.report(project)
    # Sessions the owner or an app opened leave no run rows: no minutes, tokens, or cost. While any worked in
    # the window, the per-unit run numbers would cover only part of the work, so they are left out, not guessed.
    # Tablet's showed a falling cost per unit for two days after its runner had stopped.
    outside = _outside_sessions(project, coord, since)
    per = (lambda total: round(total / closed, 1) if closed and not outside else None)
    numbers = {
        "closed": closed,
        "lead_hours": round(median(lead), 1) if lead else None,
        "rounds": round(median([rounds.get(i, 0) for i in done_at]), 1) if done_at else None,
        "runs": len(runs),
        "runs_per_unit": per(len(runs)),
        "minutes_per_unit": per(sum(float(r.get("minutes") or 0) for r in runs)),
        "tokens_per_unit": per(sum(_tokens(r) for r in runs)),
        "usd_per_unit": per(sum(float(r.get("usd") or 0) for r in runs)),
        "idle_share": round(sum(1 for r in measured if not r["changes"]) / len(measured), 2)
        if measured and not outside else None,
        "process_mib": round(_mib(project) + clutter.archive_bytes(project) / 1048576, 1),  # each byte once
        "untracked": found["counts"]["untracked"],
        "archives": found["counts"]["archives"],
        "clutter_key": found["key"],
    }
    by_role: dict[str, dict[str, Any]] = {}
    for run in runs:
        row = by_role.setdefault(run.get("role", "?"), {"runs": 0, "minutes": 0.0, "tokens": 0, "idle": 0})
        row["runs"] += 1
        row["minutes"] = round(row["minutes"] + float(run.get("minutes") or 0), 1)
        row["tokens"] += _tokens(run)
        row["idle"] += 1 if run.get("changes") == 0 else 0
    process_units = sorted(t["id"] for t in board.tasks if t["status"] != "done"
                           and {"process", "simplify"} & set(tags_of(t)))
    path = state_dir(project) / "flow.jsonl"
    previous = _last(path)
    result = {"days": days, "since": since, **numbers, "by_role": dict(sorted(by_role.items())),
              "storage_mib": _storage(project), "open_process_units": process_units}
    if outside:
        result["unmeasured"] = {
            "sessions": len(outside), "roles": sorted({s["agent_id"] for s in outside}),
            "note": "These sessions ran outside the runner, which logs no minutes, tokens, or cost for them. "
                    "Runs, minutes, tokens, dollars per unit and idle share are left out; time to delivery, "
                    "review rounds, and disk still hold."}
    if previous:
        result["previous"] = {"at": previous["at"], **{k: previous.get(k) for k in COMPARED}}
        result["worse"] = [k for k in COMPARED if _worse(k, numbers.get(k), previous.get(k))]
    if record:
        with path.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"at": now.isoformat(timespec="seconds"), "days": days, **numbers}) + "\n")
    return result


def _outside_sessions(project: Project, coord: Coordination, since: str) -> list[dict[str, Any]]:
    """Role sessions started outside the runner (``softory start``) and seen inside the window."""
    started = {row.get("session") for row in manual_starts(project, hours=24 * 3650)}
    if not started:
        return []
    return [s for s in coord.all_rows("session", "list") if s.get("id") in started
            and str(s.get("last_seen_at") or s.get("started_at") or "") >= since]


def _done_at(coord: Coordination, since: str) -> dict[str, str]:
    """When each unit last moved to done inside the window, from the audit log."""
    found: dict[str, str] = {}
    for row in coord.all_rows("audit", "list", "--object-type", "task", "--action", "status"):
        at = str(row.get("created_at", ""))
        if at >= since and "-> done;" in f"{row.get('detail', '')};":
            found[str(row["object_id"])] = max(found.get(str(row["object_id"]), ""), at)
    return found


def _delivered(board: Board, task_id: str) -> bool:
    """Work that shipped: not a review record, and not dropped as won't do or superseded."""
    task = board.by_id.get(task_id)
    return bool(task) and not spec_for(task, board.gates)[1].get("record") and not resolution_of(task)


def _hours(start: Any, end: str) -> float | None:
    try:
        a = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        b = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    a, b = (t if t.tzinfo else t.replace(tzinfo=timezone.utc) for t in (a, b))
    return (b - a).total_seconds() / 3600


def _tokens(run: dict[str, Any]) -> int:
    return sum(int(run.get(k) or 0) for k in ("input_tokens", "cached_tokens", "output_tokens"))


def _storage(project: Project) -> dict[str, float]:
    """Disk held by softory's own process state, by folder."""
    base = state_dir(project)
    return {name: round(clutter.folder_size(base / name) / 1048576, 1)
            for name in ("logs", "verify", "workspaces", "evidence") if (base / name).exists()}


def _mib(project: Project) -> float:
    return sum(_storage(project).values())


def last_snapshot(project: Project) -> dict[str, Any] | None:
    """The snapshot Sage's last check-in recorded, if any."""
    return _last(state_dir(project) / "flow.jsonl")


def _last(path: Any) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


#: The smallest rise that counts as worse, besides 10%: a share moves in hundredths, counts and hours in units.
MIN_RISE = {"idle_share": 0.05}


def _worse(key: str, now: Any, before: Any) -> bool:
    if not isinstance(now, (int, float)) or not isinstance(before, (int, float)):
        return False
    return now > before * 1.1 and now - before > MIN_RISE.get(key, 0.5)
