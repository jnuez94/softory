"""Pure unit tests for tags, IDs, hierarchy rules, and the gate."""

from __future__ import annotations

import json
import sys
import unittest

from tests.helpers import REPO

sys.path.insert(0, str(REPO / "lib"))

from softory import gate, grants, units  # noqa: E402
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

    def test_co_assigning_the_specialist_does_not_move_the_review(self) -> None:
        # Jade builds a security change and adds Toby: Toby can't review it, and Quinn doesn't stand in.
        item = task(tags="unit:task,parent:STORY-1,lane:frontend,security", assignees=["jade", "toby"],
                    reviews=[review("gold", "accepted"), review("quinn", "accepted")])
        report = self.evaluate(item, actor="jade")
        security = next(c for c in report["checks"] if c["check"] == "review:tag:security")
        self.assertFalse(security["pass"])
        self.assertIn("toby helped build it", security["detail"])

    def test_jade_or_gold_review_quinns_architecture(self) -> None:
        item = task(tags="unit:task,parent:STORY-1,lane:frontend,arch", assignees=["quinn"],
                    reviews=[review("jade", "accepted")])
        self.assertTrue(self.evaluate(item, actor="quinn")["pass"])


class ReviewRecordTest(unittest.TestCase):
    """A review run kept as a task is a record: its verdicts are output, and it is never reviewed again."""

    TARGETS = {"BUG-3": {"id": "BUG-3", "assignees": ["jade"]}, "TASK-2": {"id": "TASK-2", "assignees": ["gold"]}}

    def run_gate(self, tags: str = "unit:review,for:BUG-3,for:TASK-2", reviews: list | None = None,
                 target_reviews: dict | None = None, tasks: dict | None = None, actor: str = "avery", **fields) -> dict:
        item = task(id="REVIEW-1", tags=tags, assignees=["avery"], reviews=reviews or [], **fields)
        related = {"tasks": {**self.TARGETS, **(tasks or {})}, "reviews": target_reviews or {}}
        return gate.evaluate(item, GATES, {}, [], actor, related)

    def failing(self, report: dict) -> set:
        return {c["check"] for c in report["checks"] if not c["pass"]}

    def test_closes_once_every_target_has_the_builders_verdict(self) -> None:
        report = self.run_gate("unit:review,for:BUG-3,for:TASK-2,code-review,privacy", target_reviews={
            "BUG-3": [review("avery", "changes_requested")], "TASK-2": [review("avery", "accepted")]})
        self.assertTrue(report["pass"], report)

    def test_a_tag_needs_a_reviewer_qualified_for_it(self) -> None:
        tags = "unit:review,for:BUG-3,for:TASK-2,security"
        unqualified = self.run_gate(tags, reviews=[review("avery", "accepted")])
        self.assertEqual(self.failing(unqualified), {"review:tag:security"})
        self.assertIn("toby", next(c for c in unqualified["checks"] if c["check"] == "review:tag:security")["detail"])
        self.assertEqual([r["source"] for r in gate.required_reviews(task(id="REVIEW-1", tags=tags, assignees=["avery"]), GATES)],
                         ["tag:security"])
        signed = self.run_gate(tags, reviews=[review("avery", "accepted"), review("toby", "accepted")])
        self.assertTrue(signed["pass"], signed)
        item = task(id="REVIEW-1", tags=tags, assignees=["avery"], reviews=[review("avery", "accepted")])
        standing_in = dict(GATES, stand_ins=[{"agent": "avery", "roles": ["toby"]}])
        self.assertTrue(gate.evaluate(item, standing_in, {}, [], "avery", {"tasks": self.TARGETS})["pass"])

    def test_a_builder_cannot_relabel_their_own_security_fix(self) -> None:
        # Quinn's own security fix, relabelled as a review of someone else's task and self-accepted.
        fix = task(id="VR-SEC-FIX-001", tags="unit:review,for:TASK-2,security", assignees=["quinn"], status="todo",
                   evidence=[{"evidence_type": "artifact"}], reviews=[review("quinn", "accepted")])
        report = gate.evaluate(fix, GATES, {}, [], "quinn", {"tasks": self.TARGETS})
        self.assertEqual(self.failing(report), {"review:tag:security"})

    def test_own_changes_requested_with_filed_follow_ups_closes(self) -> None:
        # How Avery records reviews in VaultRadar: the verdict on the run, the fixes as follow-ups.
        verdict = dict(review("avery", "changes_requested"), follow_up_tasks="BUG-9 (Jade, frontend), BUG-10")
        report = self.run_gate(reviews=[verdict], tasks={"BUG-9": {"id": "BUG-9"}, "BUG-10": {"id": "BUG-10"}})
        self.assertTrue(report["pass"], report)

    def test_follow_ups_must_exist(self) -> None:
        verdict = dict(review("avery", "changes_requested"), follow_up_tasks="BUG-9,BUG-10")
        report = self.run_gate(reviews=[verdict], tasks={"BUG-9": {"id": "BUG-9"}, "BUG-10": None})
        self.assertEqual(self.failing(report), {"findings_tracked"})
        self.assertIn("BUG-10", next(c for c in report["checks"] if c["check"] == "findings_tracked")["detail"])

    def test_changes_without_follow_ups_hold_until_the_reviewer_accepts(self) -> None:
        held = self.run_gate(reviews=[review("avery", "changes_requested")])
        self.assertEqual(self.failing(held), {"findings_tracked"})
        later = self.run_gate(reviews=[review("avery", "changes_requested"), review("avery", "accepted")])
        self.assertTrue(later["pass"], later)

    def test_someone_elses_untracked_objection_holds(self) -> None:
        report = self.run_gate(reviews=[review("avery", "accepted"), review("greg", "changes_requested")])
        self.assertEqual(self.failing(report), {"findings_tracked"})

    def test_missing_verdict_fails(self) -> None:
        report = self.run_gate(target_reviews={"BUG-3": [review("gold", "accepted")]})
        verdicts = next(c for c in report["checks"] if c["check"] == "verdicts_recorded")
        self.assertFalse(verdicts["pass"])
        self.assertIn("BUG-3, TASK-2", verdicts["detail"])

    def test_holds_reports_not_code(self) -> None:
        report = self.run_gate(reviews=[review("avery", "accepted")], evidence=[{"evidence_type": "commit"}])
        self.assertEqual(self.failing(report), {"record_only"})

    def test_reviewer_cannot_review_their_own_work(self) -> None:
        report = self.run_gate(reviews=[review("avery", "accepted")], tasks={"BUG-3": {"id": "BUG-3", "assignees": ["avery"]}})
        self.assertEqual(self.failing(report), {"independent"})

    def test_needs_named_targets(self) -> None:
        self.assertIn("independent", self.failing(self.run_gate("unit:review", reviews=[review("avery", "accepted")])))

    def test_closes_from_blocked_but_not_from_someone_elses_claim(self) -> None:
        self.assertTrue(self.run_gate(reviews=[review("avery", "accepted")], status="blocked")["pass"])
        held = self.run_gate(reviews=[review("avery", "accepted")], status="in_progress", claimed_by="toby")
        self.assertIn("status", self.failing(held))

    def test_a_plain_review_tag_is_not_a_review_unit(self) -> None:
        report = gate.evaluate(task(id="VR-FIX-9", tags="review,security", assignees=["quinn"]), GATES, {}, [], "quinn")
        self.assertEqual(report["unit"], "legacy")

    def test_follow_up_ids_from_free_text(self) -> None:
        self.assertEqual(units.follow_up_ids("BUG-9 (Jade default frontend), BUG-10 (Gold); P2 VR-FIX-B005-006E."),
                         ["BUG-9", "BUG-10", "VR-FIX-B005-006E"])
        self.assertEqual(units.follow_up_ids(""), [])


