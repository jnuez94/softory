"""0.5.0: nothing waits on the owner mid-flight. Defaults on timeout, Quinn settling, feasibility, and intake."""

from __future__ import annotations

import json
import time
import unittest

from tests.helpers import coord, git_project, install, needs_sources, revision, run, softory
from tests.test_unattended import at_terminal
from tests.test_workflow import failing, gate, start


@needs_sources
class AutonomyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.holder, self.root = git_project({"README.md": "# app\n", "web/app.js": "1\n"})
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        softory(self.root, "new", "story", "--title", "See today", "--actor", "greg")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--title", "List",
                "--tags", "ui", "--actor", "quinn")

    def approve(self, settings: dict) -> dict:
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps(settings))
        return at_terminal(self.root, "charter", "approve", str(path))

    def escalate(self, reversible: str) -> str:
        made = json.loads(softory(self.root, "escalate", "--issue", "The chat provider needs a paid key.",
                                  "--ask", "Use a fake provider for now?", "--recommend", "Use a fake provider",
                                  "--reversible", reversible, "--tasks", "TASK-1", "--actor", "jade").stdout)
        return made["escalation"]

    def test_an_undoable_escalation_defaults_and_the_owner_can_still_answer(self) -> None:
        self.approve({"decisions": {"default_after_hours": 0.0003}, "run": {"roles": []}, "feasibility": {"required": False}})
        waits = self.escalate("no")
        undoable = self.escalate("yes")
        digest = json.loads(softory(self.root, "digest").stdout)["digest"]
        self.assertTrue(any("can't be undone" in row["text"] for row in digest if row["key"] == f"esc-{waits}"))
        time.sleep(1.5)
        tick = json.loads(softory(self.root, "run").stdout)
        self.assertEqual(tick["defaulted"], [undoable])
        self.assertEqual(coord(self.root, "escalation", "show", undoable)["data"]["status"], "resolved")
        self.assertEqual(coord(self.root, "escalation", "show", waits)["data"]["status"], "open")
        inbox = coord(self.root, "inbox", "list", "--agent", "jade")["data"]
        messages = inbox.get("messages", []) if isinstance(inbox, dict) else inbox
        self.assertTrue(any("Use a fake provider" in m["body"] for m in messages))
        keys = [row["key"] for row in json.loads(softory(self.root, "digest").stdout)["digest"]]
        self.assertTrue(any(k.startswith("default-") for k in keys))
        answered = at_terminal(self.root, "answer", undoable, "Use the real provider; I added the key")
        self.assertTrue(answered["reversed_default"])
        self.assertIn("owner_terminal_required", softory(self.root, "answer", waits, "x", check=False).stderr)

    def test_feasibility_holds_the_tasks_until_the_plan_fits_the_environment(self) -> None:
        self.approve({"environment": {"accounts": ["GitHub"], "desktop_unlocked": False}})
        plan = json.loads(softory(self.root, "run", "--dry-run").stdout)
        self.assertEqual(plan["feasibility"], "STORY-1")
        self.assertNotIn("jade", plan["started"])
        needs = json.loads(softory(self.root, "feasible", "STORY-1", "--needs", "An unlocked Mac for native checks",
                                   "--actor", "quinn").stdout)
        self.assertEqual(needs["told"], ["greg", "quinn"])
        digest = json.loads(softory(self.root, "digest").stdout)["digest"]
        self.assertTrue(any(row["key"] == "needs-STORY-1" for row in digest))
        self.assertNotIn("feasibility", json.loads(softory(self.root, "run", "--dry-run").stdout))
        time.sleep(1.1)  # a re-plan after the verdict runs the check again
        coord(self.root, "task", "update", "TASK-1", "--title", "List, checked headless", "--actor", "quinn",
              "--if-revision", revision(self.root, "TASK-1"))
        self.assertEqual(json.loads(softory(self.root, "run", "--dry-run").stdout)["feasibility"], "STORY-1")
        softory(self.root, "feasible", "STORY-1", "--pass", "--actor", "quinn")
        plan = json.loads(softory(self.root, "run", "--dry-run").stdout)
        self.assertIn("jade", plan["started"])
        self.assertNotIn("feasibility", plan)

    def test_the_check_run_reads_the_plan_and_the_environment(self) -> None:
        script = 'printf %s "$1" > .git/prompt'
        self.approve({"environment": {"devices": ["this Mac, locked overnight"]},
                      "run": {"harnesses": {"fake": ["sh", "-c", script, "sh", "{prompt}"]}},
                      "feasibility": {"harness": "fake", "model": "m2"}})
        ran = json.loads(softory(self.root, "run-check", "STORY-1").stdout)
        self.assertEqual((ran["role"], ran["job"], ran["model"]), ("quinn", "feasibility", "m2"))
        prompt = (self.root / ".git/prompt").read_text()
        self.assertIn("this Mac, locked overnight", prompt)
        self.assertIn("TASK-1 [todo] List", prompt)
        self.assertIn("softory feasible STORY-1 --pass", prompt)

    def test_a_ui_unit_needs_a_check_against_its_reference(self) -> None:
        softory(self.root, "feasible", "STORY-1", "--pass", "--actor", "quinn")
        session = start(self.root, "jade")["COORDINATION_SESSION"]
        coord(self.root, "--session", session, "task", "claim", "TASK-1", "--agent", "jade",
              "--if-revision", revision(self.root, "TASK-1"))
        coord(self.root, "evidence", "add", "--task", "TASK-1", "--uri", "commit:abc", "--type", "commit",
              "--actor", "jade")
        coord(self.root, "--session", session, "task", "release", "TASK-1", "--to", "review", "--actor", "jade",
              "--if-revision", revision(self.root, "TASK-1"))
        self.assertIn("ui_reference", failing(gate(self.root, "TASK-1", "jade")))
        coord(self.root, "evidence", "add", "--task", "TASK-1", "--uri", "shots/list-vs-spec.png",
              "--type", "reference", "--actor", "jade")
        self.assertNotIn("ui_reference", failing(gate(self.root, "TASK-1", "jade")))

    def test_an_idea_becomes_a_story_for_greg_and_the_tree_shows_progress(self) -> None:
        made = json.loads(softory(self.root, "feature", "Let me pin a note to today").stdout)
        story = coord(self.root, "task", "show", made["id"])["data"]
        self.assertEqual((story["assignees"], made["unit"]), (["greg"], "story"))
        self.assertIn("idea", story["tags"])
        self.assertIn("STORY-1 [todo, 0/1 done]", softory(self.root, "tree").stdout)
        kickoff = json.loads(softory(self.root, "kickoff").stdout)
        self.assertIn("softory charter approve", (self.root / kickoff["prompt"]).read_text())


class RecoveryUnitTest(unittest.TestCase):
    def test_a_session_is_stale_after_twice_the_longest_run(self) -> None:
        from tests.test_unattended import DEFAULTS
        from softory import charter as charters, recovery

        self.assertEqual(recovery.stale_after_minutes(DEFAULTS), 60)
        longer = charters.merge(DEFAULTS, {"budget": {"roles": {"gold": {"minutes_per_run": 45}}}})
        self.assertEqual(recovery.stale_after_minutes(longer), 90)


if __name__ == "__main__":
    unittest.main()
