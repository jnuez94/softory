"""Shared fixtures: throwaway git projects with softory installed from local checkouts.

Set SOFTORY_SCAFFOLD_SRC and SOFTORY_TRACKER_SRC to checkouts at the pinned
commits. Without them the integration tests skip, so the unit tests still run.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOFTORY = REPO / "bin" / "softory"
SCAFFOLD_SRC = os.environ.get("SOFTORY_SCAFFOLD_SRC")
TRACKER_SRC = os.environ.get("SOFTORY_TRACKER_SRC")
#: Optional: a checkout of the scaffold release before the pin, for the upgrade test.
PREVIOUS_SRC = os.environ.get("SOFTORY_SCAFFOLD_PREVIOUS_SRC")
PINNED = json.loads((REPO / "dependencies.json").read_text(encoding="utf-8"))["scaffold"]["version"]
COORDINATION = ".agents/agentic-project-scaffold-lite/bin/coordination"


def run(args: list[str], cwd: Path, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    full_env = {k: v for k, v in os.environ.items() if k not in ("COORDINATION_SESSION", "SOFTORY_ROLE")}
    full_env.update(env or {})
    result = subprocess.run(args, cwd=cwd, env=full_env, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise AssertionError(f"{args} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
    return result


def git_project(files: dict[str, str] | None = None) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    """A committed git repo with the given files."""
    holder = tempfile.TemporaryDirectory(prefix="softory-test-")
    root = Path(holder.name)
    run(["git", "init", "-q"], root)
    for name, text in (files or {"README.md": "# app\n", ".gitignore": "node_modules/\n"}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    run(["git", "add", "-A"], root)
    run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], root)
    return holder, root


def install(root: Path, *extra: str) -> dict:
    result = run([str(SOFTORY), "install", "--target", str(root), "--owner-name", "Tester",
                  "--scaffold-src", SCAFFOLD_SRC or "", "--tracker-src", TRACKER_SRC or "", *extra], root)
    return json.loads(result.stdout)


def softory(root: Path, *args: str, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run([str(root / ".agents/softory/bin/softory"), *args], root, env, check)


def coord(root: Path, *args: str, check: bool = True) -> dict:
    result = run([str(root / COORDINATION), *args], root, check=check)
    return json.loads(result.stdout or result.stderr)


def revision(root: Path, task_id: str) -> str:
    return str(coord(root, "task", "show", task_id)["data"]["revision"])


def git_status(root: Path) -> str:
    return run(["git", "status", "--porcelain", "--untracked-files=all"], root).stdout


needs_sources = unittest.skipUnless(
    SCAFFOLD_SRC and TRACKER_SRC, "set SOFTORY_SCAFFOLD_SRC and SOFTORY_TRACKER_SRC to run integration tests"
)
