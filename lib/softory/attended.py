"""Attended runs: the runner opens each role where the owner can watch it and type to it.

Tablet's owner couldn't see headless runs (``claude -p``, ``codex exec``) in either app, or step in while
one worked (10 Nov). With ``run.mode`` set to ``attended``, the runner still decides who to wake and when,
but starts each role's interactive harness (``run.attended``) in a tmux window, or a Terminal window on a
Mac without tmux. ``softory attach`` shows the tmux session.

An interactive harness doesn't exit when its work is done, so a run ends at the first of: the role ends its
session (``softory end``), the owner closes the window or quits the harness, or the run's time limit. The
runner then stops what is left and closes the window, as it does for a headless run.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .errors import SoftoryError
from .project import Project
from .runstate import state_dir

#: Seconds between checks on an attended run, and the grace a stopped harness gets before SIGKILL.
POLL = 5.0
GRACE = 30.0


def surface() -> str | None:
    """Where attended runs open: tmux if it is installed, else Terminal on a Mac, else nowhere."""
    if shutil.which("tmux"):
        return "tmux"
    if sys.platform == "darwin" and shutil.which("osascript"):
        return "terminal"
    return None


def session_name(project: Project) -> str:
    """The project's tmux session. tmux refuses '.' and ':' in names."""
    return "softory-" + re.sub(r"[^A-Za-z0-9_-]", "-", project.root.name.lower())


def run(project: Project, role: str, command: list[str], env: dict[str, str], out_path: Path,
        minutes: float, finished: Callable[[], bool]) -> int:
    """Open ``command`` where the owner can see it, wait for the run to end, and return its exit code.

    ``finished`` says whether the role has ended its session. 124 means the time limit stopped it.
    """
    where = surface()
    if where is None:
        raise SoftoryError("run.mode is attended, but neither tmux nor macOS Terminal is available here: "
                           "install tmux, or set run.mode back to unattended", "configuration_error")
    folder = state_dir(project) / "attended"
    folder.mkdir(exist_ok=True)
    stem = out_path.stem
    pid_file, exit_file, script = folder / f"{stem}.pid", folder / f"{stem}.exit", folder / f"{stem}.sh"
    go = folder / f"{stem}.go"  # tmux: the harness waits until the window's output is being logged
    exports = " ".join(f"{k}={shlex.quote(v)}" for k, v in sorted(env.items()) if k in _PASSED)
    script.write_text("\n".join([
        "#!/bin/sh",
        f"cd {shlex.quote(str(project.root))} || exit 1",
        f"echo $$ > {shlex.quote(str(pid_file))}",
        *([f"while [ ! -f {shlex.quote(str(go))} ]; do sleep 0.1; done"] if where == "tmux" else []),
        f"env {exports} {shlex.join(command)}",
        f"echo $? > {shlex.quote(str(exit_file))}",
        "",
    ]), encoding="utf-8")
    window = _open_tmux(project, role, script, out_path) if where == "tmux" else _open_terminal(script, out_path)
    go.touch()
    deadline = time.monotonic() + minutes * 60
    try:
        while True:
            if exit_file.is_file():
                return _exit_code(exit_file)
            if finished():  # the role ended its session: its work is done
                _stop(pid_file, exit_file)
                return 0
            if time.monotonic() >= deadline:
                _stop(pid_file, exit_file)
                return 124
            time.sleep(POLL)
    except BaseException:  # Ctrl-C or a kill of the runner: stop the harness before its claims go back
        _stop(pid_file, exit_file)
        raise
    finally:
        if window:
            subprocess.run(["tmux", "kill-window", "-t", window], capture_output=True, check=False)
        for path in (pid_file, exit_file, script, go):
            path.unlink(missing_ok=True)


#: What the harness's window gets from the runner's environment: the session, the role, and enough to run.
_PASSED = {"COORDINATION_SESSION", "SOFTORY_ROLE", "SOFTORY_RUNNER", "PATH", "HOME", "LANG", "TERM", "USER",
           "SHELL", "TMPDIR"}


def _open_tmux(project: Project, role: str, script: Path, out_path: Path) -> str:
    name = session_name(project)
    exists = subprocess.run(["tmux", "has-session", "-t", f"={name}"], capture_output=True, check=False)
    where = ["new-window", "-t", f"={name}:"] if exists.returncode == 0 else ["new-session", "-d", "-s", name]
    made = subprocess.run(["tmux", *where, "-P", "-F", "#{window_id}", "-n", role, "-c", str(project.root),
                           "sh", str(script)], capture_output=True, text=True, check=False)
    if made.returncode != 0:
        raise SoftoryError(f"tmux couldn't open a window for {role}: {made.stderr.strip()}", "harness_error")
    window = made.stdout.strip()
    subprocess.run(["tmux", "pipe-pane", "-t", window, f"cat >> {shlex.quote(str(out_path))}"],
                   capture_output=True, check=False)
    return window


def _open_terminal(script: Path, out_path: Path) -> str:
    """A new Terminal window; ``script`` keeps a copy of what it shows in the run's log."""
    line = f"script -q {shlex.quote(str(out_path))} sh {shlex.quote(str(script))}; exit"
    quoted = line.replace("\\", "\\\\").replace('"', '\\"')
    made = subprocess.run(["osascript", "-e", f'tell application "Terminal" to do script "{quoted}"'],
                          capture_output=True, text=True, check=False)
    if made.returncode != 0:
        raise SoftoryError(f"Terminal didn't open: {made.stderr.strip()} (allow softory to control Terminal "
                           "in System Settings > Privacy & Security > Automation)", "harness_error")
    return ""


def _exit_code(exit_file: Path) -> int:
    try:
        return int(exit_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 1


def _stop(pid_file: Path, exit_file: Path) -> None:
    """Stop the window's shell and the harness under it: SIGTERM to its process group, then SIGKILL."""
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return  # it never started, or already cleaned up
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return
        except PermissionError:
            os.kill(pid, sig)
        waited = 0.0
        while waited < GRACE and _alive(pid) and not exit_file.is_file():
            time.sleep(0.5)
            waited += 0.5
        if not _alive(pid):
            return


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def attach(project: Project) -> dict[str, Any]:
    """How to watch attended runs; in a terminal with tmux, attach to them."""
    where = surface()
    name = session_name(project)
    if where == "tmux":
        live = subprocess.run(["tmux", "has-session", "-t", f"={name}"], capture_output=True, check=False)
        if live.returncode != 0:
            return {"surface": "tmux", "session": name, "running": False,
                    "note": "No role is running now. The runner opens a window here when it starts one."}
        if sys.stdin.isatty() and sys.stdout.isatty():
            os.execvp("tmux", ["tmux", "attach", "-t", f"={name}"])
        return {"surface": "tmux", "session": name, "running": True, "attach": f"tmux attach -t {name}",
                "note": "One window per running role. Ctrl-b w lists them; Ctrl-b d detaches and leaves them running."}
    if where == "terminal":
        return {"surface": "terminal", "note": "Each running role has its own Terminal window."}
    return {"surface": None, "note": "Neither tmux nor macOS Terminal is available, so attended runs can't open."}
