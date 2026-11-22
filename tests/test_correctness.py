"""0.6.6: an accepted review covers the commit it was given for, and no later one."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

from tests.helpers import coord, git_project, git_status, install, needs_sources, revision, run, softory
from tests.helpers import REPO
from tests.test_workflow import at_terminal, failing, gate, start

sys.path.insert(0, str(REPO / "lib"))
from softory.coordination import Coordination  # noqa: E402
from softory.project import Project  # noqa: E402


class Built(unittest.TestCase):
    """A task with real commits on a branch off the base, built by Gold and reviewed by Jade."""

    def setUp(self) -> None:
        self.holder, self.root = git_project()
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        run(["git", "branch", "-M", "main"], self.root)
        run(["git", "checkout", "-qb", "work"], self.root)  # the unit's commits sit on a branch off the base
        softory(self.root, "new", "epic", "--title", "Radar", "--actor", "greg")
        softory(self.root, "new", "story", "--parent", "EPIC-1", "--title", "See today", "--actor", "greg")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "backend", "--title", "List", "--actor", "quinn")

    def commit(self, name: str) -> str:
        (self.root / name).write_text(name + "\n")
        run(["git", "add", name], self.root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", name], self.root)
        return run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()

    def build(self, sha: str) -> None:
        session = start(self.root, "gold")["COORDINATION_SESSION"]
        coord(self.root, "--session", session, "task", "claim", "TASK-1", "--agent", "gold",
              "--if-revision", revision(self.root, "TASK-1"))
        softory(self.root, "commit", "TASK-1", sha, "--actor", "gold")
        coord(self.root, "--session", session, "task", "release", "TASK-1", "--to", "review", "--actor", "gold",
              "--if-revision", revision(self.root, "TASK-1"))

    def accept(self, number: int, artifact: str) -> None:
        coord(self.root, "review", "add", "--id", f"REV-{number}", "--task", "TASK-1", "--reviewer", "jade",
              "--artifact", artifact, "--scope", "the change", "--decision", "accepted")

    def waiting_for_jade(self) -> list[str]:
        queue = json.loads(softory(self.root, "queue", "--agent", "jade").stdout)
        return [row["id"] for row in queue["reviews_waiting"]]

@needs_sources
class ReviewCoversCommitTest(Built):
    def test_a_newer_commit_needs_a_new_review(self) -> None:
        first, second = self.commit("a.py"), self.commit("b.py")
        self.build(first)
        self.accept(1, f"commit:{first}")
        self.assertTrue(gate(self.root, "TASK-1", "gold")["pass"])
        softory(self.root, "commit", "TASK-1", second, "--actor", "gold")
        report = gate(self.root, "TASK-1", "gold")
        self.assertEqual(failing(report), {"reviews_cover_commit"})
        self.assertFalse(json.loads(softory(self.root, "close", "TASK-1", "--actor", "gold", check=False).stdout)["closed"])
        self.assertEqual(self.waiting_for_jade(), ["TASK-1"])
        self.accept(2, f"commit:{second}")
        self.assertTrue(gate(self.root, "TASK-1", "gold")["pass"])
        self.assertEqual(self.waiting_for_jade(), [])

    def test_a_review_that_names_no_commit_covers_what_was_recorded_before_it(self) -> None:
        first, second = self.commit("a.py"), self.commit("b.py")
        self.build(first)
        time.sleep(1.1)  # records are stamped to the second
        self.accept(1, "reports/review.md")
        self.assertTrue(gate(self.root, "TASK-1", "gold")["pass"])
        time.sleep(1.1)
        softory(self.root, "commit", "TASK-1", second, "--actor", "gold")
        self.assertEqual(failing(gate(self.root, "TASK-1", "gold")), {"reviews_cover_commit"})


    def test_a_report_review_does_not_cover_a_commit_first_named_as_a_base(self) -> None:
        first, second = self.commit("a.py"), self.commit("b.py")
        session = start(self.root, "gold")["COORDINATION_SESSION"]
        coord(self.root, "--session", session, "task", "claim", "TASK-1", "--agent", "gold",
              "--if-revision", revision(self.root, "TASK-1"))
        softory(self.root, "commit", "TASK-1", second, "--base", first, "--actor", "gold")
        coord(self.root, "--session", session, "task", "release", "TASK-1", "--to", "review", "--actor", "gold",
              "--if-revision", revision(self.root, "TASK-1"))
        time.sleep(1.1)
        self.accept(1, "reports/review.md")  # the report read the second commit
        self.assertTrue(gate(self.root, "TASK-1", "gold")["pass"])
        time.sleep(1.1)
        softory(self.root, "commit", "TASK-1", first, "--actor", "gold")
        self.assertEqual(failing(gate(self.root, "TASK-1", "gold")), {"reviews_cover_commit"})

    def test_a_report_review_does_not_cover_a_return_to_an_earlier_commit(self) -> None:
        first, second = self.commit("a.py"), self.commit("b.py")
        self.build(first)
        softory(self.root, "commit", "TASK-1", second, "--actor", "gold")
        time.sleep(1.1)
        self.accept(1, "reports/review.md")
        time.sleep(1.1)
        softory(self.root, "commit", "TASK-1", first, "--actor", "gold")
        self.assertEqual(failing(gate(self.root, "TASK-1", "gold")), {"reviews_cover_commit"})

    def test_a_report_review_does_not_cover_the_commit_a_retraction_returns_to(self) -> None:
        first, second = self.commit("a.py"), self.commit("b.py")
        self.build(first)
        softory(self.root, "commit", "TASK-1", second, "--actor", "gold")
        time.sleep(1.1)
        self.accept(1, "reports/review.md")  # the report read the second commit
        time.sleep(1.1)
        rows = coord(self.root, "task", "show", "TASK-1")["data"]["evidence"]
        newer = next(row for row in rows if second in str(row["uri"]))
        softory(self.root, "supersede", "TASK-1", str(newer["id"]), "--reason", "wrong commit", "--actor", "gold")
        self.assertEqual(failing(gate(self.root, "TASK-1", "gold")), {"reviews_cover_commit"})

    def test_a_review_nobody_required_does_not_hold_the_unit(self) -> None:
        first, second = self.commit("a.py"), self.commit("b.py")
        self.build(first)
        coord(self.root, "review", "add", "--id", "REV-1", "--task", "TASK-1", "--reviewer", "toby",
              "--artifact", f"commit:{first}", "--scope", "a look nobody asked for", "--decision", "accepted")
        softory(self.root, "commit", "TASK-1", second, "--actor", "gold")
        self.accept(2, f"commit:{second}")  # the required review, at the commit delivered now
        self.assertTrue(gate(self.root, "TASK-1", "gold")["pass"])

@needs_sources
class VerifyOnceTest(Built):
    def test_two_verifies_started_together_run_the_tests_once(self) -> None:
        ran = self.root / ".git" / "ran.log"
        charter = self.root / ".git" / "charter.json"
        charter.write_text(json.dumps({"verify": {"command": f"echo run >> {ran}; sleep 2"}}))
        at_terminal(self.root, "charter", "approve", str(charter), "--merge")
        self.build(self.commit("a.py"))
        command = [str(self.root / ".agents/softory/bin/softory"), "verify", "TASK-1", "--actor", "gold"]
        both = [subprocess.Popen(command, cwd=self.root, stdout=subprocess.PIPE, text=True) for _ in range(2)]
        results = [json.loads(run.communicate()[0]) for run in both]
        self.assertEqual([r["passed"] for r in results], [True, True])
        self.assertEqual(ran.read_text().count("run"), 1)


@needs_sources
class SameSecondTest(Built):
    def test_work_that_changed_in_the_second_the_role_last_started_still_counts(self) -> None:
        self.build(self.commit("a.py"))
        coord(self.root, "review", "add", "--id", "REV-1", "--task", "TASK-1", "--reviewer", "jade", "--artifact",
              "reports/review.md", "--scope", "the change", "--decision", "changes_requested",
              "--required-changes", "handle the empty list")
        task = coord(self.root, "task", "show", "TASK-1")["data"]
        at = max(task["updated_at"], task["reviews"][-1]["created_at"])  # records are stamped to the second
        found = json.loads(softory(self.root, "pending", "gold", "--since", at, "--retry-hours", "0",
                                   check=False).stdout)
        self.assertEqual([r["ids"] for r in found["reasons"] if r["why"] == "changes requested"], [["TASK-1"]])


@needs_sources
class TrackedInstructionsTest(unittest.TestCase):
    """Softory created AGENTS.md; the owner later wrote project rules in it and committed it."""

    def setUp(self) -> None:
        self.holder, self.root = git_project()
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        agents = self.root / "AGENTS.md"
        self.rules = agents.read_text() + "\n## Our rules\n\nTabs, never spaces.\n"
        agents.write_text(self.rules)
        run(["git", "add", "-f", "AGENTS.md"], self.root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "our rules"], self.root)

    def test_sync_leaves_an_instruction_file_the_project_now_tracks(self) -> None:
        softory(self.root, "sync")
        self.assertEqual((self.root / "AGENTS.md").read_text(), self.rules)
        self.assertEqual(git_status(self.root), "")
        override = (self.root / "AGENTS.override.md").read_text()
        self.assertIn("Tabs, never spaces.", override)  # Codex reads the override, so it carries both
        self.assertIn("softory-operating-loop", override)

    def test_sync_keeps_writing_the_override_after_the_project_stops_tracking_its_file(self) -> None:
        softory(self.root, "sync")
        run(["git", "rm", "-q", "--cached", "AGENTS.md"], self.root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "untrack"], self.root)
        (self.root / "AGENTS.md").write_text(self.rules + "\nSpaces after all.\n")
        softory(self.root, "sync")
        override = (self.root / "AGENTS.override.md").read_text()  # Codex reads it first, so it must be current
        self.assertIn("Spaces after all.", override)
        self.assertIn("softory-operating-loop", override)
        self.assertEqual(git_status(self.root), "?? AGENTS.md\n")  # the project's own file, as it left it

    def test_sync_keeps_a_shared_folder_hidden_when_instruction_ownership_changes(self) -> None:
        # setUp committed AGENTS.md; this sync is the first to see it tracked.
        (self.root / "review-cache").mkdir()
        (self.root / "review-cache/kept.txt").write_text("x\n")
        softory(self.root, "worktree", "add", str(self.root.parent / (self.root.name + "-wt")), "-b", "jade/list",
                "--share", "review-cache")
        self.addCleanup(run, ["git", "worktree", "prune"], self.root)
        self.assertEqual(git_status(self.root), "")
        softory(self.root, "sync")
        self.assertEqual(git_status(self.root), "")
        manifest = json.loads((self.root / ".agents/softory/manifest.json").read_text())
        self.assertIn("/review-cache", manifest["exclude_patterns"])

    def test_uninstall_leaves_an_instruction_file_the_project_now_tracks(self) -> None:
        softory(self.root, "uninstall")
        self.assertEqual((self.root / "AGENTS.md").read_text(), self.rules)
        self.assertEqual(git_status(self.root), "")


@needs_sources
class LinkedWorktreeInstructionsTest(unittest.TestCase):
    def test_a_linked_worktree_keeps_its_instructions_when_main_untracks_the_file(self) -> None:
        holder, root = git_project({"README.md": "# app\n", "AGENTS.md": "# Our rules\n\nTabs, never spaces.\n"})
        self.addCleanup(holder.cleanup)
        install(root)
        tree = root.parent / (root.name + "-wt")
        softory(root, "worktree", "add", str(tree), "-b", "jade/list")
        self.addCleanup(run, ["git", "worktree", "remove", "--force", str(tree)], root, None, False)
        run(["git", "rm", "-q", "--cached", "AGENTS.md"], root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "untrack"], root)
        softory(root, "sync")
        linked = tree / "AGENTS.override.md"
        self.assertTrue(linked.exists())  # a symlink into the main checkout: its target must still be there
        self.assertIn("softory-operating-loop", linked.read_text())
        self.assertEqual(git_status(tree), "")


@needs_sources
class OperationLogTest(unittest.TestCase):
    def test_an_error_keeps_its_code_while_the_scaffold_logs_operations(self) -> None:
        holder, root = git_project()
        self.addCleanup(holder.cleanup)
        install(root)
        project = Project.find(root)
        with mock.patch.dict(os.environ, {"COORDINATION_LOG": "stderr"}):
            found = Coordination(project.coordination_bin, project.root).call("agent", "show", "nobody")
        self.assertEqual(found["error"]["code"], "not_found")


@needs_sources
class DefaultsWithoutARunnerTest(unittest.TestCase):
    def test_a_due_default_applies_when_a_role_checks_for_work(self) -> None:
        holder, root = git_project()
        self.addCleanup(holder.cleanup)
        install(root)
        softory(root, "new", "story", "--title", "See today", "--actor", "greg")
        softory(root, "new", "task", "--parent", "STORY-1", "--lane", "backend", "--title", "List", "--actor", "quinn")
        charter = root / ".git" / "charter.json"
        charter.write_text(json.dumps({"decisions": {"default_after_hours": 0.0003}, "feasibility": {"required": False}}))
        at_terminal(root, "charter", "approve", str(charter))
        made = json.loads(softory(root, "escalate", "--issue", "The chat provider needs a paid key.", "--ask",
                                  "Use a fake provider for now?", "--recommend", "Use a fake provider",
                                  "--reversible", "yes", "--tasks", "TASK-1", "--actor", "jade").stdout)
        time.sleep(1.5)
        softory(root, "pending", "jade", check=False)  # attended: no runner ticks, the role's own check does
        self.assertEqual(coord(root, "escalation", "show", made["escalation"])["data"]["status"], "resolved")


if __name__ == "__main__":
    unittest.main()
