"""Command-line entry point: ``softory <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, external, feedback, ops, team, work, worktree
from .coordination import Coordination
from .errors import SoftoryError
from .project import Project
from .units import LANES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="softory", description="Softory software factory")
    parser.add_argument("--version", action="version", version=f"softory {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("install", help="Install softory into a git project (run from a softory checkout)")
    p.add_argument("--target", default=".", help="Project root (default: current directory)")
    p.add_argument("--owner-name", help="Display name for the human owner (agent ID 'owner')")
    p.add_argument("--scaffold-src", help="Local scaffold checkout at the pinned commit (default: clone it)")
    p.add_argument("--tracker-src", help="Local tracker checkout at the pinned commit (default: clone it)")
    p.add_argument("--allow-unpinned", action="store_true", help="Accept local checkouts not at the pinned commits")

    p = sub.add_parser("start", help="Start a session for a role; use with eval")
    p.add_argument("role")
    p.add_argument("--harness", help="claude, codex, ... (default: the role's recommendation)")
    p.add_argument("--model", default="", help="Model name to record on the session")

    p = sub.add_parser("new", help="Create an epic, story, task, or bug")
    p.add_argument("unit", choices=["epic", "story", "task", "bug"])
    p.add_argument("--title", required=True)
    p.add_argument("--parent", help="EPIC-n for a story, STORY-n for a task, either for a bug")
    p.add_argument("--lane", choices=LANES, help="Required for a task or bug")
    p.add_argument("--tags", help="Extra review tags: arch, ui, security, auth, data, deps")
    p.add_argument("--assignee", help="Default: from gates.json by unit and lane")
    p.add_argument("--priority", type=int, choices=[1, 2, 3, 4, 5])
    p.add_argument("--description", help="Default: the unit's template")
    p.add_argument("--description-file", help="Read the description from a file")
    p.add_argument("--acceptance", help="Acceptance criteria")
    p.add_argument("--actor", help="Acting role (default: $SOFTORY_ROLE)")

    p = sub.add_parser("tree", help="Show the epic > story > task hierarchy")
    p.add_argument("id", nargs="?")
    p.add_argument("--all", action="store_true", help="Also list tasks without a unit")

    p = sub.add_parser("adopt", help="Bring a task created before softory into an epic or story")
    p.add_argument("id")
    p.add_argument("--unit", choices=["story", "task", "bug"], required=True)
    p.add_argument("--parent", help="EPIC-n for a story, STORY-n for a task, either for a bug")
    p.add_argument("--lane", choices=LANES, help="Required for a task or bug")
    p.add_argument("--tags", help="Extra review tags: arch, ui, security, auth, data, deps")
    p.add_argument("--assignee", help="Reassign it to this agent (default: keep the current assignees)")
    p.add_argument("--actor", help="Acting role (default: $SOFTORY_ROLE)")

    sub.add_parser("triage", help="Open tasks that already have an accepted review (likely done, not closed)")

    p = sub.add_parser("feedback", help="Tell softory's maintainers what got in your way; --list shows the notes")
    p.add_argument("note", nargs="?", help="What happened, and what you expected")
    p.add_argument("--kind", choices=["friction", "bug", "idea"], default="friction")
    p.add_argument("--task", help="The unit you were working on")
    p.add_argument("--actor", help="Your role (default: $SOFTORY_ROLE)")
    p.add_argument("--list", action="store_true", help="Show every note recorded in this project")
    sub.add_parser("coord", help="Run the coordination CLI from the main checkout; arguments pass through")

    p = sub.add_parser("link", help="Give a git worktree softory's files, as hidden symlinks")
    p.add_argument("path", nargs="?", default=".", help="A path inside the worktree (default: current directory)")
    p.add_argument("--share", action="append", help="Also link this untracked path, e.g. .web/node_modules (repeatable)")

    p = sub.add_parser("end", help="End your coordination session")
    p.add_argument("--session", help="Default: $COORDINATION_SESSION")

    p = sub.add_parser("worktree", help="Create a git worktree with softory linked in")
    wt = p.add_subparsers(dest="worktree_command", required=True)
    p = wt.add_parser("add")
    p.add_argument("path")
    p.add_argument("-b", "--branch", help="Create this branch for it")
    p.add_argument("start", nargs="?", help="Commit or branch to start from (default: HEAD)")
    p.add_argument("--share", action="append", help="Also link this untracked path, e.g. .web/node_modules (repeatable)")

    p = sub.add_parser("standin", help="Let an existing agent act for a softory role")
    standin = p.add_subparsers(dest="standin_command", required=True)
    standin.add_parser("list")
    p = standin.add_parser("add")
    p.add_argument("agent")
    p.add_argument("--for", dest="roles", required=True, help="Comma-separated role IDs, e.g. jade,gold")
    p.add_argument("--actor", default="owner", help="Who decides (default: owner)")
    p = standin.add_parser("remove")
    p.add_argument("agent")
    p.add_argument("--actor", default="owner", help="Who decides (default: owner)")

    p = sub.add_parser("gate", help="Check whether a unit may move to done")
    p.add_argument("id")
    p.add_argument("--actor", help="Who intends to close it (default: $SOFTORY_ROLE)")

    p = sub.add_parser("close", help="Run the gate and move the unit to done only if it passes")
    p.add_argument("id")
    p.add_argument("--actor", help="Who is closing it (default: $SOFTORY_ROLE)")

    p = sub.add_parser("reviewers", help="Who must review a unit, and where each review stands")
    p.add_argument("id")

    p = sub.add_parser("queue", help="Your claimed work, waiting reviews, and assigned work")
    p.add_argument("--agent", help="Default: $SOFTORY_ROLE")

    sub.add_parser("roles", help="List the roles and their recommended harnesses")
    sub.add_parser("doctor", help="Check the installation, registration, and that nothing leaks into git")
    sub.add_parser("tracker", help="Run the tracker web console; options after it go to the console (--port, --open)")
    sub.add_parser("sync", help="Rewrite the instruction files (after AGENTS.md changes)")

    p = sub.add_parser("skills", help="List or add recommended open-source skills")
    skills = p.add_subparsers(dest="skills_command", required=True)
    skills.add_parser("list")
    p = skills.add_parser("add")
    p.add_argument("names", nargs="*")
    p.add_argument("--recommended", action="store_true", help="Add every recommended skill")

    p = sub.add_parser("uninstall", help="Remove softory (keeps .coordination unless --purge)")
    p.add_argument("--purge", action="store_true", help="Also delete the coordination database")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["tracker"], ["coord"]) and not {"-h", "--help"} & set(argv[1:2]):
        # Everything after the command belongs to the program it runs, flags included.
        try:
            runner = ops.tracker if argv[0] == "tracker" else ops.coord
            return runner(Project.find(), argv[1:])
        except SoftoryError as error:
            print(json.dumps({"ok": False, "error": {"code": error.code, "message": error.message}}), file=sys.stderr)
            return 1
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except SoftoryError as error:
        print(json.dumps({"ok": False, "error": {"code": error.code, "message": error.message, "details": error.details}}, indent=2), file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "install":
        from .install import install

        source = Path(__file__).resolve().parents[2]
        result = install(source, Path(args.target), vars(args))
        print(ops.dumps(result), end="")
        return 0 if not result["git_status_changes"] else 2

    project = Project.find()
    coord = Coordination(project.coordination_bin, project.root)
    if args.command == "start":
        print(work.start(project, coord, args.role, args.harness, args.model), end="")
    elif args.command == "new":
        options = vars(args).copy()
        if args.description_file:
            options["description"] = Path(args.description_file).read_text(encoding="utf-8")
        print(ops.dumps(work.new_unit(project, coord, args.unit, options)), end="")
    elif args.command == "tree":
        print(work.tree(project, coord, args.id, args.all), end="")
    elif args.command == "adopt":
        options = dict(vars(args), actor=work.actor_of(args.actor))
        print(ops.dumps(team.adopt(project, coord, args.id, args.unit, options)), end="")
    elif args.command == "end":
        print(ops.dumps(work.end(coord, args.session)), end="")
    elif args.command == "feedback":
        result = {"notes": feedback.entries(project)} if args.list else feedback.add(
            project, args.note or "", args.kind, args.task, args.actor)
        print(ops.dumps(result), end="")
    elif args.command == "triage":
        print(ops.dumps(team.triage(project, coord)), end="")
    elif args.command == "link":
        result = worktree.link(project, Path(args.path).resolve(), args.share)
        print(ops.dumps(result), end="")
        return 0 if not result["git_status_changes"] else 2
    elif args.command == "worktree":
        result = worktree.add(project, Path(args.path).resolve(), args.branch, args.start, args.share)
        print(ops.dumps(result), end="")
        return 0 if not result["git_status_changes"] else 2
    elif args.command == "standin":
        if args.standin_command == "list":
            print(ops.dumps(team.stand_ins(project)), end="")
        elif args.standin_command == "add":
            roles = [r.strip() for r in args.roles.split(",") if r.strip()]
            print(ops.dumps(team.add_stand_in(project, coord, args.agent, roles, args.actor)), end="")
        else:
            print(ops.dumps(team.remove_stand_in(project, coord, args.agent, args.actor)), end="")
    elif args.command == "gate":
        result = work.gate(project, coord, args.id, args.actor)
        print(ops.dumps(result), end="")
        return 0 if result["pass"] else 3
    elif args.command == "close":
        result = work.close(project, coord, args.id, args.actor)
        print(ops.dumps(result), end="")
        return 0 if result["closed"] else 3
    elif args.command == "reviewers":
        print(ops.dumps(work.reviewers(project, coord, args.id)), end="")
    elif args.command == "queue":
        print(ops.dumps(work.queue(project, coord, args.agent)), end="")
    elif args.command == "roles":
        print(ops.roles_table(project), end="")
    elif args.command == "doctor":
        result = ops.doctor(project, coord)
        print(ops.dumps(result), end="")
        return 0 if result["pass"] else 3
    elif args.command == "sync":
        print(ops.dumps({"regenerated": ops.sync(project)}), end="")
    elif args.command == "skills":
        if args.skills_command == "list":
            print(external.listing(project), end="")
        else:
            print(ops.dumps({"added": external.add(project, args.names, args.recommended)}), end="")
    elif args.command == "uninstall":
        print(ops.dumps(ops.uninstall(project, args.purge)), end="")
    return 0
