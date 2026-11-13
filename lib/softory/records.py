"""Records agents write that need more care than a raw coordination call: commits, corrections, escalations.

``softory commit`` records the commit a unit delivered by its full hash, with
its base kept apart, so verify and the gate never mistake one for the other.
``softory supersede`` retracts a wrong evidence row without deleting it: the
row and its audit stay, the reason is kept on the retraction, and softory reads past it. ``softory escalate``
raises an escalation the owner can read at a glance: one plain question, a
length limit, and no words run together.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from . import charter as charters
from . import decide, feasibility, holds as unit_holds, ops
from .coordination import Coordination
from .errors import SoftoryError
from .gitlocal import git, is_tracked
from .project import Project
from .work import actor_of

COMMANDS = ("commit", "supersede", "escalate", "answer", "settle", "feasible", "defer", "report")
ISSUE_LIMIT = 600
ASK_LIMIT = 300
REASON_LIMIT = 300
# "contain9", "runnerusage0", "atthe186": a word fused with a number reads as noise to the owner.
_HASH = re.compile(r"^[0-9a-f]{7,40}$")  # commit hashes are fine
_FUSED = re.compile(r"\b(?:[a-z]{3,}\d+[a-z]*|\d+[a-z]{4,})\b")


def add_parsers(sub: Any) -> None:
    p = sub.add_parser("commit", help="Record the commit a unit delivered, by full hash, with its base kept apart")
    p.add_argument("id")
    p.add_argument("sha")
    p.add_argument("--base", help="The commit it was built on, if reviewers need it")
    p.add_argument("--actor")
    p = sub.add_parser("report", help="File a report or other evidence file with a unit, outside the checkout, "
                                      "and record it")
    p.add_argument("id")
    p.add_argument("file", help="The file; an untracked one is moved, so the main checkout stays clean")
    p.add_argument("--type", default="report", help="Evidence type (default: report; screenshot, reference, test...)")
    p.add_argument("--keep", action="store_true", help="Copy instead of moving")
    p.add_argument("--actor")
    p = sub.add_parser("supersede", help="Retract a wrong evidence row; it stays in the audit, and softory reads past it")
    p.add_argument("id", help="The task the evidence is on")
    p.add_argument("evidence", help="The evidence row's number, from task show")
    p.add_argument("--reason", required=True)
    p.add_argument("--actor")
    p = sub.add_parser("escalate", help="Ask the owner one plain question, checked so it reads at a glance")
    p.add_argument("--issue", required=True, help=f"What happened, in plain sentences (up to {ISSUE_LIMIT} characters)")
    p.add_argument("--ask", required=True, help=f"The one question for the owner (up to {ASK_LIMIT} characters)")
    p.add_argument("--tasks", help="Related task IDs, comma-separated")
    p.add_argument("--holds", help="Units that can't move until the answer, comma-separated: they leave every "
                   "queue and wake their builders when it comes")
    p.add_argument("--recommend", required=True, help="The option you'd take, in one line")
    p.add_argument("--reversible", required=True, choices=("yes", "no"),
                   help="yes if it can be undone: then it applies after the charter's timeout with no answer")
    p.add_argument("--owner", help="Who decides; default the project owner")
    p.add_argument("--actor")
    p = sub.add_parser("defer", help="Hide a unit from every queue on the owner's decision, or --lift it")
    p.add_argument("id")
    p.add_argument("--decision", help="The owner's decision: an answer, or a ruling from softory ruling")
    p.add_argument("--until", help="Last day it stays hidden, YYYY-MM-DD (default: until lifted)")
    p.add_argument("--lift", action="store_true", help="Bring it back now")
    p.add_argument("--actor")
    p = sub.add_parser("answer", help="Answer an escalation, or replace one that defaulted (owner, at a terminal)")
    p.add_argument("id", help="The escalation")
    p.add_argument("text", help="Your answer, which the role that asked is told")
    p = sub.add_parser("feasible", help="Record a story's feasibility check: --pass, or what's missing (the check run)")
    p.add_argument("id")
    p.add_argument("--pass", dest="passed", action="store_true")
    p.add_argument("--needs", action="append", default=[], help="One thing the plan needs that the environment "
                   "doesn't declare; repeat for more")
    p.add_argument("--plan", help="The plan hash the check's prompt named")
    p.add_argument("--actor")
    p = sub.add_parser("settle", help="Settle a unit stopped at the review cap: retry, split, or drop (Quinn or owner)")
    p.add_argument("id")
    p.add_argument("action", choices=decide.ACTIONS)
    p.add_argument("--reason", required=True)
    p.add_argument("--into", help="With split: the smaller units you created, comma-separated")
    p.add_argument("--actor")


def dispatch(args: argparse.Namespace, project: Project, coord: Coordination) -> int:
    actor = actor_of(args.actor) if args.command != "answer" else ""
    if args.command == "commit":
        result = commit(project, coord, args.id, args.sha, args.base, actor)
    elif args.command == "answer":
        from .owner import confirm_at_terminal  # noqa: PLC0415

        result = decide.answer(project, coord, args.id, args.text, confirm_at_terminal)
    elif args.command == "feasible":
        result = feasibility.record(project, coord, args.id, args.passed, args.needs, actor, args.plan)
    elif args.command == "settle":
        into = [i.strip() for i in (args.into or "").split(",") if i.strip()]
        result = decide.settle(project, coord, charters.load(project), args.id, args.action, args.reason, actor, into)
    elif args.command == "defer":
        if args.lift == bool(args.decision):
            raise SoftoryError("Give --decision to defer, or --lift to bring it back", "invalid_arguments")
        result = unit_holds.lift(project, args.id, actor) if args.lift else unit_holds.defer(
            project, coord, args.id, args.decision, args.until, actor)
    elif args.command == "report":
        result = report(project, coord, args.id, Path(args.file), args.type, args.keep, actor)
    elif args.command == "supersede":
        result = supersede(project, coord, args.id, args.evidence, args.reason, actor)
    else:
        result = escalate(project, coord, args.issue, args.ask, args.tasks, args.owner, actor,
                          args.recommend, args.reversible == "yes", args.holds)
    print(ops.dumps(result), end="")
    return 0


def commit(project: Project, coord: Coordination, task_id: str, sha: str, base: str | None,
           actor: str) -> dict[str, Any]:
    head = _full(project, sha)
    uri = f"commit:{head}" + (f";base={_full(project, base)}" if base else "")
    coord.run("evidence", "add", "--task", task_id, "--uri", uri, "--type", "commit", "--actor", actor)
    return {"task": task_id, "commit": head, "uri": uri}


def evidence_folder(project: Project, task_id: str) -> Path:
    return project.state / "evidence" / task_id


def report(project: Project, coord: Coordination, task_id: str, source: Path, kind: str, keep: bool,
           actor: str) -> dict[str, Any]:
    """Put a report beside softory's state, under the unit, and record it as evidence. Tablet's main checkout
    held 66 untracked reports, which made it unsafe to review in and pushed agents into copies in /tmp."""
    coord.task(task_id)  # must exist
    source = source.expanduser().resolve()
    if not source.is_file():
        raise SoftoryError(f"{source} is not a file", "not_found")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", task_id):
        raise SoftoryError(f"{task_id} can't name a folder", "invalid_arguments")
    folder = evidence_folder(project, task_id)
    folder.mkdir(parents=True, exist_ok=True)
    inside = source.is_relative_to(project.root.resolve())
    tracked = inside and is_tracked(project.root, str(source.relative_to(project.root.resolve())))
    filed = source.is_relative_to((project.state / "evidence").resolve())  # another unit's evidence: keep it
    keep = keep or tracked or not inside or filed
    if source.parent == folder.resolve():
        target = source  # already filed: record it again, don't copy it over itself
    else:
        target = _reserve(folder, source.name)
        if keep:  # never take a tracked file, one from outside the project, or one already filed
            shutil.copy2(source, target)
        else:
            shutil.move(str(source), target)
    uri = str(target.relative_to(project.root))
    coord.run("evidence", "add", "--task", task_id, "--uri", uri, "--type", kind, "--actor", actor)
    return {"task": task_id, "uri": uri, "type": kind, "moved": not keep and target != source}


def _reserve(folder: Path, name: str) -> Path:
    """A new file in ``folder`` named after ``name``, created atomically, so no report overwrites another."""
    stem, suffix = Path(name).stem, Path(name).suffix
    for n in range(1, 10_000):
        target = folder / (name if n == 1 else f"{stem}-{n}{suffix}")
        try:
            os.close(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
            return target
        except FileExistsError:
            continue
    raise SoftoryError(f"Too many reports named {name} under {folder}", "invalid_arguments")


def _full(project: Project, sha: str) -> str:
    found = git(project.root, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
    if found.returncode != 0:
        raise SoftoryError(f"{sha} is not a commit in this repository", "not_found")
    return found.stdout.strip()


def supersede(project: Project, coord: Coordination, task_id: str, evidence_id: str, reason: str,
              actor: str) -> dict[str, Any]:
    """Only whoever added the row, Quinn, or the owner may retract it. The reason is kept on the retracting
    row, not as a decision: Tablet's corrections were 150 of its 250 decisions in four days."""
    task = coord.task(task_id)
    row = next((e for e in task.get("evidence") or [] if str(e.get("id")) == str(evidence_id)), None)
    if row is None:
        raise SoftoryError(f"{task_id} has no evidence row {evidence_id}", "not_found")
    owner = project.roster()["owner"]["id"]
    if actor not in (row.get("added_by"), "quinn", owner):
        raise SoftoryError(f"Only {row.get('added_by')}, quinn, or the owner may supersede evidence {evidence_id}",
                           "not_allowed")
    if not reason.strip():
        raise SoftoryError("Say why with --reason", "invalid_arguments")
    why = " ".join(reason.split())[:REASON_LIMIT]
    coord.run("evidence", "add", "--task", task_id, "--uri", f"softory-supersedes:{evidence_id}:{why}",
              "--type", "note", "--actor", actor)
    return {"task": task_id, "superseded": evidence_id, "reason": why,
            "note": "The row and its audit stay; the gate and verify read past it."}


