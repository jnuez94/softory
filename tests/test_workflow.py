"""An epic > story > task runs end to end through softory new, gate, and the CLI."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.helpers import coord, git_project, git_status, install, needs_sources, revision, softory


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

    def test_start_records_harness(self) -> None:
        session = start(self.root, "toby")["COORDINATION_SESSION"]
        row = coord(self.root, "session", "show", session)["data"]
        self.assertEqual((row["agent_id"], row["harness"]), ("toby", "codex"))


if __name__ == "__main__":
    unittest.main()
