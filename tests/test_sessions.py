"""Sessions the owner opens are first-class (0.6.2, from Tablet's BUG-157): a session checking on itself is
told about its work during a pause, sees its mail and Quinn's due feasibility checks, can't open the same
review twice, and softory stops reporting run numbers it didn't measure."""

from __future__ import annotations

import json
import unittest

from tests.helpers import coord, git_project, install, needs_sources, softory
from tests.test_workflow import at_terminal, start


@needs_sources
class SessionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.holder, self.root = git_project({"README.md": "# app\n"})
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        softory(self.root, "new", "story", "--title", "See today", "--actor", "greg")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--title", "List",
                "--actor", "quinn")

    def charter(self, settings: dict) -> None:
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps(settings))
        at_terminal(self.root, "charter", "approve", str(path), "--merge")

    def attended(self) -> None:
        self.charter({"run": {"mode": "attended", "attended": {"claude": ["sh", "-c", "true"], "codex": ["sh", "-c", "true"]}}})

    def pending(self, role: str) -> tuple[int, dict]:
        result = softory(self.root, "pending", role, check=False)
        return result.returncode, json.loads(result.stdout)

    def test_an_attended_session_hears_about_its_work_during_a_pause(self) -> None:
        softory(self.root, "feasible", "STORY-1", "--pass", "--actor", "quinn")
        softory(self.root, "pause", "--reason", "owner runs the sessions")
        code, report = self.pending("jade")
        self.assertEqual((code, report["state"]), (3, "paused"))  # unattended: a pause stops a check-in too
        softory(self.root, "resume", check=False)
        at_terminal(self.root, "resume")
        self.attended()
        softory(self.root, "pause", "--reason", "owner runs the sessions")
        code, report = self.pending("jade")
        self.assertEqual((code, report["state"]), (0, "work"))
        self.assertIn("runner starts only", report["paused_for"])
        idle = self.pending("darwin")
        self.assertEqual((idle[0], idle[1]["state"]), (3, "idle"))  # paused with nothing to do reads as idle
        # The runner itself still holds off: nothing starts while the pause stands.
        self.assertEqual(json.loads(softory(self.root, "run", "--dry-run").stdout)["started"], [])

    def test_a_session_sees_untagged_mail_sent_to_it(self) -> None:
        softory(self.root, "feasible", "STORY-1", "--pass", "--actor", "quinn")
        session = start(self.root, "jade")["COORDINATION_SESSION"]
        coord(self.root, "--session", session, "message", "send", "--id", "MSG-1", "--sender", "jade",
              "--recipient", "darwin", "--body", "Handoff: the list needs a sort order.")
        coord(self.root, "--session", session, "message", "send", "--id", "MSG-2", "--sender", "jade",
              "--recipient", "team", "--body", "News for everyone.")
        code, report = self.pending("toby")
        self.assertEqual(code, 3, report)  # team news alone wakes nobody
        code, report = self.pending("darwin")
        self.assertEqual(code, 3, report)  # a scheduler asking for Darwin starts nobody for an untagged note
        mine = softory(self.root, "pending", "darwin", env=start(self.root, "darwin"), check=False)
        code, report = mine.returncode, json.loads(mine.stdout)  # Darwin's own open session reads its mail
        self.assertEqual(code, 0, report)
        self.assertIn({"why": "unread messages to you", "count": 1}, report["reasons"])
        queue = json.loads(softory(self.root, "queue", "--agent", "darwin").stdout)
        self.assertEqual(queue["unread"]["count"], 1)
        # The runner still starts nobody for it: an untagged note isn't worth a cold start.
        self.assertNotIn("darwin", json.loads(softory(self.root, "run", "--dry-run").stdout)["started"])

    def test_quinn_sees_feasibility_checks_that_are_due(self) -> None:
        queue = json.loads(softory(self.root, "queue", "--agent", "quinn").stdout)
        row = queue["feasibility_due"][0]
        self.assertEqual((row["story"], row["checked_plan"], row["run"]), ("STORY-1", None, "softory run-check STORY-1"))
        code, report = self.pending("quinn")
        self.assertEqual(code, 0)
        self.assertIn("STORY-1", next(r["ids"] for r in report["reasons"] if r["why"].startswith("feasibility")))
        softory(self.root, "feasible", "STORY-1", "--pass", "--actor", "quinn")
        self.assertNotIn("feasibility_due", json.loads(softory(self.root, "queue", "--agent", "quinn").stdout))
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "backend", "--title", "Store",
                "--actor", "quinn")  # the plan changed, so the check is due again and says which plan it covered
        again = json.loads(softory(self.root, "queue", "--agent", "quinn").stdout)["feasibility_due"][0]
        self.assertEqual(again["last_verdict"], "pass")
        self.assertNotEqual(again["plan"], again["checked_plan"])
        self.assertNotIn("feasibility_due", json.loads(softory(self.root, "queue", "--agent", "jade").stdout))

    def test_a_role_cannot_open_two_review_records_for_one_task(self) -> None:
        first = json.loads(softory(self.root, "new", "review", "--for", "TASK-1", "--title", "Review the list",
                                   "--actor", "gold").stdout)
        second = softory(self.root, "new", "review", "--for", "TASK-1", "--title", "Review the list again",
                         "--actor", "gold", check=False)
        self.assertNotEqual(second.returncode, 0)
        error = json.loads(second.stderr)["error"]
        self.assertEqual((error["code"], error["details"]["existing"]), ("conflict", first["id"]))
        softory(self.root, "new", "review", "--for", "TASK-1", "--title", "Security pass", "--actor", "toby")

    def test_new_ends_with_the_id(self) -> None:
        output = softory(self.root, "new", "bug", "--parent", "STORY-1", "--lane", "frontend", "--type", "functional",
                         "--title", "Wrong order", "--actor", "quinn").stdout
        self.assertEqual(output.rstrip().splitlines()[-2].strip(), '"id": "BUG-1"')

    def test_coord_keeps_softorys_actor_flag_out_of_read_commands(self) -> None:
        start(self.root, "greg")
        shown = softory(self.root, "coord", "task", "show", "STORY-1", "--actor", "greg")
        self.assertEqual(json.loads(shown.stdout)["data"]["id"], "STORY-1")
        listed = softory(self.root, "coord", "--actor", "greg", "task", "list", "--limit", "1", check=False)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        # A command that takes --actor still gets it.
        added = softory(self.root, "coord", "evidence", "add", "--task", "STORY-1", "--uri", "note:x", "--type",
                        "note", "--actor", "greg")
        self.assertTrue(json.loads(added.stdout)["ok"])

    def test_a_stand_in_starts_a_session_and_gets_a_review_workspace(self) -> None:
        coord(self.root, "agent", "add", "--id", "avery", "--name", "Avery", "--role", "Reviewer", "--actor", "owner")
        refused = softory(self.root, "start", "avery", "--harness", "codex", check=False)
        self.assertIn("Unknown role", refused.stderr)  # not until the owner grants it
        at_terminal(self.root, "standin", "add", "avery", "--for", "jade,gold")
        exports = softory(self.root, "start", "avery", "--harness", "codex").stdout
        self.assertIn("SOFTORY_ROLE=avery", exports)
        made = softory(self.root, "workspace", "avery", check=False)
        self.assertEqual(made.returncode, 0, made.stderr)

    def test_flow_leaves_out_run_numbers_it_did_not_measure(self) -> None:
        before = json.loads(softory(self.root, "flow").stdout)
        self.assertNotIn("unmeasured", before)
        start(self.root, "jade")  # a session the owner opened: the runner logs nothing for it
        report = json.loads(softory(self.root, "flow").stdout)
        self.assertEqual(report["unmeasured"]["roles"], ["jade"])
        for key in ("runs_per_unit", "minutes_per_unit", "tokens_per_unit", "usd_per_unit", "idle_share"):
            self.assertIsNone(report[key], key)

    def test_doctor_does_not_call_attended_sessions_a_second_scheduler(self) -> None:
        self.charter({"feasibility": {"required": False}})
        start(self.root, "jade")
        warned = json.loads(softory(self.root, "doctor", check=False).stdout)["warnings"]
        self.assertTrue([w for w in warned if "started outside the runner" in w])
        self.attended()
        quiet = json.loads(softory(self.root, "doctor", check=False).stdout)["warnings"]
        self.assertFalse([w for w in quiet if "started outside the runner" in w])


if __name__ == "__main__":
    unittest.main()
