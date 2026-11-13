"""Objective checks for the gate: the project's tests pass at the commit, and the diff stays in its lane.

``softory verify <ID>`` runs the charter's ``verify.command`` in a clean
worktree at the task's latest commit and records the result in a local
ledger. With a command set, the gate's ``verified`` check needs a passing
ledger entry for that commit, so "tests pass" is something softory saw,
not something an agent wrote. ``lane_paths`` fails when the unit's own
commits touch paths outside its lane, unless Quinn (or, when Quinn built it,
Quinn's named backup) accepted it as cross-lane. Commits another unit's
verified commit already holds are inherited, not the unit's own.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import design, leaks, verifyenv
from .coordination import Coordination
from .errors import SoftoryError
from .gate import builders, with_stand_ins
from .gitlocal import git
from .gitlocal import status_entries as gitlocal_status
from .project import Project
from .units import CODE_EVIDENCE, lane_of, live_evidence, tags_of, unit_of

CODE_UNITS = ("task", "bug")
NO_TEST_LANES = ("design",)
_SHA = re.compile(r"\b([0-9a-f]{7,40})\b")
_HEAD = re.compile(r"(?:^commit:|\bhead=)([0-9a-f]{7,40})\b")
TAIL_LINES = 40


def ledger_path(project: Project) -> Path:
    return project.state / "verified.json"


def ledger(project: Project) -> dict[str, Any]:
    try:
        return json.loads(ledger_path(project).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def commit_of(root: Path, task: dict[str, Any]) -> str | None:
    """The full hash of the newest code evidence that names exactly one commit this repository has.

    ``commit:<sha>`` (what ``softory commit`` writes) and ``head=<sha>`` name the commit outright. Free text
    that names several commits, such as a head and its base, is ambiguous and skipped, so a base commit's
    passing tests are never credited to the head. Evidence superseded with ``softory supersede`` is skipped.
    """
    for row in reversed(live_evidence(task.get("evidence"))):
        if str(row.get("evidence_type", "")).lower() not in CODE_EVIDENCE:
            continue
        uri = str(row.get("uri", "")).lower()
        named = _HEAD.findall(uri)
        candidates = named[-1:] if named else list(dict.fromkeys(_SHA.findall(uri)))
        found = [full for full in (_resolve(root, c) for c in candidates) if full]
        if len(set(found)) == 1:
            return found[0]
    return None


def _resolve(root: Path, candidate: str) -> str | None:
    found = git(root, "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}")
    return found.stdout.strip() if found.returncode == 0 else None


def run(project: Project, coord: Coordination, charter: dict[str, Any], task_id: str, actor: str,
        commit: str | None = None) -> dict[str, Any]:
    """Run the verify command at the task's commit in a throwaway worktree, and record what happened.

    One verify runs at a time per project; the rest wait their turn. ``verify.setup``, when set, runs
    first, and its failure is recorded as a setup failure, not a test failure.
    """
    settings = charter["verify"]
    command = settings["command"]
    if not command:
        raise SoftoryError("The charter sets no verify.command; the owner adds one with softory charter approve",
                           "configuration_error")
    task = coord.task(task_id)
    sha = commit or commit_of(project.root, task)
    if sha:
        resolved = git(project.root, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
        sha = resolved.stdout.strip() if resolved.returncode == 0 else None
    if not sha:
        raise SoftoryError(f"{task_id} has no commit evidence this repository knows; add one with softory commit "
                           "or pass --commit", "not_found")
    scan, found = None, None
    if design.applies(project, charter, task):  # a ui unit's own UI files go through the design detector too
        files = unit_files(project, charter, task_id, sha)
        if files is None:  # never read "git couldn't diff" as "no UI files changed"
            found = design.unscanned(f"git can't diff {sha[:12]} against {charter['git']['base']}, so the "
                                     "unit's UI files are unknown")
        else:
            scan = {"launcher": design.detector(project), "files": design.ui_files(files)}
    with verifyenv.turn(project, task_id, actor):
        outcome = _run_in_tree(project, settings, task_id, sha, scan)
    tests_passed = outcome["code"] == 0 and outcome["stage"] == "test"
    found = found or outcome.get("design")
    if found and tests_passed and not found["passed"]:
        outcome["stage"] = "design"
    passed = tests_passed and (found is None or found["passed"])
    entries = ledger(project)
    previous = entries.get(sha) or {}
    # The tests are the commit's; a design result is one unit's, so another unit's run at this commit keeps it.
    entry = {"task": task_id, "passed": tests_passed, "exit": outcome["code"], "command": command, "by": actor,
             "at": outcome["started"].isoformat(timespec="seconds"), "stage": outcome["stage"],
             "seconds": round((datetime.now(timezone.utc) - outcome["started"]).total_seconds(), 1),
             "designs": dict(previous.get("designs") or {})}
    if outcome["stage"] == "setup":
        entry["setup_failed"] = True
    if found and tests_passed:
        entry["designs"][task_id] = {"passed": found["passed"], "detail": found["detail"], "at": entry["at"]}
    if not entry["designs"]:
        del entry["designs"]
    entries[sha] = entry
    ledger_path(project).parent.mkdir(parents=True, exist_ok=True)
    ledger_path(project).write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verdict = "pass" if passed else ("setup-fail" if outcome["stage"] == "setup" else "fail")
    coord.run("evidence", "add", "--task", task_id, "--uri", f"softory-verify:{verdict}:{sha}",
              "--type", "test", "--actor", actor)
    result = {"task": task_id, "commit": sha, "passed": passed, "exit": outcome["code"], "stage": outcome["stage"],
              "log": outcome["log"], "tail": "\n".join(outcome["output"].splitlines()[-TAIL_LINES:]),
              "shared": outcome["shared"]}
    if outcome["kept"]:
        result["kept"] = outcome["kept"]
    loose = sorted(gitlocal_status(project.root))
    if loose:  # verify tests the commit, so these never count; they make the checkout unsafe to review in
        result["warning"] = (f"{len(loose)} changed or untracked path(s) in the main checkout, e.g. "
                             f"{', '.join(e[3:] for e in loose[:3])}. Commit code on your branch; file reports "
                             "with softory report.")
    if found:
        result["design"] = found
    return result


def run_at(project: Project, charter: dict[str, Any], sha: str, label: str, actor: str) -> dict[str, Any]:
    """Run the verify command at a commit no unit owns (a merge candidate, the base) and record it."""
    settings = charter["verify"]
    with verifyenv.turn(project, label, actor):
        outcome = _run_in_tree(project, settings, label, sha)
        entries = ledger(project)
        entries[sha] = {"task": label, "passed": outcome["code"] == 0 and outcome["stage"] == "test",
                        "exit": outcome["code"], "command": settings["command"], "by": actor, "stage": outcome["stage"],
                        "at": outcome["started"].isoformat(timespec="seconds"), "log": outcome["log"]}
        ledger_path(project).write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return entries[sha]


def _run_in_tree(project: Project, settings: dict[str, Any], task_id: str, sha: str,
                 scan: dict[str, Any] | None = None) -> dict[str, Any]:
    place = Path(tempfile.mkdtemp(prefix="softory-verify-"))
    tree = place / "tree"
    worktree = _checkout(project.root, sha, tree)
    if worktree is None:
        shutil.rmtree(place, ignore_errors=True)
        raise SoftoryError(f"git could check out {sha[:12]} neither as a worktree nor as an archive", "git_error")
    out_dir = project.state / "verify"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{task_id}-{sha[:12]}"
    shared, kept = {}, []
    found = None
    started = datetime.now(timezone.utc)
    try:
        for path in settings.get("share") or []:
            source = project.root / path
            if source.exists() and not (tree / path).exists():
                shared[path] = verifyenv.share(source, tree / path, settings.get("share_mode") or "clone")
        stage, code, output = "test", 0, ""
        timeout = float(settings["timeout_minutes"]) * 60
        if settings.get("setup"):
            code, output = _shell(settings["setup"], tree, timeout)
            stage = "setup" if code != 0 else "test"
        if stage == "test":
            code, more = _shell(verifyenv.awake(settings["command"]), tree, timeout)
            output += more
        if stage == "test" and code == 0 and scan:
            found = design.scan(scan["launcher"], tree, scan["files"])
            output += f"\n[softory] design detector: {found['detail']}\n"
        if code != 0:
            kept = verifyenv.keep_artifacts(tree, list(settings.get("keep") or []), out_dir / name)
    finally:
        if worktree:
            git(project.root, "worktree", "remove", "--force", str(tree))
        shutil.rmtree(place, ignore_errors=True)
    log = out_dir / f"{name}.log"
    # A failure keeps the whole log for whoever has to fix it; a pass keeps the tail.
    log.write_text(output if code != 0 else output[-200_000:], encoding="utf-8")
    return {"stage": stage, "code": code, "output": output, "log": str(log), "shared": shared, "kept": kept,
            "started": started, "design": found}


def _checkout(root: Path, sha: str, tree: Path) -> bool | None:
    """Check out ``sha`` at ``tree``: True for a git worktree, False for a plain archive, None if neither worked.

    A worktree writes under .git, which some harness sandboxes protect (Codex's workspace-write does), so the
    same verify falls back to a snapshot through a throwaway index kept outside .git: ``read-tree`` then
    ``checkout-index`` writes every tracked file as a checkout would. Not ``git archive``: it honors
    ``export-ignore`` and ``export-subst``, so a repository that keeps tests out of its archives would pass
    with no tests run. Tests that need git history see no .git, but the files are the commit's either way.
    """
    if git(root, "worktree", "add", "--detach", "--quiet", str(tree), sha).returncode == 0:
        return True
    shutil.rmtree(tree, ignore_errors=True)
    tree.mkdir(parents=True)
    index = tree.parent / f"{tree.name}.index"
    env = {**os.environ, "GIT_INDEX_FILE": str(index)}
    try:
        for args in (["read-tree", sha], ["checkout-index", "--all", "--force", f"--prefix={tree}/"]):
            done = subprocess.run(["git", *args], cwd=root, env=env, capture_output=True, check=False)  # noqa: S603, S607
            if done.returncode != 0:
                return None
    finally:
        index.unlink(missing_ok=True)
    return False


def _shell(command: str, cwd: Path, timeout: float, extra: dict[str, str] | None = None) -> tuple[int, str]:
    env = {**{k: v for k, v in os.environ.items() if k not in ("COORDINATION_SESSION",)}, **(extra or {})}
    try:
        done = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True,  # noqa: S602 - owner's command
                              timeout=timeout, check=False, env=env)
        return done.returncode, done.stdout + done.stderr
    except subprocess.TimeoutExpired as error:
        return 124, f"{_text(error.stdout)}{_text(error.stderr)}\n(timed out)"


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def changed_files(root: Path, base: str, sha: str, inherited: list[str] | None = None) -> list[str] | None:
    """Files the unit's own commits change: those reachable from ``sha`` but not from ``base``
    or from any ``inherited`` commit (another unit's work it was built on). None if git can't tell.

    A unit built on a branch that isn't merged yet would otherwise answer for every file
    the units below it changed (Tablet's TASK-34 failed on 166 paths it never touched).
    """
    listed = git(root, "rev-list", sha, f"^{base}")
    if listed.returncode != 0:
        return None
    mine = set(listed.stdout.split())
    below = [f"^{c}" for c in dict.fromkeys(inherited or []) if c in mine and c != sha]
    plain = git(root, "log", "--no-merges", "--no-renames", "--name-only", "--format=", sha, f"^{base}", *below, "--")
    merges = git(root, "rev-list", "--merges", sha, f"^{base}", *below)
    if plain.returncode != 0 or merges.returncode != 0:
        return None
    files = {line for line in plain.stdout.splitlines() if line}
    for merge in merges.stdout.split():
        changed = merge_changes(root, merge)
        if changed is None:
            return None
        files |= changed
    return sorted(files)


def merge_changes(root: Path, merge: str) -> set[str] | None:
    """Files a merge commit changed itself: where its tree differs from git's own automatic merge of its parents.

    That catches a conflict resolution, an edit made while merging, and a merge that keeps one parent's
    whole file and so drops the other side's change, which ``--cc`` misses because the result equals a parent.
    Files the automatic merge would have produced anyway stay with the parents that brought them.
    """
    against_all = merge_baselines(root, merge)
    if against_all is None:
        return None
    files: set[str] = set()
    for against in against_all:
        found = git(root, "diff", "--no-renames", "--name-only", against, merge, "--")
        if found.returncode != 0:
            return None
        files |= {line for line in found.stdout.splitlines() if line}
    return files


def merge_baselines(root: Path, merge: str) -> list[str] | None:
    """What a merge commit's own changes are measured against: git's automatic merge of its two parents.
    An octopus merge, or a git too old for merge-tree --write-tree, has none, so every parent counts. That
    can over-count, never miss a change. None if git can't read the parents."""
    parents = git(root, "rev-parse", f"{merge}^@")
    if parents.returncode != 0:
        return None
    heads = parents.stdout.split()
    if len(heads) == 2:
        tried = git(root, "merge-tree", "--write-tree", "--no-messages", *heads)
        if tried.returncode in (0, 1) and tried.stdout.split():  # 1: conflicts; the tree holds conflict markers
            return [tried.stdout.split()[0]]
    return heads


def unit_files(project: Project, charter: dict[str, Any], task_id: str, sha: str) -> list[str] | None:
    """The files a unit's own commits change, reading past work other units verified."""
    others = [c for c, entry in ledger(project).items() if entry.get("task") != task_id]
    return changed_files(project.root, charter["git"]["base"], sha, others)


def tests_state(project: Project, charter: dict[str, Any], task: dict[str, Any], gates: dict[str, Any]) -> str:
    """'passed', 'failed', or 'not run' at the unit's commit; 'n/a' when the charter has no tests or it isn't code."""
    if not charter["verify"]["command"] or not needs_tests(task, gates):
        return "n/a"
    entry = ledger(project).get(commit_of(project.root, task) or "")
    if not entry:
        return "not run"
    if entry.get("setup_failed"):
        return "setup failed"
    if not entry["passed"]:
        return "failed"
    state = design_state(project, charter, task, entry)
    if state is None:
        return "passed"
    return "not run" if state[0] is None else ("passed" if state[0] else "failed")


def design_state(project: Project, charter: dict[str, Any], task: dict[str, Any],
                 entry: dict[str, Any]) -> tuple[bool | None, str] | None:
    """For a unit the design detector applies to: (passed, detail), passed None when it never ran for this unit
    at this commit (an older pass, or a run for another unit). None when the detector doesn't apply."""
    if not design.applies(project, charter, task):
        return None
    result = (entry.get("designs") or {}).get(task["id"])
    if not result:
        return None, f"the design detector hasn't run for {task['id']} at this commit: run softory verify {task['id']}"
    return bool(result["passed"]), result["detail"]


def needs_tests(task: dict[str, Any], gates: dict[str, Any]) -> bool:
    """Code units need softory verify; design deliverables don't."""
    return unit_of(task, gates) in CODE_UNITS and lane_of(task) not in NO_TEST_LANES


def checks(project: Project, charter: dict[str, Any], task: dict[str, Any], unit: str | None,
           gates: dict[str, Any]) -> list[dict[str, Any]]:
    """The gate's objective checks for a code unit. None apply until the charter configures them."""
    if unit not in CODE_UNITS:
        return []
    result = []
    command = charter["verify"]["command"]
    globs = (charter.get("lanes") or {}).get(lane_of(task) or "", [])
    process = (charter.get("simplify") or {}).get("process_paths") or []
    scan = (charter.get("secrets") or {}).get("scan", True)
    if not command and not globs and not process and not scan:
        return []
    sha = commit_of(project.root, task)
    if command and lane_of(task) not in NO_TEST_LANES:
        entry = ledger(project).get(sha or "")
        if not sha:
            result.append(_check("verified", False, "no commit evidence with a hash this repository has"))
        elif not entry:
            result.append(_check("verified", False, f"tests not run at {sha[:12]}: run softory verify {task['id']}"))
        else:
            how = "setup failed" if entry.get("setup_failed") else ("passed" if entry["passed"] else "failed")
            passed = bool(entry["passed"])
            state = design_state(project, charter, task, entry) if passed else None
            if state is not None:
                passed = bool(state[0])
                how += f"; design detector: {state[1]}" if state[0] is not None else f", but {state[1]}"
            result.append(_check("verified", passed, f"`{entry['command']}` {how} at {sha[:12]} ({entry['at']})"))
    if globs:
        result.append(_lane_check(project, charter, task, sha, globs, gates))
    if process and lane_of(task) not in NO_TEST_LANES:
        result.append(_process_check(project, charter, task, sha, process))
    if scan:
        others = [c for c, entry in ledger(project).items() if entry.get("task") != task["id"]]
        found = leaks.check(project.root, charter, sha, others)
        if found:
            result.append(found)
    return result


def _process_check(project: Project, charter: dict[str, Any], task: dict[str, Any], sha: str | None,
                   globs: list[str]) -> dict[str, Any]:
    """A unit that changes how work is built or delivered (scripts, CI, packaging) carries the process tag,
    so Sage reviews it. Tablet grew a 390-line installer and a zip per commit with nobody asked."""
    if "process" in tags_of(task):
        return _check("process_paths", True, "tagged process: Sage reviews it")
    if not sha:  # a PR link alone doesn't say which files changed
        return _check("process_paths", False, f"no commit to check for process paths: record it with softory commit "
                      f"{task['id']} <sha>, or tag it process if it changes scripts, CI, or packaging")
    files = unit_files(project, charter, task["id"], sha)
    if files is None:  # on by default, so a project whose git.base is off isn't stopped by it
        return _check("process_paths", True, f"git can't diff {sha[:12]} against {charter['git']['base']}; not checked")
    touched = [f for f in files if any(fnmatch.fnmatch(f, g) for g in globs)]
    if not touched:
        return _check("process_paths", True, "changes no process paths")
    listed = ", ".join(touched[:5]) + (f" and {len(touched) - 5} more" if len(touched) > 5 else "")
    return _check("process_paths", False, f"changes process paths ({listed}): tag it process so Sage reviews it")


def _lane_check(project: Project, charter: dict[str, Any], task: dict[str, Any], sha: str | None,
                globs: list[str], gates: dict[str, Any]) -> dict[str, Any]:
    if not sha:
        return _check("lane_paths", False, "no commit evidence to compare with the lane")
    files = unit_files(project, charter, task["id"], sha)
    if files is None:
        return _check("lane_paths", False, f"git can't diff {sha[:12]} against {charter['git']['base']}")
    allowed = [*globs, *(charter.get("shared_paths") or [])]
    outside = [f for f in files if not any(fnmatch.fnmatch(f, g) for g in allowed)]
    if not outside:
        return _check("lane_paths", True, f"{len(files)} changed file(s), all in lane:{lane_of(task)}")
    who = cross_lane_approvers(task, gates)
    accepting = set(gates["accepting_decisions"])
    accepted = sorted({(r.get("reviewer_id") or r.get("reviewer")) for r in task.get("reviews") or []
                       if (r.get("reviewer_id") or r.get("reviewer")) in who and r.get("decision") in accepting})
    listed = ", ".join(outside[:5]) + (f" and {len(outside) - 5} more" if len(outside) > 5 else "")
    if "cross-lane" in tags_of(task) and accepted:
        return _check("lane_paths", True, f"cross-lane, accepted by {', '.join(accepted)}: {listed}")
    return _check("lane_paths", False, f"outside lane:{lane_of(task)}: {listed}. Split the task, or tag it "
                  f"cross-lane and get an accepted review from {' or '.join(who) or 'quinn'}")


def cross_lane_approvers(task: dict[str, Any], gates: dict[str, Any]) -> list[str]:
    """Quinn accepts cross-lane work. When Quinn built it, Quinn's named backup for architecture does,
    as for an ``arch`` review, so Quinn's own work never waits on the owner."""
    built_by = builders(task)
    named = ["quinn"]
    if "quinn" in built_by:
        named = list((gates.get("tag_reviews") or {}).get("arch", {}).get("if_builder") or ["jade", "gold"])
    return [who for who in with_stand_ins(named, gates, task.get("id")) if who not in built_by]


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"check": name, "pass": bool(passed), "detail": detail}
