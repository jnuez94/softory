"""The runner: wake each role when it has work, inside the owner's budget.

``softory run`` is one tick, meant for launchd or cron every few minutes. For
each role in the charter it skips the role if it is paused, already running,
over today's budget, or has nothing pending (no model call), and otherwise
starts ``softory run-role <role>`` in the background. That wrapper picks the
model, runs the harness with a time limit, and logs the run, which is what
the budget counts. Nothing here edits the database.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import charter as charters
from . import digest, perms, watch
from .runstate import budget, now, is_paused, state_dir
from .coordination import Coordination
from .errors import SoftoryError
from .project import Project


# ---- one tick ---------------------------------------------------------------------------------

def tick(project: Project, coord: Coordination, dry_run: bool = False) -> dict[str, Any]:
    charter = charters.load(project)
    report: dict[str, Any] = {"at": now().isoformat(timespec="seconds"), "started": [], "skipped": {}}
    if not dry_run:
        report["paged"] = digest.page_due(project, coord, charter)
    for role in charter["run"]["roles"]:
        why = is_paused(project, role)
        if why:
            report["skipped"][role] = f"paused: {why}"
            continue
        if running(project, role):
            report["skipped"][role] = "already running"
            continue
        use = budget(project, charter, role)
        if use["over"]:
            report["skipped"][role] = f"budget reached today ({use['runs']} runs, {use['minutes']} min)"
            continue
        wanted = watch.pending(project, coord, role)
        if not wanted["pending"]:
            report["skipped"][role] = "nothing pending" if not wanted["running"] else "a session is active"
            continue
        if not dry_run:
            spawn(project, role)
        report["started"].append(role)
    return report


def running(project: Project, role: str) -> bool:
    pid_file = state_dir(project) / f"{role}.pid"
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        pid_file.unlink(missing_ok=True)
        return False


def spawn(project: Project, role: str) -> None:
    logs = state_dir(project) / "logs"
    logs.mkdir(exist_ok=True)
    out = (logs / f"{role}-{now().strftime('%Y%m%dT%H%M%SZ')}.log").open("w", encoding="utf-8")
    subprocess.Popen([sys.executable, str(project.bundle / "bin" / "softory"), "run-role", role],  # noqa: S603
                     cwd=project.root, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     start_new_session=True, env=_clean_env())


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in ("COORDINATION_SESSION", "SOFTORY_ROLE")}


# ---- one role's run ---------------------------------------------------------------------------

def run_role(project: Project, coord: Coordination, role: str) -> dict[str, Any]:
    """Run one role once: build a short prompt from what is pending, run its harness, and log the run."""
    charter = charters.load(project)
    wanted = watch.pending(project, coord, role)
    if not wanted["pending"]:
        return {"role": role, "ran": False, "why": "nothing pending"}
    escalated = bool(wanted.get("escalate"))
    pick = charters.model_for(charter, role, escalated)
    command = harness_command(project, charter, role, pick, prompt(project, role, pick, wanted))
    pid_file = state_dir(project) / f"{role}.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    started = now()
    limit = float(charter["budget"]["minutes_per_run"]) * 60
    try:
        child = subprocess.Popen(command, cwd=project.root, env=_clean_env(), start_new_session=True)  # noqa: S603
        try:
            code = child.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGTERM)
            code = 124
    except FileNotFoundError as error:
        code = 127
        print(f"softory: {error}", file=sys.stderr)
    finally:
        pid_file.unlink(missing_ok=True)
    row = {"role": role, "started": started.isoformat(timespec="seconds"), "harness": pick["harness"],
           "model": pick["model"], "escalated": escalated, "exit": code,
           "minutes": round((now() - started).total_seconds() / 60, 2),
           "reasons": [r["why"] for r in wanted["reasons"]]}
    with (state_dir(project) / "runs.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(row) + "\n")
    return {"ran": True, **row}


def harness_command(project: Project, charter: dict[str, Any], role: str, pick: dict[str, str],
                    text: str) -> list[str]:
    template = charter["run"]["harnesses"].get(pick["harness"])
    if not template:
        raise SoftoryError(f"run.harnesses has no command for {pick['harness']}", "configuration_error")
    settings = perms.write_settings(project, charter, role) if pick["harness"] == "claude" else ""
    values = {"prompt": text, "model": pick["model"], "settings": str(settings), "role": role}
    return [part.format(**values) for part in template]


def prompt(project: Project, role: str, pick: dict[str, str], wanted: dict[str, Any]) -> str:
    """Short on purpose: the agent reads the details itself, with limits."""
    name = project.role(role)["name"]
    waiting = "; ".join(f"{r['why']}" + (f": {', '.join(r['ids'][:8])}" if r.get("ids") else "")
                        for r in wanted["reasons"])
    return (f"You are {name} ({role}) in a softory project, running unattended: nobody is watching. "
            f"Waiting for you: {waiting}. "
            f"Start with: eval \"$(.agents/softory/bin/softory start {role} --harness {pick['harness']} "
            f"--model {pick['model']})\". Follow the softory-operating-loop and softory-token-economy skills. "
            f"Finish one unit, then stop. If you need the owner, raise an escalation with --owner owner and move on; "
            f"never wait for an answer. End with softory end.")


def schedule(project: Project, minutes: int = 5) -> dict[str, Any]:
    """A launchd job and a cron line that run one tick every few minutes. The owner installs one."""
    label = f"dev.softory.{project.root.name.lower()}"
    binary = project.bundle / "bin" / "softory"
    log = state_dir(project) / "runner.log"
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key><array><string>{binary}</string><string>run</string></array>
  <key>WorkingDirectory</key><string>{project.root}</string>
  <key>StartInterval</key><integer>{minutes * 60}</integer>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>{os.environ.get('PATH', '/usr/bin:/bin')}</string></dict>
</dict></plist>
"""
    path = state_dir(project) / f"{label}.plist"
    path.write_text(plist, encoding="utf-8")
    return {
        "launchd": str(path),
        "install_launchd": f"cp {path} ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/{label}.plist",
        "cron": f"*/{minutes} * * * * cd {project.root} && {binary} run >> {log} 2>&1",
    }
