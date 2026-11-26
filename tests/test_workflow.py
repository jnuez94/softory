"""An epic > story > task runs end to end through softory new, gate, and the CLI."""

from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
import time
import unittest
from pathlib import Path

import sys

from tests.helpers import REPO, coord, in_terminal, git_project, git_status, install, needs_sources, revision, run, softory

sys.path.insert(0, str(REPO / "lib"))


def start(root: Path, role: str) -> dict[str, str]:
    exports = softory(root, "start", role).stdout
    env = dict(line.removeprefix("export ").split("=", 1) for line in exports.splitlines())
    return env


def gate(root: Path, unit: str, actor: str) -> dict:
    result = softory(root, "gate", unit, "--actor", actor, check=False)
    return json.loads(result.stdout)


def failing(report: dict) -> set[str]:
    return {check["check"] for check in report["checks"] if not check["pass"]}


def at_terminal(root: Path, *args: str, answer: str = "yes") -> dict:
    """Run softory as the owner would, in a terminal, typing ``answer`` at the prompt."""
    command = shlex.join([str(root / ".agents/softory/bin/softory"), *args])
    env = {k: v for k, v in os.environ.items() if k not in ("COORDINATION_SESSION", "SOFTORY_ROLE")}
    result = subprocess.run(in_terminal(command), input=answer + "\n", cwd=root, env=env,
                            capture_output=True, text=True, check=False)
    output = result.stdout.replace("\r", "")
    return json.loads(output[output.index("{\n"):])  # after the echoed answer and the prompt


