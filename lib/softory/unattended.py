"""CLI for unattended runs: charter, setup, run, pause and resume, verify, digest, schedule."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from . import charter as charters
from . import digest, ops, runner, runstate, setup, verify
from .coordination import Coordination
from .owner import confirm_at_terminal
from .project import Project
from .work import actor_of

COMMANDS = ("charter", "setup", "run", "run-role", "pause", "resume", "verify", "digest", "schedule", "usage")


def add_parsers(sub: Any) -> None:
    p = sub.add_parser("charter", help="Show the charter unattended runs follow, or approve yours (owner, at a terminal)")
    charter = p.add_subparsers(dest="charter_command", required=True)
    charter.add_parser("show")
    p = charter.add_parser("approve")
    p.add_argument("file", help="A JSON file of the settings you change; everything else keeps its default")

    sub.add_parser("setup", help="The owner's one-time checklist for unattended runs, checked")
    p = sub.add_parser("run", help="One runner tick: start each role that has work, inside the budget")
    p.add_argument("--dry-run", action="store_true", help="Say who would start; start nothing and page nobody")
    p = sub.add_parser("run-role", help="Run one role once now (the runner calls this)")
    p.add_argument("role")
    p = sub.add_parser("pause", help="Stop unattended runs, for every role or one; anyone may")
    p.add_argument("--role")
    p.add_argument("--reason", default="paused")
    p.add_argument("--actor")
    p = sub.add_parser("resume", help="Start unattended runs again (owner, at a terminal)")
    p.add_argument("--role")
    p = sub.add_parser("verify", help="Run the charter's tests at a unit's commit and record the result for the gate")
    p.add_argument("id")
    p.add_argument("--commit", help="Default: the newest commit named in the unit's evidence")
    p.add_argument("--actor")
    p = sub.add_parser("digest", help="What needs the owner; --send pages it now")
    p.add_argument("--send", action="store_true")
    p = sub.add_parser("schedule", help="Write a launchd job and print a cron line for the runner")
    p.add_argument("--minutes", type=int, default=5)
    sub.add_parser("usage", help="Today's runs and minutes per role against the budget")


def dispatch(args: argparse.Namespace, project: Project, coord: Coordination) -> int:
    command = args.command
    if command == "charter":
        if args.charter_command == "show":
            result: Any = charters.load(project)
        else:
            result = charters.approve(project, coord, Path(args.file), confirm_at_terminal)
    elif command == "setup":
        result = setup.checklist(project)
    elif command == "run":
        result = runner.tick(project, coord, args.dry_run)
    elif command == "run-role":
        result = runner.run_role(project, coord, args.role)
    elif command == "pause":
        result = runstate.pause(project, args.role, args.reason, args.actor or _actor_or_owner(project))
    elif command == "resume":
        result = runstate.resume(project, args.role, confirm_at_terminal)
    elif command == "verify":
        result = verify.run(project, coord, charters.load(project), args.id, actor_of(args.actor), args.commit)
        print(ops.dumps(result), end="")
        return 0 if result["passed"] else 3
    elif command == "digest":
        charter = charters.load(project)
        result = digest.build(project, coord, charter)
        if args.send:
            result["paged"] = digest.page_due(project, coord, charter, force_digest=True)
    elif command == "schedule":
        result = runner.schedule(project, args.minutes)
    else:
        charter = charters.load(project)
        result = {role: runstate.budget(project, charter, role) for role in charter["run"]["roles"]}
    print(ops.dumps(result), end="")
    return 0


def _actor_or_owner(project: Project) -> str:
    try:
        return actor_of(None)
    except Exception:  # noqa: BLE001 - no session means the owner, at a shell
        return project.roster()["owner"]["id"]
