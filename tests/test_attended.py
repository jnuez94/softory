"""Attended runs: the runner opens a role's interactive harness where the owner can watch it (0.5.8)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
import unittest

from tests.helpers import git_project, install, needs_sources, softory
from tests.test_unattended import at_terminal


@needs_sources
@unittest.skipUnless(shutil.which("tmux"), "tmux isn't installed")
class AttendedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.holder, self.root = git_project({"README.md": "# app\n"})
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        softory(self.root, "new", "story", "--title", "See today", "--actor", "greg")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--title", "List",
                "--actor", "quinn")
        softory(self.root, "feasible", "STORY-1", "--pass", "--actor", "quinn")
        sockets = tempfile.TemporaryDirectory(prefix="tmux-")  # a tmux server of the test's own
        self.addCleanup(sockets.cleanup)
        self.env = {"TMUX_TMPDIR": sockets.name}
        self.addCleanup(subprocess.run, ["tmux", "kill-server"], env={**self.env, "PATH": "/usr/bin:/bin"},
                        capture_output=True, check=False)

    def attended(self, script: str, minutes: float = 5) -> None:
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps({
            "run": {"mode": "attended", "roles": ["jade"], "attended": {"fake": ["sh", "-c", script]},
                    "harnesses": {"fake": ["sh", "-c", "exit 9"]}},
            "models": {"jade": {"harness": "fake", "model": "m1", "escalate": None}},
            "budget": {"minutes_per_run": minutes}}))
        self.assertTrue(at_terminal(self.root, "charter", "approve", str(path))["approved"])

    def run_role(self) -> dict:
        return json.loads(softory(self.root, "run-role", "jade", env=self.env).stdout)

    def windows(self) -> str:
        listed = subprocess.run(["tmux", "list-windows", "-a", "-F", "#{window_name}"], env={**self.env, "PATH": "/usr/bin:/bin"},
                                capture_output=True, text=True, check=False)
        return listed.stdout

    def test_a_role_runs_in_a_tmux_window_with_its_session(self) -> None:
        self.attended("echo \"$SOFTORY_ROLE $COORDINATION_SESSION {model}\" > .git/ran; echo working")
        ran = self.run_role()
        self.assertEqual((ran["exit"], ran["harness"]), (0, "fake"))
        role, session, model = (self.root / ".git/ran").read_text().split()
        self.assertEqual((role, model), ("jade", "m1"))
        self.assertTrue(session.startswith("jade-fake-"))
        self.assertNotIn("jade", self.windows())  # the window closes with the run
        self.assertIn("working", (self.root / ".coordination/softory/logs").joinpath(
            sorted(p.name for p in (self.root / ".coordination/softory/logs").glob("jade-*.out"))[-1]).read_text())
        self.assertEqual(json.loads(softory(self.root, "attach", env=self.env).stdout)["surface"], "tmux")

    def test_the_run_ends_when_the_role_ends_its_session(self) -> None:
        self.attended(".agents/softory/bin/softory end --actor jade; echo done; sleep 600")  # an idle chat stays open
        began = time.monotonic()
        ran = self.run_role()
        self.assertEqual(ran["exit"], 0)
        self.assertLess(time.monotonic() - began, 60)
        self.assertNotIn("jade", self.windows())

    def test_the_time_limit_stops_an_attended_run(self) -> None:
        self.attended("sleep 600", minutes=0.05)
        ran = self.run_role()
        self.assertEqual(ran["exit"], 124)
        self.assertNotIn("jade", self.windows())
        self.assertEqual(json.loads(softory(self.root, "run", "--dry-run", env=self.env).stdout)["attended"], "tmux")
