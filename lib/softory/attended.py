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

#: Seconds between checks on an attended run, the grace a stopped harness gets before SIGKILL, and how long
#: a new window may take to start the run.
POLL = 5.0
GRACE = 30.0
START_WAIT = 60.0


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
        minutes: float, finished: Callable[[], bool]) -> tuple[int, bool]:
    """Open ``command`` where the owner can see it, wait for the run to end, and return its exit code and
    whether everything it started has stopped.

    ``finished`` says whether the role has ended its session. 124 means the time limit stopped it, 129 that
    the window closed, and 127 that it never ran.
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
    began = time.monotonic()
    deadline = began + minutes * 60
    code = None
    try:
        while code is None:
            pid = _pid(pid_file)
            if exit_file.is_file():
                code = _exit_code(exit_file)  # the harness exited
            elif pid is None and time.monotonic() - began > START_WAIT:
                code = 127  # the window never ran the script
            elif pid is not None and not _alive(pid):
                code = 129  # the owner closed the window, or tmux lost it
            elif finished():
                code = 0  # the role ended its session: its work is done
            elif time.monotonic() >= deadline:
                code = 124
            else:
                time.sleep(POLL)
    except BaseException:  # Ctrl-C or a kill of the runner: stop the harness before its claims go back
        _stop(pid_file)
        raise
    finally:
        if window:
            subprocess.run(["tmux", "kill-window", "-t", window], capture_output=True, check=False)
    stopped = _stop(pid_file)  # whatever the window started, even after a clean exit
    for path in (exit_file, script, go, *([pid_file] if stopped else [])):
        path.unlink(missing_ok=True)
    return code, stopped


#: What the harness's window gets from the runner's environment: the session, the role, and enough to run.
_PASSED = {"COORDINATION_SESSION", "SOFTORY_ROLE", "SOFTORY_RUNNER", "PATH", "HOME", "LANG", "TERM", "USER",
           "SHELL", "TMPDIR"}


def _open_tmux(project: Project, role: str, script: Path, out_path: Path) -> str:
    """A window in the project's tmux session, creating the session if needed. The runner starts roles side
    by side, so two of them may both find no session: whichever loses the race to create it adds a window."""
    name = session_name(project)
    made = None
    for _ in range(3):
        exists = subprocess.run(["tmux", "has-session", "-t", f"={name}"], capture_output=True, check=False)
        where = ["new-window", "-t", f"={name}:"] if exists.returncode == 0 else ["new-session", "-d", "-s", name]
        made = subprocess.run(["tmux", *where, "-P", "-F", "#{window_id}", "-n", role, "-c", str(project.root),
                               "sh", str(script)], capture_output=True, text=True, check=False)
        if made.returncode == 0:
            break
    if made is None or made.returncode != 0:
        raise SoftoryError(f"tmux couldn't open a window for {role}: {made.stderr.strip() if made else ''}",
                           "harness_error")
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


def _pid(pid_file: Path) -> int | None:
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _stop(pid_file: Path) -> bool:
    """Stop everything in the window's process group: SIGTERM, then SIGKILL, until no member is left.

    The window's shell leads the group, so a worker that ignores SIGTERM outlives it; the group is checked,
    not the shell. False means something survived even SIGKILL: its claims must stay where they are.
    """
    pid = _pid(pid_file)
    if pid is None:
        return True
    for sig, grace in ((signal.SIGTERM, GRACE), (signal.SIGKILL, GRACE)):
        if not _group_alive(pid):
            return True
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        waited = 0.0
        while waited < grace and _group_alive(pid):
            time.sleep(0.2)
            waited += 0.2
    return not _group_alive(pid)


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


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