class ScopedStandInTest(unittest.TestCase):
    """Stand-ins limited to tasks and dates, and never a side door around a named backup."""

    def gates(self, *grant_list: dict) -> dict:
        return dict(GATES, stand_ins=list(grant_list), today="2026-10-23")

    def threat_model(self, *reviews: dict, task_id: str = "VR-SEC-MODEL") -> dict:
        return task(id=task_id, tags="unit:task,parent:STORY-1,lane:backend,security", assignees=["toby"],
                    reviews=list(reviews))

    def security(self, report: dict) -> dict:
        return next(c for c in report["checks"] if c["check"] == "review:tag:security")

    def test_role_wide_stand_in_does_not_review_the_specialists_own_work(self) -> None:
        gates = self.gates({"agent": "avery", "roles": ["toby"]})
        report = gate.evaluate(self.threat_model(review("gold", "accepted"), review("avery", "accepted")), gates, {}, [], "toby")
        self.assertFalse(self.security(report)["pass"])
        self.assertIn("quinn", self.security(report)["detail"])

    def test_stand_in_scoped_to_the_task_does(self) -> None:
        gates = self.gates({"agent": "avery", "roles": ["toby"], "tasks": ["VR-SEC-MODEL"]})
        item = self.threat_model(review("gold", "accepted"), review("avery", "accepted"))
        self.assertTrue(gate.evaluate(item, gates, {}, [], "toby")["pass"])
        other = self.threat_model(review("gold", "accepted"), review("avery", "accepted"), task_id="VR-SEC-OTHER")
        self.assertFalse(gate.evaluate(other, gates, {}, [], "toby")["pass"])

    def test_expired_grant_lapses(self) -> None:
        item = task(reviews=[review("avery", "accepted")])
        live = self.gates({"agent": "avery", "roles": ["gold"], "until": "2026-10-23"})
        lapsed = self.gates({"agent": "avery", "roles": ["gold"], "until": "2026-10-22"})
        self.assertTrue(gate.evaluate(item, live, {}, [], "jade")["pass"])
        self.assertFalse(gate.evaluate(item, lapsed, {}, [], "jade")["pass"])

    def test_old_dict_format_still_reads(self) -> None:
        self.assertEqual(grants.normalize_stand_ins({"avery": ["jade", "gold"]})[0]["roles"], ["gold", "jade"])


