"""Deploys: the charter's targets (preview, staging, production), each a command plus a smoke test.

``softory deploy <target>`` runs a target's ``command`` and then its ``smoke`` in a clean checkout of
one commit, only after ``softory verify`` passed there, and logs the outcome. ``softory ship`` deploys
every ``auto`` target after it merges. A release unit closes only when every target but production
passed at its commit, and production deploys only a closed release, by the owner at a terminal.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import verify, verifyenv
from .coordination import Coordination
from .errors import SoftoryError
from .gitlocal import git
from .project import Project
from .units import live_evidence, unit_of

PRODUCTION = "production"


def targets(charter: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(t.get("name")): t for t in (charter.get("deploy") or {}).get("targets") or []}


def problems(charter: dict[str, Any]) -> list[str]:
    """What's wrong with the deploy targets, for softory charter."""
    found, names = [], []
    for target in (charter.get("deploy") or {}).get("targets") or []:
        name = target.get("name") if isinstance(target, dict) else None
        if not name or not target.get("command"):
            found.append("each deploy target needs a name and a command")
            continue
        if name in names:
            found.append(f"deploy target {name} is listed twice")
        names.append(name)
        if name == PRODUCTION and target.get("auto"):
            found.append("production can't be an auto target: the owner deploys it")
    if names and not charter["verify"].get("command"):
        found.append("deploy targets need verify.command: softory deploys only a commit whose tests passed")
    return found


def log_path(project: Project) -> Path:
    return project.state / "deploys.jsonl"


def history(project: Project) -> list[dict[str, Any]]:
    try:
        lines = log_path(project).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def passed_at(project: Project, name: str, sha: str) -> bool:
    """Whether the latest deploy of ``sha`` to ``name`` passed, smoke test included."""
    rows = [r for r in history(project) if r.get("target") == name and r.get("commit") == sha]
    return bool(rows) and bool(rows[-1].get("passed"))


def run(project: Project, coord: Coordination, charter: dict[str, Any], name: str, actor: str, sha: str | None = None,
        release: str | None = None, confirm: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Deploy one commit to one target and record it. Production takes a closed release and the owner's yes."""
    target = targets(charter).get(name)
    if target is None:
        raise SoftoryError(f"The charter has no deploy target {name!r}; it lists {', '.join(targets(charter)) or 'none'}",
                           "not_found")
    task = coord.task(release) if release else None
    if task is not None:
        if unit_of(task, project.gates()) != "release":
            raise SoftoryError(f"{release} is not a release unit", "not_allowed")
        recorded = verify.commit_of(project.root, task)
        if not recorded:
            raise SoftoryError(f"{release} records no commit; it ships the commit it was reviewed at", "not_allowed")
        if sha and _full(project, sha) != recorded:
            raise SoftoryError(f"{release} ships {recorded[:12]}, not {sha[:12]}: a release deploys only its own "
                               "commit", "not_allowed")
        sha = recorded
    sha = _full(project, sha or charter["git"]["base"])
    if name == PRODUCTION:
        if not task or task.get("status") != "done":
            raise SoftoryError("Production deploys a closed release: softory deploy production --release <ID>",
                               "not_allowed")
        if confirm is None:
            raise SoftoryError("Only the owner deploys to production, at a terminal", "not_allowed")
        confirm(f"Deploy {release} ({sha[:12]}) to production?")
    entry = verify.ledger(project).get(sha) or {}
    if not entry.get("passed"):
        raise SoftoryError(f"softory verify hasn't passed at {sha[:12]}; deploy only tested commits", "not_verified")
    with verifyenv.turn(project, f"deploy:{name}", actor):
        outcome = _deploy(project, charter, target, sha)
    row = {"target": name, "commit": sha, "passed": outcome["passed"], "stage": outcome["stage"], "by": actor,
           "release": release, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "log": outcome["log"]}
    with log_path(project).open("a", encoding="utf-8") as out:
        out.write(json.dumps(row) + "\n")
    if release:
        verdict = "pass" if outcome["passed"] else "fail"
        coord.run("evidence", "add", "--task", release, "--uri", f"softory-deploy:{name}:{verdict}:{sha}",
                  "--type", "deploy", "--actor", actor)
    return {**row, "tail": outcome["tail"]}


def _deploy(project: Project, charter: dict[str, Any], target: dict[str, Any], sha: str) -> dict[str, Any]:
    place = Path(tempfile.mkdtemp(prefix="softory-deploy-"))
    tree = place / "tree"
    worktree = verify._checkout(project.root, sha, tree)  # noqa: SLF001 - the same clean checkout verify uses
    if worktree is None:
        shutil.rmtree(place, ignore_errors=True)
        raise SoftoryError(f"git couldn't check out {sha[:12]}", "git_error")
    settings = charter["verify"]
    timeout = float(target.get("timeout_minutes") or settings["timeout_minutes"]) * 60
    stage, code, output = "deploy", 0, ""
    extra = {"SOFTORY_DEPLOY_TARGET": str(target["name"]), "SOFTORY_DEPLOY_COMMIT": sha}
    try:
        for path in settings.get("share") or []:
            source = project.root / path
            if source.exists() and not (tree / path).exists():
                verifyenv.share(source, tree / path, settings.get("share_mode") or "clone")
        code, output = verify._shell(target["command"], tree, timeout, extra)  # noqa: SLF001
        if code == 0 and target.get("smoke"):
            stage = "smoke"
            code, more = verify._shell(target["smoke"], tree, timeout, extra)  # noqa: SLF001
            output += more
    finally:
        if worktree:
            git(project.root, "worktree", "remove", "--force", str(tree))
        shutil.rmtree(place, ignore_errors=True)
    folder = project.state / "deploys"
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / f"{target['name']}-{sha[:12]}.log"
    log.write_text(output[-200_000:], encoding="utf-8")
    return {"passed": code == 0, "stage": stage, "log": str(log),
            "tail": "\n".join(output.splitlines()[-verify.TAIL_LINES:])}


def _full(project: Project, ref: str) -> str:
    found = git(project.root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if found.returncode != 0:
        raise SoftoryError(f"{ref} is not a commit in this repository", "not_found")
    return found.stdout.strip()


def release_checks(project: Project, charter: dict[str, Any], task: dict[str, Any],
                   gates: dict[str, Any]) -> list[dict[str, Any]]:
    """A release's own checks: a rollback plan, and a passing deploy to every target but production."""
    spec = (gates["units"].get("release") or {}).get("release") or {}
    kinds = set(spec.get("rollback_evidence") or ["rollback"])
    plans = [r for r in live_evidence(task.get("evidence")) if str(r.get("evidence_type", "")).lower() in kinds]
    result = [{"check": "rollback_plan", "pass": bool(plans),
               "detail": f"rollback plan: {plans[-1].get('uri')}" if plans else
               f"needs a rollback plan: softory report {task['id']} <file> --type rollback"}]
    sha = verify.commit_of(project.root, task)
    staged = [n for n in targets(charter) if n != PRODUCTION]
    if not sha:
        result.append({"check": "staged", "pass": False, "detail": "no commit evidence naming what it ships"})
    elif not staged:
        result.append({"check": "staged", "pass": True, "detail": "the charter declares no target before production"})
    else:
        missing = [n for n in staged if not passed_at(project, n, sha)]
        result.append({"check": "staged", "pass": not missing,
                       "detail": f"not deployed and smoke-tested at {sha[:12]}: {', '.join(missing)}. Run softory "
                                 f"deploy <target> --release {task['id']}" if missing else
                                 f"{', '.join(staged)} passed at {sha[:12]}"})
    return result
