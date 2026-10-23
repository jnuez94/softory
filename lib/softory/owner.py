"""The owner's changes: stand-ins, waivers, review adoptions, proposals, and rulings recorded for the owner.

Stand-ins and waivers change who and what the gate accepts, and adopting an
older task as a review record lets it close on its author's own verdict, so
only the owner makes them, at a terminal: ``softory standin add`` and ``softory
approve`` ask for a typed "yes" and refuse to run without one. An agent's
shell has no terminal, so agents propose instead (``softory propose``),
which records the request and grants nothing until the owner approves it.

This is a speed bump, not a lock: an agent that fakes a terminal, or edits
the read-only files, is working around the owner on purpose, and the gate's
``config_intact`` check and ``softory doctor`` show the edit.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timezone
from typing import Any, Callable

from . import grants, ops
from .coordination import Coordination
from .errors import SoftoryError
from .project import Project

Confirm = Callable[[str], None]


def confirm_at_terminal(summary: str) -> None:
    """Show the change and require the owner to type yes at a terminal."""
    if not sys.stdin.isatty():
        raise SoftoryError(
            "Only the owner can make this change, at a terminal. Agents: ask for it with softory propose; "
            "the owner then runs softory approve.",
            "owner_terminal_required",
        )
    print(summary, file=sys.stderr)
    print("Type yes to approve: ", end="", file=sys.stderr, flush=True)
    if sys.stdin.readline().strip().lower() != "yes":
        raise SoftoryError("Not approved. Nothing changed.", "not_approved")


# ---- stand-ins ---------------------------------------------------------------------------------

def stand_in_rows(project: Project) -> list[dict[str, Any]]:
    return [{**grant, "active": grants.is_active(grant)} for grant in project.stand_ins()]


def _checked_grant(project: Project, coord: Coordination, agent: str, roles: list[str], tasks: list[str],
                   until: str | None) -> dict[str, Any]:
    known = {role["id"] for role in project.roster()["roles"]}
    unknown = sorted(set(roles) - known)
    if not roles or unknown:
        raise SoftoryError(f"Unknown role(s): {', '.join(unknown) or '(none given)'}. Roles: {', '.join(sorted(known))}",
                           "invalid_arguments")
    if agent in roles:
        raise SoftoryError(f"{agent} cannot stand in for itself", "invalid_arguments")
    if not coord.agent_exists(agent):
        raise SoftoryError(f"Agent {agent!r} is not registered in the coordination database", "not_found")
    for task_id in tasks:
        coord.task(task_id)  # must exist
    if until is not None:
        try:
            ends = date.fromisoformat(until)
        except ValueError as error:
            raise SoftoryError("--until takes a date: YYYY-MM-DD", "invalid_arguments") from error
        if ends.isoformat() < grants.today():
            raise SoftoryError(f"{until} has already passed", "invalid_arguments")
    return {"agent": agent, "roles": sorted(set(roles)), "tasks": sorted(set(tasks)), "until": until, "decision": None}


def add_stand_in(project: Project, coord: Coordination, agent: str, roles: list[str], tasks: list[str],
                 until: str | None, confirm: Confirm = confirm_at_terminal) -> dict[str, Any]:
    """Let ``agent`` review and close wherever ``roles`` may: everywhere, or on ``tasks`` only, until ``until``."""
    grant = _checked_grant(project, coord, agent, roles, tasks, until)
    confirm(f"Stand-in: {grants.describe(grant)}")
    return _apply_grant(project, coord, grant, None)


def _apply_grant(project: Project, coord: Coordination, grant: dict[str, Any], decision: str | None) -> dict[str, Any]:
    owner = project.roster()["owner"]["id"]
    if decision is None:
        decision = record_decision(coord, owner, "STANDIN", f"{grant['agent']} stands in for {', '.join(grant['roles'])}",
                                   grants.describe(grant).replace("`", ""),
                                   "The owner named a stand-in under softory's flex rule (boundaries.md).")
    grant = {**grant, "decision": decision}
    settings = project.local()
    settings["stand_ins"] = [*grants.normalize_stand_ins(settings.get("stand_ins")), grant]
    project.save_local(settings)
    return {"granted": grant, "decision": decision, "regenerated": ops.sync(project)}


def remove_stand_in(project: Project, coord: Coordination, agent: str, roles: list[str] | None,
                    confirm: Confirm = confirm_at_terminal) -> dict[str, Any]:
    """Take ``roles`` (default: all) away from ``agent``'s grants."""
    settings = project.local()
    current = grants.normalize_stand_ins(settings.get("stand_ins"))
    theirs = [g for g in current if g["agent"] == agent]
    if not theirs:
        raise SoftoryError(f"{agent} is not a stand-in", "not_found")
    dropping = set(roles or [r for g in theirs for r in g["roles"]])
    confirm(f"Stop {agent} standing in for {', '.join(sorted(dropping))}")
    kept = []
    for grant in current:
        if grant["agent"] == agent:
            grant = {**grant, "roles": [r for r in grant["roles"] if r not in dropping]}
            if not grant["roles"]:
                continue
        kept.append(grant)
    owner = project.roster()["owner"]["id"]
    decision = record_decision(coord, owner, "STANDIN", f"{agent} no longer stands in for {', '.join(sorted(dropping))}",
                               f"{agent} stops acting for {', '.join(sorted(dropping))}.",
                               "The owner removed a stand-in.")
    settings["stand_ins"] = kept
    project.save_local(settings)
    return {"removed": {"agent": agent, "roles": sorted(dropping)}, "decision": decision, "regenerated": ops.sync(project)}


