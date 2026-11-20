"""An accepted review covers the commit it was given for, and no later one.

Tablet's gate counted an accepted review whatever commit the unit delivered afterwards: Jade accepts
commit A, Gold records commit B, and the unit closes with B unreviewed. ``softory verify`` at B proves
the tests ran there, not that anyone read it. So a review that names a commit covers that commit only,
and one that names none (a report, a pull request link) covers what the unit had recorded when the
review was written. A release's sign-off is stricter: it must name the commit the release ships.

The gate, the review queue, and a handoff's requests all read ``stale_reviews``, so they agree.
"""

from __future__ import annotations

from typing import Any

from . import verify
from .gate import latest_reviews
from .project import Project
from .units import CODE_EVIDENCE, live_evidence, unit_of


#: Units that deliver one commit. A story or an epic is accepted for what its children delivered.
COVERED = ("task", "bug", "release")


def stale_reviews(project: Project, task: dict[str, Any]) -> list[str]:
    """Reviewers whose accepted review doesn't cover the commit the unit delivers now."""
    gates = project.gates()
    unit = unit_of(task, gates)
    sha = verify.commit_of(project.root, task) if unit in COVERED else None
    if not sha:
        return []  # no commit this repository knows: a document, or a unit not built yet
    strict = unit == "release"
    accepting = set(gates["accepting_decisions"])
    recorded = _recorded_at(project, task, sha)
    stale = []
    for who, review in latest_reviews(task).items():
        if review.get("decision") not in accepting:
            continue
        named = reviewed_commit(project, review)
        if named:
            covers = named == sha
        else:  # records are stamped to the second; a tie reads as covered
            covers = not strict and str(review.get("created_at") or "") >= recorded
        if not covers:
            stale.append(who)
    return sorted(stale)


def reviewed_commit(project: Project, review: dict[str, Any]) -> str | None:
    """The full hash of the commit a review's artifact names, read as ``verify.commit_of`` reads evidence:
    ``commit:<sha>`` or ``head=<sha>`` names it outright, and otherwise the artifact must name exactly one
    commit this repository has. A report path with a date in it, or a base beside a head, names none."""
    artifact = str(review.get("artifact_uri") or review.get("artifact") or "").lower()
    named = verify._HEAD.findall(artifact)  # noqa: SLF001
    candidates = named[-1:] if named else list(dict.fromkeys(verify._SHA.findall(artifact)))  # noqa: SLF001
    found = {full for full in (verify._resolve(project.root, c) for c in candidates) if full}  # noqa: SLF001
    return found.pop() if len(found) == 1 else None


def _recorded_at(project: Project, task: dict[str, Any], sha: str) -> str:
    """When the unit's evidence first named ``sha``."""
    for row in live_evidence(task.get("evidence")):
        if str(row.get("evidence_type", "")).lower() in CODE_EVIDENCE and sha in {
                verify._resolve(project.root, c)  # noqa: SLF001
                for c in verify._SHA.findall(str(row.get("uri", "")).lower())}:  # noqa: SLF001
            return str(row.get("created_at") or "")
    return ""


def check(project: Project, task: dict[str, Any]) -> dict[str, Any] | None:
    """The gate's ``reviews_cover_commit`` check, or None for a unit with no commit."""
    sha = verify.commit_of(project.root, task) if unit_of(task, project.gates()) in COVERED else None
    if not sha:
        return None
    stale = stale_reviews(project, task)
    return {"check": "reviews_cover_commit", "pass": not stale,
            "detail": f"accepted for another commit, not {sha[:12]}: {', '.join(stale)}. Each reviews again "
                      f"with --artifact {sha}" if stale else f"every accepted review covers {sha[:12]}"}
