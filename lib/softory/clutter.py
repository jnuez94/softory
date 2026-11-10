"""What the team left lying around: part of the evidence for Sage's process check-in.

Tablet (10 Nov) held 11 copies of the same plugin zip, one folder per commit someone wanted to "prove", 66
untracked review documents in the main checkout, four leftover worktrees, and a backup branch. Nothing
asked for any of it. ``softory clutter`` lists such things and never removes anything: Sage reads it, files
a simplify unit or asks the owner, and ``softory gc`` cleans what is softory's own.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import time
from pathlib import Path
from typing import Any

from . import charter as charters
from .gitlocal import git
from .project import Project

ARCHIVES = ("*.zip", "*.tar", "*.tar.gz", "*.tgz", "*.tar.bz2", "*.tar.xz", "*.7z", "*.rar", "*.bundle")
#: Folders that are never the team's own clutter: git itself, installed dependencies, softory's install.
SKIP = {".git", "node_modules", ".npm-cache", ".venv", "venv", "__pycache__"}
LIST_LIMIT = 30


def report(project: Project, idle_days: float | None = None) -> dict[str, Any]:
    """Untracked files, archives, extra worktrees, and merged or idle branches. Read-only."""
    charter = charters.load(project)
    simplify = charter.get("simplify") or {}
    idle_days = float(simplify.get("idle_branch_days", 14) if idle_days is None else idle_days)
    root = project.root.resolve()
    untracked = untracked_files(root)
    archives = _archives(root)
    names: dict[str, int] = {}
    for path in archives:
        names[Path(path).name] = names.get(Path(path).name, 0) + 1
    worktrees = _worktrees(project, root)
    branches = _branches(root, charter["git"]["base"], idle_days)
    counts = {"untracked": len(untracked), "archives": len(archives), "worktrees": len(worktrees),
              "branches": len(branches)}
    seen = [*untracked, *archives, *(w["path"] for w in worktrees), *(b["branch"] for b in branches)]
    return {"clean": not any(counts.values()), "counts": counts, "key": hashlib.sha256("\0".join(seen).encode()).hexdigest()[:16],
            "archive_mib": round(sum(_size(root / p) for p in archives) / 1048576, 1),
            "copies": {name: n for name, n in sorted(names.items()) if n > 1},
            "untracked": untracked[:LIST_LIMIT], "archives": archives[:LIST_LIMIT],
            "worktrees": worktrees[:LIST_LIMIT], "branches": branches[:LIST_LIMIT],
            "note": "Read-only. Commit what belongs in the repository, file reports with softory report, and "
                    "file a simplify unit for whatever keeps making copies."}


def archive_bytes(project: Project) -> int:
    """Bytes in archives outside softory's state folder, which flow already counts as state."""
    root = project.root.resolve()
    state = project.state.resolve()
    return sum(_size(root / p) for p in _archives(root) if not (root / p).resolve().is_relative_to(state))


def untracked_files(root: Path) -> list[str]:
    """Files git would show as untracked, not ignored. Softory's own are hidden by the exclude file.
    NUL-separated, so a name with spaces or non-ASCII characters comes back as itself, not quoted."""
    listed = git(root, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted(name for name in listed.stdout.split("\0") if name)


def _archives(root: Path) -> list[str]:
    """Archives anywhere in the checkout, ignored folders included: that is where build copies pile up."""
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP and not (folder == str(root) and d == ".agents")]
        for name in files:
            if any(fnmatch.fnmatch(name.lower(), pattern) for pattern in ARCHIVES):
                found.append(str((Path(folder) / name).relative_to(root)))
    return sorted(found)


def _worktrees(project: Project, root: Path) -> list[dict[str, Any]]:
    """Linked worktrees other than softory's own review workspaces."""
    listed = git(root, "worktree", "list", "--porcelain")
    if listed.returncode != 0:
        return []
    ours = (project.state / "workspaces").resolve()
    rows: list[dict[str, Any]] = []
    for block in listed.stdout.strip().split("\n\n"):
        fields = dict((line.split(" ", 1) + [""])[:2] for line in block.splitlines() if line)
        path = Path(fields.get("worktree", ""))
        if not fields.get("worktree") or path.resolve() == root or path.resolve().is_relative_to(ours):
            continue
        rows.append({"path": str(path), "branch": fields.get("branch", "").removeprefix("refs/heads/") or None,
                     "prunable": "prunable" in fields})
    return rows


def _branches(root: Path, base: str, idle_days: float) -> list[dict[str, Any]]:
    """Local branches already merged into the base, or with no commit for ``idle_days``."""
    current = git(root, "branch", "--show-current").stdout.strip()
    merged = set(git(root, "branch", "--format=%(refname:short)", "--merged", base).stdout.split())
    listed = git(root, "for-each-ref", "refs/heads", "--format=%(refname:short) %(committerdate:unix)")
    cutoff = time.time() - idle_days * 86400
    rows = []
    for line in listed.stdout.splitlines():
        name, _, stamp = line.rpartition(" ")
        if not name or name in (current, base):
            continue
        if name in merged:
            rows.append({"branch": name, "why": f"merged into {base}"})
        elif stamp.isdigit() and int(stamp) < cutoff:
            rows.append({"branch": name, "why": f"no commit in {idle_days:g} days"})
    return rows


def folder_size(path: Path) -> int:
    """Bytes under ``path``, never following symlinks (workspaces link the main checkout's dependencies)."""
    total = 0
    for folder, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(folder) / name).lstat().st_size
            except OSError:
                continue
    return total


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def summary(found: dict[str, Any]) -> str:
    """One line for the digest."""
    counts = found["counts"]
    parts = [f"{counts['untracked']} untracked file(s)", f"{counts['archives']} archive(s) ({found['archive_mib']} MiB)",
             f"{counts['worktrees']} extra worktree(s)", f"{counts['branches']} merged or idle branch(es)"]
    return "Clutter: " + ", ".join(p for p in parts if not p.startswith("0 ")) + ". Sage checks in on it; softory clutter lists it"
