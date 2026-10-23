"""Pure unit tests for tags, IDs, hierarchy rules, and the gate."""

from __future__ import annotations

import json
import sys
import unittest

from tests.helpers import REPO

sys.path.insert(0, str(REPO / "lib"))

from softory import gate, units  # noqa: E402
from softory.errors import SoftoryError  # noqa: E402

GATES = json.loads((REPO / "factory/governance/gates.json").read_text())


def task(**fields: object) -> dict:
    base = {"id": "TASK-1", "status": "review", "tags": "unit:task,parent:STORY-1,lane:frontend",
            "assignees": ["jade"], "claimed_by": None, "evidence_count": 1, "dependencies": [], "reviews": []}
    base.update(fields)
    return base


def review(reviewer: str, decision: str) -> dict:
    return {"reviewer_id": reviewer, "decision": decision}


class UnitsTest(unittest.TestCase):
    def test_next_id_skips_other_prefixes_and_gaps(self) -> None:
        self.assertEqual(units.next_id("TASK", ["TASK-1", "TASK-7", "STORY-9", "TASK-x"]), "TASK-8")
        self.assertEqual(units.next_id("EPIC", []), "EPIC-1")

    def test_build_tags(self) -> None:
        self.assertEqual(units.build_tags("task", "STORY-2", "backend", ["auth", "auth"]),
                         "unit:task,parent:STORY-2,lane:backend,auth")
        with self.assertRaises(SoftoryError):
            units.build_tags("task", "STORY-2", None, [])
        with self.assertRaises(SoftoryError):
            units.build_tags("story", None, "frontend", [])
        with self.assertRaises(SoftoryError):
            units.build_tags("task", "STORY-2", "backend", ["lane:frontend"])

    def test_parent_rules(self) -> None:
        units.check_parent("story", "epic", "EPIC-1")
        units.check_parent("bug", None, None)
        with self.assertRaises(SoftoryError):
            units.check_parent("task", None, None)
        with self.assertRaises(SoftoryError):
            units.check_parent("story", "story", "STORY-1")

    def test_review_and_follow_up_tags(self) -> None:
        self.assertEqual(units.build_tags("review", None, None, ["ui"], ["BUG-3", "BUG-3", "TASK-2"]),
                         "unit:review,for:BUG-3,for:TASK-2,ui")
        self.assertEqual(units.build_tags("bug", "STORY-1", "backend", [], source="TASK-4"),
                         "unit:bug,parent:STORY-1,lane:backend,from:TASK-4")
        with self.assertRaises(SoftoryError):
            units.build_tags("review", None, None, [])  # a review names what it reviewed
        with self.assertRaises(SoftoryError):
            units.build_tags("task", "STORY-1", "backend", [], ["BUG-3"])
        with self.assertRaises(SoftoryError):
            units.build_tags("task", "STORY-1", "backend", ["for:BUG-3"])
        self.assertEqual(units.targets_of({"tags": "unit:review,for:BUG-3,for:TASK-2"}), ["BUG-3", "TASK-2"])

    def test_unit_falls_back_to_id_prefix(self) -> None:
        self.assertEqual(units.unit_of({"id": "BUG-3", "tags": ""}, GATES), "bug")
        self.assertIsNone(units.unit_of({"id": "X-3", "tags": ""}, GATES))


class GateTest(unittest.TestCase):
    def evaluate(self, item: dict, actor: str | None = "jade", deps: dict | None = None, children: list | None = None) -> dict:
        return gate.evaluate(item, GATES, deps or {}, children or [], actor)

    def test_passes_with_peer_review(self) -> None:
        self.assertTrue(self.evaluate(task(reviews=[review("gold", "accepted")]))["pass"])

    def test_latest_review_wins(self) -> None:
        reviews = [review("gold", "accepted"), review("gold", "changes_requested")]
        self.assertFalse(self.evaluate(task(reviews=reviews))["pass"])

    def test_open_blocking_dependency(self) -> None:
        dep = {"depends_on_task_id": "TASK-0", "dependency_type": "blocks", "status": "active"}
        result = self.evaluate(task(dependencies=[dep], reviews=[review("gold", "accepted")]), deps={"TASK-0": "todo"})
        self.assertFalse(result["pass"])
        resolved = dict(dep, status="resolved")
        self.assertTrue(self.evaluate(task(dependencies=[resolved], reviews=[review("gold", "accepted")]))["pass"])

    def test_no_evidence(self) -> None:
        self.assertFalse(self.evaluate(task(evidence_count=0, reviews=[review("gold", "accepted")]))["pass"])

    def test_flex_builder_cannot_review_as_peer(self) -> None:
        # Gold built a frontend task under the flex rule; only Jade's review counts.
        item = task(assignees=["gold"], reviews=[review("gold", "accepted")])
        self.assertFalse(self.evaluate(item, actor="gold")["pass"])
        item["reviews"].append(review("jade", "accepted"))
        self.assertTrue(self.evaluate(item, actor="gold")["pass"])


class StandInTest(unittest.TestCase):
    """Avery stands in for Jade and Gold, as on a project that already had a reviewer."""

    GATES = dict(GATES, stand_ins={"avery": ["jade", "gold"]})

    def evaluate(self, item: dict, actor: str = "jade") -> dict:
        return gate.evaluate(item, self.GATES, {}, [], actor)

    def test_stand_in_review_counts_for_the_peer_review(self) -> None:
        self.assertTrue(self.evaluate(task(reviews=[review("avery", "accepted")]))["pass"])

    def test_stand_in_never_reviews_its_own_build(self) -> None:
        item = task(assignees=["avery"], reviews=[review("avery", "accepted")])
        self.assertFalse(self.evaluate(item, actor="avery")["pass"])

    def test_stand_in_does_not_cover_other_roles(self) -> None:
        item = task(tags="unit:task,parent:STORY-1,lane:frontend,data", reviews=[review("avery", "accepted")])
        failing = {c["check"] for c in self.evaluate(item)["checks"] if not c["pass"]}
        self.assertEqual(failing, {"review:tag:data"})

    def test_stand_in_may_close_for_a_named_closer(self) -> None:
        gates = dict(GATES, stand_ins={"pat": ["greg"]})
        story = task(id="STORY-1", tags="unit:story,parent:EPIC-1", assignees=["greg"], reviews=[review("greg", "accepted")])
        self.assertTrue(gate.evaluate(story, gates, {}, [], "pat")["pass"])


