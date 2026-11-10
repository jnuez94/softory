"""Attended runs: the runner opens a role's interactive harness where the owner can watch it (0.5.8)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import signal

from tests.helpers import REPO, coord, git_project, install, needs_sources, softory
from tests.test_unattended import at_terminal

sys.path.insert(0, str(REPO / "lib"))
from softory import attended  # noqa: E402
from softory import charter as charters  # noqa: E402


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

    def attended(self, script: str, minutes: float = 5, headless: str = "exit 9") -> None:
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps({
            "run": {"mode": "attended", "roles": ["jade"], "attended": {"fake": ["sh", "-c", script]},
                    "harnesses": {"fake": ["sh", "-c", headless]}},
            "feasibility": {"harness": "fake", "model": "m2"},
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

    def test_a_worker_that_ignores_sigterm_is_stopped_before_claims_go_back(self) -> None:
        self.attended("(trap '' TERM HUP; exec sleep 600) & echo $! > .git/worker; "
                      ".agents/softory/bin/softory end --actor jade; wait")
        self.assertEqual(self.run_role()["exit"], 0)
        worker = int((self.root / ".git/worker").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(worker, 0)

    def test_closing_the_window_ends_the_run(self) -> None:
        self.attended("sleep 600")
        running = self.start_in_background()
        subprocess.run(["tmux", "kill-window", "-t", "jade"], env={**self.env, "PATH": "/usr/bin:/bin"}, check=False)
        out, _ = running.communicate(timeout=60)
        self.assertEqual(json.loads(out)["exit"], 129)

    def start_in_background(self, extra_env: dict | None = None) -> subprocess.Popen:
        running = subprocess.Popen([str(self.root / ".agents/softory/bin/softory"), "run-role", "jade"],
                                   cwd=self.root, env={**os.environ, **self.env, **(extra_env or {})},
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.addCleanup(running.kill)
        for _ in range(100):
            if "jade" in self.windows():
                break
            time.sleep(0.2)
        time.sleep(1)  # the window has started its script
        return running

    def test_an_interrupted_run_still_hands_its_session_back(self) -> None:
        self.attended("sleep 600")
        running = self.start_in_background()
        running.send_signal(signal.SIGINT)
        running.communicate(timeout=60)
        active = coord(self.root, "session", "list", "--agent", "jade", "--status", "active")["data"]
        self.assertEqual(active, [])

    def test_the_window_gets_the_runners_environment_not_the_tmux_servers(self) -> None:
        subprocess.run(["tmux", "new-session", "-d", "-s", "older", "sleep 600"],
                       env={**self.env, "PATH": "/usr/bin:/bin"}, check=True)  # a server started without it
        self.attended('echo "$FAKE_SIGNIN" > .git/signin')
        ran = json.loads(softory(self.root, "run-role", "jade", env={**self.env, "FAKE_SIGNIN": "token-1"}).stdout)
        self.assertEqual(ran["exit"], 0)
        self.assertEqual((self.root / ".git/signin").read_text().strip(), "token-1")

    def test_a_feasibility_check_stays_headless(self) -> None:
        self.attended("touch .git/attended-check", headless="touch .git/headless-check")
        softory(self.root, "run-check", "STORY-1", env=self.env, check=False)
        self.assertTrue((self.root / ".git/headless-check").exists())
        self.assertFalse((self.root / ".git/attended-check").exists())


@unittest.skipUnless(shutil.which("tmux"), "tmux isn't installed")
class TmuxRaceTest(unittest.TestCase):
    def test_roles_starting_together_each_get_a_window(self) -> None:
        sockets = tempfile.TemporaryDirectory(prefix="tmux-")
        self.addCleanup(sockets.cleanup)
        before = os.environ.get("TMUX_TMPDIR")
        os.environ["TMUX_TMPDIR"] = sockets.name
        self.addCleanup(lambda: os.environ.pop("TMUX_TMPDIR") if before is None else os.environ.update(TMUX_TMPDIR=before))
        self.addCleanup(subprocess.run, ["tmux", "kill-server"], capture_output=True, check=False)
        script = Path(sockets.name) / "idle.sh"
        script.write_text("sleep 30\n")
        project = SimpleNamespace(root=Path(sockets.name) / "race")
        project.root.mkdir()
        with ThreadPoolExecutor(6) as pool:
            windows = list(pool.map(lambda n: attended._open_tmux(project, f"role{n}", script,
                                                                  Path(sockets.name) / f"{n}.out"), range(6)))
        self.assertEqual(len(set(windows)), 6)


class AttendedCharterTest(unittest.TestCase):
    def test_attended_mode_needs_a_command_for_each_escalation_harness(self) -> None:
        defaults = json.loads((REPO / "factory/governance/charter.json").read_text())
        project = SimpleNamespace(role_ids=lambda: ["greg", "darwin", "quinn", "jade", "gold", "toby"])
        charter = charters.merge(defaults, {
            "run": {"mode": "attended", "harnesses": {"esc": ["esc", "{prompt}"]}},
            "models": {"jade": {"harness": "claude", "model": "m", "escalate": {"harness": "esc", "model": "big"}}}})
        self.assertIn("run.mode is attended, but run.attended has no interactive command for esc",
                      charters.validate(project, charter))
