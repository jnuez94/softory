"""0.6.3: a commit is tested once, the detector answers for the unit's own lines, and bugs don't re-run feasibility."""

from __future__ import annotations

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO, coord, git_project, install, needs_sources, run, softory

sys.path.insert(0, str(REPO / "lib"))
from softory import design, feasibility  # noqa: E402
from softory.units import children_by_parent  # noqa: E402
from tests.test_unattended import at_terminal  # noqa: E402
from tests.test_workflow import failing, gate  # noqa: E402

GATES = json.loads((REPO / "factory/governance/gates.json").read_text())
# A stand-in for Impeccable's launcher that reports the line of every gradient.
FAKE = """#!/bin/sh
shift 2
out="["; sep=""
for f in "$@"; do
  for n in $(grep -n gradient "$f" | cut -d: -f1); do
    out="$out$sep{\\"antipattern\\":\\"gradient-text\\",\\"file\\":\\"$f\\",\\"line\\":$n,\\"severity\\":\\"warning\\"}"; sep=","
  done
done
echo "$out]"
case "$out" in *warning*) exit 2;; esac
"""
GRADIENT = "h1 { background: linear-gradient(red, blue) }\n"


def fake_launcher(root: Path) -> Path:
    launcher = root / ".claude/skills" / design.LAUNCHER
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(FAKE)
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
    return launcher


class Board:
    def __init__(self, tasks: list[dict]) -> None:
        self.tasks, self.gates = tasks, GATES
        self.children = children_by_parent(tasks)
        self.by_id = {t["id"]: t for t in tasks}

    def show(self, task_id: str) -> dict:
        return self.by_id[task_id]


def needing(story: str, plan: str, *needs: str) -> dict:
    uri = f"{feasibility.MARK}needs@{plan}:" + " | ".join(needs)
    return {"id": story, "status": "todo", "tags": "unit:story", "title": story,
            "evidence": [{"uri": uri, "evidence_type": "review", "created_at": "2026-11-13T10:00:00Z"}]}


