"""0.5.0: nothing waits on the owner mid-flight. Defaults on timeout, Quinn settling, feasibility, and intake."""

from __future__ import annotations

import json
import os
import threading
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
                                  "--ask", "Use a fake provider for now?" if reversible == "yes" else
                                  "Use a fake provider until the key arrives?", "--recommend", "Use a fake provider",
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
        # Jade only: a Quinn run the tick starts (to re-plan) holds the check for a later tick.
        self.approve({"environment": {"accounts": ["GitHub"], "desktop_unlocked": False}, "run": {"roles": ["jade"]}})
        plan = json.loads(softory(self.root, "run", "--dry-run").stdout)
        self.assertEqual(plan["feasibility"], "STORY-1")
        self.assertNotIn("jade", plan["started"])
        needs = json.loads(softory(self.root, "feasible", "STORY-1", "--needs", "An unlocked Mac for native checks",
                                   "--actor", "quinn").stdout)
        self.assertEqual(needs["told"], ["greg", "quinn"])
        digest = json.loads(softory(self.root, "digest").stdout)["digest"]
        self.assertTrue(any(row["key"].startswith("needs-") and "STORY-1" in row["text"] for row in digest))
        self.assertNotIn("feasibility", json.loads(softory(self.root, "run", "--dry-run").stdout))
        self.approve({"environment": {"accounts": ["GitHub"], "devices": ["An unlocked Mac"]},  # the owner provides it
                      "run": {"roles": ["jade"]}})
        self.assertEqual(json.loads(softory(self.root, "run", "--dry-run").stdout)["feasibility"], "STORY-1")
        softory(self.root, "feasible", "STORY-1", "--needs", "A paid provider tier", "--actor", "quinn")
        self.assertNotIn("feasibility", json.loads(softory(self.root, "run", "--dry-run").stdout))
        coord(self.root, "task", "update", "TASK-1", "--title", "List, checked headless", "--actor", "quinn",
              "--if-revision", revision(self.root, "TASK-1"))
        self.assertEqual(json.loads(softory(self.root, "run", "--dry-run").stdout)["feasibility"], "STORY-1")
        softory(self.root, "feasible", "STORY-1", "--pass", "--actor", "quinn")
        plan = json.loads(softory(self.root, "run", "--dry-run").stdout)
        self.assertIn("jade", plan["started"])
        self.assertNotIn("feasibility", plan)
        coord(self.root, "task", "update", "TASK-1", "--acceptance", "Signs in with the real provider",  # a new need
              "--actor", "quinn", "--if-revision", revision(self.root, "TASK-1"))
        plan = json.loads(softory(self.root, "run", "--dry-run").stdout)
        self.assertEqual(plan["feasibility"], "STORY-1")  # the pass was for the old plan
        self.assertNotIn("jade", plan["started"])

    def test_a_pause_or_a_running_quinn_holds_the_feasibility_check(self) -> None:
        self.approve({"run": {"roles": []}})
        self.assertEqual(json.loads(softory(self.root, "run", "--dry-run").stdout)["feasibility"], "STORY-1")
        softory(self.root, "pause", "--role", "quinn", "--reason", "stop")
        self.assertNotIn("feasibility", json.loads(softory(self.root, "run", "--dry-run").stdout))
        at_terminal(self.root, "resume", "--task", "STORY-1", "--roles", "quinn")
        self.assertEqual(json.loads(softory(self.root, "run", "--dry-run").stdout)["feasibility"], "STORY-1")
        at_terminal(self.root, "resume", "--role", "quinn")
        from softory.runstate import state_dir  # noqa: PLC0415
        from softory.project import Project  # noqa: PLC0415
        pid = state_dir(Project.find(self.root)) / "quinn.pid"
        pid.write_text(str(os.getpid()))
        self.addCleanup(pid.unlink, missing_ok=True)
        self.assertNotIn("feasibility", json.loads(softory(self.root, "run", "--dry-run").stdout))
        pid.unlink()
        start(self.root, "quinn")  # a Quinn session from outside the runner has no pid file
        self.assertNotIn("feasibility", json.loads(softory(self.root, "run", "--dry-run").stdout))

    def test_a_pass_wakes_the_builder_of_work_it_releases(self) -> None:
        def changed() -> list:
            since = coord(self.root, "task", "show", "TASK-1")["data"]["updated_at"]  # as if Jade ran after it
            found = json.loads(softory(self.root, "pending", "jade", "--since", since, check=False).stdout)
            return [r for r in found["reasons"] if r["why"] == "assigned work changed"]

        self.assertEqual(changed(), [])  # held, and unchanged since
        time.sleep(1.1)
        softory(self.root, "feasible", "STORY-1", "--pass", "--actor", "quinn")
        self.assertEqual(changed()[0]["ids"], ["TASK-1"])

    def test_escalation_notes_from_many_roles_all_survive(self) -> None:
        from softory import decide  # noqa: PLC0415
        from softory.project import Project  # noqa: PLC0415
        project = Project.find(self.root)
        threads = [threading.Thread(target=decide.note, args=(project, f"ESC-{n}", "x", True, "jade"))
                   for n in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(decide.recommendations(project)), 20)

    def test_the_check_run_reads_the_plan_and_the_environment(self) -> None:
        script = 'printf %s "$1" > .git/prompt'
        self.approve({"environment": {"devices": ["this Mac, locked overnight"]},
                      "run": {"harnesses": {"fake": ["sh", "-c", script, "sh", "{prompt}"]}},
                      "feasibility": {"harness": "fake", "model": "m2"}})
        coord(self.root, "task", "update", "TASK-1", "--acceptance", "Works with a fake provider", "--actor", "quinn",
              "--description", "word " * 400 + "Needs an unlocked Mac", "--if-revision", revision(self.root, "TASK-1"))
        ran = json.loads(softory(self.root, "run-check", "STORY-1").stdout)
        self.assertEqual((ran["role"], ran["job"], ran["model"]), ("quinn", "feasibility", "m2"))
        prompt = (self.root / ".git/prompt").read_text()
        self.assertIn("this Mac, locked overnight", prompt)
        self.assertIn("TASK-1 [todo] List", prompt)
        self.assertIn("Acceptance: Works with a fake provider", prompt)
        self.assertIn("Needs an unlocked Mac", prompt)  # past 2,000 characters: requirements arrive whole

        self.assertRegex(prompt, r"softory feasible STORY-1 --plan [0-9a-f]{12} --pass")
        self.assertFalse((self.root / ".coordination/softory/manual-starts.jsonl").exists())  # the runner's own

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