class WaiverAndIntegrityTest(unittest.TestCase):
    def test_owner_waiver_passes_one_check_on_one_task(self) -> None:
        item = task(tags="unit:task,parent:STORY-1,lane:frontend,security", reviews=[review("gold", "accepted")])
        waiver = {"task": "TASK-1", "check": "review:tag:security", "reason": "no security surface", "decision": "D-1"}
        report = gate.evaluate(item, dict(GATES, waivers=[waiver]), {}, [], "jade")
        self.assertTrue(report["pass"], report)
        self.assertIn("waived by the owner (D-1)", next(c for c in report["checks"] if c["check"] == "review:tag:security")["detail"])
        other = task(id="TASK-2", tags=item["tags"], reviews=item["reviews"])
        self.assertFalse(gate.evaluate(other, dict(GATES, waivers=[waiver]), {}, [], "jade")["pass"])

    def test_core_checks_cannot_be_waived(self) -> None:
        waiver = {"task": "TASK-1", "check": "evidence", "reason": "x"}
        report = gate.evaluate(task(evidence_count=0, reviews=[review("gold", "accepted")]), dict(GATES, waivers=[waiver]), {}, [], "jade")
        self.assertFalse(report["pass"])

    def test_changed_rules_fail_closed(self) -> None:
        report = gate.evaluate(task(reviews=[review("gold", "accepted")]), dict(GATES, integrity={"changed": ["lib/softory/gate.py"]}), {}, [], "jade")
        self.assertEqual({c["check"] for c in report["checks"] if not c["pass"]}, {"config_intact"})


