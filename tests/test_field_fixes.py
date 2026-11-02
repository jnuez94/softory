"""Pure tests for 0.4.2: the fixes from the 2026-11-01 field report on Vault Radar."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO

sys.path.insert(0, str(REPO / "lib"))

from softory import charter, digest, gate, perms, records, runner, team, units, verify, verifyenv, watch  # noqa: E402

GATES = json.loads((REPO / "factory/governance/gates.json").read_text())


class FakeBoard:
    def __init__(self, tasks: list[dict], reviews: dict[str, list[dict]]) -> None:
        self.gates = GATES
        self.tasks = tasks
        self.by_id = {t["id"]: t for t in tasks}
        self.reviews = reviews


def asked(text: str = "blocking: fix it") -> dict:
    return {"reviewer_id": "avery", "decision": "changes_requested", "required_changes": text}


class ReviewRoundsTest(unittest.TestCase):
    def test_review_records_never_count_toward_the_cap(self) -> None:
        board = FakeBoard([{"id": "REVIEW-1", "tags": "unit:review"}, {"id": "TASK-1", "tags": "unit:task"}],
                          {"REVIEW-1": [asked()] * 5, "TASK-1": [asked()] * 2})
        self.assertEqual(watch.review_rounds(board), {"TASK-1": 2})

    def test_one_evidence_only_round_is_free(self) -> None:
        rows = [asked(), asked("evidence: screenshot at 1440\nEvidence: trace at the head"), asked("evidence: again")]
        board = FakeBoard([{"id": "TASK-1", "tags": "unit:task"}], {"TASK-1": rows})
        self.assertEqual(watch.review_rounds(board, 1), {"TASK-1": 2})
        self.assertEqual(watch.review_rounds(board, 0), {"TASK-1": 3})

    def test_a_mixed_request_is_not_evidence_only(self) -> None:
        self.assertFalse(watch.evidence_only(asked("evidence: screenshot; blocking: null check")))
        self.assertFalse(watch.evidence_only(asked("")))


class DesignLaneTest(unittest.TestCase):
    def test_greg_reviews_a_design_task_instead_of_the_engineers(self) -> None:
        task = {"id": "TASK-9", "tags": "unit:task,parent:STORY-1,lane:design", "assignees": ["darwin"]}
        reviewers = [r["reviewers"] for r in gate.required_reviews(task, GATES)]
        self.assertEqual(reviewers, [["greg"]])

    def test_a_code_task_keeps_peer_review(self) -> None:
        task = {"id": "TASK-8", "tags": "unit:task,parent:STORY-1,lane:frontend", "assignees": ["jade"]}
        self.assertEqual([r["reviewers"] for r in gate.required_reviews(task, GATES)], [["jade", "gold"]])

    def test_design_work_needs_no_test_run(self) -> None:
        self.assertFalse(verify.needs_tests({"id": "TASK-9", "tags": "unit:task,lane:design"}, GATES))
        self.assertTrue(verify.needs_tests({"id": "TASK-8", "tags": "unit:task,lane:backend"}, GATES))
        self.assertIn("design", units.LANES)


class EvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        run = lambda *a: subprocess.run(["git", *a], cwd=self.root, check=True, capture_output=True, text=True)  # noqa: E731
        run("init", "-q")
        run("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "base")
        self.base = run("rev-parse", "HEAD").stdout.strip()
        run("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "head")
        self.head = run("rev-parse", "HEAD").stdout.strip()

    def row(self, number: int, uri: str, kind: str = "commit") -> dict:
        return {"id": number, "evidence_type": kind, "uri": uri}

    def test_free_text_naming_head_and_base_is_ambiguous(self) -> None:
        text = f"{self.head[:7]} (fix branch on {self.base[:7]})"
        self.assertIsNone(verify.commit_of(self.root, {"evidence": [self.row(1, text)]}))

    def test_structured_commit_names_the_head(self) -> None:
        uri = f"commit:{self.head};base={self.base}"
        self.assertEqual(verify.commit_of(self.root, {"evidence": [self.row(1, uri)]}), self.head)
        legacy = f"fix on {self.base[:7]}, head={self.head[:9]}"
        self.assertEqual(verify.commit_of(self.root, {"evidence": [self.row(1, legacy)]}), self.head)

    def test_superseded_evidence_is_read_past(self) -> None:
        rows = [self.row(1, f"commit:{self.base}"), self.row(2, f"commit:{self.head}"),
                self.row(3, "softory-supersedes:2:SOFTORY-DEC-X", "note")]
        self.assertEqual(verify.commit_of(self.root, {"evidence": rows}), self.base)
        self.assertEqual(units.code_evidence_types({"evidence": rows}), ["commit"])
        self.assertEqual(units.code_evidence_types({"evidence": rows[1:]}), [])


class TriageTest(unittest.TestCase):
    def test_a_review_named_task_that_shipped_code_is_not_a_review_run(self) -> None:
        built = {"id": "VR-FOUNDATION-REVIEW-TS-001", "title": "Fix lint", "tags": "",
                 "evidence": [{"evidence_type": "commit", "uri": "commit:abc"}]}
        run = {"id": "VR-REVIEW-BATCH-006", "title": "Independent review queue", "tags": "",
               "evidence": [{"evidence_type": "report", "uri": "files/reviews/x.md"}]}
        self.assertFalse(team._looks_like_review_run(built))  # noqa: SLF001
        self.assertTrue(team._looks_like_review_run(run))  # noqa: SLF001


class OwnerTextTest(unittest.TestCase):
    def test_escalation_text_must_read_at_a_glance(self) -> None:
        problems = records.text_problems("BUG60 source records contain9 changes; runnerusage0", "Approve one cycle")
        self.assertTrue(any("question" in p for p in problems))
        self.assertTrue(any("contain9" in p and "runnerusage0" in p for p in problems))
        self.assertEqual(records.text_problems("BUG-60 has 9 rounds at e3e4ab5fdbad.", "Approve one more cycle?"), [])
        self.assertTrue(records.text_problems("x" * 700, "Ok?"))

    def test_charter_diff_lists_only_what_changes(self) -> None:
        before = {"verify": {"command": "npm test", "share": [], "description": "x"}, "vision": "a"}
        after = {"verify": {"command": "npm test", "share": [".web/node_modules"], "description": "y"}, "vision": "a"}
        self.assertEqual(charter.diff(before, after), ['verify.share: [] -> [".web/node_modules"]'])

    def test_digest_cuts_on_a_word(self) -> None:
        self.assertEqual(digest._cut("one two three", 9), "one two…")  # noqa: SLF001
        self.assertEqual(digest._cut("short", 50), "short")  # noqa: SLF001


class VerifyEnvTest(unittest.TestCase):
    def test_shared_folders_are_copies_an_installer_cannot_delete(self) -> None:
        place = Path(tempfile.mkdtemp())
        source = place / "main" / "node_modules"
        (source / "pkg").mkdir(parents=True)
        (source / "pkg" / "index.js").write_text("x")
        target = place / "tree" / "node_modules"
        how = verifyenv.share(source, target, "clone")
        self.assertIn(how, ("cloned", "copied"))
        self.assertFalse(target.is_symlink())
        subprocess.run(["rm", "-rf", str(target)], check=True)
        self.assertTrue((source / "pkg" / "index.js").is_file())

    def test_failure_artifacts_are_kept(self) -> None:
        place = Path(tempfile.mkdtemp())
        (place / "tree" / "results" / "trace").mkdir(parents=True)
        (place / "tree" / "results" / "trace" / "t.zip").write_text("z")
        kept = verifyenv.keep_artifacts(place / "tree", ["results/**/*.zip"], place / "kept")
        self.assertEqual(kept, ["results/trace/t.zip"])
        self.assertTrue((place / "kept" / "results" / "trace" / "t.zip").is_file())


DEFAULT_CHARTER = json.loads((REPO / "factory/governance/charter.json").read_text())


class ReviewFollowUpTest(unittest.TestCase):
    """The six findings on the 0.4.2 pull request."""

    def test_withdrawn_evidence_does_not_satisfy_the_evidence_check(self) -> None:
        record = {"id": "REVIEW-1", "status": "review", "tags": "unit:review,for:TASK-1", "assignees": ["avery"],
                  "evidence_count": 2, "dependencies": [], "reviews": [],
                  "evidence": [{"id": 1, "evidence_type": "report", "uri": "files/r.md"},
                               {"id": 2, "evidence_type": "note", "uri": "softory-supersedes:1:SOFTORY-DEC-X"}]}
        check = next(c for c in gate.evaluate(record, GATES, {}, [], "avery")["checks"] if c["check"] == "evidence")
        self.assertFalse(check["pass"])
        self.assertIn("not counting 2", check["detail"])

    def test_darwin_may_edit_the_design_lane_paths(self) -> None:
        self.assertEqual(perms.role_paths(DEFAULT_CHARTER, "darwin"), ["docs/design/**"])
        wider = charter.merge(DEFAULT_CHARTER, {"lanes": {"design": ["design/**"]}})
        self.assertEqual(perms.role_paths(wider, "darwin"), ["docs/design/**", "design/**"])
        self.assertNotIn("darwin", perms.unscoped(DEFAULT_CHARTER))

    def test_a_machine_without_cron_reports_no_scheduler(self) -> None:
        real = runner.subprocess.run

        def missing(command, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            if command[0] in ("crontab", "launchctl"):
                raise FileNotFoundError(command[0])
            return real(command, *args, **kwargs)

        class Fake:
            root = Path(tempfile.mkdtemp())
            bundle = root

        runner.subprocess.run = missing
        try:
            state = runner.scheduler_state(Fake())
        finally:
            runner.subprocess.run = real
        self.assertEqual((state["cron"], state["loaded"]), (False, False))


if __name__ == "__main__":
    unittest.main()
