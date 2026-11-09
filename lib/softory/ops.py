"""Operator commands: roles, doctor, tracker, sync, uninstall."""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from . import SCAFFOLD_DIR, gitlocal, instructions, sessions
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
    for grant in project.stand_ins():
        scope = f" on {len(grant['tasks'])} task(s)" if grant["tasks"] else ""
        rows.append(f"{grant['agent']:<7} {'-':<7} {'stand-in for ' + ', '.join(grant['roles']) + scope:<43} {'-':<13} -")
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
    # Scaffold 1.4.1 reports the database's filesystem. A warning never fails doctor:
    # it can't tell a VM that's still attached from one that left files behind.
    report = health.get("data") or {}
    warnings = [report["filesystem_warning"]] if report.get("filesystem_warning") else []
    if report.get("filesystem_fuse_leftovers"):
        warnings.append("Leftover files beside the database: " + ", ".join(report["filesystem_fuse_leftovers"])
                        + ". Delete them only when nothing in a VM or container has the folder open.")
    warnings += _scheduler_warnings(project)
    older = _older_scaffold_block(project)
    if older:
        warnings.append(older)
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
    changed = project.integrity_changes()
    check("config_intact", not changed,
          "softory's rules, code, and local.json are as installed" if changed == []
          else "installed before integrity checks; re-run the installer" if changed is None
          else "changed since install: " + ", ".join(changed) + ". The gate fails until it's restored or reinstalled.")
    return {"pass": all(c["pass"] for c in checks), "checks": checks, "warnings": warnings, "installed_paths": paths}


def _scheduler_warnings(project: Project) -> list[str]:
    """A charter approved for unattended runs, with no runner firing, means roles only start by hand."""
    from . import charter as charters  # noqa: PLC0415 - keep doctor's import light
    from . import runner, runstate, watch  # noqa: PLC0415

    if not charters.load(project).get("approved"):
        return []
    state = runner.scheduler_state(project)
    warnings = []
    last = state["last_tick"]
    if not state["loaded"]:
        warnings.append(f"No scheduler runs softory for this project: load the launchd job ({state['label']}) with "
                        "softory setup --load-schedule. Until then roles start only when someone starts them.")
    elif last is None or (watch.parse_time(last) < datetime.now(timezone.utc) - timedelta(minutes=30)):
        warnings.append(f"The scheduler is loaded but the runner last ticked at {last or 'never'}; check run/runner.log.")
    manual = runstate.manual_starts(project)
    if manual:
        roles = sorted({row["role"] for row in manual})
        warnings.append(f"{len(manual)} session(s) in the last day started outside the runner ({', '.join(roles)}). "
                        "Turn off other schedulers for this project, such as an app's scheduled check-ins, so the "
                        "runner's budgets, caps, and run log see every run.")
    return warnings


def _installed_scaffold_block(project: Project) -> str | None:
    """The installed scaffold's AGENTS block, saved at install (None before 0.3.1)."""
    path = project.bundle / "generated" / instructions.SCAFFOLD_BLOCK_FILE
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _older_scaffold_block(project: Project) -> str | None:
    """A warning when the project's own tracked AGENTS.md carries a scaffold block that differs
    from the installed scaffold's. Codex gets the current one through AGENTS.override.md;
    Claude Code reads AGENTS.md itself, and softory never edits a tracked file."""
    current = _installed_scaffold_block(project)
    agents = project.root / "AGENTS.md"
    if not current or not agents.is_file() or not gitlocal.is_tracked(project.root, "AGENTS.md"):
        return None
    theirs = instructions.scaffold_block_of(agents.read_text(encoding="utf-8"))
    if theirs is None or theirs.strip() == current.strip():
        return None
    stale = " It still says `inbox mark-read --cursor HEAD`, which the CLI rejects." if "--cursor HEAD" in theirs else ""
    return ("AGENTS.md (tracked) has a scaffold block that differs from the installed scaffold's." + stale
            + " To update it, replace everything between the agentic-project-scaffold-lite markers with "
            f"{project.bundle.relative_to(project.root)}/generated/{instructions.SCAFFOLD_BLOCK_FILE}, "
            "commit, and run softory sync.")


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
        expected = instructions.override_text(source, body, _installed_scaffold_block(project))
        if path.read_text(encoding="utf-8") != expected:
            stale.append(name)
    return stale


def coord(project: Project, args: list[str]) -> int:
    """Run the coordination CLI from the main checkout, so it finds the database
    from any worktree. Arguments pass through unchanged, except that a command naming
    a role (``--agent`` or ``--actor``) with no session gets the session softory opened
    for that role, for harnesses whose shells drop ``COORDINATION_SESSION``."""
    os.chdir(project.root)
    binary = str(project.coordination_bin)
    _refuse_bare_handoff(project, Coordination(binary, project.root), args)
    if "--session" not in args and not os.environ.get("COORDINATION_SESSION"):
        role = next((args[i + 1] for i, a in enumerate(args[:-1]) if a in ("--agent", "--actor")), None)
        found = sessions.recall(project, role, sessions.open_check(Coordination(binary, project.root)))
        if found:
            args = ["--session", found, *args]
    os.execv(binary, [binary, *args])
    return 0  # unreachable


#: The coordination CLI's global options that take a value, and ``task release``'s.
_GLOBAL_VALUES = {"--session", "--db"}
_RELEASE_VALUES = {"--to", "--actor", "--if-revision", "--note"}


def _release_to_review(args: list[str]) -> str | None:
    """The task a ``task release ... --to review`` command moves to review, however its arguments are
    ordered or spelled (``--to review`` or ``--to=review``), or None for any other command."""
    i = 0
    while i < len(args) and args[i].startswith("-"):  # global options come before the command
        i += 1 if "=" in args[i] or args[i] not in _GLOBAL_VALUES else 2
    if args[i:i + 2] != ["task", "release"]:
        return None
    task, to, rest = None, None, args[i + 2:]
    j = 0
    while j < len(rest):
        token = rest[j]
        if token.startswith("--"):
            name, _, value = token.partition("=")
            if not _ and name in _RELEASE_VALUES:
                value = rest[j + 1] if j + 1 < len(rest) else ""
                j += 1
            if name == "--to":
                to = value
        elif task is None:
            task = token
        j += 1
    return task if to == "review" and task else None


def _refuse_bare_handoff(project: Project, coord: Coordination, args: list[str]) -> None:
    """``task release <ID> --to review`` through softory gets the same checks as ``softory handoff``."""
    from .lifecycle import ready_for_review  # noqa: PLC0415

    task_id = _release_to_review(args)
    if task_id is None:
        return
    shown = coord.call("task", "show", task_id)
    if shown.get("ok"):  # an unknown task fails in the CLI itself, with its own error
        ready_for_review(project, shown["data"])


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
    body = instructions.compose(base_file.read_text(encoding="utf-8"), project.stand_ins())
    instructions.write(project.root, actions, body, _installed_scaffold_block(project))
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
    # Agents' feedback, the run log and the verify ledger live in .coordination/softory, kept with the history.
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

