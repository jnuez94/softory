"""Reusable review workspaces, and cleanup of what runs leave behind.

Tablet's reviewers checked out each commit into /tmp by hand, and some ran ``npm ci`` in every copy (Jade,
9 Nov). ``softory workspace <role> [commit]`` keeps one checkout per role beside softory's state, moves it to
the commit asked for, and links the charter's ``verify.share`` folders (dependencies) from the main checkout.
It is a git worktree where git allows one, and a plain snapshot of the commit's files where a sandbox
protects .git. The verify ledger is the test proof, so a reviewer reads code here and doesn't rerun the suite.

``softory gc`` removes what nothing reads any more: workspaces unused for ``--days``, run and verify logs
older than that, and verify trees a crashed run left in the temp folder.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from . import charter as charters
from .errors import SoftoryError
from .gitlocal import git
from .project import Project
from .verify import _checkout


def _folder(project: Project) -> Path:
    return project.state / "workspaces"


def workspace(project: Project, role: str, commit: str | None = None) -> dict[str, Any]:
    """The role's workspace, at ``commit`` (default: HEAD)."""
    project.member(role)  # a role, or the owner's stand-in for one
    found = git(project.root, "rev-parse", "--verify", "--quiet", f"{commit or 'HEAD'}^{{commit}}")
    if found.returncode != 0:
        raise SoftoryError(f"{commit} is not a commit in this repository", "not_found")
    sha = found.stdout.strip()
    tree = _folder(project) / role
    mode = _move(tree, sha) if (tree / ".git").is_file() else None
    if mode is None:  # first use, a snapshot, or a worktree git won't move: start it afresh
        _remove(project, tree)
        tree.parent.mkdir(parents=True, exist_ok=True)
        made = _checkout(project.root, sha, tree)
        if made is None:
            shutil.rmtree(tree, ignore_errors=True)
            raise SoftoryError(f"git could check out {sha[:12]} neither as a worktree nor as a snapshot", "git_error")
        mode = "worktree" if made else "snapshot"
    shared = []
    for relative in charters.load(project)["verify"].get("share") or []:
        source, target = project.root / relative, tree / relative
        if source.exists() and not (target.exists() or target.is_symlink()):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(source, target_is_directory=source.is_dir())
            shared.append(relative)
    tree.touch()  # gc goes by when a workspace was last used
    return {"role": role, "workspace": str(tree), "commit": sha, "mode": mode, "linked": shared,
            "note": "Reused on your next call. softory verify's result is the test proof: read the code here, "
                    "and don't rerun the suite or install dependencies. Run softory from the project root."}


def _move(tree: Path, sha: str) -> str | None:
    """Move an existing worktree to ``sha``, dropping local edits. Ignored files (linked folders) stay."""
    for args in (["checkout", "--quiet", "--detach", "--force", sha], ["clean", "-fdq"]):
        if git(tree, *args).returncode != 0:
            return None
    return "worktree"


def _remove(project: Project, tree: Path) -> None:
    if (tree / ".git").is_file():
        git(project.root, "worktree", "remove", "--force", str(tree))
    _rmtree_keep_links(tree)
    git(project.root, "worktree", "prune")


def _rmtree_keep_links(tree: Path) -> None:
    """Remove a tree without following symlinks into the main checkout's folders."""
    if tree.is_symlink():
        tree.unlink()
    elif tree.exists():
        shutil.rmtree(tree, ignore_errors=True)  # rmtree removes symlinks, never their targets


def gc(project: Project, days: float = 14, dry_run: bool = False) -> dict[str, Any]:
    """Remove workspaces unused for ``days``, logs older than that, and verify trees older than a day."""
    now = time.time()
    old = now - days * 86400
    found: list[tuple[Path, str]] = []
    folder = _folder(project)
    for tree in sorted(folder.iterdir()) if folder.is_dir() else []:
        if tree.stat().st_mtime < old:
            found.append((tree, "workspace"))
    for logs, pattern in ((project.state / "logs", "*.out"), (project.state / "verify", "*.log")):
        for path in sorted(logs.glob(pattern)) if logs.is_dir() else []:
            if path.stat().st_mtime < old:
                found.append((path, "log"))
    for tree in sorted(Path(tempfile.gettempdir()).glob("softory-verify-*")):
        if tree.is_dir() and tree.stat().st_mtime < now - 86400:  # a running verify is younger than a day
            found.append((tree, "verify tree"))
    freed = sum(_size(path) for path, _ in found)
    if not dry_run:
        for path, kind in found:
            if kind == "workspace":
                _remove(project, path)
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        git(project.root, "worktree", "prune")
    counts: dict[str, int] = {}
    for _, kind in found:
        counts[kind] = counts.get(kind, 0) + 1
    return {"removed" if not dry_run else "would_remove": counts, "mib": round(freed / 1048576, 1),
            "older_than_days": days, "paths": [str(p) for p, _ in found][:50]}


def _size(path: Path) -> int:
    if path.is_symlink() or path.is_file():
        return path.lstat().st_size
    total = 0
    for item in path.rglob("*"):
        try:
            if not item.is_symlink() and item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total
