"""An epic > story > task runs end to end through softory new, gate, and the CLI."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.helpers import coord, git_project, git_status, install, needs_sources, revision, run, softory


def start(root: Path, role: str) -> dict[str, str]:
    exports = softory(root, "start", role).stdout
    env = dict(line.removeprefix("export ").split("=", 1) for line in exports.splitlines())
    return env


def gate(root: Path, unit: str, actor: str) -> dict:
    result = softory(root, "gate", unit, "--actor", actor, check=False)
    return json.loads(result.stdout)


def failing(report: dict) -> set[str]:
    return {check["check"] for check in report["checks"] if not check["pass"]}


@needs_sources
class WorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.holder, self.root = git_project()
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        softory(self.root, "new", "epic", "--title", "Radar", "--actor", "greg")
        softory(self.root, "new", "story", "--parent", "EPIC-1", "--title", "See today", "--tags", "ui", "--actor", "greg")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--title", "List", "--actor", "quinn")

    def build(self, task: str, builder: str) -> dict[str, str]:
        session = start(self.root, builder)["COORDINATION_SESSION"]
        coord(self.root, "--session", session, "task", "claim", task, "--agent", builder, "--if-revision", revision(self.root, task))
        coord(self.root, "evidence", "add", "--task", task, "--uri", "commit:1", "--type", "commit", "--actor", builder)
        coord(self.root, "--session", session, "task", "release", task, "--to", "review", "--actor", builder,
              "--if-revision", revision(self.root, task))
        return {"session": session}

    def review(self, task: str, reviewer: str, decision: str, number: int) -> None:
        coord(self.root, "review", "add", "--id", f"REV-{task}-{reviewer}-{number}", "--task", task, "--reviewer", reviewer,
              "--artifact", "commit:1", "--scope", "test", "--decision", decision)

    def test_hierarchy_tags_and_defaults(self) -> None:
        task = coord(self.root, "task", "show", "TASK-1")["data"]
        self.assertEqual(task["assignees"], ["jade"])
        self.assertEqual(task["tags"], "unit:task,parent:STORY-1,lane:frontend")
        story = coord(self.root, "task", "show", "STORY-1")["data"]
        self.assertEqual([d["depends_on_task_id"] for d in story["dependencies"]], ["TASK-1"])
        tree = softory(self.root, "tree").stdout.splitlines()
        self.assertEqual([line.split(" [")[0] for line in tree], ["EPIC-1", "  STORY-1", "    TASK-1"])
        self.assertEqual(git_status(self.root), "")

    def test_hierarchy_is_enforced(self) -> None:
        bad = softory(self.root, "new", "task", "--parent", "EPIC-1", "--lane", "backend", "--title", "x", "--actor", "quinn", check=False)
        self.assertIn("invalid_arguments", bad.stderr)
        no_lane = softory(self.root, "new", "task", "--parent", "STORY-1", "--title", "x", "--actor", "quinn", check=False)
        self.assertIn("needs --lane", no_lane.stderr)

    def test_self_review_never_counts(self) -> None:
        self.build("TASK-1", "jade")
        self.review("TASK-1", "jade", "accepted", 1)
        self.assertIn("review:unit:task", failing(gate(self.root, "TASK-1", "jade")))

    def test_changes_requested_blocks_until_reaccepted(self) -> None:
        self.build("TASK-1", "jade")
        self.review("TASK-1", "gold", "changes_requested", 1)
        self.assertIn("no_open_rejections", failing(gate(self.root, "TASK-1", "jade")))
        self.review("TASK-1", "gold", "accepted", 2)
        self.assertTrue(gate(self.root, "TASK-1", "jade")["pass"])

    def test_close_refuses_until_the_gate_passes(self) -> None:
        self.build("TASK-1", "jade")
        refused = softory(self.root, "close", "TASK-1", "--actor", "jade", check=False)
        self.assertEqual(refused.returncode, 3)
        self.assertEqual(coord(self.root, "task", "show", "TASK-1")["data"]["status"], "review")
        self.review("TASK-1", "gold", "accepted", 1)
        softory(self.root, "close", "TASK-1", "--actor", "jade")
        self.assertEqual(coord(self.root, "task", "show", "TASK-1")["data"]["status"], "done")

    def test_only_the_closer_may_close(self) -> None:
        self.build("TASK-1", "jade")
        self.review("TASK-1", "gold", "accepted", 1)
        self.assertEqual(failing(gate(self.root, "TASK-1", "gold")), {"closer"})

    def test_tag_reviews_are_required(self) -> None:
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "backend", "--title", "Auth",
                "--tags", "auth", "--actor", "quinn")
        self.build("TASK-2", "gold")
        self.review("TASK-2", "jade", "accepted", 1)
        self.assertIn("review:tag:auth", failing(gate(self.root, "TASK-2", "gold")))
        self.review("TASK-2", "toby", "accepted", 1)
        self.assertTrue(gate(self.root, "TASK-2", "gold")["pass"])

    def test_story_closes_only_after_children_and_acceptance(self) -> None:
        self.build("TASK-1", "jade")
        self.review("TASK-1", "gold", "accepted", 1)
        self.assertIn("children_done", failing(gate(self.root, "STORY-1", "greg")))
        softory(self.root, "close", "TASK-1", "--actor", "jade")
        self.build("STORY-1", "greg")
        report = gate(self.root, "STORY-1", "greg")
        self.assertEqual(failing(report), {"review:unit:story", "review:tag:ui"})
        self.review("STORY-1", "greg", "accepted", 1)
        self.review("STORY-1", "darwin", "accepted", 1)
        self.assertTrue(gate(self.root, "STORY-1", "greg")["pass"])

    def test_queue_lists_waiting_reviews(self) -> None:
        self.build("TASK-1", "jade")
        queue = json.loads(softory(self.root, "queue", "--agent", "gold").stdout)
        self.assertEqual([item["id"] for item in queue["reviews_waiting"]], ["TASK-1"])
        mine = json.loads(softory(self.root, "queue", "--agent", "jade").stdout)
        self.assertEqual(mine["reviews_waiting"], [])

    def test_stand_in_reviews_for_jade_and_gold(self) -> None:
        coord(self.root, "agent", "add", "--id", "avery", "--name", "Avery", "--role", "Reviewer", "--actor", "owner")
        added = json.loads(softory(self.root, "standin", "add", "avery", "--for", "jade,gold").stdout)
        decision = coord(self.root, "decision", "show", added["decision"])["data"]
        self.assertEqual(decision["status"], "accepted")
        self.assertIn("`avery` stands in for `gold`, `jade`.", (self.root / "AGENTS.md").read_text())
        self.build("TASK-1", "jade")
        queue = json.loads(softory(self.root, "queue", "--agent", "avery").stdout)
        self.assertEqual([item["id"] for item in queue["reviews_waiting"]], ["TASK-1"])
        self.review("TASK-1", "avery", "accepted", 1)
        self.assertTrue(gate(self.root, "TASK-1", "jade")["pass"])
        install(self.root)  # an upgrade keeps the stand-in
        self.assertIn("stands in for", (self.root / "AGENTS.md").read_text())
        softory(self.root, "standin", "remove", "avery")
        self.assertNotIn("stands in for", (self.root / "AGENTS.md").read_text())
        self.assertFalse(gate(self.root, "TASK-1", "jade")["pass"])
        self.assertEqual(git_status(self.root), "")

    def test_older_tasks_close_under_the_legacy_rule(self) -> None:
        coord(self.root, "task", "create", "--id", "VR-1", "--title", "Old", "--actor", "owner", "--assignee", "quinn")
        tree = softory(self.root, "tree").stdout
        self.assertNotIn("VR-1", tree)
        self.assertIn("1 task(s) without a unit", tree)
        self.build("VR-1", "quinn")
        self.assertIn("review:unit:legacy", failing(gate(self.root, "VR-1", "quinn")))
        self.review("VR-1", "darwin", "accepted", 1)
        softory(self.root, "close", "VR-1", "--actor", "quinn")
        self.assertEqual(coord(self.root, "task", "show", "VR-1")["data"]["status"], "done")

    def test_adopt_moves_an_older_task_into_a_story(self) -> None:
        coord(self.root, "task", "create", "--id", "VR-2", "--title", "Old", "--actor", "owner",
              "--assignee", "quinn", "--tags", "verify")
        adopted = json.loads(softory(self.root, "adopt", "VR-2", "--unit", "task", "--parent", "STORY-1",
                                     "--lane", "backend", "--tags", "data", "--assignee", "gold", "--actor", "quinn").stdout)
        self.assertEqual(adopted["tags"], "unit:task,parent:STORY-1,lane:backend,data,verify")
        self.assertEqual(adopted["assignees"], ["gold"])
        self.assertIn("    VR-2", softory(self.root, "tree").stdout)
        self.build("VR-2", "gold")
        self.review("VR-2", "jade", "accepted", 1)
        self.assertEqual(failing(gate(self.root, "VR-2", "gold")), {"review:tag:data"})
        again = softory(self.root, "adopt", "VR-2", "--unit", "task", "--parent", "STORY-1", "--lane", "backend",
                        "--actor", "quinn", check=False)
        self.assertIn("already a unit", again.stderr)

    def test_worktree_add_links_softory_in_hidden(self) -> None:
        (self.root / "web/node_modules").mkdir(parents=True)
        added = json.loads(softory(self.root, "worktree", "add", "../wt-jade", "-b", "jade/list",
                                   "--share", "web/node_modules").stdout)
        tree = Path(added["worktree"])
        self.addCleanup(run, ["git", "worktree", "remove", "--force", str(tree)], self.root, None, False)
        self.assertEqual(added["git_status_changes"], [])
        self.assertTrue((tree / "CLAUDE.local.md").is_symlink())
        self.assertTrue((tree / "web/node_modules").is_symlink())
        self.assertTrue((tree / ".claude/skills/softory-code-quality/SKILL.md").is_file())
        here = tree / ".agents/softory/bin/softory"
        queue = json.loads(run([str(here), "queue", "--agent", "jade"], tree).stdout)
        self.assertEqual([item["id"] for item in queue["assigned"]], ["TASK-1"])
        shown = json.loads(run([str(here), "coord", "task", "show", "TASK-1"], tree).stdout)
        self.assertEqual(shown["data"]["id"], "TASK-1")
        self.assertEqual(git_status(tree), "")
        self.assertEqual(git_status(self.root), "")

    def test_link_upgrades_old_exclude_patterns(self) -> None:
        manifest_path = self.root / ".agents/softory/manifest.json"
        manifest = json.loads(manifest_path.read_text())
        old = [p if "*" in p else p + "/" for p in manifest["exclude_patterns"]]  # as 0.1.0 wrote them
        manifest["exclude_patterns"] = old
        manifest_path.write_text(json.dumps(manifest))
        exclude = self.root / ".git/info/exclude"
        exclude.write_text("# softory:start (managed by softory; do not edit inside this block)\n" + "\n".join(old) + "\n# softory:end\n")
        tree = self.root / ".claude/worktrees/plain"
        run(["git", "worktree", "add", "--detach", str(tree)], self.root)
        self.addCleanup(run, ["git", "worktree", "remove", "--force", str(tree)], self.root, None, False)
        linked = json.loads(softory(self.root, "link", str(tree)).stdout)
        self.assertIn(".agents/softory", linked["linked"])
        self.assertEqual(git_status(tree), "")
        self.assertTrue(json.loads(softory(self.root, "doctor").stdout)["pass"])

    def test_triage_finds_accepted_work_left_open(self) -> None:
        coord(self.root, "task", "create", "--id", "VR-3", "--title", "Done, not closed", "--actor", "owner", "--assignee", "quinn")
        coord(self.root, "review", "add", "--id", "REV-VR-3", "--task", "VR-3", "--reviewer", "darwin",
              "--artifact", "commit:1", "--scope", "test", "--decision", "accepted")
        self.build("TASK-1", "jade")
        self.review("TASK-1", "gold", "accepted", 1)
        report = json.loads(softory(self.root, "triage").stdout)
        self.assertEqual([row["id"] for row in report["ready_to_close"]], ["TASK-1"])
        self.assertEqual([row["id"] for row in report["accepted_but_open"]], ["VR-3"])
        adopted = json.loads(softory(self.root, "adopt", "VR-3", "--unit", "task", "--parent", "STORY-1",
                                     "--lane", "backend", "--actor", "quinn").stdout)
        self.assertIn("already accepted", adopted["warning"])

    def test_feedback_is_recorded_locally_and_hidden(self) -> None:
        recorded = json.loads(softory(self.root, "feedback", "The gate output is long", "--task", "TASK-1",
                                      env={"SOFTORY_ROLE": "jade"}).stdout)
        self.assertEqual(recorded["count"], 1)
        notes = json.loads(softory(self.root, "feedback", "--list").stdout)["notes"]
        self.assertEqual((notes[0]["role"], notes[0]["task"], notes[0]["kind"]), ("jade", "TASK-1", "friction"))
        empty = softory(self.root, "feedback", "  ", check=False)
        self.assertIn("invalid_arguments", empty.stderr)
        self.assertEqual(git_status(self.root), "")

    def test_start_records_harness_and_end_closes(self) -> None:
        session = start(self.root, "toby")["COORDINATION_SESSION"]
        row = coord(self.root, "session", "show", session)["data"]
        self.assertEqual((row["agent_id"], row["harness"]), ("toby", "codex"))
        softory(self.root, "end", "--session", session)
        self.assertNotEqual(coord(self.root, "session", "show", session)["data"]["status"], "active")

    def test_queue_lists_what_you_may_close(self) -> None:
        self.build("TASK-1", "jade")
        self.review("TASK-1", "gold", "accepted", 1)
        jade = json.loads(softory(self.root, "queue", "--agent", "jade").stdout)
        self.assertEqual([item["id"] for item in jade["ready_to_close"]], ["TASK-1"])
        gold = json.loads(softory(self.root, "queue", "--agent", "gold").stdout)
        self.assertEqual(gold["ready_to_close"], [])

    def test_quinn_reviews_security_work_toby_built(self) -> None:
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "backend", "--title", "Secret store",
                "--tags", "security", "--assignee", "toby", "--actor", "quinn")
        self.build("TASK-2", "toby")
        self.review("TASK-2", "gold", "accepted", 1)
        queue = json.loads(softory(self.root, "queue", "--agent", "quinn").stdout)
        self.assertEqual([(i["id"], i["why"]) for i in queue["reviews_waiting"]],
                         [("TASK-2", "security review (toby built it, so quinn reviews)")])
        self.review("TASK-2", "toby", "accepted", 1)
        self.assertIn("review:tag:security", failing(gate(self.root, "TASK-2", "toby")))
        self.review("TASK-2", "quinn", "accepted", 1)
        self.assertTrue(gate(self.root, "TASK-2", "toby")["pass"])

    def test_review_runs_close_on_their_verdicts(self) -> None:
        self.build("TASK-1", "jade")
        made = json.loads(softory(self.root, "new", "review", "--title", "Review TASK-1", "--for", "TASK-1",
                                  "--actor", "gold").stdout)
        self.assertEqual((made["id"], made["assignee"], made["tags"]), ("REVIEW-1", "gold", "unit:review,for:TASK-1"))
        self.build("REVIEW-1", "gold")
        self.assertEqual(failing(gate(self.root, "REVIEW-1", "gold")), {"verdicts_recorded"})
        self.review("TASK-1", "gold", "changes_requested", 1)
        self.assertTrue(gate(self.root, "REVIEW-1", "gold")["pass"])  # the fix is TASK-1's business, not the run's
        self.assertIn("1 review run(s) not shown", softory(self.root, "tree").stdout)
        # A review run from before softory, tagged for a specialist
        coord(self.root, "task", "create", "--id", "VR-REVIEW-9", "--title", "Independent review of TASK-1",
              "--actor", "owner", "--assignee", "gold", "--tags", "review,security")
        runs = json.loads(softory(self.root, "triage").stdout)["review_runs"]
        self.assertEqual([run_["id"] for run_ in runs], ["VR-REVIEW-9"])
        softory(self.root, "adopt", "VR-REVIEW-9", "--unit", "review", "--for", "TASK-1", "--actor", "gold")
        self.build("VR-REVIEW-9", "gold")
        report = gate(self.root, "VR-REVIEW-9", "gold")
        self.assertTrue(report["pass"], report)
        self.assertNotIn("review:tag:security", {check["check"] for check in report["checks"]})

    def test_follow_up_joins_the_story_and_holds_its_source(self) -> None:
        self.build("TASK-1", "jade")
        made = json.loads(softory(self.root, "new", "bug", "--from", "TASK-1", "--title", "Focus ring missing",
                                  "--actor", "gold").stdout)
        self.assertEqual((made["id"], made["parent"], made["assignee"], made["blocks"]), ("BUG-1", "STORY-1", "jade", "TASK-1"))
        self.assertEqual(made["tags"], "unit:bug,parent:STORY-1,lane:frontend,from:TASK-1")
        self.review("TASK-1", "gold", "accepted", 1)
        self.assertEqual(failing(gate(self.root, "TASK-1", "jade")), {"blocks_resolved"})
        self.assertIn("    BUG-1", softory(self.root, "tree").stdout)

    def test_story_without_an_epic_is_flagged(self) -> None:
        made = json.loads(softory(self.root, "new", "story", "--title", "Loose", "--actor", "greg").stdout)
        self.assertIn("not under an epic", made["warning"])
        tree = softory(self.root, "tree").stdout.splitlines()
        self.assertEqual(tree[-2:], ["Not under an epic:", "  STORY-2 [todo] Loose (greg)"])

    def test_pending_tells_a_scheduler_whether_to_run(self) -> None:
        fresh = softory(self.root, "pending", "jade", check=False)
        self.assertEqual(fresh.returncode, 0)  # never ran, and TASK-1 is assigned
        self.assertEqual(json.loads(fresh.stdout)["reasons"], [{"why": "assigned work changed", "ids": ["TASK-1"]}])
        session = start(self.root, "jade")["COORDINATION_SESSION"]
        busy = softory(self.root, "pending", "jade", check=False)
        self.assertEqual((busy.returncode, json.loads(busy.stdout)["running"]), (3, [session]))
        softory(self.root, "end", "--session", session)
        idle = softory(self.root, "pending", "jade", check=False)
        self.assertEqual((idle.returncode, json.loads(idle.stdout)["reasons"]), (3, []))
        coord(self.root, "message", "send", "--id", "MSG-1", "--sender", "quinn", "--recipient", "jade",
              "--body", "TASK-1 needs a loading state")
        mail = softory(self.root, "pending", "jade", check=False)
        self.assertEqual((mail.returncode, json.loads(mail.stdout)["reasons"]), (0, [{"why": "unread messages", "count": 1}]))

    def test_triage_flags_stale_sessions(self) -> None:
        session = start(self.root, "darwin")["COORDINATION_SESSION"]
        install(self.root)  # an upgrade: darwin's session now runs older rules
        sessions = json.loads(softory(self.root, "triage").stdout)["sessions"]
        self.assertEqual([row["id"] for row in sessions["started_before_install"]], [session])
        self.assertEqual(sessions["silent"], [])


if __name__ == "__main__":
    unittest.main()
