"""Merge on green and a base that stays green: ``softory ship``, which the runner starts in the background.

With the charter's ``merge.by`` set to ``softory``, units that closed through the gate are merged onto
the base branch by softory alone. Up to ``batch_max`` of them become one candidate commit, built in a
throwaway worktree, and the base moves only when ``softory verify`` passes at the candidate. A unit
whose commit already sits on the base is a fast-forward, and its own verify result counts. A failing
batch is tried again one unit at a time; a unit that conflicts or fails alone gets a bug for its lane.
A unit built on another unit's commits waits until that unit closes too. Only a verified candidate is pushed.
After a merge, every ``auto`` deploy target gets the new base.

Whatever the merge setting, a base that moved since the last check is verified, and a red base gets one
priority 1 bug, so nobody builds on a broken base without knowing.
"""

from __future__ import annotations

import fcntl
import json
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import deploy, verify, verifyenv
from .coordination import Coordination
from .errors import SoftoryError
from .gitlocal import git
from .lifecycle import closed_by_softory
from .project import Project
from .units import lane_of, resolution_of, unit_of
from .watch import parse_time

AUTHOR = ["-c", "user.name=softory", "-c", "user.email=softory@localhost"]


def ledger_path(project: Project) -> Path:
    return project.state / "merged.json"