# ---- proposals and approval ----------------------------------------------------------------------

def _load_proposals(project: Project) -> list[dict[str, Any]]:
    path = project.proposals_path()
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save_proposals(project: Project, proposals: list[dict[str, Any]]) -> None:
    project.proposals_path().write_text(json.dumps(proposals, indent=2) + "\n", encoding="utf-8")


def proposals(project: Project, show_all: bool = False) -> list[dict[str, Any]]:
    rows = _load_proposals(project)
    return rows if show_all else [p for p in rows if p["status"] == "open"]


def propose(project: Project, coord: Coordination, kind: str, change: dict[str, Any], why: str,
            actor: str) -> dict[str, Any]:
    """Ask the owner for a stand-in or a waiver. Grants nothing until ``softory approve``."""
    if not why.strip():
        raise SoftoryError("Say why with --why: the owner reads it before approving", "invalid_arguments")
    if kind == "standin":
        checked = _checked_grant(project, coord, change["agent"], change["roles"], change.get("tasks") or [],
                                 change.get("until"))
        title = grants.describe(checked).replace("`", "")
    elif kind == "waiver":
        checked = _checked_waiver(project, coord, change["task"], change["check"], why)
        title = f"Waive {checked['check']} on {checked['task']}"
    else:
        raise SoftoryError(f"Unknown proposal kind {kind!r}", "invalid_arguments")
    existing = _load_proposals(project)
    proposal_id = _next_id(existing)
    owner = project.roster()["owner"]["id"]
    session = os.environ.get("COORDINATION_SESSION") or "no session"
    decision = record_decision(coord, owner, "PROP", f"Proposed by {actor}: {title}", title,
                               f"Proposed by {actor} ({session}): {why}. Waiting for the owner's softory approve {proposal_id}.",
                               status="proposed")
    proposal = {"id": proposal_id, "kind": kind, "change": checked, "why": why, "proposed_by": actor,
                "session": session, "created_at": _now(), "decision": decision, "status": "open"}
    _save_proposals(project, [*existing, proposal])
    return {"proposal": proposal_id, "decision": decision,
            "next": f"Tell the owner: softory approve {proposal_id} (run it in a terminal). Nothing changes until then."}


