"""Real token use and cost per run, read from each harness's own report.

Claude Code with ``--output-format json`` prints one JSON object with
``usage`` and ``total_cost_usd``. Codex with ``--json`` prints JSON lines,
and each ``turn.completed`` line carries ``usage``. When a harness gives no
cost, softory estimates it from the charter's ``prices`` (USD per million
tokens). Anything else leaves the run's usage unknown, not zero.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any


def parse(output: str, model: str, prices: dict[str, Any]) -> dict[str, Any]:
    """Tokens and cost from a run's stdout, or {} when it carries no usage report."""
    found: dict[str, Any] = {}
    for line in [output.strip(), *output.splitlines()]:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        if "total_cost_usd" in event or event.get("type") == "result":  # Claude Code
            usage = event.get("usage") or {}
            cached = int(usage.get("cache_read_input_tokens") or 0)
            fresh = int(usage.get("input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0)
            found = {"input_tokens": fresh, "cached_tokens": cached, "output_tokens": int(usage.get("output_tokens") or 0)}
            if event.get("total_cost_usd") is not None:
                found["usd"] = round(float(event["total_cost_usd"]), 4)
            break
        if event.get("type") == "turn.completed":  # Codex: input_tokens includes the cached ones
            usage = event.get("usage") or {}
            cached = int(usage.get("cached_input_tokens") or 0)
            found["input_tokens"] = found.get("input_tokens", 0) + int(usage.get("input_tokens") or 0) - cached
            found["cached_tokens"] = found.get("cached_tokens", 0) + cached
            found["output_tokens"] = found.get("output_tokens", 0) + int(usage.get("output_tokens") or 0)
    if found and "usd" not in found and model in prices:
        rate = prices[model]
        found["usd"] = round((found["input_tokens"] * rate["input"] + found["cached_tokens"] * rate["cached"]
                              + found["output_tokens"] * rate["output"]) / 1_000_000, 4)
        found["usd_estimated"] = True
    return found


# ---- what runs bought -------------------------------------------------------------------------

#: Audit rows that don't count as work: opening a session, reading the inbox, sending a message.
BOOKKEEPING = {"session", "agent", "message"}


def audit_cursor(coord: Any) -> int | None:
    """The coordination database's newest audit row, to count what a run changes after it."""
    shown = coord.call("summary", "--section", "totals")
    return (shown.get("data") or {}).get("audit_cursor") if shown.get("ok") else None


def changes_since(coord: Any, role: str, cursor: int | None) -> int | None:
    """Records ``role`` changed after ``cursor``, leaving out bookkeeping. None when it can't tell."""
    if cursor is None:
        return None
    try:
        rows = coord.all_rows("audit", "list", "--actor", role, "--since", str(cursor))
    except Exception:  # noqa: BLE001 - a measurement must never fail the run it measures
        return None
    return sum(1 for row in rows if row.get("object_type") not in BOOKKEEPING)


def week(runs: list[dict[str, Any]], closed: int, days: float = 7) -> dict[str, Any]:
    """Spend, the share of runs that changed nothing, and spend per closed unit, over the last ``days``."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    recent = [r for r in runs if str(r.get("started", "")) >= since]
    measured = [r for r in recent if r.get("changes") is not None]
    idle = [r for r in measured if not r["changes"]]
    usd = round(sum(float(r.get("usd") or 0) for r in recent), 2)
    return {"days": days, "runs": len(recent), "usd": usd, "closed": closed,
            "usd_per_closed": round(usd / closed, 2) if closed else None,
            "idle_share": round(len(idle) / len(measured), 2) if measured else None,
            "idle_usd": round(sum(float(r.get("usd") or 0) for r in idle), 2)}