class LegacyTest(unittest.TestCase):
    """Tasks created before softory: no unit tag, project-style IDs."""

    def evaluate(self, item: dict, actor: str = "quinn") -> dict:
        return gate.evaluate(item, GATES, {}, [], actor)

    def legacy(self, **fields: object) -> dict:
        return task(id="VR-FIX-1", tags="", assignees=["quinn"], **fields)

    def test_any_independent_review_passes(self) -> None:
        report = self.evaluate(self.legacy(reviews=[review("avery", "accepted")]))
        self.assertTrue(report["pass"], report)
        self.assertEqual(report["unit"], "legacy")

    def test_builder_review_never_counts(self) -> None:
        self.assertFalse(self.evaluate(self.legacy(reviews=[review("quinn", "accepted")]))["pass"])

    def test_rejection_still_blocks(self) -> None:
        reviews = [review("avery", "accepted"), review("darwin", "changes_requested")]
        self.assertFalse(self.evaluate(self.legacy(reviews=reviews))["pass"])

    def test_owner_or_assignee_closes(self) -> None:
        item = self.legacy(reviews=[review("avery", "accepted")])
        self.assertTrue(self.evaluate(item, actor="owner")["pass"])
        self.assertFalse(self.evaluate(item, actor="avery")["pass"])

    def test_without_a_legacy_rule_no_unit_fails(self) -> None:
        gates = {k: v for k, v in GATES.items() if k != "legacy"}
        report = gate.evaluate(self.legacy(reviews=[review("avery", "accepted")]), gates, {}, [], "quinn")
        self.assertFalse(report["pass"])


class BackupReviewerTest(unittest.TestCase):
    """When the only reviewer a tag names built the task, its if_builder backup reviews."""

    def evaluate(self, item: dict, actor: str = "toby") -> dict:
        return gate.evaluate(item, GATES, {}, [], actor)

    def threat_model(self, *reviews: dict) -> dict:
        return task(id="VR-SEC-MODEL", tags="security,threat-model", assignees=["toby"], reviews=list(reviews))

    def test_quinn_reviews_tobys_own_security_work(self) -> None:
        report = self.evaluate(self.threat_model(review("avery", "accepted")))
        security = next(c for c in report["checks"] if c["check"] == "review:tag:security")
        self.assertIn("toby built it, so quinn reviews", security["detail"])
        self.assertFalse(security["pass"])
        self.assertTrue(self.evaluate(self.threat_model(review("avery", "accepted"), review("quinn", "accepted")))["pass"])

    def test_toby_still_never_reviews_his_own(self) -> None:
        self.assertFalse(self.evaluate(self.threat_model(review("avery", "accepted"), review("toby", "accepted")))["pass"])

    def test_backup_only_when_the_specialist_built_it(self) -> None:
        item = task(tags="unit:task,parent:STORY-1,lane:frontend,security", reviews=[review("gold", "accepted"), review("quinn", "accepted")])
        failing = {c["check"] for c in self.evaluate(item, actor="jade")["checks"] if not c["pass"]}
        self.assertEqual(failing, {"review:tag:security"})  # Toby is free to review, so Quinn's doesn't count

    def test_jade_or_gold_review_quinns_architecture(self) -> None:
        item = task(tags="unit:task,parent:STORY-1,lane:frontend,arch", assignees=["quinn"],
                    reviews=[review("jade", "accepted")])
        self.assertTrue(self.evaluate(item, actor="quinn")["pass"])


class ReviewUnitTest(unittest.TestCase):
    """A review run kept as a task: it closes on the verdicts it recorded, not on a review of itself."""

    def run_gate(self, tags: str, target_reviews: dict, actor: str = "avery") -> dict:
        item = task(id="REVIEW-1", tags=tags, assignees=["avery"])
        return gate.evaluate(item, GATES, {}, [], actor, target_reviews)

    def test_closes_once_every_target_has_the_builders_verdict(self) -> None:
        report = self.run_gate("unit:review,for:BUG-3,for:TASK-2,security,ui",
                               {"BUG-3": [review("avery", "changes_requested")], "TASK-2": [review("avery", "accepted")]})
        self.assertTrue(report["pass"], report)
        self.assertNotIn("review:tag:security", {c["check"] for c in report["checks"]})

    def test_missing_verdict_fails(self) -> None:
        report = self.run_gate("unit:review,for:BUG-3,for:TASK-2", {"BUG-3": [review("gold", "accepted")]})
        verdicts = next(c for c in report["checks"] if c["check"] == "verdicts_recorded")
        self.assertFalse(verdicts["pass"])
        self.assertIn("BUG-3, TASK-2", verdicts["detail"])

    def test_needs_named_targets(self) -> None:
        self.assertFalse(self.run_gate("unit:review", {})["pass"])

    def test_a_plain_review_tag_is_not_a_review_unit(self) -> None:
        report = gate.evaluate(task(id="VR-FIX-9", tags="review,security", assignees=["quinn"]), GATES, {}, [], "quinn")
        self.assertEqual(report["unit"], "legacy")


if __name__ == "__main__":
    unittest.main()
