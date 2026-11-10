"""Simplification is a rule, and Sage owns it (0.5.9, from Tablet's zips, copies, and loose reports)."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
import unittest

from tests.helpers import REPO, coord, git_project, install, needs_sources, revision, run, softory
from tests.test_workflow import at_terminal, gate, start


@needs_sources
class SimplifyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.holder, self.root = git_project({"README.md": "# app\n", ".gitignore": "dist/\nnode_modules/\n"})
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        softory(self.root, "new", "story", "--title", "Ship it", "--actor", "greg")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "infra", "--title", "Package",
                "--actor", "quinn")
        path = self.root / ".git" / "charter.json"
        base = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        path.write_text(json.dumps({"feasibility": {"required": False}, "git": {"base": base}}))
        at_terminal(self.root, "charter", "approve", str(path), "--merge")

    def commit(self, name: str, text: str) -> str:
        (self.root / name).parent.mkdir(parents=True, exist_ok=True)
        (self.root / name).write_text(text)
        run(["git", "add", name], self.root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", name], self.root)
        return run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()

    def claim(self) -> str:
        session = start(self.root, "gold")["COORDINATION_SESSION"]
        coord(self.root, "--session", session, "task", "claim", "TASK-1", "--agent", "gold",
              "--if-revision", revision(self.root, "TASK-1"))
        return session

    def test_sage_is_on_the_team(self) -> None:
        self.assertIn("sage", json.dumps(coord(self.root, "agent", "list")))
        self.assertIn("sage", json.loads(softory(self.root, "charter", "show").stdout)["run"]["roles"])

    def test_clutter_lists_copies_loose_files_and_merged_branches(self) -> None:
        clean = softory(self.root, "clutter", check=False)
        self.assertEqual(clean.returncode, 0, clean.stdout)
        for folder in ("candidate-1", "candidate-2"):
            (self.root / "dist" / folder).mkdir(parents=True)
            (self.root / "dist" / folder / "plugin.zip").write_bytes(b"zip")
        (self.root / "review-notes.md").write_text("notes\n")
        run(["git", "branch", "backup/old"], self.root)
        found = softory(self.root, "clutter", check=False)
        self.assertEqual(found.returncode, 2)
        report = json.loads(found.stdout)
        self.assertEqual(report["counts"], {"untracked": 1, "archives": 2, "worktrees": 0, "branches": 1})
        self.assertEqual(report["copies"], {"plugin.zip": 2})
        self.assertEqual(report["untracked"], ["review-notes.md"])
        softory(self.root, "workspace", "jade")  # softory's own review workspace isn't clutter
        self.assertEqual(json.loads(softory(self.root, "clutter", check=False).stdout)["counts"]["worktrees"], 0)
        self.assertIn("Clutter:", json.dumps(json.loads(softory(self.root, "digest").stdout)["digest"]))

    def test_handoff_refuses_files_left_in_the_checkout_during_the_claim(self) -> None:
        sha = self.commit("src/build.txt", "a\n")
        self.claim()
        softory(self.root, "commit", "TASK-1", sha, "--actor", "gold")
        (self.root / "proof.md").write_text("it works\n")
        (self.root / "review notes é.md").write_text("quoted by git status\n")
        refused = softory(self.root, "handoff", "TASK-1", "--actor", "gold", check=False)
        self.assertIn("untracked_files", refused.stderr)
        self.assertIn("proof.md", refused.stderr)
        self.assertIn("review notes é.md", json.loads(refused.stderr)["error"]["message"])  # a name git quotes still counts
        for name in ("proof.md", "review notes é.md"):
            softory(self.root, "report", "TASK-1", str(self.root / name), "--actor", "gold")
        softory(self.root, "handoff", "TASK-1", "--actor", "gold")

    def test_a_unit_that_changes_scripts_needs_the_process_tag(self) -> None:
        sha = self.commit("scripts/package.sh", "zip -r out.zip .\n")
        coord(self.root, "evidence", "add", "--task", "TASK-1", "--uri", f"commit:{sha}", "--type", "commit",
              "--actor", "gold")
        checks = {c["check"]: c for c in gate(self.root, "TASK-1", "gold")["checks"]}
        self.assertFalse(checks["process_paths"]["pass"])
        self.assertIn("scripts/package.sh", checks["process_paths"]["detail"])
        task = coord(self.root, "task", "show", "TASK-1")["data"]
        coord(self.root, "task", "update", "TASK-1", "--tags", f"{task['tags']},process", "--actor", "quinn",
              "--if-revision", revision(self.root, "TASK-1"))
        checks = {c["check"]: c for c in gate(self.root, "TASK-1", "gold")["checks"]}
        self.assertTrue(checks["process_paths"]["pass"])
        self.assertIn("review:tag:process", checks)  # and Sage must review it
        reviewers = json.loads(softory(self.root, "reviewers", "TASK-1").stdout)
        self.assertIn("sage", json.dumps(reviewers))

    def test_sage_checks_in_only_when_there_is_something_to_look_at(self) -> None:
        def pending() -> dict:
            return json.loads(softory(self.root, "pending", "sage", check=False).stdout)

        softory(self.root, "flow", "--record")  # a check-in
        self.assertFalse(pending()["pending"])  # checked in just now, and nothing since
        time.sleep(1.1)
        state = self.root / ".coordination/softory"
        (state / "runs.jsonl").write_text(json.dumps({"role": "jade", "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                                      "minutes": 5, "input_tokens": 100, "changes": 0}) + "\n")
        self.assertFalse(pending()["pending"])  # the team ran, but the check-in isn't due yet
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps({"simplify": {"checkin_hours": 0}}))
        at_terminal(self.root, "charter", "approve", str(path), "--merge")
        woke = pending()
        self.assertTrue(woke["pending"], woke)
        self.assertIn("softory flow --record", woke["reasons"][-1]["why"])
        start(self.root, "sage")  # a process review in between doesn't count as a check-in
        softory(self.root, "end", "--actor", "sage")
        self.assertTrue(pending()["pending"])
        time.sleep(1.1)
        softory(self.root, "flow", "--record")  # the check-in
        self.assertFalse(pending()["pending"])
        (self.root / "loose.md").write_text("x\n")  # clutter that appeared since
        self.assertTrue(pending()["pending"])
        softory(self.root, "flow", "--record")
        self.assertFalse(pending()["pending"])  # seen, unchanged, and the team hasn't run: no paid run for it

    def test_pr_only_evidence_still_needs_the_process_check(self) -> None:
        coord(self.root, "evidence", "add", "--task", "TASK-1", "--uri", "https://github.com/o/r/pull/7",
              "--type", "pr", "--actor", "gold")
        check = next(c for c in gate(self.root, "TASK-1", "gold")["checks"] if c["check"] == "process_paths")
        self.assertFalse(check["pass"])
        self.assertIn("softory commit", check["detail"])

    def test_an_archive_in_softorys_state_counts_once(self) -> None:
        before = json.loads(softory(self.root, "flow").stdout)["process_mib"]
        folder = self.root / ".coordination/softory/evidence/TASK-1"
        folder.mkdir(parents=True)
        (folder / "records.zip").write_bytes(b"0" * 1048576)
        self.assertEqual(json.loads(softory(self.root, "flow").stdout)["process_mib"], round(before + 1.0, 1))

    def test_flow_counts_only_delivered_work(self) -> None:
        start(self.root, "quinn")
        softory(self.root, "drop", "TASK-1", "--reason", "Not needed", "--actor", "quinn")
        self.assertEqual(coord(self.root, "task", "show", "TASK-1")["data"]["status"], "done")
        self.assertEqual(json.loads(softory(self.root, "flow").stdout)["closed"], 0)

    def test_flow_reports_and_compares_with_the_last_snapshot(self) -> None:
        first = json.loads(softory(self.root, "flow", "--record").stdout)
        for key in ("lead_hours", "runs_per_unit", "tokens_per_unit", "idle_share", "process_mib", "storage_mib"):
            self.assertIn(key, first)
        self.assertNotIn("previous", first)
        (self.root / "loose.md").write_text("x\n")
        second = json.loads(softory(self.root, "flow").stdout)
        self.assertEqual(second["previous"]["untracked"], 0)
        self.assertEqual(second["untracked"], 1)
        self.assertIn("untracked", second["worse"])


class WorseTest(unittest.TestCase):
    def test_a_rise_in_idle_runs_counts_as_worse(self) -> None:
        sys.path.insert(0, str(REPO / "lib"))
        from softory import flow  # noqa: PLC0415

        self.assertTrue(flow._worse("idle_share", 0.6, 0.2))  # tripled
        self.assertFalse(flow._worse("idle_share", 0.21, 0.2))
        self.assertFalse(flow._worse("runs_per_unit", 4.3, 4.0))


if __name__ == "__main__":
    unittest.main()
