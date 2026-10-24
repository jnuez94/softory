"""Real token use and cost per run, read from each harness's own report.

Claude Code with ``--output-format json`` prints one JSON object with
``usage`` and ``total_cost_usd``. Codex with ``--json`` prints JSON lines,
and each ``turn.completed`` line carries ``usage``. When a harness gives no
cost, softory estimates it from the charter's ``prices`` (USD per million
tokens). Anything else leaves the run's usage unknown, not zero.
"""

from __future__ import annotations

import json
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