def request_adoption(project: Project, coord: Coordination, task_id: str, targets: list[str], skipped: list[str],
                     actor: str, looks_like_review: bool = True) -> dict[str, Any]:
    """Ask the owner to let an older task close as a review record. Changes nothing until approved.

    A record closes on its author's own verdict, so turning existing work into
    one would let a builder close their own work unreviewed. The owner checks
    the list and approves it in one go with ``softory approve --all``.
    """
    existing = _load_proposals(project)
    same = next((p for p in existing if p["status"] == "open" and p["kind"] == "adopt"
                 and p["change"]["task"] == task_id), None)
    if same is None:
        title = str(coord.task(task_id).get("title") or "")[:80]
        change = {"task": task_id, "targets": targets, "title": title, "looks_like_review": looks_like_review}
        same = {"id": _next_id(existing), "kind": "adopt", "change": change,
                "why": f"{task_id} is a review run of {', '.join(targets)}", "proposed_by": actor,
                "session": os.environ.get("COORDINATION_SESSION") or "no session", "created_at": _now(),
                "decision": None, "status": "open"}
        _save_proposals(project, [*existing, same])
    result: dict[str, Any] = {"proposal": same["id"], "task": task_id, "targets": same["change"]["targets"],
                              "next": "Tell the owner: softory approve --all (in a terminal) approves every waiting "
                                      "adoption at once. Nothing changes until then."}
    if skipped:
        result["not_targets"] = skipped
    return result


def _next_id(existing: list[dict[str, Any]]) -> str:
    number = 1 + max((int(p["id"].split("-")[-1]) for p in existing if re.fullmatch(r"PROP-\d+", p["id"])), default=0)
    return f"PROP-{number}"


def _summary(chosen: list[dict[str, Any]], reject: bool) -> str:
    """What the owner reads before typing yes: anything that doesn't look like a review run comes first."""
    odd = [p for p in chosen if p["kind"] == "adopt" and not p["change"].get("looks_like_review", True)]
    usual = [p for p in chosen if p not in odd]
    flag = bool(odd) and not reject
    lines = [f"{'Reject' if reject else 'Approve'} {len(chosen)} proposal(s):"]
    if flag:
        lines += ["CHECK THESE FIRST. Not tagged or named as a review run, so it may be work posing as one "
                  "(to leave one out, run softory approve <ID> --reject first):", *(_describe(p) for p in odd), ""]
    lines += [_describe(p) for p in (usual if flag else chosen)]
    return "\n".join(lines)


def _describe(proposal: dict[str, Any]) -> str:
    change = proposal["change"]
    if proposal["kind"] == "standin":
        what = f"Stand-in: {grants.describe(change)}"
    elif proposal["kind"] == "waiver":
        what = f"Waive {change['check']} on {change['task']}: {change['reason']}"
    else:
        what = (f"Close {change['task']} (\"{change.get('title', '')}\") as a review record of "
                f"{', '.join(change['targets'])}")
    return f"{proposal['id']} from {proposal['proposed_by']}: {what}" + (
        f"\n  Why: {proposal['why']}" if proposal["kind"] != "adopt" else "")


def approve(project: Project, coord: Coordination, proposal_ids: list[str], reject: bool = False,
            every: bool = False, confirm: Confirm = confirm_at_terminal) -> dict[str, Any]:
    """Apply (or reject) proposals, after one typed yes. Only the owner, at a terminal.

    ``every`` takes every waiting review adoption. Stand-ins and waivers change
    who the gate trusts, so they're approved one by one, by ID.
    """
    rows = _load_proposals(project)
    open_rows = [p for p in rows if p["status"] == "open"]
    if every:
        chosen = [p for p in open_rows if p["kind"] == "adopt"]
        others = [p["id"] for p in open_rows if p["kind"] != "adopt"]
        if not chosen:
            note = "No review adoptions are waiting."
            if others:
                note += f" Approve stand-ins and waivers by ID: {', '.join(others)}."
            return {"results": [], "note": note}
    else:
        missing = [i for i in proposal_ids if i not in {p["id"] for p in open_rows}]
        if missing or not proposal_ids:
            raise SoftoryError(f"No open proposal {', '.join(missing) or '(none named)'}; softory proposals lists them",
                               "not_found")
        chosen = [p for p in open_rows if p["id"] in proposal_ids]
    confirm(_summary(chosen, reject))
    owner = project.roster()["owner"]["id"]
    results = []
    adopted = [p for p in chosen if p["kind"] == "adopt"]
    batch = None
    if adopted and not reject:  # one decision for the whole batch
        batch = record_decision(coord, owner, "ADOPT", f"Owner approved {len(adopted)} review run(s) as records",
                                "Close as review records: " + "; ".join(
                                    f"{p['change']['task']} (reviews {', '.join(p['change']['targets'])})" for p in adopted),
                                "Approved with softory approve at the owner's terminal.")
    for proposal in chosen:
        result = _decide(project, coord, proposal, reject, owner, batch)
        results.append(result)
        if proposal["status"] != "open":
            proposal["decided_at"] = _now()
    _save_proposals(project, rows)
    return {"results": results} if len(results) > 1 or every else results[0]


