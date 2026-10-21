"""Install softory, scaffold 1.4.0, and the tracker into a project, hidden from git."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import BUNDLE_DIR, COORDINATION_BIN, SCAFFOLD_DIR, __version__, gitlocal, instructions
from .coordination import Coordination
from .errors import SoftoryError
from .project import Project
from .registration import register_roster
from .sources import fetch_sources

SKILL_ROOTS = (".claude/skills", ".agents/skills")
BUNDLE_PARTS = (
    "factory", "lib", "bin", "docs", "dependencies.json", "external-skills.json", "VERSION", "LICENSE", "README.md",
)


def install(source: Path, target: Path, options: dict[str, Any]) -> dict[str, Any]:
    target = target.resolve()
    if not gitlocal.is_repo(target):
        raise SoftoryError(f"{target} is not the root of a git repository. Run `git init` first.", "not_a_repo")
    for relative in (BUNDLE_DIR, SCAFFOLD_DIR, ".coordination"):
        if gitlocal.tracked_under(target, relative):
            raise SoftoryError(f"{relative} is tracked in git; softory keeps it local. Untrack it first.", "tracked_path")

    previous = _previous_manifest(target)
    scaffold_found = _existing_scaffold(target)
    status_before = gitlocal.status_entries(target)
    deps = json.loads((source / "dependencies.json").read_text(encoding="utf-8"))

    # Decide every path first and hide it before writing anything, so even a
    # failed install never shows up in git status.
    skills = sorted(p.name for p in (source / "skills").iterdir() if (p / "SKILL.md").is_file())
    external = previous.get("external_skills", [])
    _check_skills(skills, target, previous)
    actions = instructions.plan(target, set(previous.get("owned_files", [])))
    owned = sorted(name for name, action in actions.items() if action in ("create", "override"))
    patterns = exclude_patterns(skills + external, owned)
    gitlocal.write_exclude_block(target, sorted(set(patterns) | set(previous.get("exclude_patterns", []))))

    with tempfile.TemporaryDirectory(prefix="softory-src-") as scratch:
        scaffold_src, tracker_src = fetch_sources(deps, Path(scratch), options)
        _install_scaffold(scaffold_src, target)
        bundle = target / BUNDLE_DIR
        _copy_bundle(source, bundle)
        _copy_tree(tracker_src / "coordination_ui", bundle / "tracker" / "coordination_ui")
        shutil.copy2(tracker_src / "LICENSE", bundle / "tracker" / "LICENSE")
        scaffold_block = _scaffold_block(scaffold_src)

    _install_skills(source / "skills", skills, target, previous)
    softory_text = (source / "factory" / "INSTRUCTIONS.md").read_text(encoding="utf-8")
    base = softory_text if _project_has_scaffold_block(target, actions) else scaffold_block + "\n" + softory_text
    body = instructions.compose(base, Project(target).local().get("stand_ins", {}))
    instructions.write(target, actions, body)
    (bundle / "generated").mkdir(exist_ok=True)
    (bundle / "generated" / "base.md").write_text(base, encoding="utf-8")
    (bundle / "generated" / "instructions.md").write_text(body, encoding="utf-8")

    coord = Coordination(target / COORDINATION_BIN, target)
    roster = json.loads((source / "factory" / "roles" / "roster.json").read_text(encoding="utf-8"))
    registered = register_roster(coord, roster, options)
    gitlocal.write_exclude_block(target, patterns)
    manifest = {
        "softory_version": __version__,
        "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scaffold": deps["scaffold"],
        "tracker": deps["tracker"],
        "skills": skills,
        "external_skills": external,
        "owned_files": owned,
        # Uninstall leaves a scaffold the project had before softory. Unknown
        # (an install from before this field) counts as pre-existing: keeping is safe.
        "scaffold_preexisting": previous.get("scaffold_preexisting", scaffold_found is not None) if previous
        else scaffold_found is not None,
        "instruction_actions": actions,
        "exclude_patterns": patterns,
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    leaked = sorted(gitlocal.status_entries(target) - status_before)
    return {"target": str(target), "scaffold_found": scaffold_found, "scaffold_installed": deps["scaffold"]["version"],
            "registered": registered, "skills": skills, "instruction_files": actions, "git_status_changes": leaked}


def exclude_patterns(skills: list[str], owned_files: list[str]) -> list[str]:
    # No trailing slashes: in a linked worktree these paths are symlinks, and
    # a pattern ending in "/" matches only real directories.
    patterns = [
        f"/{BUNDLE_DIR}",
        f"/{SCAFFOLD_DIR}",
        "/.agents/.agentic-project-scaffold-lite*",
        "/.coordination",
    ]
    patterns += [f"/{root}/{name}" for name in skills for root in SKILL_ROOTS]
    patterns += [f"/{name}" for name in owned_files]
    return patterns


def _previous_manifest(target: Path) -> dict[str, Any]:
    path = target / BUNDLE_DIR / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _existing_scaffold(target: Path) -> str | None:
    """The scaffold version already in the project. Refuse anything but 1.x:
    reinstalling 1.4 over a 2.x scaffold would run old code on a newer database."""
    version_file = target / SCAFFOLD_DIR / "VERSION"
    if not version_file.is_file():
        return None
    version = version_file.read_text(encoding="utf-8").strip()
    if not version.startswith("1."):
        raise SoftoryError(f"This project already runs scaffold {version}; softory pins 1.4.0 and won't downgrade it.",
                           "scaffold_version_conflict", {"found": version})
    return version


def _install_scaffold(scaffold_src: Path, target: Path) -> None:
    """Run the scaffold's own installer, then undo its edit to .gitignore."""
    gitignore = target / ".gitignore"
    before = gitignore.read_bytes() if gitignore.exists() else None
    try:
        result = subprocess.run(  # noqa: S603 - the pinned scaffold installer
            [str(scaffold_src / "scripts" / "install.sh"), "--target", str(target),
             "--adapter", "sqlite", "--no-agents-file"],
            capture_output=True, text=True, check=False,
        )
    finally:
        if before is None:
            gitignore.unlink(missing_ok=True)
        else:
            gitignore.write_bytes(before)
    if result.returncode != 0:
        raise SoftoryError("Scaffold installer failed: " + (result.stderr or result.stdout).strip(), "scaffold_install_failed")