@needs_sources
class WorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.holder, self.root = git_project()
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        # These tests record placeholder evidence ("commit:1") that no git commit backs; process paths need one.
        charter = self.root / ".git" / "charter.json"
        charter.write_text(json.dumps({"simplify": {"process_paths": []}}))
        at_terminal(self.root, "charter", "approve", str(charter), "--merge")
        softory(self.root, "new", "epic", "--title", "Radar", "--actor", "greg")
        softory(self.root, "new", "story", "--parent", "EPIC-1", "--title", "See today", "--tags", "ui", "--actor", "greg")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--title", "List", "--actor", "quinn")

    def build(self, task: str, builder: str, kind: str = "commit") -> dict[str, str]:
        session = start(self.root, builder)["COORDINATION_SESSION"]
        coord(self.root, "--session", session, "task", "claim", task, "--agent", builder, "--if-revision", revision(self.root, task))
        coord(self.root, "evidence", "add", "--task", task, "--uri", f"{kind}:1", "--type", kind, "--actor", builder)
        coord(self.root, "--session", session, "task", "release", task, "--to", "review", "--actor", builder,
              "--if-revision", revision(self.root, task))
        return {"session": session}

    def review(self, task: str, reviewer: str, decision: str, number: int, follow_ups: str = "") -> None:
        coord(self.root, "review", "add", "--id", f"REV-{task}-{reviewer}-{number}", "--task", task, "--reviewer", reviewer,
              "--artifact", "commit:1", "--scope", "test", "--decision", decision, "--follow-up-tasks", follow_ups)

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
        refused = softory(self.root, "standin", "add", "avery", "--for", "jade,gold", check=False)
        self.assertIn("owner_terminal_required", refused.stderr)  # an agent's shell has no terminal
        added = at_terminal(self.root, "standin", "add", "avery", "--for", "jade,gold")
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
        at_terminal(self.root, "standin", "remove", "avery")
        self.assertNotIn("stands in for", (self.root / "AGENTS.md").read_text())
        self.assertFalse(gate(self.root, "TASK-1", "jade")["pass"])
        self.assertEqual(git_status(self.root), "")

    def test_a_task_without_a_unit_does_not_close(self) -> None:
        coord(self.root, "task", "create", "--id", "VR-1", "--title", "Old", "--actor", "owner", "--assignee", "quinn")
        tree = softory(self.root, "tree").stdout
        self.assertNotIn("VR-1", tree)
        self.assertIn("1 task(s) without a unit", tree)
        self.build("VR-1", "quinn")
        self.review("VR-1", "darwin", "accepted", 1)
        self.assertIn("unit", failing(gate(self.root, "VR-1", "quinn")))
        refused = softory(self.root, "close", "VR-1", "--actor", "quinn", check=False)
        self.assertEqual((refused.returncode, json.loads(refused.stdout)["closed"]), (3, False))
        self.assertEqual(coord(self.root, "task", "show", "VR-1")["data"]["status"], "review")

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
        manifest_path.chmod(0o644)  # the installer makes it read-only; root ignores that, a normal user doesn't
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

    def test_triage_flags_work_closed_outside_softory(self) -> None:
        self.build("TASK-1", "jade")
        self.review("TASK-1", "gold", "accepted", 1)
        softory(self.root, "close", "TASK-1", "--actor", "jade")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "backend", "--title", "Quick fix", "--actor", "quinn")
        self.build("TASK-2", "gold")
        coord(self.root, "decision", "add", "--id", "DEC-ME", "--title", "Ship it", "--owner", "gold", "--status",
              "accepted", "--context", "x", "--decision", "done")
        coord(self.root, "task", "status", "TASK-2", "done", "--actor", "gold", "--if-revision", revision(self.root, "TASK-2"),
              "--note", "done, trust me", "--because", "decision:DEC-ME")  # strict closure takes any decision; softory's gate never ran
        flagged = json.loads(softory(self.root, "triage").stdout)["closed_outside_softory"]
        self.assertEqual([(t["id"], t["notes"]) for t in flagged], [("TASK-2", "done, trust me")])

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
        own = softory(self.root, "new", "review", "--title", "Self", "--for", "TASK-1", "--actor", "jade", check=False)
        self.assertIn("not_independent", own.stderr)
        self.build("REVIEW-1", "gold", kind="report")
        self.assertEqual(failing(gate(self.root, "REVIEW-1", "gold")), {"verdicts_recorded"})
        self.review("TASK-1", "gold", "changes_requested", 1)
        self.assertTrue(gate(self.root, "REVIEW-1", "gold")["pass"])  # the fix is TASK-1's business, not the run's
        self.assertIn("1 review run(s) not shown", softory(self.root, "tree").stdout)

    def test_a_review_record_closes_on_its_own_verdicts(self) -> None:
        # The run is a unit linked to what it reviewed, the verdict sits on the run, and the fixes are follow-ups.
        self.build("TASK-1", "jade")
        softory(self.root, "new", "review", "--title", "Independent review of TASK-1", "--for", "TASK-1", "--actor", "gold")
        session = self.build("REVIEW-1", "gold", kind="report")["session"]
        coord(self.root, "--session", session, "task", "claim", "REVIEW-1", "--agent", "gold",
              "--if-revision", revision(self.root, "REVIEW-1"))
        coord(self.root, "--session", session, "task", "release", "REVIEW-1", "--to", "blocked", "--actor", "gold",
              "--if-revision", revision(self.root, "REVIEW-1"))
        self.review("REVIEW-1", "gold", "changes_requested", 1, follow_ups="BUG-1")
        self.assertEqual(failing(gate(self.root, "REVIEW-1", "gold")), {"findings_tracked"})
        softory(self.root, "new", "bug", "--type", "functional", "--from", "TASK-1", "--title", "Fix it", "--actor", "gold")
        report = gate(self.root, "REVIEW-1", "gold")
        self.assertTrue(report["pass"], report)  # no second review of the review
        queue = json.loads(softory(self.root, "queue", "--agent", "gold").stdout)
        self.assertIn("REVIEW-1", [item["id"] for item in queue["ready_to_close"]])
        closed = softory(self.root, "close", "REVIEW-1", "--actor", "gold", env={"COORDINATION_SESSION": session})
        self.assertTrue(json.loads(closed.stdout)["closed"])  # straight from blocked
        self.assertEqual(coord(self.root, "task", "show", "REVIEW-1")["data"]["status"], "done")

    def test_a_security_review_record_by_someone_else_still_needs_toby(self) -> None:
        # Without this, a builder could label their own security fix a review and close it on their own verdict.
        self.build("TASK-1", "jade")
        softory(self.root, "new", "review", "--title", "Security pass", "--for", "TASK-1", "--tags", "security",
                "--actor", "quinn")
        coord(self.root, "evidence", "add", "--task", "REVIEW-1", "--uri", "artifact:notes", "--type", "artifact",
              "--actor", "quinn")
        self.review("REVIEW-1", "quinn", "accepted", 1)
        self.assertEqual(failing(gate(self.root, "REVIEW-1", "quinn")), {"review:tag:security"})
        waiting = json.loads(softory(self.root, "queue", "--agent", "toby").stdout)["reviews_waiting"]
        self.assertEqual([item["id"] for item in waiting], ["REVIEW-1"])
        self.review("REVIEW-1", "toby", "accepted", 1)
        self.assertTrue(gate(self.root, "REVIEW-1", "quinn")["pass"])

    def test_follow_up_joins_the_story_without_holding_its_source(self) -> None:
        self.build("TASK-1", "jade")
        made = json.loads(softory(self.root, "new", "bug", "--type", "functional", "--from", "TASK-1", "--title", "Focus ring missing",
                                  "--actor", "gold").stdout)
        self.assertEqual((made["id"], made["parent"], made["assignee"], made["follows_up"]), ("BUG-1", "STORY-1", "jade", "TASK-1"))
        self.assertNotIn("blocks", made)
        self.assertEqual(made["tags"], "unit:bug,parent:STORY-1,lane:frontend,from:TASK-1,finding:functional,found:review")
        self.review("TASK-1", "gold", "accepted", 1)
        self.assertTrue(gate(self.root, "TASK-1", "jade")["pass"])
        self.assertIn("    BUG-1", softory(self.root, "tree").stdout)
        held = json.loads(softory(self.root, "new", "bug", "--type", "functional", "--from", "TASK-1", "--blocks-source", "--title", "Must fix first",
                                  "--actor", "gold").stdout)
        self.assertEqual(held["blocks"], "TASK-1")
        self.assertEqual(failing(gate(self.root, "TASK-1", "jade")), {"blocks_resolved"})

    def test_drop_closes_work_nobody_will_build(self) -> None:
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "backend", "--title", "Old plan", "--actor", "quinn")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "backend", "--title", "New plan", "--actor", "quinn")
        refused = softory(self.root, "drop", "TASK-2", "--reason", "x", "--actor", "gold", check=False)
        self.assertIn("not_allowed", refused.stderr)
        no_session = softory(self.root, "drop", "TASK-2", "--reason", "x", "--actor", "quinn", check=False)
        self.assertIn("session_required", no_session.stderr)
        session = start(self.root, "quinn")["COORDINATION_SESSION"]
        dropped = json.loads(softory(self.root, "drop", "TASK-2", "--reason", "TASK-3 replaces it", "--superseded-by", "TASK-3",
                                     "--actor", "quinn", env={"COORDINATION_SESSION": session}).stdout)
        self.assertEqual((dropped["resolution"], dropped["note"]), ("superseded", "STORY-1 no longer waits for TASK-2."))
        task = coord(self.root, "task", "show", "TASK-2")["data"]
        self.assertEqual((task["status"], task["assignees"]), ("done", ["gold"]))  # quinn's claim doesn't stick
        self.assertIn("resolution:superseded", task["tags"])
        self.assertEqual(coord(self.root, "decision", "show", dropped["decision"])["data"]["status"], "accepted")
        self.assertIn("TASK-2 [done: superseded by TASK-3]", softory(self.root, "tree").stdout)
        story = softory(self.root, "drop", "STORY-1", "--reason", "x", "--actor", "greg", check=False)
        self.assertIn("children_open", story.stderr)

    def test_a_bug_says_what_kind_of_finding_it_is(self) -> None:
        untyped = softory(self.root, "new", "bug", "--from", "TASK-1", "--title", "x", "--actor", "gold", check=False)
        self.assertIn("--type", untyped.stderr)
        made = json.loads(softory(self.root, "new", "bug", "--type", "visual", "--found-at", "acceptance",
                                  "--parent", "STORY-1", "--lane", "frontend", "--title", "Preview blank",
                                  "--actor", "greg").stdout)
        self.assertIn("finding:visual", made["tags"])
        self.assertIn("found:acceptance", made["tags"])
        session = start(self.root, "quinn")["COORDINATION_SESSION"]
        refused = softory(self.root, "drop", "TASK-1", "--reason", "x", "--withdrawn", "--actor", "quinn",
                          env={"COORDINATION_SESSION": session}, check=False)
        self.assertIn("Only a bug", refused.stderr)
        softory(self.root, "drop", made["id"], "--reason", "renders fine on a clean vault", "--withdrawn",
                "--actor", "quinn", env={"COORDINATION_SESSION": session})
        tags = coord(self.root, "task", "show", made["id"])["data"]["tags"]
        self.assertIn("finding:withdrawn", tags)
        self.assertNotIn("finding:visual", tags)

    def test_a_story_can_open_its_design_task_before_the_breakdown(self) -> None:
        made = json.loads(softory(self.root, "new", "story", "--parent", "EPIC-1", "--title", "Settings", "--design",
                                  "--actor", "greg").stdout)
        design = coord(self.root, "task", "show", made["design_task"])["data"]
        self.assertEqual(design["assignees"], ["darwin"])
        self.assertIn(f"parent:{made['id']}", design["tags"])
        self.assertIn("lane:design", design["tags"])
        self.assertIn("docs/product/PRODUCT.md and docs/design/DESIGN.md", made["reminder"])
        self.assertIn(".agents/softory/factory/templates/", made["reminder"])
        self.assertTrue((self.root / ".agents/softory/factory/templates/DESIGN.md").is_file())

    def test_the_design_reminder_goes_once_the_project_files_exist(self) -> None:
        for path in ("docs/product/PRODUCT.md", "docs/design/DESIGN.md"):
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text("# written\n", encoding="utf-8")
        made = json.loads(softory(self.root, "new", "story", "--parent", "EPIC-1", "--title", "Inbox", "--design",
                                  "--actor", "greg").stdout)
        self.assertNotIn("reminder", made)

    def test_a_stack_closes_together_or_not_at_all(self) -> None:
        self.build("TASK-1", "jade")  # strict dependencies: TASK-1 is built before it waits on BUG-1
        softory(self.root, "new", "bug", "--type", "functional", "--from", "TASK-1", "--blocks-source", "--title", "On top", "--actor", "quinn")
        softory(self.root, "stack", "TASK-1", "BUG-1", "--actor", "jade")
        session = self.build("BUG-1", "jade")["session"]
        self.review("TASK-1", "gold", "accepted", 1)
        self.assertEqual(failing(gate(self.root, "TASK-1", "jade")), {"blocks_resolved"})  # waits for BUG-1
        held = json.loads(softory(self.root, "close", "BUG-1", "--stack", "--actor", "jade", check=False).stdout)
        self.assertEqual((held["closed"], held["failing"]), (False, ["BUG-1", "TASK-1"]))  # TASK-1 waits on BUG-1
        self.assertEqual(coord(self.root, "task", "show", "TASK-1")["data"]["status"], "review")  # nothing closed
        self.review("BUG-1", "gold", "accepted", 1)
        closed = json.loads(softory(self.root, "close", "TASK-1", "--stack", "--actor", "jade",
                                    env={"COORDINATION_SESSION": session}).stdout)
        self.assertEqual((closed["closed"], closed["order"]), (True, ["BUG-1", "TASK-1"]))

    def test_owner_approves_what_an_agent_proposes(self) -> None:
        coord(self.root, "agent", "add", "--id", "avery", "--name", "Avery", "--role", "Reviewer", "--actor", "owner")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "backend", "--title", "Threat model",
                "--tags", "security", "--assignee", "toby", "--actor", "quinn")
        proposed = json.loads(softory(self.root, "propose", "standin", "avery", "--for", "toby", "--task", "TASK-2",
                                      "--until", "2099-01-01", "--why", "Quinn is out", "--actor", "quinn").stdout)
        self.assertEqual(proposed["proposal"], "PROP-1")
        self.assertEqual(coord(self.root, "decision", "show", proposed["decision"])["data"]["status"], "proposed")
        self.build("TASK-2", "toby")
        self.review("TASK-2", "gold", "accepted", 1)
        self.review("TASK-2", "avery", "accepted", 1)
        self.assertIn("review:tag:security", failing(gate(self.root, "TASK-2", "toby")))  # nothing granted yet
        refused = softory(self.root, "approve", "PROP-1", check=False)
        self.assertIn("owner_terminal_required", refused.stderr)
        declined = subprocess.run(in_terminal(shlex.join([str(self.root / ".agents/softory/bin/softory"), "approve", "PROP-1"])),
                                   input="no\n", cwd=self.root, capture_output=True, text=True, check=False)
        self.assertIn("not_approved", declined.stdout)
        approved = at_terminal(self.root, "approve", "PROP-1")
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(coord(self.root, "decision", "show", proposed["decision"])["data"]["status"], "accepted")
        self.assertTrue(gate(self.root, "TASK-2", "toby")["pass"])  # scoped to TASK-2, so it covers Toby's own work
        self.assertIn("on TASK-2 only, until 2099-01-01", (self.root / "AGENTS.md").read_text())
        waiver = json.loads(softory(self.root, "propose", "waiver", "TASK-2", "--check", "evidence", "--why", "x",
                                    "--actor", "quinn", check=False).stderr)
        self.assertEqual(waiver["error"]["code"], "invalid_arguments")

    def test_a_proposal_about_finished_work_closes_itself(self) -> None:
        asked = json.loads(softory(self.root, "propose", "waiver", "TASK-1", "--check", "review:peer",
                                   "--why", "Gold is away", "--actor", "jade").stdout)
        self.assertEqual([p["id"] for p in json.loads(softory(self.root, "proposals").stdout)], ["PROP-1"])
        session = self.build("TASK-1", "jade")["session"]
        self.review("TASK-1", "gold", "accepted", 1)
        softory(self.root, "close", "TASK-1", "--actor", "jade", env={"COORDINATION_SESSION": session})
        self.assertEqual(json.loads(softory(self.root, "proposals").stdout), [])  # nothing left for the owner
        kept = json.loads(softory(self.root, "proposals", "--all").stdout)
        self.assertEqual([(p["id"], p["status"]) for p in kept], [("PROP-1", "lapsed")])
        self.assertEqual(coord(self.root, "decision", "show", asked["decision"])["data"]["status"], "superseded")
        self.assertIn("No open proposal", json.dumps(at_terminal(self.root, "approve", "PROP-1")))

    def test_proposal_cleanup_finishes_what_an_earlier_run_left_half_done(self) -> None:
        from softory import owner  # noqa: PLC0415
        from softory.coordination import Coordination  # noqa: PLC0415
        from softory.project import Project  # noqa: PLC0415

        project = Project(self.root)
        board = Coordination(project.coordination_bin, self.root)
        ask = lambda who: json.loads(softory(self.root, "propose", "waiver", "TASK-1", "--check", "review:peer",  # noqa: E731
                                             "--why", "Gold is away", "--actor", who).stdout)
        first, second = ask("jade"), ask("quinn")
        session = self.build("TASK-1", "jade")["session"]
        self.review("TASK-1", "gold", "accepted", 1)
        softory(self.root, "close", "TASK-1", "--actor", "jade", env={"COORDINATION_SESSION": session})
        # A run told the tracker about PROP-1 and died before it marked the proposal.
        coord(self.root, "decision", "status", first["decision"], "superseded", "--actor", "owner")
        self.assertEqual(owner.lapse_finished(project, board), ["PROP-1", "PROP-2"])  # finished, not refused
        self.assertEqual([(p["id"], p["status"]) for p in owner.proposals(project, True)],
                         [("PROP-1", "lapsed"), ("PROP-2", "lapsed")])
        self.assertEqual(coord(self.root, "decision", "show", second["decision"])["data"]["status"], "superseded")
        self.assertEqual(owner.lapse_finished(project, board), [])  # and again changes nothing
        softory(self.root, "digest")  # the digest, which runs before any role starts, builds

    def test_approval_decides_the_proposal_as_it_stands_after_the_owner_answers(self) -> None:
        from softory import owner  # noqa: PLC0415
        from softory.coordination import Coordination  # noqa: PLC0415
        from softory.project import Project  # noqa: PLC0415

        project = Project(self.root)
        board = Coordination(project.coordination_bin, self.root)
        local = lambda: json.loads(project.local_path.read_text()) if project.local_path.is_file() else {}  # noqa: E731
        asked = json.loads(softory(self.root, "propose", "waiver", "TASK-1", "--check", "review:peer",
                                   "--why", "Gold is away", "--actor", "jade").stdout)
        session = self.build("TASK-1", "jade")["session"]
        self.review("TASK-1", "gold", "accepted", 1)

        def the_unit_closes_while_the_prompt_is_open(_text: str) -> None:
            softory(self.root, "close", "TASK-1", "--actor", "jade", env={"COORDINATION_SESSION": session})

        result = owner.approve(project, board, ["PROP-1"], confirm=the_unit_closes_while_the_prompt_is_open)
        self.assertEqual(result["status"], "lapsed")
        self.assertIn("nothing to grant", result["note"])
        self.assertFalse(local().get("waivers"))  # nothing was written for finished work
        self.assertEqual(coord(self.root, "decision", "show", asked["decision"])["data"]["status"], "superseded")

        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "backend", "--title", "Second",
                "--actor", "quinn")
        again = json.loads(softory(self.root, "propose", "waiver", "TASK-2", "--check", "review:peer",
                                   "--why", "Jade is away", "--actor", "gold").stdout)

        def someone_rejects_it_first(_text: str) -> None:
            coord(self.root, "decision", "status", again["decision"], "rejected", "--actor", "owner")

        result = owner.approve(project, board, ["PROP-2"], confirm=someone_rejects_it_first)
        self.assertEqual(result["status"], "rejected")
        self.assertFalse(local().get("waivers"))  # the record was refused, so the settings are untouched

        third = json.loads(softory(self.root, "propose", "waiver", "TASK-2", "--check", "review:peer",
                                   "--why", "Jade is away", "--actor", "gold").stdout)
        from unittest import mock  # noqa: PLC0415
        with mock.patch.object(owner, "_apply_waiver", side_effect=owner.SoftoryError("disk full", "io")):
            with self.assertRaises(owner.SoftoryError):
                owner.approve(project, board, ["PROP-3"], confirm=lambda _text: None)
        self.assertEqual(owner.proposals(project)[0]["id"], "PROP-3")  # still open: the grant wasn't written
        done = owner.approve(project, board, ["PROP-3"], confirm=lambda _text: None)  # the owner runs it again
        self.assertEqual(done["status"], "approved")
        owner._apply_waiver(project, board, done["waived"], third["decision"])  # and once more writes nothing new
        self.assertEqual([w["decision"] for w in local()["waivers"]], [third["decision"]])

    def test_rules_are_read_only_and_checked(self) -> None:
        gate_file = self.root / ".agents/softory/factory/governance/gates.json"
        self.assertFalse(gate_file.stat().st_mode & stat.S_IWUSR)
        self.build("TASK-1", "jade")
        self.review("TASK-1", "gold", "accepted", 1)
        self.assertTrue(gate(self.root, "TASK-1", "jade")["pass"])
        gate_file.chmod(0o644)
        gate_file.write_text(gate_file.read_text().replace('"not_self": true', '"not_self": false'))
        self.assertEqual(failing(gate(self.root, "TASK-1", "jade")), {"config_intact"})
        doctor = json.loads(softory(self.root, "doctor", check=False).stdout)
        intact = next(c for c in doctor["checks"] if c["check"] == "config_intact")
        self.assertIn("factory/governance/gates.json", intact["detail"])
        local = self.root / ".agents/softory/local.json"
        local.chmod(0o644)  # installed read-only; only root could write it as it is
        local.write_text('{"stand_ins": {"jade": ["gold"]}}')
        refused = softory(self.root, "propose", "standin", "jade", "--for", "toby", "--why", "x", "--actor", "quinn", check=False)
        self.assertEqual(refused.returncode, 0)  # proposing writes no rules
        install(self.root)  # the owner reinstalls: what's there is trusted again
        self.assertFalse(local.stat().st_mode & stat.S_IWUSR)
        self.assertNotIn("config_intact", failing(gate(self.root, "TASK-1", "jade")))

    def test_ruling_is_recorded_under_the_owners_name(self) -> None:
        session = start(self.root, "quinn")["COORDINATION_SESSION"]
        made = json.loads(softory(self.root, "ruling", "--title", "Keep the model open", "--decision", "Do not merge yet",
                                  "--where", "Josh in Quinn's thread, 2026-10-23 15:32Z", "--actor", "quinn",
                                  env={"COORDINATION_SESSION": session}).stdout)
        decision = coord(self.root, "decision", "show", made["decision"])["data"]
        self.assertEqual((decision["owner_id"], decision["status"]), ("owner", "accepted"))
        self.assertTrue(decision["title"].startswith("Owner ruling (recorded by quinn)"))
        self.assertIn(f"Recorded by quinn ({session})", decision["context"])
        written = coord(self.root, "decision", "history", made["decision"])["data"][0]
        self.assertEqual((written["actor"], written["detail"]), ("quinn", "accepted; owner=owner"))  # the audit names the recorder

    def test_inbox_marks_read_through_what_you_saw(self) -> None:
        for number in (1, 2):
            coord(self.root, "message", "send", "--id", f"MSG-{number}", "--sender", "quinn", "--recipient", "jade",
                  "--body", f"note {number}")
        listing = json.loads(softory(self.root, "inbox", "--agent", "jade").stdout)
        self.assertEqual([m["id"] for m in listing["messages"]], ["MSG-1", "MSG-2"])
        coord(self.root, "message", "send", "--id", "MSG-3", "--sender", "quinn", "--recipient", "jade", "--body", "later")
        softory(self.root, "inbox", "--agent", "jade", "--mark-read", str(listing["read_through"]))
        after = json.loads(softory(self.root, "inbox", "--agent", "jade").stdout)
        self.assertEqual([m["id"] for m in after["messages"]], ["MSG-3"])
        self.assertEqual(json.loads(softory(self.root, "message", "MSG-1").stdout)["body"], "note 1")
        rows = json.loads(softory(self.root, "all", "task", "list", "--tag", "unit:task").stdout)
        self.assertEqual([row["id"] for row in rows], ["TASK-1"])

    def test_silent_lists_roles_with_work_and_no_session(self) -> None:
        quiet = json.loads(softory(self.root, "silent", "--hours", "1", check=False).stdout)
        self.assertIn("jade", [row["agent"] for row in quiet["silent"]])  # TASK-1 waits, and jade never ran
        self.assertNotIn("darwin", [row["agent"] for row in quiet["silent"]])  # nothing waits for darwin
        start(self.root, "jade")
        self.assertNotIn("jade", [row["agent"] for row in json.loads(softory(self.root, "silent", "--hours", "1", check=False).stdout)["silent"]])

    def test_story_without_an_epic_is_flagged(self) -> None:
        made = json.loads(softory(self.root, "new", "story", "--title", "Loose", "--actor", "greg").stdout)
        self.assertIn("not under an epic", made["warning"])
        tree = softory(self.root, "tree").stdout.splitlines()
        self.assertEqual(tree[-2:], ["Not under an epic:", "  STORY-2 [todo] Loose (greg)"])

    def test_pending_tells_a_scheduler_whether_to_run(self) -> None:
        held = softory(self.root, "pending", "jade", check=False)
        self.assertEqual(held.returncode, 3)  # TASK-1 waits for STORY-1's feasibility check
        queued = json.loads(softory(self.root, "queue", "--agent", "jade").stdout)["assigned"][0]
        self.assertEqual(queued["waits_for"], "its story's feasibility check")
        softory(self.root, "feasible", "STORY-1", "--pass", "--actor", "quinn")
        fresh = softory(self.root, "pending", "jade", check=False)
        self.assertEqual(fresh.returncode, 0)  # never ran, and TASK-1 is assigned
        self.assertEqual(json.loads(fresh.stdout)["reasons"], [{"why": "assigned work changed", "ids": ["TASK-1"]}])
        session = start(self.root, "jade")["COORDINATION_SESSION"]
        busy = softory(self.root, "pending", "jade", check=False)
        self.assertEqual((busy.returncode, json.loads(busy.stdout)["running"]), (3, [session]))
        softory(self.root, "end", "--session", session)
        idle = softory(self.root, "pending", "jade", check=False)
        self.assertEqual((idle.returncode, json.loads(idle.stdout)["reasons"]), (3, []))
        coord(self.root, "message", "send", "--id", "MSG-0", "--sender", "greg", "--recipient", "jade",
              "--body", "Thanks, noted")
        news = softory(self.root, "pending", "jade", check=False)
        self.assertEqual(news.returncode, 3)  # an acknowledgement wakes nobody
        time.sleep(1.1)  # timestamps are to the second
        stale = softory(self.root, "pending", "jade", "--retry-hours", "0.0001", check=False)
        self.assertEqual(json.loads(stale.stdout)["reasons"][0]["why"], "unread messages waiting")  # read on a later run
        coord(self.root, "message", "send", "--id", "MSG-1", "--sender", "quinn", "--recipient", "jade",
              "--task", "TASK-1", "--body", "TASK-1 needs a loading state")
        mail = softory(self.root, "pending", "jade", check=False)
        self.assertEqual((mail.returncode, json.loads(mail.stdout)["reasons"]),
                         (0, [{"why": "messages that need you", "count": 1}]))

    def test_triage_flags_stale_sessions(self) -> None:
        session = start(self.root, "darwin")["COORDINATION_SESSION"]
        install(self.root)  # an upgrade: darwin's session now runs older rules
        sessions = json.loads(softory(self.root, "triage").stdout)["sessions"]
        self.assertEqual([row["id"] for row in sessions["started_before_install"]], [session])
        self.assertEqual(sessions["silent"], [])


if __name__ == "__main__":
    unittest.main()
