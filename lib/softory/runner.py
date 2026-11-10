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
from typing import Any

from . import attended
from . import charter as charters
from . import decide, digest, feasibility, perms, recovery, runprompt, sessions, usage, watch, work
from .runstate import RUNNER_ENV, allowed_tasks, budget, is_paused, limits_for, now, state_dir
from .coordination import Coordination
from .errors import SoftoryError
from .project import Project


CHECK = "feasibility"  # the pid file of a running feasibility check


# ---- one tick ---------------------------------------------------------------------------------

def tick(project: Project, coord: Coordination, dry_run: bool = False) -> dict[str, Any]:
    charter = charters.load(project)
    report: dict[str, Any] = {"at": now().isoformat(timespec="seconds"), "started": [], "skipped": {}}
    if charter["run"].get("mode") == "attended":
        report["attended"] = attended.surface() or "unavailable: install tmux"
    if not dry_run:  # doctor reads this to tell a loaded scheduler from one that never fires
        (state_dir(project) / "last-tick.json").write_text(json.dumps({"at": report["at"]}) + "\n", encoding="utf-8")
    if not dry_run:
        report["recovered"] = recovery.sweep(project, coord, charter)
        report["defaulted"] = decide.apply_due(project, coord, charter)
        report["paged"] = digest.page_due(project, coord, charter)
    for role in charter["run"]["roles"]:
        why = is_paused(project, role)
        if why and not allowed_tasks(project, role):
            report["skipped"][role] = f"paused: {why}"
            continue
        if running(project, role) or (role == "quinn" and running(project, CHECK)):
            report["skipped"][role] = "already running"  # a feasibility check is a Quinn run too
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
    check = None if "quinn" in report["started"] else _feasibility_due(project, coord, charter)
    if check:
        if not dry_run:
            spawn(project, "quinn", ["run-check", check])
        report["feasibility"] = check
    return report


def _feasibility_due(project: Project, coord: Coordination, charter: dict[str, Any]) -> str | None:
    """One story to check this tick: Quinn isn't running, isn't paused, and is inside today's budget.

    While Quinn is paused, only a story the owner's scoped resume names for Quinn may be checked.
    """
    if running(project, CHECK) or running(project, "quinn") or budget(project, charter, "quinn")["over"]:
        return None
    scope = allowed_tasks(project, "quinn") if is_paused(project, "quinn") else None
    if scope is not None and not scope:
        return None
    if watch.active_sessions(coord, "quinn"):  # a Quinn session started outside the runner has no pid file
        return None
    from .work import Board  # noqa: PLC0415 - a full board read only when a check might be due

    due = [s for s in feasibility.due(Board(project, coord), charter) if scope is None or s in scope]
    return due[0] if due else None


def running(project: Project, role: str) -> bool:
    pid_file = state_dir(project) / f"{role}.pid"
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        pid_file.unlink(missing_ok=True)
        return False


def spawn(project: Project, role: str, command: list[str] | None = None) -> None:
    logs = state_dir(project) / "logs"
    logs.mkdir(exist_ok=True)
    name = role if command is None else f"{role}-{command[0]}"
    out = (logs / f"{name}-{now().strftime('%Y%m%dT%H%M%SZ')}.log").open("a", encoding="utf-8")
    subprocess.Popen([sys.executable, str(project.bundle / "bin" / "softory"), *(command or ["run-role", role])],  # noqa: S603
                     cwd=project.root, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     start_new_session=True, env=_clean_env())


SESSION_ENV, SOFTORY_ROLE = "COORDINATION_SESSION", "SOFTORY_ROLE"


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in (SESSION_ENV, SOFTORY_ROLE)}


# ---- one role's run ---------------------------------------------------------------------------

def run_role(project: Project, coord: Coordination, role: str) -> dict[str, Any]:
    """Run one role once: build a short prompt from what is pending, run its harness, and log the run."""
    charter = charters.load(project)
    wanted = watch.pending(project, coord, role)
    if not wanted["pending"]:
        return {"role": role, "ran": False, "why": "nothing pending"}
    escalated = bool(wanted.get("escalate"))
    pick = charters.model_for(charter, role, escalated)
    job = runprompt.job_of(wanted)
    effort = charters.effort_for(charter, role, job)
    text = runprompt.build(project, coord, charter, role, pick, wanted, job)
    return _run(project, charter, role, pick, text, job, effort, escalated, [r["why"] for r in wanted["reasons"]],
                coord=coord)