def _project_has_scaffold_block(target: Path, actions: dict[str, str]) -> bool:
    """True when the project's own AGENTS.md already carries the scaffold block,
    so repeating it would only cost every session extra tokens."""
    agents = target / "AGENTS.md"
    if actions.get("AGENTS.md") == "create" or not agents.exists():
        return False
    return "<!-- agentic-project-scaffold-lite:start -->" in agents.read_text(encoding="utf-8")


def _scaffold_block(scaffold_src: Path) -> str:
    text = (scaffold_src / "scaffold" / "AGENTS-sqlite.md").read_text(encoding="utf-8")
    start, end = "<!-- agentic-project-scaffold-lite:start -->", "<!-- agentic-project-scaffold-lite:end -->"
    return start + text.split(start, 1)[1].split(end, 1)[0] + end + "\n"


def _copy_bundle(source: Path, bundle: Path) -> None:
    bundle.mkdir(parents=True, exist_ok=True)
    for part in BUNDLE_PARTS:
        origin = source / part
        if origin.is_dir():
            _copy_tree(origin, bundle / part)
        elif origin.is_file():
            shutil.copy2(origin, bundle / part)
    (bundle / "bin" / "softory").chmod(0o755)


def _copy_tree(origin: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(origin, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def _check_skills(names: list[str], target: Path, previous: dict[str, Any]) -> None:
    """Refuse to overwrite skill folders softory didn't install, or tracked ones."""
    ours = set(previous.get("skills", []))
    for name in names:
        for root in SKILL_ROOTS:
            if (target / root / name).exists() and name not in ours:
                raise SoftoryError(f"{root}/{name} already exists and wasn't installed by softory", "skill_conflict")
            if gitlocal.tracked_under(target, f"{root}/{name}"):
                raise SoftoryError(f"{root}/{name} is tracked in git", "tracked_path")


def _install_skills(skills_src: Path, names: list[str], target: Path, previous: dict[str, Any]) -> None:
    """Copy each softory skill into Claude's and Codex's project skill folders."""
    ours = set(previous.get("skills", []))
    _check_skills(names, target, previous)
    for name in names:
        for root in SKILL_ROOTS:
            _copy_tree(skills_src / name, target / root / name)
    for stale in ours - set(names):  # skills removed in a newer softory
        for root in SKILL_ROOTS:
            shutil.rmtree(target / root / stale, ignore_errors=True)
