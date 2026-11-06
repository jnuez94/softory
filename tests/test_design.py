"""0.5.3: UI build work waits for its design, and softory verify runs the design detector on ui units."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO, coord, git_project, install, needs_sources, run, softory

sys.path.insert(0, str(REPO / "lib"))
from softory import design, external  # noqa: E402
from softory.units import children_by_parent  # noqa: E402
from tests.test_unattended import at_terminal  # noqa: E402
from tests.test_workflow import failing, gate, start  # noqa: E402

GATES = json.loads((REPO / "factory/governance/gates.json").read_text())
CHARTER = json.loads((REPO / "factory/governance/charter.json").read_text())
# A stand-in for Impeccable's launcher: a gradient is a warning, a nested card is advisory.
FAKE = """#!/bin/sh
shift 2
out="["; sep=""
for f in "$@"; do
  if grep -q gradient "$f"; then out="$out$sep{\\"antipattern\\":\\"gradient-text\\",\\"file\\":\\"$f\\",\\"line\\":1,\\"severity\\":\\"warning\\"}"; sep=","; fi
  if grep -q card "$f"; then out="$out$sep{\\"antipattern\\":\\"nested-cards\\",\\"file\\":\\"$f\\",\\"line\\":1,\\"severity\\":\\"advisory\\",\\"advisory\\":true}"; sep=","; fi
done
echo "$out]"
case "$out" in *warning*) exit 2;; esac
"""


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


def unit(task_id: str, status: str, tags: str) -> dict:
    return {"id": task_id, "status": status, "tags": tags}


class DesignUnitTest(unittest.TestCase):
    def test_ui_build_work_waits_for_its_storys_design(self) -> None:
        board = Board([
            unit("STORY-1", "todo", "unit:story"),
            unit("TASK-1", "in_progress", "unit:task,parent:STORY-1,lane:design"),
            unit("TASK-2", "todo", "unit:task,parent:STORY-1,lane:frontend"),
            unit("TASK-3", "todo", "unit:task,parent:STORY-1,lane:backend"),
            unit("TASK-4", "todo", "unit:task,parent:STORY-1,lane:backend,ui"),
        ])
        self.assertEqual(design.held(board, CHARTER), {"TASK-2": "TASK-1", "TASK-4": "TASK-1"})
        board.tasks[1]["status"] = "done"
        self.assertEqual(design.held(Board(board.tasks), CHARTER), {})
        self.assertEqual(design.held(board, {"design": {"wait_for_design": False}}), {})

    def test_the_detector_fails_on_warnings_and_counts_advisories(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            tree = Path(folder)
            launcher = fake_launcher(tree)
            (tree / "a.css").write_text("h1 { background: linear-gradient(red, blue) }\n")
            (tree / "b.html").write_text("<div class=card></div>\n")
            dirty = design.scan(launcher, tree, ["a.css", "b.html", "gone.css"])
            self.assertFalse(dirty["passed"])
            self.assertEqual(dirty["blocking"], ["a.css:1 gradient-text (warning)"])
            self.assertEqual(dirty["advisory"], 1)
            self.assertEqual(dirty["scanned"], 2)
            clean = design.scan(launcher, tree, ["b.html"])
            self.assertTrue(clean["passed"])
            self.assertIn("1 advisory", clean["detail"])
            self.assertTrue(design.scan(launcher, tree, [])["passed"])

    def test_a_detector_that_cannot_scan_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            tree = Path(folder)
            launcher = tree / "broken"
            launcher.write_text("#!/bin/sh\necho nope >&2\nexit 1\n")
            launcher.chmod(0o755)
            (tree / "a.css").write_text("x\n")
            result = design.scan(launcher, tree, ["a.css"])
            self.assertFalse(result["passed"])
            self.assertIn("exited 1", result["detail"])

    def test_only_ui_files_are_scanned(self) -> None:
        self.assertEqual(design.ui_files(["web/a.tsx", "api/b.py", "docs/c.md", "web/d.css"]), ["web/a.tsx", "web/d.css"])

    def test_a_skill_can_ship_a_build_per_harness(self) -> None:
        catalog = json.loads((REPO / "external-skills.json").read_text())
        impeccable = next(s for s in catalog["skills"] if s["name"] == "impeccable")
        self.assertEqual(external.source_path(impeccable, ".agents/skills"), ".agents/skills/impeccable")
        self.assertEqual(external.source_path(impeccable, ".claude/skills"), ".claude/skills/impeccable")
        plain = next(s for s in catalog["skills"] if s["name"] == "break-ui")
        self.assertEqual(external.source_path(plain, ".agents/skills"), "skills/break-ui")
        self.assertRegex(catalog["sources"]["pbakaus/impeccable"]["commit"], r"^[0-9a-f]{40}$")


@needs_sources
class DesignWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.holder, self.root = git_project({"README.md": "# app\n", "web/app.css": "body {}\n"})
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        base = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps({"verify": {"command": "true"}, "lanes": {"frontend": ["web/**"]},
                                    "git": {"base": base}}))
        at_terminal(self.root, "charter", "approve", str(path))
        made = json.loads(softory(self.root, "new", "story", "--title", "Today", "--design", "--actor", "greg").stdout)
        self.design_task = made["design_task"]
        made = json.loads(softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--tags", "ui",
                                  "--title", "Today list", "--actor", "quinn").stdout)
        self.task = made["id"]
        softory(self.root, "feasible", "STORY-1", "--pass", "--actor", "quinn")

    def commit(self, name: str, text: str) -> str:
        (self.root / name).write_text(text)
        run(["git", "add", name], self.root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", name], self.root)
        return run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()

    def test_queue_says_the_build_task_waits_for_the_design(self) -> None:
        queue = json.loads(softory(self.root, "queue", "--agent", "jade").stdout)
        row = next(r for r in queue["assigned"] if r["id"] == self.task)
        self.assertEqual(row["waits_for"], f"its story's design, {self.design_task}")

    def test_verify_runs_the_detector_on_a_ui_units_own_files(self) -> None:
        fake_launcher(self.root)
        sha = self.commit("web/app.css", "h1 { background: linear-gradient(red, blue) }\n")
        session = start(self.root, "jade")["COORDINATION_SESSION"]
        env = {**os.environ, "COORDINATION_SESSION": session}
        coord(self.root, "evidence", "add", "--task", self.task, "--uri", f"commit:{sha}", "--type", "commit",
              "--actor", "jade")
        failed = softory(self.root, "verify", self.task, "--actor", "jade", check=False, env=env)
        self.assertNotEqual(failed.returncode, 0)
        result = json.loads(failed.stdout)
        self.assertEqual(result["stage"], "design")
        self.assertIn("gradient-text", result["design"]["detail"])
        self.assertIn("verified", failing(gate(self.root, self.task, "jade")))
        detail = next(c for c in gate(self.root, self.task, "jade")["checks"] if c["check"] == "verified")["detail"]
        self.assertIn("design detector", detail)
        sha = self.commit("web/app.css", "h1 { color: var(--text-normal) }\n")
        coord(self.root, "evidence", "add", "--task", self.task, "--uri", f"commit:{sha}", "--type", "commit",
              "--actor", "jade")
        passed = json.loads(softory(self.root, "verify", self.task, "--actor", "jade", env=env).stdout)
        self.assertTrue(passed["passed"])
        self.assertIn("clean", passed["design"]["detail"])
