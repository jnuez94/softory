"""Install softory, scaffold 1.4.1, and the tracker into a project, hidden from git."""

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
from .project import PROTECTED_DIRS, Project, integrity_hashes, make_read_only, write_protected
from .registration import register_roster
from .sources import fetch_sources, version_tuple

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
    deps = json.loads((source / "dependencies.json").read_text(encoding="utf-8"))
    scaffold_found = _existing_scaffold(target, deps["scaffold"]["version"])
    status_before = gitlocal.status_entries(target)

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
        owner = json.loads((source / "factory" / "roles" / "roster.json").read_text(encoding="utf-8"))["owner"]["id"]
        backup = _backup_before_upgrade(target, scaffold_found, deps["scaffold"]["version"], owner)
        _install_scaffold(scaffold_src, target)
        bundle = target / BUNDLE_DIR
        _copy_bundle(source, bundle)
        _copy_tree(tracker_src / "coordination_ui", bundle / "tracker" / "coordination_ui")
        shutil.copy2(tracker_src / "LICENSE", bundle / "tracker" / "LICENSE")
        scaffold_block = _scaffold_block(scaffold_src)

    _install_skills(source / "skills", skills, target, previous)
    softory_text = (source / "factory" / "INSTRUCTIONS.md").read_text(encoding="utf-8")
    # Softory's rules and operating loop already cover the scaffold's block, so it isn't repeated.
    base = softory_text
    body = instructions.compose(base, Project(target).stand_ins())
    instructions.write(target, actions, body, scaffold_block)
    (bundle / "generated").mkdir(exist_ok=True)
    (bundle / "generated" / instructions.SCAFFOLD_BLOCK_FILE).write_text(scaffold_block, encoding="utf-8")
    (bundle / "generated" / "base.md").write_text(base, encoding="utf-8")
    (bundle / "generated" / "instructions.md").write_text(body, encoding="utf-8")

    coord = Coordination(target / COORDINATION_BIN, target)
    roster = json.loads((source / "factory" / "roles" / "roster.json").read_text(encoding="utf-8"))
    registered = register_roster(coord, roster, options)
    gitlocal.write_exclude_block(target, patterns)
    manifest = {
        "softory_version": __version__,
        "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # Triage flags work closed outside softory since this moment, so it survives upgrades.
        "first_installed_at": previous.get("first_installed_at") or previous.get("installed_at")
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
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
        # The owner runs the installer, so what it finds is what the gate trusts.
        "integrity": _protect(bundle),
    }
    write_protected(bundle / "manifest.json", json.dumps(manifest, indent=2) + "\n")

    leaked = sorted(gitlocal.status_entries(target) - status_before)
    return {"target": str(target), "scaffold_found": scaffold_found, "scaffold_installed": deps["scaffold"]["version"],
            "scaffold_backup": backup, "registered": registered, "skills": skills, "instruction_files": actions, "git_status_changes": leaked}


def _protect(bundle: Path) -> dict[str, str]:
    """Make softory's rules, code, and local.json read-only, and return their hashes."""
    for folder in PROTECTED_DIRS:
        for path in (bundle / folder).rglob("*"):
            if path.is_file():
                make_read_only(path)
    if (bundle / "local.json").is_file():
        make_read_only(bundle / "local.json")
    return integrity_hashes(bundle)


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


def _existing_scaffold(target: Path, pinned: str) -> str | None:
    """The scaffold version already in the project. Refuse one newer than the pin:
    reinstalling would run older code on a database a newer CLI has used."""
    version_file = target / SCAFFOLD_DIR / "VERSION"
    if not version_file.is_file():
        return None
    version = version_file.read_text(encoding="utf-8").strip()
    if version_tuple(version) > version_tuple(pinned):
        raise SoftoryError(f"This project already runs scaffold {version}; softory pins {pinned} and won't downgrade it.",
                           "scaffold_version_conflict", {"found": version})
    return version


def _backup_before_upgrade(target: Path, found: str | None, pinned: str, owner: str) -> str | None:
    """Back up the database with the project's current CLI before replacing that CLI,
    as the scaffold's upgrade guide asks. Same version or a fresh project: no backup.
    The copy is audited under the owner, who runs the installer, once the owner is registered."""
    if not found or version_tuple(found) >= version_tuple(pinned) or not (target / ".coordination" / "config.yml").is_file():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = target / ".coordination" / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / f"pre-scaffold-{pinned}-{stamp}.sqlite3"
    coord = Coordination(target / COORDINATION_BIN, target)
    actor = ["--actor", owner] if coord.agent_exists(owner) else []
    try:
        coord.run("backup", "--output", str(output), *actor)
    except SoftoryError as error:
        raise SoftoryError(f"Couldn't back up the database before upgrading scaffold {found} to {pinned}: "
                           f"{error.message}. The scaffold was left as it was.", "backup_failed") from error
    return str(output)


def _install_scaffold(scaffold_src: Path, target: Path) -> None:
    """Run the scaffold's own installer. ``--no-gitignore`` (1.4.1) keeps it off the
    tracked .gitignore; softory hides everything through .git/info/exclude instead."""
    result = subprocess.run(  # noqa: S603 - the pinned scaffold installer
        [str(scaffold_src / "scripts" / "install.sh"), "--target", str(target),
         "--adapter", "sqlite", "--no-agents-file", "--no-gitignore"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SoftoryError("Scaffold installer failed: " + (result.stderr or result.stdout).strip(), "scaffold_install_failed")


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
