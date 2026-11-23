"""Features removed in 0.6.11 stay removed: their commands, their settings, and the rule for untagged tasks."""

from __future__ import annotations

import json
import sys
import unittest

from tests.helpers import REPO, SOFTORY, run

sys.path.insert(0, str(REPO / "lib"))
from softory import charter as charters  # noqa: E402
from softory import gate  # noqa: E402

GATES = json.loads((REPO / "factory/governance/gates.json").read_text(encoding="utf-8"))
CHARTER = json.loads((REPO / "factory/governance/charter.json").read_text(encoding="utf-8"))


class RemovedCommandsTest(unittest.TestCase):
    def refused(self, *args: str) -> str:
        result = run([str(SOFTORY), *args], REPO, check=False)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        return result.stderr

    def test_adopt_settle_and_defer_are_not_commands(self) -> None:
        for command in ("adopt", "settle", "defer"):
            with self.subTest(command=command):
                self.assertIn("invalid choice", self.refused(command, "TASK-1"))

    def test_usage_takes_no_team_report(self) -> None:
        self.assertIn("unrecognized arguments: --team", self.refused("usage", "--team"))


class RemovedSettingsTest(unittest.TestCase):
    def test_the_charter_has_no_setting_for_a_removed_feature(self) -> None:
        self.assertNotIn("quinn_settles", CHARTER["decisions"])
        self.assertNotIn("escalate_model_after", CHARTER["task_caps"])
        self.assertNotIn("retry", CHARTER["verify"])
        self.assertEqual([role for role, pick in CHARTER["models"].items()
                          if isinstance(pick, dict) and "escalate" in pick], [])

    def test_a_charter_that_still_sets_one_is_told_the_setting_is_unknown(self) -> None:
        old = {"decisions": {"quinn_settles": True}, "task_caps": {"escalate_model_after": 2},
               "verify": {"retry": "true"}}
        self.assertEqual(charters.unknown_keys(CHARTER, old),
                         ["decisions.quinn_settles", "task_caps.escalate_model_after", "verify.retry"])

    def test_a_charter_approved_before_the_removal_can_still_be_changed(self) -> None:
        """Every charter approved before 0.6.11 that names a model holds ``escalate: null`` beside it."""
        saved = {"models": {"quinn": {"harness": "codex", "model": "m", "escalate": None, "also": []},
                            "avery": {"harness": "codex", "model": "m", "escalate": None}}}
        kept = charters.without_unset_escalation(saved)
        self.assertEqual(kept["models"], {"quinn": {"harness": "codex", "model": "m", "also": []},
                                          "avery": {"harness": "codex", "model": "m"}})
        self.assertEqual(charters.unknown_keys(CHARTER, kept), [])
        named = {"models": {"quinn": {"escalate": {"harness": "claude", "model": "big"}}}}
        self.assertEqual(charters.unknown_keys(CHARTER, charters.without_unset_escalation(named)),
                         ["models.quinn.escalate"])


class NoUnitTest(unittest.TestCase):
    def test_a_task_with_no_unit_does_not_pass_the_gate(self) -> None:
        self.assertNotIn("legacy", GATES)
        task = {"id": "VR-FIX-1", "title": "t", "status": "review", "tags": "", "assignees": ["quinn"],
                "evidence": [{"id": 1, "evidence_type": "commit", "summary": "abc1234"}], "dependencies": [],
                "reviews": [{"id": "R1", "reviewer": "avery", "decision": "accepted", "created_at": "2026-01-01"}]}
        report = gate.evaluate(task, GATES, {}, [], "quinn")
        self.assertFalse(report["pass"])
        unit = next(c for c in report["checks"] if c["check"] == "unit")
        self.assertFalse(unit["pass"])
        self.assertIn("unit:", unit["detail"])


if __name__ == "__main__":
    unittest.main()