class AskOnceTest(unittest.TestCase):
    def test_the_owner_is_asked_once_per_missing_thing(self) -> None:
        board = Board([
            needing("STORY-1", "aaa", "An unlocked Mac desktop session", "A Google test account"),
            needing("STORY-2", "bbb", "an unlocked Mac  desktop session."),
            {"id": "TASK-1", "status": "todo", "tags": "unit:task,parent:STORY-1,lane:backend"},
            {"id": "TASK-2", "status": "todo", "tags": "unit:task,parent:STORY-2,lane:backend"},
        ])
        asks = feasibility.asks(board)
        self.assertEqual([a["stories"] for a in asks], [["STORY-1", "STORY-2"], ["STORY-1"]])
        self.assertEqual(asks[0]["need"], "An unlocked Mac desktop session")
        self.assertNotEqual(asks[0]["key"], asks[1]["key"])

    def test_a_finding_on_a_line_the_unit_did_not_change_does_not_block(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            tree = Path(folder)
            launcher = fake_launcher(tree)
            (tree / "a.css").write_text(GRADIENT + "p {}\n" + GRADIENT)
            old = design.scan(launcher, tree, ["a.css"], {"a.css": {2}})
            self.assertTrue(old["passed"])
            self.assertEqual(old["unchanged"], 2)
            self.assertIn("2 on lines this unit didn't change", old["detail"])
            mixed = design.scan(launcher, tree, ["a.css"], {"a.css": {3}})
            self.assertEqual(mixed["blocking"], ["a.css:3 gradient-text (warning)"])
            self.assertEqual(mixed["unchanged"], 1)
            self.assertFalse(design.scan(launcher, tree, ["a.css"], {"a.css": None})["passed"])  # git couldn't say
            self.assertEqual(len(design.scan(launcher, tree, ["a.css"])["blocking"]), 2)


@needs_sources
class VerifyOnceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.holder, self.root = git_project({"README.md": "# app\n", "web/app.css": GRADIENT + "body {}\n"})
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        self.base = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        self.outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.outside, ignore_errors=True))
        self.count = self.outside / "runs"
        self.approve({"command": f"echo run >> {self.count}"})
        softory(self.root, "new", "story", "--title", "Today", "--actor", "greg")
        self.task = self.new("task", "--tags", "ui", "--title", "Today list")
        softory(self.root, "feasible", "STORY-1", "--pass", "--actor", "quinn")

    def approve(self, verify: dict) -> None:
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps({"verify": verify, "lanes": {"frontend": ["web/**"]}, "git": {"base": self.base}}))
        at_terminal(self.root, "charter", "approve", str(path))

    def new(self, unit: str, *args: str) -> str:
        made = softory(self.root, "new", unit, "--parent", "STORY-1", "--lane", "frontend", *args, "--actor", "quinn")
        return json.loads(made.stdout)["id"]

    def commit(self, name: str, text: str, *tasks: str) -> str:
        (self.root / name).write_text(text)
        run(["git", "add", name], self.root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", name], self.root)
        sha = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        for task in tasks or (self.task,):
            coord(self.root, "evidence", "add", "--task", task, "--uri", f"commit:{sha}", "--type", "commit",
                  "--actor", "jade")
        return sha

    def verify(self, task: str, *args: str) -> dict:
        return json.loads(softory(self.root, "verify", task, *args, "--actor", "jade", check=False).stdout)

    def runs(self) -> int:
        return len(self.count.read_text().splitlines()) if self.count.exists() else 0

    def test_a_commit_that_passed_is_not_tested_again(self) -> None:
        other = self.new("task", "--title", "Today data")
        self.commit("web/data.ts", "export const a = 1\n", self.task, other)
        first = self.verify(self.task)
        self.assertTrue(first["passed"])
        self.assertNotIn("reused", first)
        second = self.verify(other)
        self.assertTrue(second["passed"])
        self.assertIn("did not run again", second["reused"])
        self.assertEqual(self.runs(), 1)
        self.assertNotIn("verified", failing(gate(self.root, other, "jade")))
        self.assertTrue(self.verify(self.task)["passed"])  # asking twice adds no second evidence row
        rows = [e for e in coord(self.root, "task", "show", self.task)["data"]["evidence"]
                if str(e["uri"]).startswith("softory-verify:")]
        self.assertEqual(len(rows), 1)
        self.assertNotIn("reused", self.verify(other, "--fresh"))
        self.assertEqual(self.runs(), 2)
        self.approve({"command": f"echo again >> {self.count}"})  # other settings: the old pass says nothing
        self.assertNotIn("reused", self.verify(other))
        self.assertEqual(self.runs(), 3)

    def test_a_failure_is_never_reused(self) -> None:
        flag = self.outside / "fixed"
        self.approve({"command": f"echo run >> {self.count}; test -f {flag}"})
        self.commit("web/data.ts", "export const a = 1\n")
        self.assertFalse(self.verify(self.task)["passed"])
        flag.write_text("")
        self.assertTrue(self.verify(self.task)["passed"])
        self.assertEqual(self.runs(), 2)

    def test_a_reused_pass_runs_only_the_detector_the_unit_still_needs(self) -> None:
        self.commit("web/new.css", GRADIENT)
        self.assertTrue(self.verify(self.task)["passed"])
        fake_launcher(self.root)  # installed after that pass
        self.assertIn("verified", failing(gate(self.root, self.task, "jade")))
        again = self.verify(self.task)
        self.assertFalse(again["passed"])
        self.assertEqual(again["stage"], "design")
        self.assertIn("web/new.css:1", again["design"]["detail"])
        self.assertEqual(self.runs(), 1)
        self.assertIn("verified", failing(gate(self.root, self.task, "jade")))

    def test_the_detector_blocks_only_on_lines_the_unit_wrote(self) -> None:
        fake_launcher(self.root)
        self.commit("web/app.css", GRADIENT + "body {}\nh2 { color: red }\n")  # line 1 was there before the unit
        clean = self.verify(self.task)
        self.assertTrue(clean["passed"], clean)
        self.assertIn("1 on lines this unit didn't change", clean["design"]["detail"])
        self.commit("web/app.css", GRADIENT + "body {}\nh2 { color: red }\n" + GRADIENT)
        dirty = self.verify(self.task)
        self.assertFalse(dirty["passed"])
        self.assertEqual(dirty["design"]["blocking"], ["web/app.css:4 gradient-text (warning)"])

    def test_a_flaky_failure_passes_on_its_retry_and_is_logged(self) -> None:
        self.approve({"command": "echo first; false", "retry": "echo second"})
        sha = self.commit("web/data.ts", "export const a = 1\n")
        result = self.verify(self.task)
        self.assertTrue(result["passed"])
        self.assertIn("flaky test", result["flaky"])
        self.assertIn("one bug", result["flaky"])
        rows = [json.loads(line) for line in
                (self.root / ".coordination/softory/flakes.jsonl").read_text().splitlines()]
        self.assertEqual([(r["task"], r["commit"]) for r in rows], [(self.task, sha)])
        self.assertIn("first", Path(rows[0]["log"]).read_text())
        self.approve({"command": "false", "retry": "false"})  # it fails twice: a failure
        self.assertFalse(self.verify(self.task)["passed"])

    def test_a_bug_under_a_story_does_not_run_its_feasibility_check_again(self) -> None:
        queue = json.loads(softory(self.root, "queue", "--agent", "quinn").stdout)
        self.assertFalse(queue.get("feasibility_due"))
        self.new("bug", "--type", "functional", "--title", "List is empty at midnight")
        queue = json.loads(softory(self.root, "queue", "--agent", "quinn").stdout)
        self.assertFalse(queue.get("feasibility_due"))
        self.new("task", "--title", "Sync with the calendar")  # new planned work is checked
        queue = json.loads(softory(self.root, "queue", "--agent", "quinn").stdout)
        self.assertEqual([r["story"] for r in queue["feasibility_due"]], ["STORY-1"])


if __name__ == "__main__":
    unittest.main()
