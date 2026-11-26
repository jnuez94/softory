"""The owner's changes: stand-ins, waivers, proposals, and rulings recorded for the owner.

Stand-ins and waivers change who and what the gate accepts, so
only the owner makes them, at a terminal: ``softory standin add`` and ``softory
approve`` ask for a typed "yes" and refuse to run without one. An agent's
shell has no terminal, so agents propose instead (``softory propose``),
which records the request and grants nothing until the owner approves it.

This is a speed bump, not a lock: an agent that fakes a terminal, or edits
the read-only files, is working around the owner on purpose, and the gate's
``config_intact`` check and ``softory doctor`` show the edit.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterator

from . import grants, ops, verify
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
    owner = project.owner_id
    if decision is None:
        decision = record_decision(coord, owner, "STANDIN", f"{grant['agent']} stands in for {', '.join(grant['roles'])}",
                                   grants.describe(grant).replace("`", ""),
                                   "The owner named a stand-in under softory's flex rule (boundaries.md).")
    grant = {**grant, "decision": decision}
    settings = project.local()
    held = grants.normalize_stand_ins(settings.get("stand_ins"))
    if not any(g.get("decision") == decision for g in held):  # an approval run again writes it once
        settings["stand_ins"] = [*held, grant]
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
    owner = project.owner_id
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
    """Replace the file whole. ``proposals`` reads it without the lock, and the digest reads it before the
    runner starts any role: a reader sees the old list or the new one, and a write that dies leaves the old."""
    path = project.proposals_path()
    fresh = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    fresh.write_text(json.dumps(proposals, indent=2) + "\n", encoding="utf-8")
    os.replace(fresh, path)


@contextmanager
def _editing_proposals(project: Project) -> Iterator[list[dict[str, Any]]]:
    """Read, change, and write the proposals under one lock. A role proposing, the owner approving, and the
    runner's digest run in separate processes: without the lock each could write back a list the other
    had since added to. What was changed before an error is kept."""
    project.state.mkdir(parents=True, exist_ok=True)
    with (project.state / "proposals.lock").open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = _load_proposals(project)
        try:
            yield rows
        finally:
            _save_proposals(project, rows)


def proposals(project: Project, show_all: bool = False) -> list[dict[str, Any]]:
    rows = _load_proposals(project)
    return rows if show_all else [p for p in rows if p["status"] == "open"]


#: What a proposal is called once its decision in the tracker has left ``proposed``. The decision is the
#: record of what happened; the proposal's own status follows it.
_SETTLED = {"accepted": "approved", "rejected": "rejected", "superseded": "lapsed"}


def _units(proposal: dict[str, Any]) -> list[str]:
    change = proposal["change"]
    return [change["task"]] if proposal["kind"] == "waiver" else change.get("tasks") or []


def _finished(coord: Coordination, proposal: dict[str, Any]) -> bool:
    """Whether every unit the proposal names is done, so there is nothing left to waive or stand in on."""
    units = _units(proposal)
    return bool(units) and all(coord.task(unit)["status"] == "done" for unit in units)


def _settle(coord: Coordination, owner: str, proposal: dict[str, Any], to: str, note: str) -> str:
    """Move the proposal's decision from ``proposed`` to ``to`` and return where it stands. One that already
    left ``proposed`` is returned as it is: an earlier run got that far, or someone else decided first."""
    try:
        coord.run("decision", "status", proposal["decision"], to, "--actor", owner, "--if-status", "proposed",
                  "--note", note)
    except SoftoryError:
        now = coord.run("decision", "show", proposal["decision"])["status"]
        if now == "proposed":
            raise
        return now
    return to


def _granted(project: Project, proposal: dict[str, Any]) -> bool:
    """Whether local.json already holds what the proposal asks for, under the proposal's decision."""
    key = "stand_ins" if proposal["kind"] == "standin" else "waivers"
    return any(row.get("decision") == proposal["decision"] for row in project.local().get(key) or [])


