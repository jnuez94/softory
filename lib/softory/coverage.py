"""An accepted review covers the commit it was given for, and no later one.

Tablet's gate counted an accepted review whatever commit the unit delivered afterwards: Jade accepts
commit A, Gold records commit B, and the unit closes with B unreviewed. ``softory verify`` at B proves
the tests ran there, not that anyone read it. So a review that names a commit covers that commit only,
and one that names none (a report, a pull request link) covers the commit the unit delivered when the
review was written. A release's sign-off is stricter: it must name the commit the release ships.

Only required reviews count. A sign-off nobody required holds nothing, and a requirement one reviewer
covers at the commit is met whoever else accepted an earlier one. The gate, the review queue, and a
handoff's requests all read ``stale_reviews``, so they agree.
"""

from __future__ import annotations

from typing import Any

from . import verify
from .gate import builders, eligible, latest_reviews, required_reviews
from .project import Project
from .units import unit_of


#: Units that deliver one commit. A story or an epic is accepted for what its children delivered.
COVERED = ("task", "bug", "release")


def stale_reviews(project: Project, task: dict[str, Any]) -> list[str]:
    """Reviewers whose accepted review doesn't cover the commit the unit delivers now."""
    gates = project.gates()
    unit = unit_of(task, gates)
    sha = verify.commit_of(project.root, task) if unit in COVERED else None
    if not sha:
        return []  # no commit this repository knows: a document, or a unit not built yet
    accepting = set(gates["accepting_decisions"])
    stale = []
    for who, review in latest_reviews(task).items():
        if review.get("decision") not in accepting:
            continue
        named = reviewed_commit(project, review)
        if named:
            covers = named == sha
        else:  # a report or a link: it read what the unit delivered when it was written
            covers = unit != "release" and _delivered_at(project, task, str(review.get("created_at") or "")) == sha
        if not covers:
            stale.append(who)
    return sorted(stale)


def reviewed_commit(project: Project, review: dict[str, Any]) -> str | None:
    """The full hash of the one commit a review's artifact names, read as ``verify.commit_of`` reads
    evidence. A report path with a date in it, or a base beside a head, names none."""
    return verify.named_commit(project.root, str(review.get("artifact_uri") or review.get("artifact") or ""))


def _delivered_at(project: Project, task: dict[str, Any], when: str) -> str | None:
    """The commit the unit delivered at ``when``, read from its evidence as it stood then: rows recorded
    since are left out, retractions among them, so a later ``softory supersede`` can't move an old review
    onto another commit. Records are stamped to the second; a row in the same second counts as there."""
    then = [row for row in task.get("evidence") or [] if str(row.get("created_at") or "") <= when]
    return verify.commit_of(project.root, {"evidence": then})


def check(project: Project, task: dict[str, Any]) -> dict[str, Any] | None:
    """The gate's ``reviews_cover_commit`` check, or None for a unit with no commit. It fails when a
    required review's only acceptances are for another commit."""
    gates = project.gates()
    sha = verify.commit_of(project.root, task) if unit_of(task, gates) in COVERED else None
    if not sha:
        return None
    stale = set(stale_reviews(project, task))
    accepting = set(gates["accepting_decisions"])
    latest = latest_reviews(task)
    owed = []
    for requirement in required_reviews(task, gates):
        accepted = [r for r in eligible(requirement, builders(task)) if latest.get(r, {}).get("decision") in accepting]
        if accepted and all(r in stale for r in accepted):
            owed += [r for r in accepted if r not in owed]
    return {"check": "reviews_cover_commit", "pass": not owed,
            "detail": f"accepted for another commit, not {sha[:12]}: {', '.join(owed)}. Each reviews again "
                      f"with --artifact {sha}" if owed else f"every required review covers {sha[:12]}"}
