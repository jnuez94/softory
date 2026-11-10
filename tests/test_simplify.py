"""Simplification is a rule, and Sage owns it (0.5.9, from Tablet's zips, copies, and loose reports)."""

from __future__ import annotations

import json
import unittest

from tests.helpers import coord, git_project, install, needs_sources, revision, run, softory
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
        refused = softory(self.root, "handoff", "TASK-1", "--actor", "gold", check=False)
        self.assertIn("untracked_files", refused.stderr)
        self.assertIn("proof.md", refused.stderr)
        softory(self.root, "report", "TASK-1", str(self.root / "proof.md"), "--actor", "gold")
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

        start(self.root, "sage")
        softory(self.root, "end", "--actor", "sage")
        self.assertFalse(pending()["pending"])  # checked in just now, and nothing since
        state = self.root / ".coordination/softory"
        (state / "runs.jsonl").write_text(json.dumps({"role": "jade", "started": "2999-01-01T00:00:00+00:00",
                                                      "minutes": 5, "input_tokens": 100, "changes": 0}) + "\n")
        self.assertFalse(pending()["pending"])  # the team ran, but the check-in isn't due yet
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps({"simplify": {"checkin_hours": 0}}))
        at_terminal(self.root, "charter", "approve", str(path), "--merge")
        woke = pending()
        self.assertTrue(woke["pending"], woke)
        self.assertIn("softory flow --record", woke["reasons"][-1]["why"])

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


if __name__ == "__main__":
    unittest.main()