def lapse_finished(project: Project, coord: Coordination) -> list[str]:
    """Close open proposals whose every unit is done. Three waiver requests sat open in Tablet for weeks
    after their tasks closed, and the owner's digest kept listing them. The proposal and its decision stay
    on record, marked as lapsed.

    The digest calls this before the runner starts any role, so it never raises and is safe to repeat. A
    run that stopped after the tracker was told and before the proposal was marked is finished by the next
    one, and a proposal the tracker won't answer for is left for the next run.
    """
    lapsed = []
    for seen in proposals(project):
        try:
            if not _finished(coord, seen):
                continue
            stands = _settle(coord, project.owner_id, seen, "superseded", f"{', '.join(_units(seen))} finished "
                             f"before the owner decided {seen['id']}, so softory closed it")
            if stands == "accepted" and not _granted(project, seen):
                continue  # an approval that didn't finish: softory approve completes it
        except SoftoryError:
            continue
        with _editing_proposals(project) as rows:
            for row in rows:
                if row["id"] == seen["id"] and row["status"] == "open":
                    row.update(status=_SETTLED.get(stands, "lapsed"), decided_at=_now())
                    lapsed += [row["id"]] if stands == "superseded" else []
    return lapsed


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
    owner = project.owner_id
    session = os.environ.get("COORDINATION_SESSION") or "no session"
    with _editing_proposals(project) as rows:  # the number and the row are taken under one lock
        proposal_id = _next_id(rows)
        decision = record_decision(coord, owner, "PROP", f"Proposed by {actor}: {title}", title,
                                   f"Proposed by {actor} ({session}): {why}. Waiting for the owner's softory approve {proposal_id}.",
                                   status="proposed", recorded_by=actor)
        rows.append({"id": proposal_id, "kind": kind, "change": checked, "why": why, "proposed_by": actor,
                     "session": session, "created_at": _now(), "decision": decision, "status": "open"})
    return {"proposal": proposal_id, "decision": decision,
            "next": f"Tell the owner: softory approve {proposal_id} (run it in a terminal). Nothing changes until then."}


def _next_id(existing: list[dict[str, Any]]) -> str:
    number = 1 + max((int(p["id"].split("-")[-1]) for p in existing if re.fullmatch(r"PROP-\d+", p["id"])), default=0)
    return f"PROP-{number}"


def _describe(proposal: dict[str, Any]) -> str:
    change = proposal["change"]
    if proposal["kind"] == "standin":
        what = f"Stand-in: {grants.describe(change)}"
    else:
        what = (f"Waive {change['check']} on {change['task']} at "
                f"{change.get('commit') or 'no commit yet'}, for one close: {change['reason']}")
    return f"{proposal['id']} from {proposal['proposed_by']}: {what}\n  Why: {proposal['why']}"


def approve(project: Project, coord: Coordination, proposal_ids: list[str], reject: bool = False,
            confirm: Confirm = confirm_at_terminal) -> dict[str, Any]:
    """Apply (or reject) proposals, after one typed yes. Only the owner, at a terminal."""
    open_rows = proposals(project)
    missing = [i for i in proposal_ids if i not in {p["id"] for p in open_rows}]
    if missing or not proposal_ids:
        raise SoftoryError(f"No open proposal {', '.join(missing) or '(none named)'}; softory proposals lists them",
                           "not_found")
    chosen = [p for p in open_rows if p["id"] in proposal_ids]
    confirm("\n".join([f"{'Reject' if reject else 'Approve'} {len(chosen)} proposal(s):", *map(_describe, chosen)]))
    if not reject and "local.json" in (project.integrity_changes() or []):
        # Said before anything is recorded: the grant below could not be written.
        raise SoftoryError(f"{project.local_path} was edited outside softory. Restore it, or reinstall softory to "
                           "accept it as is.", "configuration_tampered")
    results = [_decide(project, coord, proposal["id"], reject, project.owner_id) for proposal in chosen]
    return {"results": results} if len(results) > 1 else results[0]


def _decide(project: Project, coord: Coordination, proposal_id: str, reject: bool, owner: str) -> dict[str, Any]:
    """Decide one proposal as it stands now, not as it stood when the owner was asked: the prompt can sit
    open while the runner's digest lapses the proposal or the unit closes.

    The decision is recorded first and the grant written second, so a refused or failed record leaves
    local.json as it was. If the grant then fails, the proposal stays open and ``softory approve`` again
    finishes it: the decision already stands, and a grant already written isn't written twice.
    """
    result: dict[str, Any] = {"proposal": proposal_id}
    with _editing_proposals(project) as rows:
        proposal = next(p for p in rows if p["id"] == proposal_id)
        if proposal["status"] != "open":
            return {**result, "status": proposal["status"], "note": "It was settled while you were asked. Nothing changed."}
        wanted = "rejected" if reject else "accepted"
        note = f"softory approve {proposal_id}{' --reject' if reject else ''}"
        if not reject and _finished(coord, proposal):
            wanted = "superseded"
            note = f"{', '.join(_units(proposal))} finished before the owner decided {proposal_id}, so softory closed it"
        stands = _settle(coord, owner, proposal, wanted, note)
        if stands == "accepted" and reject and not _granted(project, proposal):
            # An approval recorded its decision and failed before the grant. Marking the proposal now would
            # take it off the open list with nothing granted and no way back.
            raise SoftoryError(f"{proposal_id} can't be rejected: its decision {proposal['decision']} already "
                               f"stands as accepted, from an approval that didn't finish. It stays open. Run "
                               f"softory approve {proposal_id} to finish it.", "already_accepted")
        if stands == "accepted" and not reject:
            change = proposal["change"]
            if proposal["kind"] == "standin":
                result.update(_apply_grant(project, coord, change, proposal["decision"]))
            else:
                result.update(_apply_waiver(project, coord, change, proposal["decision"]))
        proposal.update(status=_SETTLED[stands], decided_at=_now())
        result["status"] = proposal["status"]
        if stands != ("rejected" if reject else "accepted"):
            result["note"] = ("Every unit it names is done, so there is nothing to grant. It is closed as lapsed."
                              if stands == "superseded" else f"Its decision already stood as {stands}. Nothing else changed.")
    return result


