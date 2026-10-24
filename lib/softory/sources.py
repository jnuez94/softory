"""Get the pinned scaffold and tracker sources: local checkouts or a git clone."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .errors import SoftoryError


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(  # noqa: S603 - fixed program, argument list
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SoftoryError(f"git {' '.join(args[:2])} failed: {result.stderr.strip()}", "git_error")
    return result.stdout.strip()


def clone_at(repository: str, commit: str, destination: Path) -> Path:
    """Clone ``repository`` and check out exactly ``commit``."""
    _git("clone", "--quiet", "--filter=blob:none", "--no-checkout", repository, str(destination))
    _git("checkout", "--quiet", commit, cwd=destination)
    return destination


def head_of(checkout: Path) -> str | None:
    try:
        return _git("rev-parse", "HEAD", cwd=checkout)
    except SoftoryError:
        return None


def verify(name: str, checkout: Path, pin: dict[str, Any], allow_unpinned: bool) -> None:
    """Refuse a checkout that isn't the pinned commit, unless told otherwise."""
    head = head_of(checkout)
    if head != pin["commit"] and not allow_unpinned:
        raise SoftoryError(
            f"{name} checkout {checkout} is at {head or 'an unknown commit'}, not the pinned "
            f"{pin['commit'][:12]} ({pin['version']}). Check out the pin, or pass --allow-unpinned.",
            "unpinned_source",
        )
    if name == "scaffold":
        version = (checkout / "VERSION").read_text(encoding="utf-8").strip()
        minimum = pin.get("minimum", pin["version"])
        if not version_tuple(minimum) <= version_tuple(version) < (2, 0, 0):
            raise SoftoryError(
                f"Scaffold {version} isn't supported: softory needs {minimum} or a later 1.x "
                "(it uses options 1.4.1 added, and the tracker requires a CLI below 2.0.0).",
                "unsupported_version",
            )


def version_tuple(text: str) -> tuple[int, ...]:
    """``"1.4.1"`` as ``(1, 4, 1)``; anything unreadable sorts lowest."""
    try:
        return tuple(int(part) for part in text.strip().lstrip("v").split(".")[:3])
    except ValueError:
        return (0,)


def fetch_sources(deps: dict[str, Any], scratch: Path, options: dict[str, Any]) -> tuple[Path, Path]:
    """Return (scaffold checkout, tracker checkout), cloning any not given."""
    allow = bool(options.get("allow_unpinned"))
    found: list[Path] = []
    for name in ("scaffold", "tracker"):
        given = options.get(f"{name}_src")
        pin = deps[name]
        if given:
            checkout = Path(given).resolve()
        else:
            checkout = clone_at(pin["repository"], pin["commit"], scratch / name)
        verify(name, checkout, pin, allow)
        found.append(checkout)
    return found[0], found[1]
