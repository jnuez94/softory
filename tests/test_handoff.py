"""0.6.5: a handoff asks every reviewer at once, a correction is re-reviewed on its change, one verdict covers a stack."""

from __future__ import annotations

import json
import os
import unittest

from tests.helpers import coord, git_project, install, needs_sources, revision, run, softory
from tests.test_unattended import at_terminal
from tests.test_workflow import start


@needs_sources
class HandoffTest(unittest.TestCase):
    def setUp(self) -> None:
        self.holder, self.root = git_project({"README.md": "# app\n"})
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        self.base = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        softory(self.root, "new", "story", "--title", "Today", "--actor", "greg")
        softory(self.root, "feasible", "STORY-1", "--pass", "--actor", "quinn")
        self.jade = {**os.environ, **start(self.root, "jade")}

    def new(self, unit: str, *args: str) -> str:
        made = softory(self.root, "new", unit, "--parent", "STORY-1", "--lane", "frontend", *args, "--actor", "quinn")
        return json.loads(made.stdout)["id"]

    def commit(self, name: str, *tasks: str) -> str:
        (self.root / name).write_text(name)
        run(["git", "add", name], self.root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", name], self.root)
        sha = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        for task in tasks:
            softory(self.root, "commit", task, sha, "--base", self.base, "--actor", "jade")
        return sha

    def claim(self, task: str) -> None:
        coord(self.root, "--session", self.jade["COORDINATION_SESSION"], "task", "claim", task, "--agent", "jade",
              "--if-revision", revision(self.root, task))

    def handoff(self, task: str, *args: str) -> dict:
        return json.loads(softory(self.root, "handoff", task, *args, "--actor", "jade", env=self.jade).stdout)

    def inbox(self, agent: str) -> list[dict]:
        found = coord(self.root, "inbox", "list", "--agent", agent)["data"]
        return found.get("messages", []) if isinstance(found, dict) else found

    def test_a_handoff_asks_every_required_reviewer_at_once(self) -> None:
        task = self.new("task", "--tags", "security", "--title", "Sign in")
        self.claim(task)
        sha = self.commit("a.txt", task)
        result = self.handoff(task, "--note", "Start with the token check.")
        self.assertEqual(sorted(a["reviewer"] for a in result["asked"]), ["gold", "toby"])
        for reviewer in ("gold", "toby"):
            asked = [m for m in self.inbox(reviewer) if m.get("task_id") == task]
            self.assertEqual(len(asked), 1)
            self.assertIn(f"Commit {sha}, built on {self.base}", asked[0]["body"])
            self.assertIn("Start with the token check.", asked[0]["body"])
            self.assertIn("request", asked[0]["tags"])
        self.assertNotIn("warnings", result)

    def test_a_correction_is_re_reviewed_on_what_changed(self) -> None:
        task = self.new("task", "--title", "Today list")
        self.claim(task)
        first = self.commit("a.txt", task)
        self.handoff(task)
        gold = {**os.environ, **start(self.root, "gold")}
        softory(self.root, "coord", "review", "add", "--id", "REV-1", "--task", task, "--reviewer", "gold",
                "--artifact", f"commit:{first}", "--scope", "all", "--decision", "changes_requested",
                "--required-changes", "Handle the empty list", env=gold)
        second = self.commit("b.txt", task)
        row = next(r for r in json.loads(softory(self.root, "queue", "--agent", "gold").stdout)["reviews_waiting"]
                   if r["id"] == task)
        self.assertEqual(row["re_review"]["diff"], f"git diff {first[:12]}..{second[:12]}")
        self.assertEqual(row["re_review"]["you_asked"], "Handle the empty list")
        self.assertIn("What you accepted stands", row["re_review"]["scope"])

    def test_a_handoff_warns_when_the_tests_have_not_passed(self) -> None:
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps({"verify": {"command": "true"}, "git": {"base": self.base}}))
        at_terminal(self.root, "charter", "approve", str(path))
        task = self.new("task", "--title", "Today list")
        self.claim(task)
        self.commit("a.txt", task)
        result = self.handoff(task)
        self.assertEqual(result["status"], "review")
        self.assertIn("softory verify is not run", result["warnings"][0])

    def test_one_verdict_covers_a_stack_of_small_bugs_at_one_commit(self) -> None:
        bugs = [self.new("bug", "--type", "functional", "--title", f"Bug {n}") for n in (1, 2, 3)]
        for bug in bugs:
            self.claim(bug)
        sha = self.commit("a.txt", bugs[0], bugs[1])
        self.commit("b.txt", bugs[2])  # a later commit: the verdict on the first doesn't reach it
        softory(self.root, "stack", *bugs, "--actor", "jade", env=self.jade)
        for bug in bugs:
            self.handoff(bug)
        gold = {**os.environ, **start(self.root, "gold")}
        alone = softory(self.root, "coord", "review", "add", "--id", "REV-A", "--task", bugs[0], "--reviewer", "gold",
                        "--artifact", f"commit:{sha}", "--scope", "this fix", "--decision", "changes_requested",
                        "--required-changes", "x", env=gold)
        self.assertNotIn("same verdict", alone.stderr)
        self.assertEqual(coord(self.root, "task", "show", bugs[1])["data"]["reviews"], [])
        both = softory(self.root, "coord", "review", "add", "--id", "REV-B", "--task", bugs[0], "--reviewer", "gold",
                       "--artifact", f"commit:{sha}", "--scope", f"both fixes, stack:{bugs[0]}", "--decision",
                       "accepted", env=gold)
        self.assertIn(f"recorded on {bugs[1]} ", both.stderr)
        second = coord(self.root, "task", "show", bugs[1])["data"]["reviews"]
        self.assertEqual([(r["reviewer_id"], r["decision"], r["id"]) for r in second],
                         [("gold", "accepted", f"REV-B-{bugs[1]}")])
        self.assertEqual(coord(self.root, "task", "show", bugs[2])["data"]["reviews"], [])

    def test_flow_reports_how_delivered_units_went_through_review(self) -> None:
        report = json.loads(softory(self.root, "flow").stdout)
        for key in ("first_verdict_hours", "handoff_to_close_hours", "fix_bugs_per_unit"):
            self.assertIn(key, report)
        task = self.new("task", "--title", "Today list")
        self.claim(task)
        sha = self.commit("a.txt", task)
        self.handoff(task)
        gold = {**os.environ, **start(self.root, "gold")}
        softory(self.root, "coord", "review", "add", "--id", "REV-1", "--task", task, "--reviewer", "gold",
                "--artifact", f"commit:{sha}", "--scope", "all", "--decision", "accepted", env=gold)
        closed = json.loads(softory(self.root, "close", task, "--actor", "jade", env=self.jade, check=False).stdout)
        self.assertTrue(closed["closed"], closed)
        softory(self.root, "new", "bug", "--from", task, "--lane", "frontend", "--type", "functional", "--title",
                "Empty list", "--actor", "gold")
        report = json.loads(softory(self.root, "flow").stdout)
        self.assertEqual(report["closed"], 1)
        self.assertEqual(report["first_verdict_hours"], 0.0)
        self.assertEqual(report["handoff_to_close_hours"], 0.0)
        self.assertEqual(report["fix_bugs_per_unit"], 1.0)


if __name__ == "__main__":
    unittest.main()
