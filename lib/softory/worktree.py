"""Git worktrees: give a linked worktree the same softory as the main checkout.

Softory's files are untracked, so ``git worktree add`` checks out none of them.
``link`` symlinks them in from the main checkout. The exclude rules live in the
repository's shared ``info/exclude``, so the links stay hidden too. The
database is not linked: the scaffold refuses symlinked ``.coordination``
folders, so ``softory coord`` runs the CLI from the main checkout instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import gitlocal
from .errors import SoftoryError
from .ops import installed_paths
from .project import Project

NOT_LINKED = (".coordination",)


def add(project: Project, path: Path, branch: str | None, start: str | None, share: list[str] | None = None) -> dict[str, Any]:
    """``git worktree add`` at an absolute ``path``, then ``link``."""
    args = ["worktree", "add"]
    if branch:
        args += ["-b", branch]
    args.append(str(path))
    if start:
        args.append(start)
    result = gitlocal.git(project.root, *args)
    if result.returncode != 0:
        raise SoftoryError("git worktree add failed: " + result.stderr.strip(), "git_error")
    return link(project, path, share)


def link(project: Project, path: Path, share: list[str] | None = None) -> dict[str, Any]:
    """Symlink every installed softory path into the worktree that holds ``path``.

    ``share`` names more untracked paths to link from the main checkout, such
    as ``.web/node_modules``, so the worktree can build without the network.
    """
    worktree = gitlocal.toplevel(path)
    if worktree is None:
        raise SoftoryError(f"{path} is not inside a git checkout", "not_a_repo")
    if worktree == project.root.resolve():
        raise SoftoryError("That is the main checkout; softory is already installed there", "invalid_arguments")
    if gitlocal.main_checkout(worktree) != project.root.resolve():
        raise SoftoryError(f"{worktree} is not a worktree of {project.root}", "invalid_arguments")
    shared = [p.strip("/") for p in share or []]
    for relative in shared:
        if not (project.root / relative).exists() or gitlocal.tracked_under(project.root, relative):
            raise SoftoryError(f"{relative} must be an untracked path in the main checkout", "invalid_arguments")
    _unslash_exclude_patterns(project, shared)
    linked, kept = [], []
    for relative in [*installed_paths(project), *shared]:
        source, target = project.root / relative, worktree / relative
        if relative in NOT_LINKED or not source.exists():
            continue
        if target.is_symlink() and target.resolve() == source.resolve():
            kept.append(relative)
        elif target.exists() or target.is_symlink():
            kept.append(relative)  # the branch has its own; leave it
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(source, target_is_directory=source.is_dir())
            linked.append(relative)
    visible = sorted(e for e in gitlocal.status_entries(worktree) if any(e[3:].startswith(p) for p in linked))
    return {"worktree": str(worktree), "linked": linked, "already_present": kept, "git_status_changes": visible}


def _unslash_exclude_patterns(project: Project, shared: list[str]) -> None:
    """A trailing slash matches only directories, and a symlink isn't one.

    Installs from before ``link`` existed wrote ``/.agents/softory/``; rewrite
    those patterns so they also hide the symlinks, and hide shared paths too.
    """
    manifest = project.manifest()
    patterns = manifest["exclude_patterns"]
    fixed = [p.rstrip("/") if not p.endswith("*") else p for p in patterns]
    fixed += [f"/{relative}" for relative in shared if f"/{relative}" not in fixed]
    if fixed != patterns:
        gitlocal.write_exclude_block(project.root, fixed)
        manifest["exclude_patterns"] = fixed
        project.save_manifest(manifest)