def _apply_waiver(project: Project, coord: Coordination, change: dict[str, Any], decision: str) -> dict[str, Any]:
    settings = project.local()
    held = grants.normalize_waivers(settings.get("waivers"))
    waiver = next((w for w in held if w.get("decision") == decision), None)
    if waiver is None:
        waiver = {**change, "commit": change.get("commit") or "", "decision": decision, "approved_at": _now()}
        settings["waivers"] = [*held, waiver]
        project.save_local(settings)
    result: dict[str, Any] = {"waived": waiver}
    now = verify.commit_of(project.root, coord.task(change["task"])) or ""
    if now != waiver["commit"]:
        result["note"] = (f"{change['task']} has delivered {now[:12] or 'no commit'} since this was asked for at "
                          f"{waiver['commit'][:12] or 'no commit'}. The waiver covers what was asked for only.")
    return result


def _checked_waiver(project: Project, coord: Coordination, task_id: str, check: str, reason: str) -> dict[str, Any]:
    if not grants.waivable(check):
        raise SoftoryError(f"{check} can't be waived. Waivable: review:<source>, {', '.join(grants.WAIVABLE_CHECKS)}",
                           "invalid_arguments")
    return {"task": task_id, "check": check, "reason": reason,
            "commit": verify.commit_of(project.root, coord.task(task_id)) or ""}


# ---- rulings ----------------------------------------------------------------------------------

def ruling(project: Project, coord: Coordination, title: str, decision: str, where: str, context: str | None,
           actor: str, review: str | None = None, escalation: str | None = None) -> dict[str, Any]:
    """Record a decision the owner made, under the owner's name, marked with who recorded it and where.

    ``review`` also records it as the owner's accepted review of that unit, and ``escalation`` closes that
    escalation with it: what the owner says in a session counts without a second trip to a terminal. Both
    name the ruling and who recorded it, and the owner's digest lists them for a day.
    """
    from . import decide, verify  # noqa: PLC0415 - both import this module

    if not where.strip():
        raise SoftoryError("Say where the owner said it with --where (a thread, a message, a date)", "invalid_arguments")
    owner = project.owner_id
    task = coord.task(review) if review else None  # both must exist before anything is written
    asked = decide.open_escalation(coord, escalation) if escalation else None
    session = os.environ.get("COORDINATION_SESSION") or "no session"
    background = f"Recorded by {actor} ({session}) on the owner's behalf. The owner said it here: {where}."
    decision_id = record_decision(coord, owner, f"RULING-{actor}", f"Owner ruling (recorded by {actor}): {title}",
                                  decision, background + (f" {context}" if context else ""), recorded_by=actor)
    result = {"decision": decision_id, "owner": owner, "recorded_by": actor,
              "note": "A ruling is a record. It doesn't change the gate; a stand-in or waiver still needs softory approve."}
    if asked:  # first: when the owner answered it meanwhile, nothing else is written on their behalf
        decide.close_as_told(project, coord, asked, decision, decision_id, actor)
        result["escalation"] = asked["id"]
    if task:
        sha = verify.commit_of(project.root, task)
        review_id = f"REV-{task['id']}-{owner}-{decision_id.rsplit('-', 1)[-1]}"
        coord.run("review", "add", "--id", review_id, "--task", task["id"], "--reviewer", owner,
                  "--artifact", f"commit:{sha}" if sha else task["id"], "--decision", "accepted",
                  "--scope", f"The owner's approval, said here: {where}. Recorded by {actor} as {decision_id}.",
                  "--accepted-items", decision)
        result.update(review=review_id, note=f"Recorded as the owner's accepted review of {task['id']}. The owner "
                                             "sees it in the digest.")
    if task or asked:
        decide.note_on_behalf(project, {"by": actor, "decision": decision_id, "where": where, "said": decision[:200],
                                        **({"review": task["id"]} if task else {}),
                                        **({"escalation": asked["id"]} if asked else {})})
    return result


def record_decision(coord: Coordination, owner: str, kind: str, title: str, decision: str, context: str,
                    status: str = "accepted", recorded_by: str | None = None) -> str:
    """Add a decision owned by ``owner``. No session: the owner's name can't match a role's session.
    ``recorded_by`` writes the audit row under the role that recorded it (scaffold 1.4.1)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    decision_id = f"SOFTORY-DEC-{kind}-{stamp}"
    recorder = ["--recorded-by", recorded_by] if recorded_by and recorded_by != owner else []
    coord.run("decision", "add", "--id", decision_id, "--title", title[:200], "--owner", owner, "--status", status,
              "--context", context, "--decision", decision, *recorder)
    return decision_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