def text_problems(issue: str, ask: str) -> list[str]:
    """Why an escalation would be hard for the owner to read. Empty when it reads fine."""
    problems = []
    if len(issue) > ISSUE_LIMIT:
        problems.append(f"--issue is {len(issue)} characters; keep it under {ISSUE_LIMIT} and link a file for detail")
    if len(ask) > ASK_LIMIT:
        problems.append(f"--ask is {len(ask)} characters; keep it under {ASK_LIMIT}")
    if ask.count("?") != 1:
        problems.append("--ask must be exactly one question, ending in a question mark")
    fused = sorted({w for w in _FUSED.findall(f"{issue} {ask}".lower()) if not _HASH.match(w)})
    if fused:
        problems.append(f"put spaces between words and numbers: {', '.join(fused[:5])}")
    return problems


def escalate(project: Project, coord: Coordination, issue: str, ask: str, tasks: str | None, owner: str | None,
             actor: str, recommend: str = "", reversible: bool = False, holds: str | None = None) -> dict[str, Any]:
    problems = text_problems(issue.strip(), ask.strip())
    if not recommend.strip():
        problems.append("--recommend names the option you'd take, so the work doesn't wait on the answer")
    elif len(recommend) > ASK_LIMIT:
        problems.append(f"--recommend is {len(recommend)} characters; keep it under {ASK_LIMIT}")
    if problems:
        raise SoftoryError("Rewrite the escalation so the owner can read it at a glance: " + "; ".join(problems),
                           "invalid_arguments")
    held = unit_holds.check_units(coord, [h.strip() for h in (holds or "").split(",") if h.strip()])
    asked = " ".join(ask.lower().split())
    same = next((row["id"] for row in coord.all_rows("escalation", "list", "--status", "open")
                 if " ".join(str(row.get("requested_decision") or "").lower().split()) == asked), None)
    if same:  # Tablet's owner was asked one question twice, five seconds apart
        raise SoftoryError(f"{same} already asks the owner this and is still open. Wait for its answer; send what "
                           "is new as a message on its tasks.", "conflict", {"existing": same})
    decider = owner or project.roster()["owner"]["id"]
    escalation_id = f"ESC-{actor.upper()}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    args = ["escalation", "add", "--id", escalation_id, "--raised-by", actor, "--owner", decider,
            "--issue", issue.strip(), "--requested-decision", ask.strip()]
    related = list(dict.fromkeys([t.strip() for t in (tasks or "").split(",") if t.strip()] + held))
    if related:
        args += ["--related-tasks", ",".join(related)]
    coord.run(*args)
    decide.note(project, escalation_id, recommend.strip(), reversible, actor, held)
    charter = charters.load(project)
    when = decide.due_at(decide.recommendations(project)[escalation_id], charter)
    return {"escalation": escalation_id, "owner": decider, "recommend": recommend.strip(), "holds": held,
            "defaults_at": when.isoformat(timespec="minutes") if when else None,
            "next": ("Carry on as if the recommendation applies, keeping it easy to undo." if when else
                     "It can't be undone, so it waits for the owner. Split off and carry on with work that "
                     "doesn't depend on it.")}
