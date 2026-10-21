"""Operator commands: roles, doctor, tracker, sync, uninstall."""

from __future__ import annotations

import json
import os
import shutil
import sys
from typing import Any

from . import SCAFFOLD_DIR, gitlocal, instructions
from .coordination import Coordination
from .install import SKILL_ROOTS
from .project import Project


def roles_table(project: Project) -> str:
    roster = project.roster()
    rows = ["ID      NAME    ROLE                                        LANE          HARNESS"]
    for role in roster["roles"]:
        rows.append(f"{role['id']:<7} {role['name']:<7} {role['title']:<43} {role['lane']:<13} {role['recommended_harness']}")
    owner = roster["owner"]
    rows.append(f"{owner['id']:<7} {'(you)':<7} {owner['title']:<43} {'-':<13} -")
    for agent, roles in sorted(project.local().get("stand_ins", {}).items()):
        rows.append(f"{agent:<7} {'-':<7} {'stand-in for ' + ', '.join(roles):<43} {'-':<13} -")
    return "\n".join(rows) + "\n"


def installed_paths(project: Project) -> list[str]:
    manifest = project.manifest()
    return [pattern.strip("/") for pattern in manifest["exclude_patterns"] if "*" not in pattern]


def doctor(project: Project, coord: Coordination) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "pass": bool(passed), "detail": detail})

    version = coord.call("version")
    cli = (version.get("data") or {}).get("cli_version", "missing")
    check("coordination_cli", str(cli).startswith("1."), f"CLI {cli} (tracker needs >=1.4.0,<2.0.0)")
    health = coord.call("doctor")
    check("coordination_doctor", bool(health.get("ok")), "database healthy" if health.get("ok") else str(health.get("error")))
    check("tracker", (project.bundle / "tracker" / "coordination_ui" / "__main__.py").is_file(), "tracker console present")
    missing = [r for r in project.role_ids() if not coord.agent_exists(r)]
    check("roles_registered", not missing, "missing: " + ", ".join(missing) if missing else "all roles registered")
    expected = project.manifest()["exclude_patterns"]
    present = gitlocal.read_exclude_block(project.root)
    check("exclude_block", present == expected, "info/exclude block matches" if present == expected else "info/exclude block drifted; re-run the installer")
    stale = _stale_instruction_files(project)
    check("instructions_in_sync", not stale, "instruction files match" if not stale else "out of date: " + ", ".join(stale) + "; run softory sync")
    paths = installed_paths(project)
    visible = sorted(e for e in gitlocal.status_entries(project.root) if any(e[3:].startswith(p) for p in paths))
    check("hidden_from_git", not visible, "nothing softory installed shows in git status" if not visible else "visible: " + ", ".join(visible))
    tracked = [p for p in paths if gitlocal.tracked_under(project.root, p)]
    check("not_tracked", not tracked, "no installed path is tracked" if not tracked else "tracked: " + ", ".join(tracked))
    return {"pass": all(c["pass"] for c in checks), "checks": checks, "installed_paths": paths}


def _stale_instruction_files(project: Project) -> list[str]:
    """Instruction files that no longer match what sync would write, such as an
    AGENTS.override.md copied from an AGENTS.md that has since changed."""
    body = (project.bundle / "generated" / "instructions.md").read_text(encoding="utf-8")
    stale = []
    for name, action in project.manifest()["instruction_actions"].items():
        path = project.root / name
        if action != "override" or not path.is_file():
            continue
        source = (project.root / "AGENTS.md").read_text(encoding="utf-8")
        expected = instructions.OVERRIDE_HEADER + instructions.upsert_block(source, instructions.managed_block(body))
        if path.read_text(encoding="utf-8") != expected:
            stale.append(name)
    return stale


def coord(project: Project, args: list[str]) -> int:
    """Run the coordination CLI from the main checkout, so it finds the database
    from any worktree. Arguments pass through unchanged."""
    os.chdir(project.root)
    binary = str(project.coordination_bin)
    os.execv(binary, [binary, *args])
    return 0  # unreachable


def tracker(project: Project, args: list[str]) -> int:
    """Run the tracker console from the bundle, against this project's database."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(project.bundle / "tracker") + os.pathsep + env.get("PYTHONPATH", "")
    os.chdir(project.root)
    os.execvpe(sys.executable, [sys.executable, "-m", "coordination_ui", *args], env)
    return 0  # unreachable


def sync(project: Project) -> list[str]:
    """Rewrite the instruction files: after AGENTS.md changes, or stand-ins change."""
    actions = project.manifest()["instruction_actions"]
    generated = project.bundle / "generated"
    base_file = generated / "base.md" if (generated / "base.md").is_file() else generated / "instructions.md"
    body = instructions.compose(base_file.read_text(encoding="utf-8"), project.local().get("stand_ins", {}))
    instructions.write(project.root, actions, body)
    (generated / "instructions.md").write_text(body, encoding="utf-8")
    return sorted(actions)


def uninstall(project: Project, purge: bool) -> dict[str, Any]:
    """Remove everything softory installed. Keeps .coordination unless purge."""
    root = project.root
    manifest = project.manifest()
    removed: list[str] = []
    for name in manifest.get("skills", []) + manifest.get("external_skills", []):
        for skill_root in SKILL_ROOTS:
            path = root / skill_root / name
            if path.exists():
                shutil.rmtree(path)
                removed.append(f"{skill_root}/{name}")
    owned = set(manifest.get("owned_files", []))
    for name, action in manifest.get("instruction_actions", {}).items():
        path = root / name
        if not path.exists():
            continue
        if name in owned:
            path.unlink()
        else:
            path.write_text(instructions.remove_block(path.read_text(encoding="utf-8")), encoding="utf-8")
        removed.append(name)
    notes = project.bundle / "feedback.jsonl"
    if notes.is_file() and not purge and (root / ".coordination").is_dir():
        shutil.move(str(notes), root / ".coordination" / "softory-feedback.jsonl")  # keep agents' notes with the history
    keep_scaffold = manifest.get("scaffold_preexisting", True)
    for directory in ([] if keep_scaffold else [SCAFFOLD_DIR]) + [".agents/softory"]:
        shutil.rmtree(root / directory, ignore_errors=True)
        removed.append(directory)
    for leftover in [] if keep_scaffold else (root / ".agents").glob(".agentic-project-scaffold-lite*"):
        if leftover.is_dir():
            shutil.rmtree(leftover, ignore_errors=True)
        else:
            leftover.unlink()
    for empty in (".agents/skills", ".claude/skills", ".agents", ".claude"):
        path = root / empty
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    if purge:
        shutil.rmtree(root / ".coordination", ignore_errors=True)
        removed.append(".coordination")
    hidden = ([] if purge else ["/.coordination/"]) + ([f"/{SCAFFOLD_DIR}/"] if keep_scaffold else [])
    gitlocal.write_exclude_block(root, hidden)
    kept = ([] if purge else [".coordination (your coordination history)"])
    kept += [f"{SCAFFOLD_DIR} (it was here before softory)"] if keep_scaffold else []
    return {"removed": removed, "kept": kept}


def dumps(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=False) + "\n"

