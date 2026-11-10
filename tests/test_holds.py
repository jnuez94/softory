"""Work waiting on the owner wakes nobody, reviewers reuse one checkout, and evidence stays out of the
main checkout (0.5.5, from the Tablet pilot)."""

from __future__ import annotations

import json
import os
import time
import unittest

from tests.helpers import coord, git_project, git_status, install, needs_sources, revision, run, softory
from tests.test_workflow import at_terminal, start


@needs_sources
class HoldsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.holder, self.root = git_project({"README.md": "# app\n", ".gitignore": "node_modules/\n"})
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        softory(self.root, "new", "story", "--title", "See today", "--actor", "greg")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--title", "List",
                "--tags", "ui", "--actor", "quinn")
        self.approve({"feasibility": {"required": False}, "verify": {"share": ["node_modules"]}})

    def approve(self, settings: dict) -> dict:
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps(settings))
        return at_terminal(self.root, "charter", "approve", str(path), "--merge")

    def commit(self, name: str, text: str) -> str:
        (self.root / name).parent.mkdir(parents=True, exist_ok=True)
        (self.root / name).write_text(text)
        run(["git", "add", name], self.root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", name], self.root)
        return run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()

    def queue(self, agent: str = "jade") -> dict:
        return json.loads(softory(self.root, "queue", "--agent", agent).stdout)

    def pending(self, agent: str = "jade") -> dict:
        return json.loads(softory(self.root, "pending", agent, check=False).stdout)

    def test_an_escalation_holds_its_units_until_the_answer(self) -> None:
        self.assertEqual([a["id"] for a in self.queue()["assigned"]], ["TASK-1"])
        made = json.loads(softory(self.root, "escalate", "--issue", "The chat provider needs a paid key.",
                                  "--ask", "Buy the provider key?", "--recommend", "Use a fake provider",
                                  "--reversible", "no", "--holds", "TASK-1", "--actor", "jade").stdout)
        self.assertEqual(made["holds"], ["TASK-1"])
        self.assertEqual(coord(self.root, "escalation", "show", made["escalation"])["data"]["related_tasks"], "TASK-1")
        queued = self.queue()
        self.assertEqual((queued["assigned"], [h["id"] for h in queued["held"]]), ([], ["TASK-1"]))
        self.assertIn(made["escalation"], queued["held"][0]["why"])
        self.assertFalse(self.pending()["pending"])
        self.assertFalse(json.loads(softory(self.root, "pending", "jade", "--retry-hours", "0.0001",
                                            check=False).stdout)["pending"])  # not even the retry
        start(self.root, "jade")  # a finished session, so released work must be newer than its start
        softory(self.root, "end", "--actor", "jade")
        time.sleep(1.1)
        at_terminal(self.root, "answer", made["escalation"], "Use a fake provider for now")
        self.assertEqual([a["id"] for a in self.queue()["assigned"]], ["TASK-1"])
        woke = self.pending()
        self.assertTrue(woke["pending"])
        self.assertIn("TASK-1", {i for r in woke["reasons"] for i in r.get("ids", [])})
        self.assertIn("not_found", softory(self.root, "escalate", "--issue", "x y z.", "--ask", "Ok?",
                                           "--recommend", "a", "--reversible", "no", "--holds", "TASK-99",
                                           "--actor", "jade", check=False).stderr)

    def test_a_run_sees_its_own_work_and_every_command_takes_actor(self) -> None:
        session = start(self.root, "jade")["COORDINATION_SESSION"]
        self.assertFalse(self.pending()["pending"])  # from outside, Jade is busy: don't start her twice
        inside = json.loads(softory(self.root, "pending", "jade", env={"COORDINATION_SESSION": session},
                                    check=False).stdout)
        self.assertTrue(inside["pending"], inside)  # from inside her own run, the work is still hers to do
        for command in (["queue"], ["inbox"], ["pending"], ["charter", "show"]):
            ran = softory(self.root, *command, "--actor", "jade", check=False)
            self.assertNotIn("unrecognized arguments", ran.stderr, command)
        self.assertEqual(json.loads(softory(self.root, "queue", "--actor", "jade").stdout)["agent"], "jade")

    def test_an_unanswered_escalation_holds_however_old_it_is(self) -> None:
        made = json.loads(softory(self.root, "escalate", "--issue", "The chat provider needs a paid key.",
                                  "--ask", "Buy the provider key?", "--recommend", "Use a fake provider",
                                  "--reversible", "no", "--holds", "TASK-1", "--actor", "jade").stdout)
        rows_path = self.root / ".coordination/softory/escalations.json"
        rows = json.loads(rows_path.read_text())
        rows[made["escalation"]]["at"] = "2020-01-01T00:00:00+00:00"
        rows_path.write_text(json.dumps(rows))
        self.assertEqual([h["id"] for h in self.queue()["held"]], ["TASK-1"])

    def test_reports_with_the_same_name_never_overwrite_each_other(self) -> None:
        uris = []
        for n in range(3):
            report = self.root / "review.md"
            report.write_text(f"pass {n}\n")
            uris.append(json.loads(softory(self.root, "report", "TASK-1", str(report), "--actor", "gold").stdout)["uri"])
        self.assertEqual(len(set(uris)), 3)
        self.assertEqual([(self.root / u).read_text() for u in uris], ["pass 0\n", "pass 1\n", "pass 2\n"])

    def test_an_owner_waiver_of_the_reference_check_counts_at_handoff(self) -> None:
        sha = self.commit("web/a.js", "a\n")
        start(self.root, "jade")
        coord(self.root, "--session", json.loads((self.root / ".coordination/softory/sessions/jade.json").read_text())
              ["session"], "task", "claim", "TASK-1", "--agent", "jade", "--if-revision", revision(self.root, "TASK-1"))
        softory(self.root, "commit", "TASK-1", sha, "--actor", "jade")
        self.assertIn("ui_reference_missing", softory(self.root, "handoff", "TASK-1", "--actor", "jade",
                                                      check=False).stderr)
        proposal = json.loads(softory(self.root, "propose", "waiver", "TASK-1", "--check", "ui_reference",
                                      "--why", "a text-only fix", "--actor", "jade").stdout)
        at_terminal(self.root, "approve", proposal["proposal"])
        self.assertEqual(json.loads(softory(self.root, "handoff", "TASK-1", "--actor", "jade").stdout)["status"],
                         "review")

    def test_held_work_in_review_stays_in_its_builders_queue(self) -> None:
        sha = self.commit("web/a.js", "a\n")
        session = start(self.root, "jade")["COORDINATION_SESSION"]
        coord(self.root, "--session", session, "task", "claim", "TASK-1", "--agent", "jade",
              "--if-revision", revision(self.root, "TASK-1"))
        softory(self.root, "commit", "TASK-1", sha, "--actor", "jade")
        proposal = json.loads(softory(self.root, "propose", "waiver", "TASK-1", "--check", "ui_reference",
                                      "--why", "a text-only fix", "--actor", "jade").stdout)
        at_terminal(self.root, "approve", proposal["proposal"])
        softory(self.root, "handoff", "TASK-1", "--actor", "jade")
        ruling = json.loads(softory(self.root, "ruling", "--title", "Park it", "--decision", "Wait", "--where", "x",
                                    "--actor", "quinn").stdout)["decision"]
        softory(self.root, "defer", "TASK-1", "--decision", ruling, "--actor", "quinn")
        self.assertEqual([h["id"] for h in self.queue()["held"]], ["TASK-1"])

    def test_an_owner_ruling_defers_a_unit_until_lifted(self) -> None:
        refused = softory(self.root, "defer", "TASK-1", "--decision", "nope", "--actor", "quinn", check=False)
        self.assertIn("not_found", refused.stderr)
        coord(self.root, "decision", "add", "--id", "DEC-Q", "--title", "Mine", "--owner", "quinn",
              "--status", "accepted", "--context", "c", "--decision", "d")
        self.assertIn("not_allowed", softory(self.root, "defer", "TASK-1", "--decision", "DEC-Q", "--actor", "quinn",
                                             check=False).stderr)
        ruling = json.loads(softory(self.root, "ruling", "--title", "Park the list", "--decision", "Wait for v2",
                                    "--where", "thread, 9 Nov", "--actor", "quinn").stdout)["decision"]
        coord(self.root, "decision", "add", "--id", "DEC-ASK", "--title", "Asked", "--owner", "owner",
              "--status", "proposed", "--context", "c", "--decision", "d")
        self.assertIn("not accepted", softory(self.root, "defer", "TASK-1", "--decision", "DEC-ASK",
                                              "--actor", "quinn", check=False).stderr)
        softory(self.root, "defer", "TASK-1", "--decision", ruling, "--until", "2099-01-01", "--actor", "quinn")
        coord(self.root, "message", "send", "--id", "MSG-FYI", "--sender", "quinn", "--recipient", "jade",
              "--task", "TASK-1", "--body", "FYI on the list")
        self.assertFalse(self.pending()["pending"])  # news about held work wakes nobody
        time.sleep(1.1)
        self.assertFalse(json.loads(softory(self.root, "pending", "jade", "--retry-hours", "0.0001",
                                            check=False).stdout)["pending"])  # not even on the retry
        self.assertEqual(self.queue()["assigned"], [])
        self.assertIn("2099-01-01", self.queue()["held"][0]["why"])
        softory(self.root, "defer", "TASK-1", "--lift", "--actor", "quinn")
        self.assertEqual([a["id"] for a in self.queue()["assigned"]], ["TASK-1"])

    def test_a_blocked_unit_wakes_its_builder_when_its_deferral_is_lifted(self) -> None:
        session = start(self.root, "jade")["COORDINATION_SESSION"]
        coord(self.root, "--session", session, "task", "claim", "TASK-1", "--agent", "jade",
              "--if-revision", revision(self.root, "TASK-1"))
        coord(self.root, "--session", session, "task", "release", "TASK-1", "--to", "blocked", "--actor", "jade",
              "--if-revision", revision(self.root, "TASK-1"), "--note", "waits for the owner")
        softory(self.root, "end", "--actor", "jade")
        ruling = json.loads(softory(self.root, "ruling", "--title", "Park it", "--decision", "Wait", "--where", "x",
                                    "--actor", "quinn").stdout)["decision"]
        softory(self.root, "defer", "TASK-1", "--decision", ruling, "--actor", "quinn")
        self.assertFalse(self.pending()["pending"])
        time.sleep(1.1)
        softory(self.root, "defer", "TASK-1", "--lift", "--actor", "quinn")
        woke = self.pending()
        self.assertTrue(woke["pending"], woke)
        self.assertIn({"why": "held work released: the owner answered, or the deferral ended", "ids": ["TASK-1"]},
                      woke["reasons"])
        start(self.root, "jade")  # a run that ends without touching the unit
        softory(self.root, "end", "--actor", "jade")
        time.sleep(1.1)
        retry = lambda: json.loads(softory(self.root, "pending", "jade", "--retry-hours", "0.0001", check=False).stdout)
        self.assertIn("TASK-1", json.dumps(retry()["reasons"]))  # still unhandled: the retry picks it up
        coord(self.root, "task", "update", "TASK-1", "--next-steps", "Unblock with the ruling", "--actor", "jade",
              "--if-revision", revision(self.root, "TASK-1"))
        time.sleep(1.1)
        self.assertNotIn("TASK-1", json.dumps(retry()["reasons"]))  # handled: blocked work rests again

    def test_handoff_needs_the_reference_check_for_ui_work(self) -> None:
        sha = self.commit("web/a.js", "a\n")
        session = start(self.root, "jade")["COORDINATION_SESSION"]
        coord(self.root, "--session", session, "task", "claim", "TASK-1", "--agent", "jade",
              "--if-revision", revision(self.root, "TASK-1"))
        refused = softory(self.root, "handoff", "TASK-1", "--actor", "jade", check=False)
        self.assertIn("evidence_required", refused.stderr)
        empty = softory(self.root, "coord", "task", "release", "TASK-1", "--to", "review", "--actor", "jade",
                        "--if-revision", revision(self.root, "TASK-1"), check=False)
        self.assertIn("evidence_required", empty.stderr)  # the passthrough asks the same as handoff
        softory(self.root, "commit", "TASK-1", sha, "--actor", "jade")
        refused = softory(self.root, "handoff", "TASK-1", "--actor", "jade", check=False)
        self.assertIn("ui_reference_missing", refused.stderr)
        rev = revision(self.root, "TASK-1")
        for spelling in (["TASK-1", "--to", "review", "--actor", "jade", "--if-revision", rev],
                         ["TASK-1", "--to=review", "--actor", "jade", "--if-revision", rev],
                         ["--actor", "jade", "TASK-1", "--to", "review", "--if-revision", rev],
                         ["--because", "decision:DEC-1", "TASK-1", "--to", "review", "--actor", "jade",
                          "--if-revision", rev]):
            bare = softory(self.root, "coord", "task", "release", *spelling, check=False)
            self.assertIn("ui_reference_missing", bare.stderr, spelling)
        shot = self.root / "shot.png"
        shot.write_bytes(b"png")
        filed = json.loads(softory(self.root, "report", "TASK-1", str(shot), "--type", "reference",
                                   "--actor", "jade").stdout)
        self.assertTrue(filed["moved"])
        self.assertFalse(shot.exists())
        self.assertTrue((self.root / filed["uri"]).is_file())
        self.assertEqual(git_status(self.root), "")  # the checkout stays clean
        handed = json.loads(softory(self.root, "handoff", "TASK-1", "--actor", "jade").stdout)
        self.assertEqual(handed["status"], "review")
        self.assertEqual(coord(self.root, "task", "show", "TASK-1")["data"]["status"], "review")
        tracked = json.loads(softory(self.root, "report", "TASK-1", str(self.root / "README.md"),
                                     "--actor", "jade").stdout)
        self.assertFalse(tracked["moved"])  # a tracked file is copied, never taken
        self.assertTrue((self.root / "README.md").is_file())
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--title", "Other",
                "--actor", "quinn")
        reused = json.loads(softory(self.root, "report", "TASK-2", str(self.root / filed["uri"]),
                                    "--actor", "jade").stdout)
        self.assertFalse(reused["moved"])  # another unit's evidence is copied, so TASK-1's link still works
        self.assertTrue((self.root / filed["uri"]).is_file())
        self.assertTrue((self.root / reused["uri"]).is_file())

    def test_reviewers_wait_for_the_reference_check_even_when_messaged(self) -> None:
        sha = self.commit("web/a.js", "a\n")
        session = start(self.root, "jade")["COORDINATION_SESSION"]
        coord(self.root, "--session", session, "task", "claim", "TASK-1", "--agent", "jade",
              "--if-revision", revision(self.root, "TASK-1"))
        softory(self.root, "commit", "TASK-1", sha, "--actor", "jade")
        # Released straight through the tracker, as units were before handoff checked the reference
        coord(self.root, "--session", session, "task", "release", "TASK-1", "--to", "review", "--actor", "jade",
              "--if-revision", revision(self.root, "TASK-1"))
        softory(self.root, "end", "--actor", "jade")
        others = ["greg", "darwin", "quinn", "gold", "toby"]
        for role in others:
            coord(self.root, "message", "send", "--id", f"MSG-{role}", "--sender", "jade", "--recipient", role,
                  "--task", "TASK-1", "--tags", "request", "--body", "Ready for review")
        for role in others:
            self.assertNotIn("TASK-1", [r["id"] for r in self.queue(role)["reviews_waiting"]], role)
            woke = self.pending(role)
            self.assertNotIn("messages that need you", [r["why"] for r in woke["reasons"]], role)
            self.assertNotIn("TASK-1", json.dumps(woke["reasons"]), role)
        self.assertIn("TASK-1", json.dumps(self.pending("jade")["reasons"]))  # the builder owes the check
        shot = self.root / "shot.png"
        shot.write_bytes(b"png")
        softory(self.root, "report", "TASK-1", str(shot), "--type", "reference", "--actor", "jade")
        self.assertTrue(any("TASK-1" in [r["id"] for r in self.queue(role)["reviews_waiting"]] for role in others))

    def test_a_reviewer_reuses_one_workspace(self) -> None:
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules/dep.js").write_text("dep\n")
        first = self.commit("web/a.js", "a\n")
        second = self.commit("web/b.js", "b\n")
        made = json.loads(softory(self.root, "workspace", "gold", first).stdout)
        tree = self.root / ".coordination/softory/workspaces/gold"
        self.assertEqual((made["mode"], made["workspace"]), ("worktree", str(tree)))
        self.assertTrue((tree / "web/a.js").is_file())
        self.assertFalse((tree / "web/b.js").exists())
        self.assertTrue((tree / "node_modules/dep.js").is_file())
        (tree / "scratch.txt").write_text("left over\n")
        moved = json.loads(softory(self.root, "workspace", "gold", second).stdout)
        self.assertEqual((moved["mode"], moved["commit"]), ("worktree", second))
        self.assertTrue((tree / "web/b.js").is_file())
        self.assertFalse((tree / "scratch.txt").exists())
        self.assertTrue((self.root / "node_modules/dep.js").is_file())  # the shared folder is never touched
        run(["git", "worktree", "remove", "--force", str(tree)], self.root)
        (self.root / ".git/worktrees").write_text("")  # as under a .git-protecting sandbox
        snap = json.loads(softory(self.root, "workspace", "gold", first).stdout)
        self.assertEqual(snap["mode"], "snapshot")
        self.assertTrue((tree / "web/a.js").is_file())

    def test_start_refuses_a_harness_the_charter_doesnt_name(self) -> None:
        refused = softory(self.root, "start", "jade", "--harness", "codex", check=False)
        self.assertIn("wrong_harness", refused.stderr)
        self.approve({"models": {"jade": {"harness": "claude", "model": "m", "escalate": None, "also": ["codex"]}}})
        allowed = softory(self.root, "start", "jade", "--harness", "codex")
        self.assertIn("COORDINATION_SESSION=jade-codex-", allowed.stdout)

    def test_gc_removes_old_logs_and_idle_workspaces(self) -> None:
        softory(self.root, "workspace", "gold")
        logs = self.root / ".coordination/softory/logs"
        logs.mkdir(parents=True, exist_ok=True)
        old, new = logs / "jade-old.out", logs / "jade-new.out"
        old.write_text("x" * 1000)
        new.write_text("y")
        week_ago = time.time() - 30 * 86400
        os.utime(old, (week_ago, week_ago))
        os.utime(self.root / ".coordination/softory/workspaces/gold", (week_ago, week_ago))
        listed = json.loads(softory(self.root, "gc", "--dry-run").stdout)
        self.assertEqual(listed["would_remove"], {"workspace": 1, "log": 1})
        self.assertTrue(old.exists())
        json.loads(softory(self.root, "gc").stdout)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())
        self.assertFalse((self.root / ".coordination/softory/workspaces/gold").exists())
        self.assertNotIn("workspaces/gold", run(["git", "worktree", "list"], self.root).stdout)

    def test_verify_warns_about_loose_files_in_the_checkout(self) -> None:
        self.approve({"verify": {"command": "true"}})
        sha = self.commit("web/a.js", "a\n")
        coord(self.root, "evidence", "add", "--task", "TASK-1", "--uri", f"commit:{sha}", "--type", "commit",
              "--actor", "jade")
        (self.root / "review-notes.md").write_text("notes\n")
        result = json.loads(softory(self.root, "verify", "TASK-1", "--actor", "jade").stdout)
        self.assertTrue(result["passed"])
        self.assertIn("review-notes.md", result["warning"])


if __name__ == "__main__":
    unittest.main()