def ledger(project: Project) -> dict[str, Any]:
    try:
        return json.loads(ledger_path(project).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(project: Project, data: dict[str, Any]) -> None:
    ledger_path(project).parent.mkdir(parents=True, exist_ok=True)
    ledger_path(project).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def head(project: Project, ref: str) -> str | None:
    found = git(project.root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return found.stdout.strip() if found.returncode == 0 else None


def waiting(project: Project, coord: Coordination, charter: dict[str, Any]) -> list[dict[str, Any]]:
    """Units closed through the gate since softory began merging, whose commit isn't on the base yet."""
    data = ledger(project)
    since = charter["merge"].get("since")
    if not since:  # merge.by softory but no start time (set before 0.6.0): only what closes from now on
        since = data.setdefault("since", _now())
        _save(project, data)
    since_at = parse_time(since)
    seen = data.get("units") or {}
    base = charter["git"]["base"]
    gates = project.gates()
    tasks = {task["id"]: task for task in coord.all_tasks()}
    found = []
    for task in tasks.values():
        if task["status"] != "done" or task["id"] in seen or unit_of(task, gates) not in verify.CODE_UNITS:
            continue
        if lane_of(task) in verify.NO_TEST_LANES or not _closed(task) or parse_time(str(task.get("updated_at"))) < since_at:
            continue
        sha = verify.commit_of(project.root, coord.task(task["id"]))
        if sha and not _contains(project.root, base, sha) and not open_below(project, base, sha, task["id"], tasks):
            found.append({"id": task["id"], "title": task["title"], "commit": sha, "lane": lane_of(task),
                          "closed": task.get("updated_at")})
    return sorted(found, key=lambda row: (row["closed"] or "", row["id"]))


def _closed(task: dict[str, Any]) -> bool:
    return task["status"] == "done" and not resolution_of(task) and closed_by_softory(task)


def open_below(project: Project, base: str, sha: str, task_id: str, tasks: dict[str, dict[str, Any]]) -> list[str]:
    """Other units whose verified commits ``sha`` is built on and that haven't closed through the gate.
    Merging ``sha`` would carry their work onto the base, so it waits for them."""
    listed = git(project.root, "rev-list", sha, f"^{base}")
    if listed.returncode != 0:
        return ["(git can't list its history)"]
    mine = set(listed.stdout.split())
    below = {entry.get("task") for commit, entry in verify.ledger(project).items() if commit in mine}
    return sorted(t for t in below if t in tasks and t != task_id and not _closed(tasks[t]))


def _contains(root: Path, base: str, sha: str) -> bool:
    """Whether the base already holds the commit, or every change it makes (a squash or a cherry-pick)."""
    if git(root, "merge-base", "--is-ancestor", sha, base).returncode == 0:
        return True
    tried = git(root, "merge-tree", "--write-tree", "--no-messages", base, sha)
    tree = git(root, "rev-parse", f"{base}^{{tree}}")
    return tried.returncode == 0 and tree.returncode == 0 and tried.stdout.split()[:1] == tree.stdout.split()[:1]


def ship(project: Project, coord: Coordination, charter: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    """Check the base, merge what's waiting, and deploy the auto targets. One at a time per project."""
    if not charter["verify"].get("command"):
        return {"skipped": "the charter sets no verify.command, so softory can't tell green from red"}
    base = charter["git"]["base"]
    if head(project, base) is None:
        raise SoftoryError(f"The base branch {base} doesn't exist; set git.base in the charter", "configuration_error")
    with (project.state / "ship.lock").open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return {"skipped": "another softory ship is running"}
        report: dict[str, Any] = {"base": base}
        if dry_run:
            report["waiting"] = waiting(project, coord, charter) if charter["merge"].get("by") == "softory" else []
            return report
        data = ledger(project)
        if charter["merge"].get("by") == "softory":
            report["push"] = _push(project, charter, data)
        report["base_check"] = check_base(project, coord, charter)
        if charter["merge"].get("by") == "softory":
            report["merge"] = merge(project, coord, charter)
        return report


def check_base(project: Project, coord: Coordination, charter: dict[str, Any]) -> dict[str, Any]:
    """Verify the base head if it moved since the last check. A red base gets one priority 1 bug."""
    data = ledger(project)
    state = data.get("base") or {}
    sha = head(project, charter["git"]["base"])
    if state.get("sha") == sha:
        return state
    green = _verified(project, coord, charter, sha, "base")
    moved_outside = bool(state.get("sha")) and sha != data.get("last_candidate")
    state = {"sha": sha, "green": green, "checked_at": _now(), "bug": state.get("bug") if not green else None,
             "moved_outside": moved_outside and charter["merge"].get("by") == "softory"}
    if not green and not state["bug"]:
        entry = verify.ledger(project).get(sha) or {}
        state["bug"] = file_bug(project, coord, None, f"Base {charter['git']['base']} is red at {sha[:12]}",
                                f"softory verify failed on the base at {sha}. Log: {entry.get('log', 'see verify')}. "
                                "Fix the base before anything else merges on top of it.", "infra", "verify")
    data = ledger(project)
    data["base"] = state
    _save(project, data)
    return state


def merge(project: Project, coord: Coordination, charter: dict[str, Any]) -> dict[str, Any]:
    """Merge one batch of waiting units onto the base, or none of it."""
    units = waiting(project, coord, charter)
    if not units:
        return {"merged": []}
    data = ledger(project)
    red = data.get("base") or {}
    if red.get("green") is False:  # stop the line: only the fix for the red base merges
        units = [u for u in units if u["id"] == red.get("bug")]
        if not units:
            return {"merged": [], "waiting": f"the base is red; {red.get('bug') or 'its fix'} merges first"}
    size = 1 if data.get("split") else max(1, int(charter["merge"].get("batch_max") or 1))
    batch = units[:size]
    base = charter["git"]["base"]
    before = head(project, base)
    candidate, merged, conflicts = build_candidate(project, before, batch)
    result: dict[str, Any] = {"tried": [u["id"] for u in batch], "merged": [], "held": {}}
    for unit, files in conflicts:
        result["held"][unit["id"]] = _hold(project, coord, unit, "conflict",
                                           f"Rebase {unit['id']} onto {base}: it conflicts in {', '.join(files[:5])}",
                                           "build")
    if not candidate:
        return result
    if not _verified(project, coord, charter, candidate, "merge"):
        if len(merged) > 1:
            data = ledger(project)
            data["split"] = True  # find the unit that breaks it: one at a time from now on
            _save(project, data)
            result["split"] = True
        else:
            result["held"][merged[0]["id"]] = _hold(
                project, coord, merged[0], "red",
                f"{merged[0]['id']} fails softory verify on top of {base}", "verify")
        return result
    _advance(project, base, before, candidate)
    data = ledger(project)
    for unit in merged:
        data.setdefault("units", {})[unit["id"]] = {"commit": unit["commit"], "merged_as": candidate, "at": _now()}
        coord.call("evidence", "add", "--task", unit["id"], "--uri", f"softory-merged:{candidate}", "--type", "note",
                   "--actor", project.roster()["owner"]["id"])
    data["last_candidate"] = candidate
    data["base"] = {"sha": candidate, "green": True, "checked_at": _now(), "bug": None, "moved_outside": False}
    if len(units) <= len(merged) + len(conflicts):
        data.pop("split", None)  # everything waiting got through: batches again
    _save(project, data)
    result["merged"] = [u["id"] for u in merged]
    result["base"] = candidate
    result["push"] = _push(project, charter, data)
    result["deployed"] = auto_deploy(project, coord, charter, candidate, merged)
    return result


def build_candidate(project: Project, base_sha: str, units: list[dict[str, Any]]
                    ) -> tuple[str | None, list[dict[str, Any]], list[tuple[dict[str, Any], list[str]]]]:
    """One commit holding the base plus each unit, merged in order. A unit that conflicts is left out."""
    root = project.root
    if len(units) == 1 and git(root, "merge-base", "--is-ancestor", base_sha, units[0]["commit"]).returncode == 0:
        return units[0]["commit"], units, []  # a fast-forward: the unit's own verify counts
    place = Path(tempfile.mkdtemp(prefix="softory-merge-"))
    tree = place / "tree"
    if git(root, "worktree", "add", "--detach", "--quiet", str(tree), base_sha).returncode != 0:
        shutil.rmtree(place, ignore_errors=True)
        raise SoftoryError("git couldn't add a worktree to build the merge candidate", "git_error")
    merged, conflicts = [], []
    try:
        for unit in units:
            done = git(tree, *AUTHOR, "merge", "--no-ff", "--no-edit", "-m",
                       f"softory: merge {unit['id']}: {unit['title']}"[:200], unit["commit"])
            if done.returncode == 0:
                merged.append(unit)
                continue
            files = git(tree, "diff", "--name-only", "--diff-filter=U").stdout.split()
            git(tree, "merge", "--abort")
            conflicts.append((unit, files or ["(unknown)"]))
        candidate = git(tree, "rev-parse", "HEAD").stdout.strip() if merged else None
    finally:
        git(root, "worktree", "remove", "--force", str(tree))
        shutil.rmtree(place, ignore_errors=True)
    return candidate, merged, conflicts


def _verified(project: Project, coord: Coordination, charter: dict[str, Any], sha: str, label: str) -> bool:
    """Whether softory verify passed at ``sha``, running it once if it never ran there."""
    entry = verify.ledger(project).get(sha)
    if entry is None:
        verify.run_at(project, charter, sha, label, project.roster()["owner"]["id"])
        entry = verify.ledger(project).get(sha) or {}
    return bool(entry.get("passed"))


def _advance(project: Project, base: str, before: str, candidate: str) -> None:
    """Move the base to the candidate: fast-forward where it's checked out, else update the ref."""
    listed = git(project.root, "worktree", "list", "--porcelain").stdout.split("\n\n")
    where = next((Path(block.split("\n", 1)[0].removeprefix("worktree ")) for block in listed
                  if f"branch refs/heads/{base}" in block.splitlines()), None)
    if where is None:
        moved = git(project.root, "update-ref", f"refs/heads/{base}", candidate, before)
    else:
        moved = git(where, "merge", "--ff-only", "--quiet", candidate)
    if moved.returncode != 0:
        raise SoftoryError(f"Couldn't move {base} to {candidate[:12]}: {moved.stderr.strip()[:300]}", "git_error")


def _push(project: Project, charter: dict[str, Any], data: dict[str, Any]) -> str | None:
    """Push the base to the charter's remote when it is still the last candidate softory verified and
    merged. A failure is reported and tried again next time."""
    remote, base = charter["merge"].get("push"), charter["git"]["base"]
    sha = head(project, base)
    # Only a candidate softory verified: a commit made on the base by hand waits for check_base and the owner.
    if not remote or sha != data.get("last_candidate") or data.get("pushed") == sha:
        return None
    done = git(project.root, "push", "--quiet", remote, f"refs/heads/{base}:refs/heads/{base}")
    if done.returncode != 0:
        return f"push failed: {done.stderr.strip()[:200]}"
    saved = ledger(project)
    saved["pushed"] = sha
    _save(project, saved)
    return "pushed"


def _hold(project: Project, coord: Coordination, unit: dict[str, Any], why: str, title: str, stage: str) -> str:
    """Keep a unit off the base and give its builder a bug that says why."""
    bug = file_bug(project, coord, unit["id"], title, f"softory ship couldn't merge {unit['id']} ({unit['commit']}). "
                   "Fix it on top of the base in this bug; the original stays off the base.", unit["lane"], stage)
    data = ledger(project)
    data.setdefault("units", {})[unit["id"]] = {"commit": unit["commit"], "held": why, "bug": bug, "at": _now()}
    _save(project, data)
    return bug


def file_bug(project: Project, coord: Coordination, source: str | None, title: str, description: str, lane: str | None,
             stage: str) -> str | None:
    from .work import new_unit  # noqa: PLC0415 - work imports most modules

    options = {"title": title[:200], "description": description, "lane": lane or "infra", "type": "functional",
               "found_at": stage, "priority": 1, "actor": project.roster()["owner"]["id"]}
    if source:
        options["from"] = source
    try:
        return new_unit(project, coord, "bug", options)["id"]
    except SoftoryError:
        return None


def auto_deploy(project: Project, coord: Coordination, charter: dict[str, Any], sha: str,
                merged: list[dict[str, Any]]) -> dict[str, Any]:
    """Deploy the new base to every auto target. A failed deploy or smoke test gets a priority 1 bug."""
    outcome: dict[str, Any] = {}
    for name, target in deploy.targets(charter).items():
        if not target.get("auto"):
            continue
        try:
            row = deploy.run(project, coord, charter, name, project.roster()["owner"]["id"], sha)
        except SoftoryError as error:
            outcome[name] = f"not deployed: {error.message}"
            continue
        outcome[name] = "passed" if row["passed"] else f"failed at {row['stage']}"
        if not row["passed"]:
            source = merged[-1]["id"] if merged else None
            file_bug(project, coord, source, f"{name} deploy of {sha[:12]} failed at {row['stage']}",
                     f"softory deployed {sha} to {name} after merging {', '.join(u['id'] for u in merged)}, and the "
                     f"{row['stage']} step failed. Log: {row['log']}", merged[-1]["lane"] if merged else "infra",
                     "staging")
    return outcome


def owner_items(project: Project) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(urgent, digest) lines for the owner: a red base, a base moved outside softory, held units."""
    data = ledger(project)
    state = data.get("base") or {}
    urgent, later = [], []
    if state.get("green") is False:
        urgent.append({"key": f"base-red-{state.get('sha')}", "text": f"The base is red at {str(state.get('sha'))[:12]}: "
                       f"{state.get('bug') or 'a bug'} is filed, and nothing else merges until it's fixed"})
    if state.get("moved_outside"):
        later.append({"key": f"base-outside-{state.get('sha')}", "text": f"The base moved to {str(state.get('sha'))[:12]} "
                      "outside softory ship, though the charter has softory merge"})
    week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    held = {i: u for i, u in (data.get("units") or {}).items() if u.get("held") and str(u.get("at")) >= week}
    if held:
        later.append({"key": "held-" + ",".join(sorted(held)), "text": f"{len(held)} unit(s) kept off the base this week, each with a bug: "
                      + ", ".join(f"{i} ({u['held']}, {u.get('bug')})" for i, u in sorted(held.items())[:5])})
    return urgent, later
