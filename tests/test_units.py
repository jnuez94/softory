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


if __name__ == "__main__":
    unittest.main()