class FeasibilityUnitTest(unittest.TestCase):
    def board(self, story_status: str) -> object:
        from types import SimpleNamespace  # noqa: PLC0415
        from softory.units import children_by_parent  # noqa: PLC0415

        story = {"id": "STORY-1", "status": story_status, "title": "See today", "tags": "unit:story", "updated_at": "1"}
        old = {"id": "TASK-1", "status": "done", "title": "List", "tags": "unit:task,parent:STORY-1", "updated_at": "1"}
        new = {"id": "TASK-2", "status": "todo", "title": "Follow-up", "tags": "unit:task,parent:STORY-1",
               "updated_at": "2"}
        tasks = [story, old, new]
        by_id = {t["id"]: t for t in tasks}
        return SimpleNamespace(tasks=tasks, by_id=by_id, gates={"units": {}}, children=children_by_parent(tasks),
                               show=lambda i: by_id[i])

    def test_new_work_under_a_done_story_is_held_and_checked(self) -> None:
        from softory import feasibility  # noqa: PLC0415

        charter = {"feasibility": {"required": True}}
        board = self.board("done")
        self.assertEqual(feasibility.held(board, charter), {"TASK-2"})
        self.assertEqual(feasibility.due(board, charter), ["STORY-1"])  # every held task has a check coming

    def test_a_changed_environment_changes_the_plan(self) -> None:
        from softory import feasibility  # noqa: PLC0415

        board = self.board("in_progress")
        before = feasibility.plan_hash(board.show, "STORY-1", ["TASK-1", "TASK-2"], {"environment": {"accounts": []}})
        after = feasibility.plan_hash(board.show, "STORY-1", ["TASK-1", "TASK-2"], {"environment": {"accounts": ["x"]}})
        self.assertNotEqual(before, after)


class RecoveryUnitTest(unittest.TestCase):
    def test_a_session_is_stale_after_twice_the_longest_run(self) -> None:
        from tests.test_unattended import DEFAULTS
        from softory import charter as charters, recovery

        self.assertEqual(recovery.stale_after_minutes(DEFAULTS), 60)
        longer = charters.merge(DEFAULTS, {"budget": {"roles": {"gold": {"minutes_per_run": 45}}}})
        self.assertEqual(recovery.stale_after_minutes(longer), 90)


if __name__ == "__main__":
    unittest.main()
