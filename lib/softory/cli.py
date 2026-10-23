"""Command-line entry point: ``softory <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, external, feedback, lifecycle, messages, ops, owner, team, watch, work, worktree
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

    p = sub.add_parser("new", help="Create an epic, story, task, bug, or review")
    p.add_argument("unit", choices=["epic", "story", "task", "bug", "review"])
    p.add_argument("--title", required=True)
    p.add_argument("--parent", help="EPIC-n for a story, STORY-n for a task, either for a bug")
    p.add_argument("--from", dest="from", metavar="ID",
                   help="File a follow-up from this task: inherits its story and lane, and links back to it")
    p.add_argument("--blocks-source", action="store_true",
                   help="With --from: the source can't close until this follow-up does (default: it can)")
    p.add_argument("--for", dest="for", metavar="IDS", help="A review's reviewed tasks, comma-separated")
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

    p = sub.add_parser("adopt", help="Bring a task created before softory into an epic or story, or ask the owner "
                                     "to mark it a review record")
    p.add_argument("id")
    p.add_argument("--unit", choices=["story", "task", "bug", "review"], required=True)
    p.add_argument("--for", dest="for", metavar="IDS",
                   help="For a review: the tasks it reviewed, comma-separated (default: the tasks it informs on)")
    p.add_argument("--parent", help="EPIC-n for a story, STORY-n for a task, either for a bug")
    p.add_argument("--lane", choices=LANES, help="Required for a task or bug")
    p.add_argument("--tags", help="Extra review tags: arch, ui, security, auth, data, deps")
    p.add_argument("--assignee", help="Reassign it to this agent (default: keep the current assignees)")
    p.add_argument("--actor", help="Acting role (default: $SOFTORY_ROLE)")

    sub.add_parser("triage", help="Finished work left open, review runs to adopt, and stale sessions")

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

    p = sub.add_parser("standin", help="Let an existing agent act for a softory role (owner only, at a terminal)")
    standin = p.add_subparsers(dest="standin_command", required=True)
    standin.add_parser("list")
    p = standin.add_parser("add")
    p.add_argument("agent")
    p.add_argument("--for", dest="roles", required=True, help="Comma-separated role IDs, e.g. jade,gold")
    p.add_argument("--task", dest="tasks", help="Only on these tasks, comma-separated (default: everywhere)")
    p.add_argument("--until", help="Last day it applies, YYYY-MM-DD (default: no end)")
    p = standin.add_parser("remove")
    p.add_argument("agent")
    p.add_argument("--for", dest="roles", help="Only these roles, comma-separated (default: all of them)")

    p = sub.add_parser("propose", help="Ask the owner for a stand-in or a waiver; nothing changes until they approve")
    propose = p.add_subparsers(dest="propose_command", required=True)
    p = propose.add_parser("standin")
    p.add_argument("agent")
    p.add_argument("--for", dest="roles", required=True, help="Comma-separated role IDs")
    p.add_argument("--task", dest="tasks", help="Only on these tasks, comma-separated")
    p.add_argument("--until", help="Last day it applies, YYYY-MM-DD")
    p.add_argument("--why", required=True, help="What the owner should know before approving")
    p.add_argument("--actor", help="Who proposes (default: $SOFTORY_ROLE)")
    p = propose.add_parser("waiver")
    p.add_argument("id", help="The task")
    p.add_argument("--check", required=True, help="The gate check to waive, e.g. review:tag:security")
    p.add_argument("--why", required=True, help="Why it should close without that check")
    p.add_argument("--actor", help="Who proposes (default: $SOFTORY_ROLE)")

    p = sub.add_parser("proposals", help="List proposals waiting for the owner")
    p.add_argument("--all", action="store_true", help="Include approved and rejected ones")

    p = sub.add_parser("approve", help="Apply proposals (owner only, at a terminal)")
    p.add_argument("proposal", nargs="?", help="PROP-n, or several comma-separated")
    p.add_argument("--all", dest="every", action="store_true",
                   help="Every waiting review adoption, after one yes (stand-ins and waivers go by ID)")
    p.add_argument("--reject", action="store_true", help="Reject them instead")

    p = sub.add_parser("ruling", help="Record a decision the owner made, under the owner's name, marked recorded by you")
    p.add_argument("--title", required=True)
    p.add_argument("--decision", required=True, help="What the owner decided")
    p.add_argument("--where", required=True, help="Where the owner said it: a thread, message, or date")
    p.add_argument("--context", help="Background")
    p.add_argument("--actor", help="Who records it (default: $SOFTORY_ROLE)")

    p = sub.add_parser("drop", help="Close a unit nobody will build, as won't do or superseded")
    p.add_argument("id")
    p.add_argument("--reason", required=True)
    p.add_argument("--superseded-by", metavar="ID", help="The unit that replaces it")
    p.add_argument("--actor", help="Who drops it (default: $SOFTORY_ROLE)")

    p = sub.add_parser("stack", help="Group work built on top of other work, bottom first, to close together")
    p.add_argument("ids", nargs="+", metavar="ID")
    p.add_argument("--actor", help="Default: $SOFTORY_ROLE")

    p = sub.add_parser("gate", help="Check whether a unit may move to done")
    p.add_argument("id")
    p.add_argument("--actor", help="Who intends to close it (default: $SOFTORY_ROLE)")

    p = sub.add_parser("close", help="Run the gate and move the unit to done only if it passes")
    p.add_argument("id")
    p.add_argument("--stack", action="store_true", help="Close the unit's whole stack together, or none of it")
    p.add_argument("--actor", help="Who is closing it (default: $SOFTORY_ROLE)")

    p = sub.add_parser("reviewers", help="Who must review a unit, and where each review stands")
    p.add_argument("id")

    p = sub.add_parser("queue", help="Your claimed work, what you may close now, waiting reviews, and assigned work")
    p.add_argument("--agent", help="Default: $SOFTORY_ROLE")

    p = sub.add_parser("pending", help="Exit 0 if a role has work waiting, 3 if not; for schedulers, starts nothing")
    p.add_argument("agent", nargs="?", help="Default: $SOFTORY_ROLE")
    p.add_argument("--since", help="Count work changed after this time (default: the role's last finished session)")
    p.add_argument("--retry-hours", type=float, default=4.0,
                   help="Count any waiting work once this long passes without a run (default 4; 0 turns it off)")

    p = sub.add_parser("silent", help="Exit 0 if a role has work waiting and no session for --hours; 3 if none")
    p.add_argument("--hours", type=float, default=12.0)
    p.add_argument("--notify", action="store_true", help="Message the owner, once a day per silent role")
    p.add_argument("--sender", default="owner", help="Who the message is from (default: owner)")

    p = sub.add_parser("inbox", help="Your unread messages, and the number to mark them read with")
    p.add_argument("--agent", help="Default: $SOFTORY_ROLE")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--mark-read", type=int, metavar="N", help="Mark read through N, the read_through of a listing")

    p = sub.add_parser("message", help="Show one message by its ID")
    p.add_argument("id")
    sub.add_parser("all", help="Run a coordination list command and follow every page, e.g. softory all task list")

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
    if argv[:1] in (["tracker"], ["coord"], ["all"]) and not {"-h", "--help"} & set(argv[1:2]):
        # Everything after the command belongs to the program it runs, flags included.
        try:
            if argv[0] == "all":
                project = Project.find()
                rows = messages.all_rows(Coordination(project.coordination_bin, project.root), argv[1:])
                print(ops.dumps(rows), end="")
                return 0
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


def _split(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


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
            print(ops.dumps(owner.stand_in_rows(project)), end="")
        elif args.standin_command == "add":
            result = owner.add_stand_in(project, coord, args.agent, _split(args.roles), _split(args.tasks), args.until)
            print(ops.dumps(result), end="")
        else:
            print(ops.dumps(owner.remove_stand_in(project, coord, args.agent, _split(args.roles) or None)), end="")
    elif args.command == "propose":
        actor = work.actor_of(args.actor)
        if args.propose_command == "standin":
            change = {"agent": args.agent, "roles": _split(args.roles), "tasks": _split(args.tasks), "until": args.until}
        else:
            change = {"task": args.id, "check": args.check}
        print(ops.dumps(owner.propose(project, coord, args.propose_command, change, args.why, actor)), end="")
    elif args.command == "proposals":
        print(ops.dumps(owner.proposals(project, args.all)), end="")
    elif args.command == "approve":
        print(ops.dumps(owner.approve(project, coord, _split(args.proposal), args.reject, args.every)), end="")
    elif args.command == "ruling":
        actor = work.actor_of(args.actor)
        result = owner.ruling(project, coord, args.title, args.decision, args.where, args.context, actor)
        print(ops.dumps(result), end="")
    elif args.command == "drop":
        result = lifecycle.drop(project, coord, args.id, args.reason, args.superseded_by, work.actor_of(args.actor))
        print(ops.dumps(result), end="")
    elif args.command == "stack":
        print(ops.dumps(lifecycle.stack(project, coord, args.ids, work.actor_of(args.actor))), end="")
    elif args.command == "gate":
        result = work.gate(project, coord, args.id, args.actor)
        print(ops.dumps(result), end="")
        return 0 if result["pass"] else 3
    elif args.command == "close":
        result = work.close(project, coord, args.id, args.actor, args.stack)
        print(ops.dumps(result), end="")
        return 0 if result["closed"] else 3
    elif args.command == "reviewers":
        print(ops.dumps(work.reviewers(project, coord, args.id)), end="")
    elif args.command == "queue":
        print(ops.dumps(work.queue(project, coord, args.agent)), end="")
    elif args.command == "pending":
        result = watch.pending(project, coord, args.agent, args.since, args.retry_hours)
        print(ops.dumps(result), end="")
        return 0 if result["pending"] else 3
    elif args.command == "silent":
        result = watch.silent(project, coord, args.hours, args.notify, args.sender)
        print(ops.dumps(result), end="")
        return 0 if result["silent"] else 3
    elif args.command == "inbox":
        print(ops.dumps(messages.inbox(coord, args.agent, args.limit, args.mark_read)), end="")
    elif args.command == "message":
        print(ops.dumps(messages.message(coord, args.id)), end="")
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