def _decide(project: Project, coord: Coordination, proposal: dict[str, Any], reject: bool, owner: str,
            batch: str | None) -> dict[str, Any]:
    proposal_id = proposal["id"]
    change = proposal["change"]
    result: dict[str, Any] = {"proposal": proposal_id}
    if proposal["kind"] == "adopt":
        if reject:
            proposal["status"] = "rejected"
        else:
            from . import team  # imported here: team -> work -> ops would import this module first
            try:
                result.update(team.adopt(project, coord, change["task"], "review",
                                         {"actor": owner, "for": ",".join(change["targets"]), "approved": True}))
            except SoftoryError as error:  # it changed since it was proposed; leave it for another look
                result.update(status="open", error=error.message)
                return result
            proposal.update(status="approved", decision=batch)
        result["status"] = proposal["status"]
        return result
    if not reject:
        if proposal["kind"] == "standin":
            result.update(_apply_grant(project, coord, change, proposal["decision"]))
        else:
            settings = project.local()
            waiver = {**change, "decision": proposal["decision"]}
            settings["waivers"] = [*grants.normalize_waivers(settings.get("waivers")), waiver]
            project.save_local(settings)
            result["waived"] = waiver
    coord.run("decision", "status", proposal["decision"], "rejected" if reject else "accepted", "--actor", owner,
              "--if-status", "proposed", "--note", f"softory approve {proposal_id}{' --reject' if reject else ''}")
    proposal["status"] = "rejected" if reject else "approved"
    result["status"] = proposal["status"]
    return result


def _checked_waiver(project: Project, coord: Coordination, task_id: str, check: str, reason: str) -> dict[str, Any]:
    coord.task(task_id)  # must exist
    if not grants.waivable(check):
        raise SoftoryError(f"{check} can't be waived. Waivable: review:<source>, {', '.join(grants.WAIVABLE_CHECKS)}",
                           "invalid_arguments")
    return {"task": task_id, "check": check, "reason": reason}


# ---- rulings ----------------------------------------------------------------------------------

def ruling(project: Project, coord: Coordination, title: str, decision: str, where: str, context: str | None,
           actor: str) -> dict[str, Any]:
    """Record a decision the owner made, under the owner's name, marked with who recorded it and where."""
    if not where.strip():
        raise SoftoryError("Say where the owner said it with --where (a thread, a message, a date)", "invalid_arguments")
    owner = project.roster()["owner"]["id"]
    session = os.environ.get("COORDINATION_SESSION") or "no session"
    background = f"Recorded by {actor} ({session}) on the owner's behalf. The owner said it here: {where}."
    decision_id = record_decision(coord, owner, f"RULING-{actor}", f"Owner ruling (recorded by {actor}): {title}",
                                  decision, background + (f" {context}" if context else ""))
    return {"decision": decision_id, "owner": owner, "recorded_by": actor,
            "note": "A ruling is a record. It doesn't change the gate; a stand-in or waiver still needs softory approve."}


def record_decision(coord: Coordination, owner: str, kind: str, title: str, decision: str, context: str,
                    status: str = "accepted") -> str:
    """Add a decision owned by ``owner``. No session: the owner's name can't match a role's session."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    decision_id = f"SOFTORY-DEC-{kind}-{stamp}"
    coord.run("decision", "add", "--id", decision_id, "--title", title[:200], "--owner", owner, "--status", status,
              "--context", context, "--decision", decision)
    return decision_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
