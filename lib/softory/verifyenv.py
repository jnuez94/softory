"""Where ``softory verify`` runs: one at a time, awake, with shared folders cloned instead of linked.

Only one verify runs per project. The others wait their turn on a lock and
show in ``softory queue``, so roles never have to book the test machine by
message. Shared folders such as ``node_modules`` are cloned copy-on-write,
so an installer the test command runs can't delete the main checkout's copy.
On macOS the run holds ``caffeinate -i``, so the Mac doesn't sleep under it.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .project import Project


def _queue_file(project: Project) -> Path:
    return project.bundle / "run" / "verify-queue.json"


def waiting(project: Project) -> list[dict[str, Any]]:
    """Verifies running or waiting, oldest first. Entries whose process is gone are left out."""
    try:
        rows = json.loads(_queue_file(project).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in rows if _alive(int(row.get("pid", 0)))]


@contextlib.contextmanager
def turn(project: Project, task_id: str, actor: str) -> Iterator[None]:
    """Wait for this project's verify lock, showing the wait in the queue file, and hold it while running."""
    run_dir = project.bundle / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    me = {"task": task_id, "by": actor, "pid": os.getpid(),
          "since": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _edit_queue(project, lambda rows: [*rows, me])
    try:
        with (run_dir / "verify.lock").open("w", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    finally:
        _edit_queue(project, lambda rows: [r for r in rows if r.get("pid") != me["pid"] or r.get("task") != task_id])


def _edit_queue(project: Project, change: Any) -> None:
    path = _queue_file(project)
    with (path.parent / "verify-queue.lock").open("w", encoding="utf-8") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        path.write_text(json.dumps(change(waiting(project)), indent=2) + "\n", encoding="utf-8")


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def share(source: Path, target: Path, mode: str) -> str:
    """Put ``source`` at ``target`` inside the verify tree. Returns how: cloned, copied, or linked."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == "link":
        target.symlink_to(source)
        return "linked"
    clone = ["cp", "-cR"] if sys.platform == "darwin" else ["cp", "-R", "--reflink=auto"]
    done = subprocess.run([*clone, str(source), str(target)], capture_output=True, check=False)
    if done.returncode == 0:
        return "cloned"
    shutil.rmtree(target, ignore_errors=True)
    if source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target)
    return "copied"


def awake(command: str) -> str:
    """The command, held awake with caffeinate where macOS has it."""
    if sys.platform == "darwin" and shutil.which("caffeinate"):
        return f"caffeinate -i /bin/sh -c {shlex.quote(command)}"
    return command


def keep_artifacts(tree: Path, globs: list[str], into: Path) -> list[str]:
    """Copy files matching ``globs`` out of the verify tree before it is removed. Returns what was kept."""
    kept = []
    for pattern in globs:
        for found in tree.glob(pattern):
            relative = found.relative_to(tree)
            destination = into / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if found.is_dir():
                shutil.copytree(found, destination, symlinks=True, dirs_exist_ok=True)
            else:
                shutil.copy2(found, destination)
            kept.append(str(relative))
    return kept
