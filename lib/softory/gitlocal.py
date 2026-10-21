"""Local git queries and the managed block in ``.git/info/exclude``.

Softory hides itself with ``info/exclude`` instead of ``.gitignore``: exclude
rules work the same way but are never committed, so the project's history and
other clones show no trace of the factory.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .errors import SoftoryError

EXCLUDE_START = "# softory:start (managed by softory; do not edit inside this block)"
EXCLUDE_END = "# softory:end"


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _git(root, *args)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed program, argument list
        ["git", *args], cwd=root, capture_output=True, text=True, check=False
    )


def is_repo(root: Path) -> bool:
    result = _git(root, "rev-parse", "--show-toplevel")
    return result.returncode == 0 and Path(result.stdout.strip()).resolve() == root.resolve()


def exclude_path(root: Path) -> Path:
    """The exclude file for this checkout. Worktrees share the main repo's."""
    result = _git(root, "rev-parse", "--git-path", "info/exclude")
    if result.returncode != 0:
        raise SoftoryError("Not a git repository: " + str(root), "not_a_repo")
    path = Path(result.stdout.strip())
    return path if path.is_absolute() else root / path


def toplevel(path: Path) -> Path | None:
    """The checkout (main or linked worktree) that contains ``path``."""
    result = _git(path, "rev-parse", "--show-toplevel")
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None


def main_checkout(path: Path) -> Path | None:
    """The main working tree of the repository ``path`` belongs to, even from a linked worktree."""
    result = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if result.returncode != 0:  # git older than 2.31
        result = _git(path, "rev-parse", "--git-common-dir")
    if result.returncode != 0:
        return None
    common = Path(result.stdout.strip())
    common = (common if common.is_absolute() else path / common).resolve()
    return common.parent if common.name == ".git" else None


def is_tracked(root: Path, relative: str) -> bool:
    return _git(root, "ls-files", "--error-unmatch", "--", relative).returncode == 0


def tracked_under(root: Path, relative: str) -> list[str]:
    result = _git(root, "ls-files", "--", relative)
    return [line for line in result.stdout.splitlines() if line]


def status_entries(root: Path) -> set[str]:
    """Every path ``git status`` reports, including untracked files."""
    result = _git(root, "status", "--porcelain=v1", "--untracked-files=all", "--ignored=no")
    if result.returncode != 0:
        raise SoftoryError("git status failed: " + result.stderr.strip(), "git_error")
    return {line for line in result.stdout.splitlines() if line}


def write_exclude_block(root: Path, patterns: list[str]) -> Path:
    """Replace softory's block in the exclude file with ``patterns``."""
    path = exclude_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    kept = _without_block(path.read_text(encoding="utf-8") if path.exists() else "")
    if patterns:
        block = "\n".join([EXCLUDE_START, *patterns, EXCLUDE_END]) + "\n"
        kept = (kept.rstrip("\n") + "\n\n" if kept.strip() else "") + block
    path.write_text(kept, encoding="utf-8")
    return path


def read_exclude_block(root: Path) -> list[str]:
    path = exclude_path(root)
    if not path.exists():
        return []
    inside, found = False, []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line == EXCLUDE_START:
            inside = True
        elif line == EXCLUDE_END:
            inside = False
        elif inside and line.strip():
            found.append(line)
    return found


def _without_block(text: str) -> str:
    lines, skipping = [], False
    for line in text.splitlines():
        if line == EXCLUDE_START:
            skipping = True
            continue
        if skipping:
            skipping = line != EXCLUDE_END
            continue
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")