def run_check(project: Project, coord: Coordination, story_id: str) -> dict[str, Any]:
    """Run the feasibility check on one story: Quinn on the charter's other model, reading only the plan."""
    charter = charters.load(project)
    settings = charter["feasibility"]
    pick = {"harness": settings["harness"], "model": settings["model"]}
    text = feasibility.prompt(project, coord, charter, story_id)
    return _run(project, charter, "quinn", pick, text, "feasibility", settings.get("effort") or "high", False,
                [f"feasibility check of {story_id}"], pid_name=CHECK, coord=coord)


def _run(project: Project, charter: dict[str, Any], role: str, pick: dict[str, str], text: str, job: str,
         effort: str, escalated: bool, reasons: list[str], pid_name: str | None = None,
         coord: Coordination | None = None) -> dict[str, Any]:
    """Run the harness once with a time limit, and log the run where the budget counts it.

    The runner opens the role's session and hands it to the harness in its environment, and ends it when
    the run exits or times out, so no harness has to keep shell state between commands.
    """
    limits = limits_for(charter, role)
    watched = charter["run"].get("mode") == "attended"
    command = harness_command(project, charter, role, pick, text, effort, limits.get("usd_per_run") or 0,
                              attended_run=watched)
    pid_file = state_dir(project) / f"{pid_name or role}.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    try:
        session = work.open_session(project, coord, role, pick["harness"], pick["model"], by_runner=True) if coord else None
        cursor = usage.audit_cursor(coord) if coord else None
    except BaseException:
        pid_file.unlink(missing_ok=True)
        raise
    started = now()
    logs = state_dir(project) / "logs"
    logs.mkdir(exist_ok=True)
    out_path = logs / f"{pid_name or role}-{started.strftime('%Y%m%dT%H%M%SZ')}-{os.getpid()}.out"  # one per run
    child: subprocess.Popen | None = None
    env = {**_clean_env(), RUNNER_ENV: "1", SOFTORY_ROLE: role}  # sessions it starts aren't logged as manual
    if session:
        env[SESSION_ENV] = session
    try:
        if watched:  # in a window the owner can see and type into; it ends when the role ends its session
            out_path.touch()
            code = attended.run(project, role, command, env, out_path, float(limits["minutes_per_run"]),
                                lambda: bool(session) and _ended(coord, session))
        else:
            with out_path.open("w", encoding="utf-8") as out:
                child = subprocess.Popen(command, cwd=project.root, env=env, start_new_session=True,  # noqa: S603
                                         stdout=out, stdin=subprocess.DEVNULL)
                try:
                    code = child.wait(timeout=float(limits["minutes_per_run"]) * 60)
                except subprocess.TimeoutExpired:
                    _stop(child)
                    code = 124
                except BaseException:  # Ctrl-C or a kill of the runner: the harness has its own session, so stop it
                    _stop(child)
                    raise
    except (FileNotFoundError, SoftoryError) as error:  # no harness, or no window to open it in
        code = 127
        print(f"softory: {error}", file=sys.stderr)
    finally:
        if child is not None and child.poll() is None:
            # Stopping it was cut short. Leave its marker and session alone: handing its claims back now would
            # let another run edit the same task while it still does. Stale-session recovery finishes it.
            print(f"softory: {role}'s harness (pid {child.pid}) is still running; its session stays open",
                  file=sys.stderr)
        else:
            pid_file.unlink(missing_ok=True)
            if session:
                _close_session(project, coord, session, role)
    spent = usage.parse(out_path.read_text(encoding="utf-8", errors="replace") if out_path.is_file() else "",
                        pick["model"], charter.get("prices") or {})
    row = {"role": role, "started": started.isoformat(timespec="seconds"), "harness": pick["harness"],
           "model": pick["model"], "escalated": escalated, "job": job, "effort": effort, "exit": code,
           "minutes": round((now() - started).total_seconds() / 60, 2), **spent,
           "prompt_chars": len(text), "reasons": reasons}
    if coord:  # what the run changed besides bookkeeping; 0 means a run that bought nothing
        row["changes"] = usage.changes_since(coord, role, cursor)
    with (state_dir(project) / "runs.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(row) + "\n")
    return {"ran": True, **row}


def _ended(coord: Coordination, session: str) -> bool:
    shown = coord.call("session", "show", session)
    return bool(shown.get("ok")) and (shown.get("data") or {}).get("status") != "active"


#: Seconds a harness gets to exit after SIGTERM before its process group is killed.
STOP_GRACE = 30.0


def _stop(child: subprocess.Popen, grace: float = STOP_GRACE) -> None:
    """Stop a timed-out harness and everything it started, and wait until it has. Its claims go back to todo
    only after this, so a harness that ignores SIGTERM can't keep editing a task another run may claim."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(child.pid, sig)
        except ProcessLookupError:
            break  # the whole group is gone
        try:
            child.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            continue  # still running: kill it
        if sig == signal.SIGTERM:  # the harness exited; take down anything it left running in its group
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        break
    child.wait()


def _close_session(project: Project, coord: Coordination, session: str, role: str) -> None:
    """End the run's session unless the role already did.

    The scaffold won't end a session that still owns claims, so a run that exited or timed out mid-task
    hands each claim back to todo first: the role's next run claims it fresh instead of the task sitting
    in progress until stale-session recovery blocks it. If the session still won't end, it stays
    remembered so ``softory end --actor <role>`` or recovery can finish it.
    """
    shown = coord.call("session", "show", session)
    if not (shown.get("ok") and (shown.get("data") or {}).get("status") == "active"):
        sessions.forget(project, session)
        return
    ended = coord.call("session", "end", session)
    error = ended.get("error") or {}
    if not ended.get("ok") and error.get("code") == "session_has_active_claims":
        for task_id in (error.get("details") or {}).get("tasks") or []:
            task = coord.call("task", "show", task_id)
            revision = str((task.get("data") or {}).get("revision", ""))
            coord.call("--session", session, "task", "release", task_id, "--to", "todo", "--actor", role,
                       "--if-revision", revision, "--note", "run ended with the task unfinished; claim it again")
        ended = coord.call("session", "end", session)
    if ended.get("ok"):
        sessions.forget(project, session)
    else:
        print(f"softory: session {session} left open: {(ended.get('error') or {}).get('message', '')}",
              file=sys.stderr)


def harness_command(project: Project, charter: dict[str, Any], role: str, pick: dict[str, str],
                    text: str, effort: str = "", usd_per_run: float = 0, attended_run: bool = False) -> list[str]:
    """The harness's template with values filled in. A flag whose value comes out empty is left out.
    An attended run uses the interactive template in run.attended."""
    table = "attended" if attended_run else "harnesses"
    template = (charter["run"].get(table) or {}).get(pick["harness"])
    if not template:
        raise SoftoryError(f"run.{table} has no command for {pick['harness']}", "configuration_error")
    settings = perms.write_settings(project, charter, role) if pick["harness"] == "claude" else ""
    values = {"prompt": text, "model": pick["model"], "settings": str(settings), "role": role, "effort": effort,
              "usd_per_run": f"{float(usd_per_run):g}" if float(usd_per_run or 0) > 0 else ""}
    command: list[str] = []
    for part in template:
        filled = part.format(**values)
        empty = "{" in part and all(not values[k] for k in values if "{" + k + "}" in part)
        if empty:
            if command and command[-1].startswith("-"):
                command.pop()  # the flag that named the empty value
            continue
        command.append(filled)
    return command


def scheduler_state(project: Project) -> dict[str, Any]:
    """Whether a launchd job or cron line runs the runner for this project, and when it last ticked."""
    label = f"dev.softory.{project.root.name.lower()}"
    launchd = None
    if sys.platform == "darwin":
        try:
            launchd = subprocess.run(["launchctl", "list", label], capture_output=True, check=False).returncode == 0
        except OSError:
            launchd = False
    try:
        listed = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    except OSError:  # no cron on this machine: not loaded, not an error
        listed = subprocess.CompletedProcess(["crontab"], 1, "", "")
    cron = listed.returncode == 0 and any(str(project.root) in line and " run" in line
                                          for line in listed.stdout.splitlines() if not line.lstrip().startswith("#"))
    try:
        last = json.loads((state_dir(project) / "last-tick.json").read_text(encoding="utf-8")).get("at")
    except (OSError, json.JSONDecodeError):
        last = None
    return {"label": label, "launchd_loaded": launchd, "cron": cron, "loaded": bool(launchd or cron), "last_tick": last}


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
