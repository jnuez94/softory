"""One operating loop whatever the harness: sessions that survive fresh shells, state any sandbox can write,
and a gate no close path skips (0.5.4, from the Tablet pilot)."""

from __future__ import annotations

import json
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.helpers import REPO

sys.path.insert(0, str(REPO / "lib"))
from softory import digest, runner, watch, work  # noqa: E402
from softory.coordination import Coordination  # noqa: E402
from tests.helpers import COORDINATION, coord, git_project, git_status, install, needs_sources, revision, run, softory
from tests.test_workflow import at_terminal, failing, gate, start


@needs_sources
class HarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.holder, self.root = git_project({"README.md": "# app\n", "web/app.js": "1\n", "api/app.py": "1\n"})
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        softory(self.root, "new", "story", "--title", "See today", "--actor", "greg")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--title", "List",
                "--actor", "quinn")

    def approve(self, settings: dict) -> dict:
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps(settings))
        return at_terminal(self.root, "charter", "approve", str(path))

    def commit(self, name: str, text: str) -> str:
        (self.root / name).parent.mkdir(parents=True, exist_ok=True)
        (self.root / name).write_text(text)
        run(["git", "add", name], self.root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", name], self.root)
        return run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()

    def build(self, task: str, builder: str, sha: str) -> None:
        session = start(self.root, builder)["COORDINATION_SESSION"]
        coord(self.root, "--session", session, "task", "claim", task, "--agent", builder,
              "--if-revision", revision(self.root, task))
        coord(self.root, "evidence", "add", "--task", task, "--uri", f"commit:{sha}", "--type", "commit",
              "--actor", builder)
        coord(self.root, "--session", session, "task", "release", task, "--to", "review", "--actor", builder,
              "--if-revision", revision(self.root, task))
        softory(self.root, "end", "--session", session)

    def review(self, task: str, reviewer: str, decision: str, n: int = 1) -> None:
        coord(self.root, "review", "add", "--id", f"REV-{task}-{reviewer}-{n}", "--task", task, "--reviewer", reviewer,
              "--artifact", "x", "--scope", "t", "--decision", decision, "--required-changes",
              "" if decision == "accepted" else "blocking: fix it")

    def test_a_stack_close_runs_the_tests_and_lane_checks(self) -> None:
        self.approve({"verify": {"command": "true"}, "lanes": {"frontend": ["web/**"]}, "git": {"base": "HEAD"}})
        self.build("TASK-1", "jade", self.commit("web/a.js", "a\n"))  # strict dependencies: built before it waits
        softory(self.root, "new", "bug", "--type", "functional", "--from", "TASK-1", "--blocks-source",
                "--title", "On top", "--actor", "quinn")
        softory(self.root, "stack", "TASK-1", "BUG-1", "--actor", "jade")
        self.build("BUG-1", "jade", self.commit("web/b.js", "b\n"))
        self.review("TASK-1", "gold", "accepted")
        self.review("BUG-1", "gold", "accepted")
        softory(self.root, "verify", "BUG-1", "--actor", "jade")  # TASK-1 never tested
        held = json.loads(softory(self.root, "close", "TASK-1", "--stack", "--actor", "jade", check=False).stdout)
        self.assertFalse(held["closed"])
        self.assertIn("TASK-1", held["failing"])
        self.assertIn("verified", {c["check"] for g in held["gates"] for c in g["checks"] if not c["pass"]})
        softory(self.root, "verify", "TASK-1", "--actor", "jade")
        closed = json.loads(softory(self.root, "close", "TASK-1", "--stack", "--actor", "jade").stdout)
        self.assertTrue(closed["closed"])
        at_close = json.loads((self.root / ".coordination/softory/closed.json").read_text())
        self.assertEqual(set(at_close), {"TASK-1", "BUG-1"})  # each member's approved commit, for softory ship

    def test_a_fresh_shell_keeps_the_session_through_the_role(self) -> None:
        session = start(self.root, "jade")["COORDINATION_SESSION"]  # exports printed, then lost: no env below
        claimed = softory(self.root, "coord", "task", "claim", "TASK-1", "--agent", "jade",
                          "--if-revision", revision(self.root, "TASK-1"))
        self.assertTrue(json.loads(claimed.stdout)["ok"])
        self.assertEqual(coord(self.root, "task", "show", "TASK-1")["data"]["claimed_by"], "jade")
        released = softory(self.root, "coord", "task", "release", "TASK-1", "--to", "todo", "--actor", "jade",
                           "--if-revision", revision(self.root, "TASK-1"))
        self.assertTrue(json.loads(released.stdout)["ok"])
        ended = json.loads(softory(self.root, "end", "--actor", "jade").stdout)
        self.assertEqual(ended["ended"], session)
        refused = softory(self.root, "coord", "task", "claim", "TASK-1", "--agent", "jade",
                          "--if-revision", revision(self.root, "TASK-1"), check=False)
        self.assertNotEqual(refused.returncode, 0)  # an ended session is never reused
        self.assertEqual(git_status(self.root), "")

    def test_runtime_state_lives_where_any_sandbox_can_write(self) -> None:
        softory(self.root, "feedback", "a note", "--actor", "jade")
        self.assertTrue((self.root / ".coordination/softory/feedback.jsonl").is_file())
        self.assertFalse((self.root / ".agents/softory/feedback.jsonl").exists())
        old = self.root / ".agents/softory/run"  # what 0.5.3 left behind
        old.mkdir(parents=True, exist_ok=True)
        (old / "runs.jsonl").write_text('{"role": "jade", "started": "2026-11-08T00:00:00+00:00"}\n')
        (self.root / ".coordination/softory/feedback.jsonl").rename(self.root / ".agents/softory/feedback.jsonl")
        install(self.root)  # the upgrade moves it
        self.assertTrue((self.root / ".coordination/softory/runs.jsonl").is_file())
        self.assertTrue((self.root / ".coordination/softory/feedback.jsonl").is_file())
        self.assertEqual(list(old.iterdir()), [])
        self.assertEqual(git_status(self.root), "")

    def test_verify_works_where_the_sandbox_protects_git(self) -> None:
        self.approve({"verify": {"command": "test -f web/c.js && test ! -e .git"}})
        self.build("TASK-1", "jade", self.commit("web/c.js", "c\n"))
        (self.root / ".git/worktrees").write_text("")  # git worktree add now fails, as under a .git-protecting sandbox
        result = json.loads(softory(self.root, "verify", "TASK-1", "--actor", "jade").stdout)
        self.assertTrue(result["passed"])

    def test_the_fallback_snapshot_keeps_files_archives_leave_out(self) -> None:
        self.approve({"verify": {"command": "test ! -d tests || sh tests/check.sh"}})
        self.commit(".gitattributes", "tests/ export-ignore\n")
        self.build("TASK-1", "jade", self.commit("tests/check.sh", "exit 1\n"))  # a failing suite
        (self.root / ".git/worktrees").write_text("")
        result = json.loads(softory(self.root, "verify", "TASK-1", "--actor", "jade", check=False).stdout)
        self.assertFalse(result["passed"])  # git archive would have dropped tests/ and passed

    def test_a_review_another_reviewer_covered_is_not_owed(self) -> None:
        coord(self.root, "agent", "add", "--id", "avery", "--name", "Avery", "--role", "Reviewer", "--actor", "owner")
        softory(self.root, "propose", "standin", "avery", "--for", "gold", "--why", "share reviews", "--actor", "gold")
        at_terminal(self.root, "approve", "PROP-1")
        self.build("TASK-1", "jade", "1")

        def owed(agent: str) -> list[str]:
            return [r["id"] for r in json.loads(softory(self.root, "queue", "--agent", agent).stdout)["reviews_waiting"]]

        self.assertEqual((owed("gold"), owed("avery")), (["TASK-1"], ["TASK-1"]))
        self.review("TASK-1", "gold", "accepted")
        self.assertEqual(owed("avery"), [])  # gold covered the peer review
        self.assertEqual(owed("gold"), [])

    def test_a_reviewer_waits_for_new_evidence_after_asking_for_changes(self) -> None:
        self.build("TASK-1", "jade", "1")
        self.review("TASK-1", "gold", "changes_requested")
        queue = lambda: [r["id"] for r in json.loads(softory(self.root, "queue", "--agent", "gold").stdout)["reviews_waiting"]]
        self.assertEqual(queue(), [])  # the builder has the move, though its evidence may share the second
        coord(self.root, "evidence", "add", "--task", "TASK-1", "--uri", "commit:2", "--type", "commit", "--actor", "jade")
        self.assertEqual(queue(), ["TASK-1"])

    def test_retracting_evidence_answers_a_request_for_changes(self) -> None:
        self.build("TASK-1", "jade", "1")
        self.review("TASK-1", "gold", "changes_requested")
        queue = lambda: [r["id"] for r in json.loads(softory(self.root, "queue", "--agent", "gold").stdout)["reviews_waiting"]]
        self.assertEqual(queue(), [])
        row = coord(self.root, "task", "show", "TASK-1")["data"]["evidence"][0]
        softory(self.root, "supersede", "TASK-1", str(row["id"]), "--reason", "wrong commit", "--actor", "jade")
        self.assertEqual(queue(), ["TASK-1"])

    def test_an_interrupted_runner_stops_the_harness_before_handing_back_claims(self) -> None:
        import signal
        import subprocess

        script = (f"{COORDINATION} --session \"$COORDINATION_SESSION\" task claim TASK-1 --agent jade "
                  f"--if-revision {revision(self.root, 'TASK-1')}; sleep 4; touch .git/late")
        self.approve({"run": {"roles": ["jade"], "harnesses": {"fake": ["sh", "-c", script]}},
                      "models": {"jade": {"harness": "fake", "model": "m1", "escalate": None}},
                      "feasibility": {"required": False}})
        runner_process = subprocess.Popen([str(self.root / ".agents/softory/bin/softory"), "run-role", "jade"],
                                          cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(100):
            if coord(self.root, "task", "show", "TASK-1")["data"].get("claimed_by") == "jade":
                break
            time.sleep(0.1)
        runner_process.send_signal(signal.SIGINT)
        runner_process.communicate(timeout=60)
        task = coord(self.root, "task", "show", "TASK-1")["data"]
        self.assertEqual((task["status"], task.get("claimed_by")), ("todo", None))
        time.sleep(4.5)
        self.assertFalse((self.root / ".git/late").exists())  # the harness was stopped, not left editing

    def test_the_week_counts_moves_to_done_not_edits(self) -> None:
        softory(self.root, "start", "quinn")
        softory(self.root, "drop", "TASK-1", "--reason", "not needed", "--actor", "quinn")
        connection = Coordination(self.root / COORDINATION, self.root)
        self.assertEqual(digest.closed_since(connection, "2000-01-01T00:00:00+00:00"), {"TASK-1"})
        time.sleep(1.1)
        after = datetime.now(timezone.utc).isoformat(timespec="seconds")
        coord(self.root, "task", "update", "TASK-1", "--title", "Renamed", "--actor", "quinn",
              "--if-revision", revision(self.root, "TASK-1"))
        self.assertEqual(digest.closed_since(connection, after), set())  # an edit isn't a delivery

    def test_runs_record_what_they_changed_and_the_digest_sums_it(self) -> None:
        (self.root / ".git/report.json").write_text(json.dumps({"total_cost_usd": 0.25,
                                                                 "usage": {"input_tokens": 1, "output_tokens": 1}}))
        script = "cat .git/report.json"
        self.approve({"run": {"roles": ["jade"], "harnesses": {"fake": ["sh", "-c", script, "sh", "{prompt}"]}},
                      "models": {"jade": {"harness": "fake", "model": "m1", "escalate": None}},
                      "feasibility": {"required": False}})
        ran = json.loads(softory(self.root, "run-role", "jade").stdout)
        self.assertEqual(ran["changes"], 0)  # the fake harness did nothing
        week = json.loads(softory(self.root, "usage").stdout)["last_7_days"]
        self.assertEqual((week["runs"], week["usd"], week["idle_share"]), (1, 0.25, 1.0))
        digest = Path(json.loads(softory(self.root, "digest").stdout)["file"]).read_text()
        self.assertIn("100% changed nothing", digest)

    def test_a_run_that_stops_mid_task_hands_the_claim_back(self) -> None:
        script = (f"{COORDINATION} --session \"$COORDINATION_SESSION\" task claim TASK-1 --agent jade "
                  f"--if-revision {revision(self.root, 'TASK-1')}")  # then the harness exits, claim held
        self.approve({"run": {"roles": ["jade"], "harnesses": {"fake": ["sh", "-c", script]}},
                      "models": {"jade": {"harness": "fake", "model": "m1", "escalate": None}},
                      "feasibility": {"required": False}})
        softory(self.root, "run-role", "jade")
        task = coord(self.root, "task", "show", "TASK-1")["data"]
        self.assertEqual((task["status"], task.get("claimed_by")), ("todo", None))
        self.assertIn("claim it again", task["notes"])
        self.assertEqual(coord(self.root, "session", "list", "--agent", "jade", "--status", "active")["data"], [])
        self.assertFalse((self.root / ".coordination/softory/sessions/jade.json").exists())


class OrderingTest(unittest.TestCase):
    """Whole-second timestamps and paged inboxes, without a project."""

    def test_evidence_in_the_reviews_second_goes_by_the_audit_order(self) -> None:
        task = {"evidence": [{"id": "7", "created_at": "2026-11-09T01:00:00+00:00"}]}
        latest = {"gold": {"id": "REV-1", "decision": "changes_requested", "created_at": "2026-11-09T01:00:00+00:00"}}
        owed = lambda after: work.review_owed(task, {}, "gold", {"jade"}, latest, {"accepted"}, after)
        self.assertTrue(owed(lambda e, r: True))
        self.assertFalse(owed(lambda e, r: False))
        self.assertTrue(owed(None))  # unknown order: wake the reviewer rather than stall the task

    def test_an_owner_message_past_the_first_page_still_wakes(self) -> None:
        inbox = [{"id": f"MSG-{n}", "sender_id": "greg", "body": "noted"} for n in range(5)]
        inbox.append({"id": "MSG-5", "sender_id": "owner", "body": "please look"})

        class Coord:
            def run(self, *args: str) -> dict:
                limit, offset = int(args[args.index("--limit") + 1]), int(args[args.index("--offset") + 1])
                return {"messages": inbox[offset:offset + limit]}

        class Board:
            tasks: list = []
            reviews: dict = {}

            class project:
                @staticmethod
                def roster() -> dict:
                    return {"owner": {"id": "owner"}}

        wanted, rest = watch.unread_messages(Coord(), "jade", Board(), {}, page=2)
        self.assertEqual([m["id"] for m in wanted], ["MSG-5"])
        self.assertEqual(len(rest), 5)

    def test_a_timed_out_harness_that_ignores_sigterm_is_stopped_before_cleanup(self) -> None:
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / "still-running"
            script = f"trap '' TERM; (trap '' TERM; sleep 2; touch {marker}) & sleep 60"
            child = subprocess.Popen(["sh", "-c", script], start_new_session=True)
            started = time.monotonic()
            runner._stop(child, grace=0.5)
            self.assertIsNotNone(child.returncode)  # it has exited when _stop returns
            self.assertLess(time.monotonic() - started, 10)
            time.sleep(2.5)
            self.assertFalse(marker.exists())  # the background job it left was killed with it


if __name__ == "__main__":
    unittest.main()