if __name__ == "__main__":
    unittest.main()


FAKE_CLI = '''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CLI_LOG"], "a") as log:
    log.write(" ".join(args) + "\\n")
tie = os.environ.get("FAKE_CLI_TIE") == "1"
second = "2026-10-24T10:00:01+00:00"
# Recorded in this order: REV-9 accepted, then REV-10 asks for changes.
nine = {"id": "REV-9", "reviewer_id": "gold", "decision": "accepted", "created_at": "2026-10-24T10:00:00+00:00"}
ten = {"id": "REV-10", "reviewer_id": "gold", "decision": "changes_requested", "created_at": second}
if tie:
    nine["created_at"] = second
if args[:2] == ["task", "show"]:
    shown = [ten, nine] if tie else [nine, ten]  # task show sorts by created_at, then ID text
    data = {"id": args[2], "reviews": shown}
elif args[:2] == ["review", "list"]:
    data = [dict(nine, sequence=1), dict(ten, sequence=2)]
else:
    data = None
print(json.dumps({"ok": True, "data": data}))
'''


class ReviewOrderTest(unittest.TestCase):
    """``task show`` sorts reviews by whole seconds, then ID, so REV-10 can come before REV-9."""

    def setUp(self) -> None:
        import os
        import tempfile
        from pathlib import Path

        from softory.coordination import Coordination

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        binary = Path(folder.name) / "coordination"
        binary.write_text(FAKE_CLI)
        binary.chmod(0o755)
        self.log = Path(folder.name) / "calls.log"
        self.coord = Coordination(binary, Path(folder.name))
        self.environ = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self.environ)))
        os.environ["FAKE_CLI_LOG"] = str(self.log)

    def test_a_tie_reads_reviews_in_the_order_they_were_recorded(self) -> None:
        import os

        os.environ["FAKE_CLI_TIE"] = "1"
        task = self.coord.task("TASK-1")
        self.assertEqual([r["id"] for r in task["reviews"]], ["REV-9", "REV-10"])
        self.assertEqual(gate.latest_reviews(task)["gold"]["decision"], "changes_requested")

    def test_no_tie_costs_no_extra_call(self) -> None:
        import os

        os.environ["FAKE_CLI_TIE"] = "0"
        self.assertEqual([r["id"] for r in self.coord.task("TASK-1")["reviews"]], ["REV-9", "REV-10"])
        self.assertEqual(self.log.read_text().splitlines(), ["task show TASK-1"])

    def test_an_inherited_database_path_is_ignored(self) -> None:
        import os

        os.environ["COORDINATION_DB"] = "/somewhere/else.sqlite3"
        os.environ["FAKE_CLI_TIE"] = "0"
        probe = self.log.parent / "env.txt"
        script = self.coord.binary.read_text().replace(
            "args = sys.argv[1:]", f"args = sys.argv[1:]\nopen({str(probe)!r}, 'w').write(os.environ.get('COORDINATION_DB', ''))")
        self.coord.binary.write_text(script)
        self.coord.task("TASK-1")
        self.assertEqual(probe.read_text(), "")


class ScaffoldBlockTest(unittest.TestCase):
    def test_refresh_swaps_only_the_scaffold_block(self) -> None:
        from softory import instructions

        start, end = instructions.SCAFFOLD_START, instructions.SCAFFOLD_END
        text = f"# Rules\n\n{start}\nold --cursor HEAD\n{end}\n\nUse tabs.\n"
        current = f"{start}\nnew head number\n{end}\n"
        self.assertEqual(instructions.refresh_scaffold_block(text, current),
                         f"# Rules\n\n{start}\nnew head number\n{end}\n\nUse tabs.\n")
        self.assertEqual(instructions.refresh_scaffold_block("# Rules\n", current), "# Rules\n")
        self.assertEqual(instructions.refresh_scaffold_block(text, None), text)
