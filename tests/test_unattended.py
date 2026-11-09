"""Unattended runs: the charter, the runner, budgets and caps, the objective gate checks, and the digest."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
import sys
import unittest
from datetime import datetime
from pathlib import Path

from tests.helpers import REPO, in_terminal, coord, git_project, install, needs_sources, revision, run, softory

sys.path.insert(0, str(REPO / "lib"))
from softory import charter as charters  # noqa: E402
from softory import digest, perms  # noqa: E402
import os  # noqa: E402
import shlex  # noqa: E402
import subprocess  # noqa: E402

from tests.test_workflow import failing, gate, start  # noqa: E402


def at_terminal(root: Path, *args: str) -> dict:
    """Run softory in a terminal, typing yes; the JSON result follows the prompt."""
    command = shlex.join([str(root / ".agents/softory/bin/softory"), *args])
    env = {k: v for k, v in os.environ.items() if k not in ("COORDINATION_SESSION", "SOFTORY_ROLE")}
    result = subprocess.run(in_terminal(command), input="yes\n", cwd=root, env=env,
                            capture_output=True, text=True, check=False)
    output = result.stdout.replace("\r", "").split("Type yes to approve: ")[-1]
    return json.loads(output[output.index("{"):])

DEFAULTS = json.loads((Path(__file__).resolve().parents[1] / "factory/governance/charter.json").read_text())


class CharterUnitTest(unittest.TestCase):
    def test_overrides_merge_and_unknown_keys_are_named(self) -> None:
        merged = charters.merge(DEFAULTS, {"budget": {"minutes_per_run": 10}, "lanes": {"frontend": ["web/**"]}})
        self.assertEqual(merged["budget"]["minutes_per_run"], 10)
        self.assertEqual(merged["budget"]["runs_per_role_per_day"], DEFAULTS["budget"]["runs_per_role_per_day"])
        self.assertEqual(charters.unknown_keys(DEFAULTS, {"budgte": 1, "lanes": {"mobile": []}}), ["budgte"])

    def test_budget_overrides_per_role(self) -> None:
        from softory.runstate import limits_for
        self.assertEqual(limits_for(DEFAULTS, "greg")["minutes_per_run"], 15)
        self.assertEqual(limits_for(DEFAULTS, "jade")["minutes_per_run"], 30)
        self.assertEqual(limits_for(DEFAULTS, "greg")["runs_per_role_per_day"], 24)
        self.assertEqual(charters.unknown_keys(DEFAULTS, {"budget": {"roles": {"quinn": {"minutes_per_run": 60}}}}), [])

    def test_escalation_switches_model(self) -> None:
        self.assertEqual(charters.model_for(DEFAULTS, "toby", False), {"harness": "codex", "model": "gpt-6-astra"})
        self.assertEqual(charters.model_for(DEFAULTS, "jade", True)["model"], "claude-opus-5-5")  # no escalation set
        cheap = charters.merge(DEFAULTS, {"models": {"gold": {"harness": "codex", "model": "gpt-6.1-sol",
                                                             "escalate": {"harness": "claude", "model": "claude-opus-5-5"}}}})
        self.assertEqual(charters.model_for(cheap, "gold", False)["model"], "gpt-6.1-sol")
        self.assertEqual(charters.model_for(cheap, "gold", True)["harness"], "claude")

    def test_claude_settings_keep_a_role_in_its_lane(self) -> None:
        charter = charters.merge(DEFAULTS, {"lanes": {"frontend": ["web/**"]}})
        allow = perms.settings_for(charter, "jade")["permissions"]["allow"]
        self.assertIn("Edit(./web/**)", allow)
        self.assertNotIn("Edit", allow)
        self.assertIn("Edit", perms.settings_for(charter, "gold")["permissions"]["allow"])  # backend paths not set
        self.assertEqual(perms.unscoped(charter), ["gold"])
        deny = perms.settings_for(charter, "jade")["permissions"]["deny"]
        self.assertIn("Edit(./.agents/**)", deny)

    def test_claude_bash_rules_use_the_space_wildcard(self) -> None:
        allow = perms.settings_for(DEFAULTS, "jade")["permissions"]["allow"]
        self.assertTrue(all(rule.endswith(" *)") for rule in allow if rule.startswith("Bash(")))

    def test_usage_reads_each_harness_report(self) -> None:
        from softory import usage
        claude = json.dumps({"type": "result", "total_cost_usd": 0.1234567,
                             "usage": {"input_tokens": 10, "cache_creation_input_tokens": 5,
                                       "cache_read_input_tokens": 100, "output_tokens": 7}})
        self.assertEqual(usage.parse(claude, "claude-opus-5-5", DEFAULTS["prices"]),
                         {"input_tokens": 15, "cached_tokens": 100, "output_tokens": 7, "usd": 0.1235})
        codex = "\n".join([json.dumps({"type": "thread.started"}),
                           json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1_000_000,
                                       "cached_input_tokens": 400_000, "output_tokens": 100_000}})])
        found = usage.parse(codex, "gpt-6-astra", DEFAULTS["prices"])
        self.assertEqual((found["input_tokens"], found["cached_tokens"]), (600_000, 400_000))
        self.assertEqual(found["usd"], 6 + 0.4 + 5)
        self.assertTrue(found["usd_estimated"])
        self.assertEqual(usage.parse("plain text", "m", {}), {})

    def test_effort_follows_the_job_and_empty_flags_drop(self) -> None:
        from softory import runner, runprompt
        self.assertEqual(runprompt.job_of({"reasons": [{"why": "reviews waiting"}, {"why": "messages that need you"}]}), "review")
        self.assertEqual(runprompt.job_of({"reasons": [{"why": "reviews waiting"}, {"why": "assigned work changed"}]}), "build")
        self.assertEqual(charters.effort_for(DEFAULTS, "toby", "review"), "medium")
        own = charters.merge(DEFAULTS, {"models": {"toby": {"effort": {"review": "high"}}}})
        self.assertEqual(charters.effort_for(own, "toby", "review"), "high")
        pick = {"harness": "codex", "model": "gpt-6-astra"}
        command = runner.harness_command(None, DEFAULTS, "toby", pick, "go", "high")
        self.assertIn('model_reasoning_effort="high"', command)
        self.assertNotIn("-c", runner.harness_command(None, DEFAULTS, "toby", pick, "go", ""))
        self.assertEqual(command[-1], "go")

    def test_quiet_hours_wrap_midnight(self) -> None:
        self.assertTrue(digest._quiet(datetime(2026, 1, 1, 23), [22, 8]))
        self.assertTrue(digest._quiet(datetime(2026, 1, 1, 3), [22, 8]))
        self.assertFalse(digest._quiet(datetime(2026, 1, 1, 9), [22, 8]))


@needs_sources
class UnattendedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.holder, self.root = git_project({"README.md": "# app\n", "web/app.js": "1\n", "api/app.py": "1\n"})
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        softory(self.root, "new", "story", "--title", "See today", "--actor", "greg")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--title", "List", "--actor", "quinn")
        softory(self.root, "feasible", "STORY-1", "--pass", "--actor", "quinn")

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

    def build(self, task: str, builder: str, sha: str, review: bool = True) -> None:
        session = start(self.root, builder)["COORDINATION_SESSION"]
        coord(self.root, "--session", session, "task", "claim", task, "--agent", builder, "--if-revision", revision(self.root, task))
        coord(self.root, "evidence", "add", "--task", task, "--uri", f"commit:{sha}", "--type", "commit", "--actor", builder)
        coord(self.root, "--session", session, "task", "release", task, "--to", "review", "--actor", builder,
              "--if-revision", revision(self.root, task))
        if review:
            coord(self.root, "review", "add", "--id", f"REV-{task}-1", "--task", task, "--reviewer", "gold",
                  "--artifact", sha, "--scope", "t", "--decision", "accepted")
        softory(self.root, "end", "--session", session)

    def test_only_the_owner_approves_the_charter(self) -> None:
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps({"verify": {"command": "true"}}))
        refused = softory(self.root, "charter", "approve", str(path), check=False)
        self.assertIn("owner_terminal_required", refused.stderr)
        approved = self.approve({"verify": {"command": "true"}})
        self.assertEqual(approved["charter"]["verify"]["command"], "true")
        self.assertTrue(coord(self.root, "decision", "show", approved["decision"])["ok"])
        shown = json.loads(softory(self.root, "charter", "show").stdout)
        self.assertEqual(shown["approved"]["decision"], approved["decision"])

    def test_gate_needs_tests_that_softory_ran_at_the_commit(self) -> None:
        self.approve({"verify": {"command": "test -f web/app.js"}, "lanes": {"frontend": ["web/**"]},
                      "git": {"base": "HEAD~1"}})
        sha = self.commit("web/list.js", "x\n")
        self.build("TASK-1", "jade", sha)
        self.assertEqual(failing(gate(self.root, "TASK-1", "jade")), {"verified"})
        coord(self.root, "evidence", "add", "--task", "TASK-1", "--uri", f"softory-verify:pass:{sha}", "--type", "test",
              "--actor", "jade")
        self.assertEqual(failing(gate(self.root, "TASK-1", "jade")), {"verified"})  # a row an agent wrote doesn't count
        result = json.loads(softory(self.root, "verify", "TASK-1", "--actor", "jade").stdout)
        self.assertTrue(result["passed"])
        self.assertTrue(gate(self.root, "TASK-1", "jade")["pass"])
        self.assertEqual(run(["git", "worktree", "list"], self.root).stdout.count("\n"), 1)  # throwaway tree removed

    def test_failing_tests_and_out_of_lane_files_fail_the_gate(self) -> None:
        self.approve({"verify": {"command": "false"}, "lanes": {"frontend": ["web/**"]}, "git": {"base": "HEAD~1"}})
        sha = self.commit("api/secret.py", "x\n")
        self.build("TASK-1", "jade", sha)
        failed = softory(self.root, "verify", "TASK-1", "--actor", "jade", check=False)
        self.assertEqual(failed.returncode, 3)
        report = gate(self.root, "TASK-1", "jade")
        self.assertEqual(failing(report), {"verified", "lane_paths"})
        lane = next(c for c in report["checks"] if c["check"] == "lane_paths")
        self.assertIn("api/secret.py", lane["detail"])

    def test_lane_check_reads_past_work_other_units_built_below(self) -> None:
        base = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        self.approve({"verify": {"command": "true"}, "lanes": {"frontend": ["web/**"], "backend": ["api/**"]},
                      "git": {"base": base}})
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "backend", "--title", "API",
                "--actor", "quinn")
        below = self.commit("api/list.py", "x\n")
        self.build("TASK-2", "gold", below, review=False)
        softory(self.root, "verify", "TASK-2", "--actor", "gold")
        sha = self.commit("web/list.js", "x\n")
        self.build("TASK-1", "jade", sha)
        softory(self.root, "verify", "TASK-1", "--actor", "jade")
        lane = next(c for c in gate(self.root, "TASK-1", "jade")["checks"] if c["check"] == "lane_paths")
        self.assertTrue(lane["pass"], lane["detail"])
        self.assertIn("1 changed file", lane["detail"])

    def test_lane_check_counts_files_a_merge_changes(self) -> None:
        base = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        self.approve({"verify": {"command": "true"}, "lanes": {"frontend": ["web/**"], "backend": ["api/**"]},
                      "git": {"base": base}})
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "backend", "--title", "API",
                "--actor", "quinn")
        branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], self.root).stdout.strip()
        run(["git", "checkout", "-qb", "api-work"], self.root)
        below = self.commit("api/list.py", "x\n")
        self.build("TASK-2", "gold", below, review=False)
        softory(self.root, "verify", "TASK-2", "--actor", "gold")
        run(["git", "checkout", "-q", branch], self.root)
        self.commit("web/list.js", "x\n")
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "merge", "-q", "--no-commit", "api-work"], self.root)
        (self.root / "api/extra.py").write_text("slipped in while merging\n")
        run(["git", "add", "-A"], self.root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "merge"], self.root)
        sha = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        self.build("TASK-1", "jade", sha)
        softory(self.root, "verify", "TASK-1", "--actor", "jade")
        lane = next(c for c in gate(self.root, "TASK-1", "jade")["checks"] if c["check"] == "lane_paths")
        self.assertFalse(lane["pass"])
        self.assertIn("api/extra.py", lane["detail"])
        self.assertNotIn("api/list.py", lane["detail"])  # carried over from TASK-2, not this unit's change

    def test_lane_check_counts_a_merge_that_keeps_one_sides_file(self) -> None:
        self.commit("api/list.py", "a\nb\nc\nd\ne\n")
        base = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        self.approve({"verify": {"command": "true"}, "lanes": {"frontend": ["web/**"], "backend": ["api/**"]},
                      "git": {"base": base}})
        for title in ("Top", "Bottom"):
            softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "backend", "--title", title,
                    "--actor", "quinn")
        branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], self.root).stdout.strip()
        run(["git", "checkout", "-qb", "top"], self.root)
        top = self.commit("api/list.py", "A\nb\nc\nd\ne\n")
        self.build("TASK-2", "gold", top, review=False)
        softory(self.root, "verify", "TASK-2", "--actor", "gold")
        run(["git", "checkout", "-q", branch], self.root)
        bottom = self.commit("api/list.py", "a\nb\nc\nd\nE\n")
        self.build("TASK-3", "gold", bottom, review=False)
        softory(self.root, "verify", "TASK-3", "--actor", "gold")
        self.commit("web/list.js", "x\n")
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "merge", "-q", "--no-commit", "top"], self.root)
        run(["git", "checkout", "HEAD", "--", "api/list.py"], self.root)  # keep our side whole, dropping TASK-2's edit
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "merge"], self.root)
        sha = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        self.build("TASK-1", "jade", sha)
        softory(self.root, "verify", "TASK-1", "--actor", "jade")
        lane = next(c for c in gate(self.root, "TASK-1", "jade")["checks"] if c["check"] == "lane_paths")
        self.assertFalse(lane["pass"])
        self.assertIn("api/list.py", lane["detail"])

    def test_lane_check_counts_what_an_octopus_merge_drops(self) -> None:
        base = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        self.approve({"verify": {"command": "true"}, "lanes": {"frontend": ["web/**"], "backend": ["api/**"]},
                      "git": {"base": base}})
        branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], self.root).stdout.strip()
        for n, name in ((2, "one"), (3, "two")):
            softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "backend", "--title", name,
                    "--actor", "quinn")
            run(["git", "checkout", "-qb", name, base], self.root)
            sha = self.commit(f"api/{name}.py", "x\n")
            self.build(f"TASK-{n}", "gold", sha, review=False)
            softory(self.root, "verify", f"TASK-{n}", "--actor", "gold")
        run(["git", "checkout", "-q", branch], self.root)
        self.commit("web/list.js", "x\n")
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "merge", "-q", "-s", "ours", "-m", "octopus",
             "one", "two"], self.root)  # three parents, both backend changes dropped
        sha = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        self.build("TASK-1", "jade", sha)
        softory(self.root, "verify", "TASK-1", "--actor", "jade")
        lane = next(c for c in gate(self.root, "TASK-1", "jade")["checks"] if c["check"] == "lane_paths")
        self.assertFalse(lane["pass"], lane["detail"])
        self.assertIn("api/one.py", lane["detail"])
        self.assertIn("api/two.py", lane["detail"])

    def test_lane_check_counts_both_sides_of_a_rename(self) -> None:
        base = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        self.approve({"verify": {"command": "true"}, "lanes": {"frontend": ["web/**"]}, "git": {"base": base}})
        run(["git", "mv", "api/app.py", "web/app.py"], self.root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "move"], self.root)
        sha = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        self.build("TASK-1", "jade", sha)
        softory(self.root, "verify", "TASK-1", "--actor", "jade")
        lane = next(c for c in gate(self.root, "TASK-1", "jade")["checks"] if c["check"] == "lane_paths")
        self.assertFalse(lane["pass"])
        self.assertIn("api/app.py", lane["detail"])

    def test_quinns_backup_accepts_cross_lane_work_quinn_built(self) -> None:
        self.approve({"verify": {"command": "true"}, "lanes": {"frontend": ["web/**"]}, "git": {"base": "HEAD~1"}})
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--title", "Wide",
                "--tags", "cross-lane", "--assignee", "quinn", "--actor", "quinn")
        sha = self.commit("api/shared.py", "x\n")
        self.build("TASK-2", "quinn", sha)  # gold accepts
        softory(self.root, "verify", "TASK-2", "--actor", "quinn")
        lane = next(c for c in gate(self.root, "TASK-2", "quinn")["checks"] if c["check"] == "lane_paths")
        self.assertTrue(lane["pass"], lane["detail"])
        self.assertIn("accepted by gold", lane["detail"])

    def test_doctor_warns_when_sessions_start_outside_the_runner(self) -> None:
        self.approve({"verify": {"command": "true"}})
        start(self.root, "jade")
        warnings = json.loads(softory(self.root, "doctor", check=False).stdout)["warnings"]
        self.assertTrue(any("outside the runner (jade)" in w for w in warnings), warnings)
        run([str(self.root / ".agents/softory/bin/softory"), "start", "gold"], self.root, {"SOFTORY_RUNNER": "1"})
        rows = (self.root / ".coordination/softory/manual-starts.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(r)["role"] for r in rows], ["jade"])

    def test_a_setup_failure_is_not_a_test_failure_and_keeps_its_artifacts(self) -> None:
        self.approve({"verify": {"command": "true", "setup": "mkdir -p out && echo t > out/trace.txt && false",
                                 "keep": ["out/*.txt"]}, "git": {"base": "HEAD~1"}})
        sha = self.commit("web/list.js", "x\n")
        self.build("TASK-1", "jade", sha)
        result = json.loads(softory(self.root, "verify", "TASK-1", "--actor", "jade", check=False).stdout)
        self.assertEqual((result["passed"], result["stage"]), (False, "setup"))
        self.assertEqual(result["kept"], ["out/trace.txt"])
        detail = next(c for c in gate(self.root, "TASK-1", "jade")["checks"] if c["check"] == "verified")["detail"]
        self.assertIn("setup failed", detail)
        self.assertEqual(json.loads(softory(self.root, "queue", "--agent", "jade").stdout)["verify_queue"], [])

    def test_commit_and_supersede_keep_the_right_commit(self) -> None:
        base = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        sha = self.commit("web/list.js", "x\n")
        session = start(self.root, "jade")["COORDINATION_SESSION"]
        coord(self.root, "--session", session, "task", "claim", "TASK-1", "--agent", "jade",
              "--if-revision", revision(self.root, "TASK-1"))
        recorded = json.loads(softory(self.root, "commit", "TASK-1", sha[:8], "--base", base[:8], "--actor", "jade").stdout)
        self.assertEqual(recorded["uri"], f"commit:{sha};base={base}")
        coord(self.root, "evidence", "add", "--task", "TASK-1", "--uri", f"commit:{base}", "--type", "commit",
              "--actor", "jade")
        rows = coord(self.root, "task", "show", "TASK-1")["data"]["evidence"]
        wrong = str(rows[-1]["id"])
        refused = softory(self.root, "supersede", "TASK-1", wrong, "--reason", "x", "--actor", "gold", check=False)
        self.assertIn("not_allowed", refused.stderr)
        done = json.loads(softory(self.root, "supersede", "TASK-1", wrong, "--reason", "base, not head",
                                  "--actor", "jade").stdout)
        self.assertTrue(coord(self.root, "decision", "show", done["decision"])["ok"])
        sys.path.insert(0, str(REPO / "lib"))
        from softory import verify as verify_module  # noqa: PLC0415
        shown = coord(self.root, "task", "show", "TASK-1")["data"]
        self.assertEqual(verify_module.commit_of(self.root, shown), sha)

    def test_escalate_refuses_text_the_owner_cannot_read(self) -> None:
        refused = softory(self.root, "escalate", "--issue", "BUG60 had contain9 rounds", "--ask", "approve",
                          "--recommend", "x", "--reversible", "no", "--actor", "quinn", check=False)
        self.assertIn("invalid_arguments", refused.stderr)
        made = json.loads(softory(self.root, "escalate", "--issue", "TASK-1 had 3 rounds of requested changes.",
                                  "--ask", "Allow one more round on TASK-1?", "--tasks", "TASK-1",
                                  "--recommend", "One more round", "--reversible", "no",
                                  "--actor", "quinn").stdout)
        self.assertEqual(made["owner"], "owner")
        found = json.loads(softory(self.root, "digest").stdout)
        self.assertTrue(any("Allow one more round on TASK-1?" in row["text"] for row in found["digest"]))

    def test_a_scoped_resume_lets_one_task_through_a_pause(self) -> None:
        softory(self.root, "pause", "--reason", "stop everything")
        self.assertEqual(json.loads(softory(self.root, "run", "--dry-run").stdout)["started"], [])
        at_terminal(self.root, "resume", "--task", "TASK-1", "--roles", "jade")
        plan = json.loads(softory(self.root, "run", "--dry-run").stdout)
        self.assertEqual(plan["started"], ["jade"])
        wanted = json.loads(softory(self.root, "pending", "jade", check=False).stdout)
        self.assertEqual(wanted["scoped_to"], ["TASK-1"])
        queue = json.loads(softory(self.root, "queue", "--agent", "jade").stdout)
        self.assertEqual(queue["scoped_to"], ["TASK-1"])
        softory(self.root, "pause", "--role", "jade", "--reason", "stop again")
        self.assertEqual(json.loads(softory(self.root, "run", "--dry-run").stdout)["started"], [])  # the new stop wins
        at_terminal(self.root, "resume", "--task", "TASK-1", "--roles", "jade")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--title", "Other",
                "--actor", "quinn")
        outside = softory(self.root, "close", "TASK-2", "--actor", "jade", check=False)
        self.assertIn("paused", outside.stderr)
        at_terminal(self.root, "resume")
        at_terminal(self.root, "resume", "--role", "jade")
        self.assertNotIn("allow", json.loads((self.root / ".coordination/softory/paused.json").read_text()))

    def test_a_scoped_retry_is_not_hidden_by_an_unrelated_message(self) -> None:
        softory(self.root, "pause", "--reason", "stop everything")
        at_terminal(self.root, "resume", "--task", "TASK-1", "--roles", "jade")

        def pending(*extra: str) -> dict:  # TASK-1 unchanged since --since, so only the retry can schedule it
            return json.loads(softory(self.root, "pending", "jade", "--since", "2999-01-01T00:00:00+00:00",
                                      *extra, check=False).stdout)

        alone = pending()
        self.assertTrue(alone["pending"])
        coord(self.root, "message", "send", "--id", "MSG-UNRELATED", "--sender", "greg", "--recipient", "jade",
              "--body", "About something else")
        with_message = pending()
        self.assertTrue(with_message["pending"])
        self.assertEqual(with_message["reasons"], alone["reasons"])
        self.assertFalse(pending("--retry-hours", "0")["pending"])
        for n in range(3):
            coord(self.root, "review", "add", "--id", f"REV-CAP-{n}", "--task", "TASK-1", "--reviewer", "gold",
                  "--artifact", "x", "--scope", "t", "--decision", "changes_requested", "--required-changes",
                  "blocking: fix it")
        capped = pending()
        self.assertFalse(capped["pending"])
        self.assertEqual(capped["capped"], ["TASK-1"])

    def test_the_owner_can_approve_the_default_charter(self) -> None:
        approved = self.approve({})
        self.assertTrue(approved["approved"])
        self.assertTrue(json.loads(softory(self.root, "charter", "show").stdout)["approved"])
        again = self.approve({})
        self.assertFalse(again["approved"])  # once approved, an unchanged file changes nothing

    def test_charter_approve_merge_layers_on_what_is_approved(self) -> None:
        self.approve({"verify": {"command": "true"}})
        path = self.root / ".git" / "more.json"
        path.write_text(json.dumps({"task_caps": {"review_rounds": 4}}))
        merged = at_terminal(self.root, "charter", "approve", "--merge", str(path))
        self.assertEqual(merged["changed"], ["task_caps.review_rounds: 3 -> 4"])
        self.assertEqual((merged["charter"]["verify"]["command"], merged["charter"]["task_caps"]["review_rounds"]),
                         ("true", 4))

    def test_runner_starts_only_roles_with_work_and_respects_pause(self) -> None:
        plan = json.loads(softory(self.root, "run", "--dry-run").stdout)
        self.assertEqual(plan["started"], ["greg", "jade"])  # Greg owns STORY-1, Jade TASK-1; nobody else has work
        self.assertEqual(plan["skipped"]["toby"], "nothing pending")
        softory(self.root, "pause", "--role", "jade", "--reason", "upgrade")
        plan = json.loads(softory(self.root, "run", "--dry-run").stdout)
        self.assertEqual(plan["started"], ["greg"])
        self.assertIn("paused: upgrade", plan["skipped"]["jade"])
        pending = softory(self.root, "pending", "jade", check=False)
        self.assertEqual(pending.returncode, 3)
        self.assertIn("owner_terminal_required", softory(self.root, "resume", "--role", "jade", check=False).stderr)
        at_terminal(self.root, "resume", "--role", "jade")
        self.assertEqual(json.loads(softory(self.root, "run", "--dry-run").stdout)["started"], ["greg", "jade"])

    def test_a_run_is_logged_and_counts_against_the_budget(self) -> None:
        self.approve({"run": {"roles": ["jade"], "harnesses": {"fake": ["sh", "-c", "echo {model} > .git/ran-{role}"]}},
                      "models": {"jade": {"harness": "fake", "model": "m1", "escalate": None}},
                      "budget": {"runs_per_role_per_day": 1}})
        ran = json.loads(softory(self.root, "run-role", "jade").stdout)
        self.assertEqual((ran["exit"], ran["model"]), (0, "m1"))
        self.assertEqual((self.root / ".git/ran-jade").read_text().strip(), "m1")
        usage = json.loads(softory(self.root, "usage").stdout)
        self.assertTrue(usage["jade"]["over"])
        plan = json.loads(softory(self.root, "run", "--dry-run").stdout)
        self.assertIn("budget reached", plan["skipped"]["jade"])
        found = json.loads(softory(self.root, "digest").stdout)
        self.assertEqual([row["key"] for row in found["urgent"]], ["budget-jade"])

    def test_a_task_past_its_review_cap_stops_and_goes_to_the_owner(self) -> None:
        self.approve({"task_caps": {"review_rounds": 2, "escalate_model_after": 1}})
        sha = self.commit("web/a.js", "x\n")
        self.build("TASK-1", "jade", sha)
        coord(self.root, "review", "add", "--id", "REV-TASK-1-2", "--task", "TASK-1", "--reviewer", "gold",
              "--artifact", sha, "--scope", "t", "--decision", "changes_requested", "--required-changes", "x")
        once = json.loads(softory(self.root, "pending", "jade", "--since", "2000-01-01").stdout)
        self.assertEqual(once["escalate"], ["TASK-1"])
        coord(self.root, "review", "add", "--id", "REV-TASK-1-3", "--task", "TASK-1", "--reviewer", "gold",
              "--artifact", sha, "--scope", "t", "--decision", "changes_requested", "--required-changes", "x")
        capped = json.loads(softory(self.root, "pending", "jade", "--since", "2000-01-01", check=False).stdout)
        self.assertEqual(capped["capped"], ["TASK-1"])
        self.assertNotIn("TASK-1", json.dumps(capped["reasons"]))
        quinn = json.loads(softory(self.root, "pending", "quinn", "--since", "2000-01-01").stdout)
        self.assertIn("TASK-1", json.dumps(quinn["reasons"]))  # Quinn settles it, not the owner
        missed = json.loads(softory(self.root, "pending", "quinn", "--since", "2999-01-01").stdout)
        self.assertIn("TASK-1", json.dumps(missed["reasons"]))  # a run that missed it retries it
        self.assertNotIn("cap-TASK-1", [row["key"] for row in json.loads(softory(self.root, "digest").stdout)["digest"]])
        refused = softory(self.root, "settle", "TASK-1", "retry", "--reason", "x", "--actor", "gold", check=False)
        self.assertIn("not_allowed", refused.stderr)
        time.sleep(1.1)  # the extra round lands after the review that capped it
        with ThreadPoolExecutor(2) as pool:  # two retries at once: the lock lets only one extra round through
            raced = list(pool.map(lambda _: softory(self.root, "settle", "TASK-1", "retry", "--reason",
                                                    "one fix left, scoped", "--actor", "quinn", check=False), range(2)))
        self.assertEqual(sorted(r.returncode == 0 for r in raced), [False, True])
        shown = coord(self.root, "task", "show", "TASK-1")["data"]
        later = max([shown["updated_at"], *(r["created_at"] for r in shown.get("reviews") or [])])  # Jade ran since
        woken = json.loads(softory(self.root, "pending", "jade", "--since", later, "--retry-hours", "0",
                                   check=False).stdout)
        self.assertIn("TASK-1", json.dumps(woken["reasons"]))  # the extra round wakes the builder
        lifted = json.loads(softory(self.root, "pending", "jade", "--since", "2000-01-01", check=False).stdout)
        self.assertNotIn("capped", lifted)
        coord(self.root, "review", "add", "--id", "REV-TASK-1-4", "--task", "TASK-1", "--reviewer", "gold",
              "--artifact", sha, "--scope", "t", "--decision", "changes_requested", "--required-changes", "x")
        found = json.loads(softory(self.root, "digest").stdout)  # Quinn's one extra round is spent: the owner's now
        keys = [row["key"] for row in found["digest"]]
        self.assertIn("cap-TASK-1", keys)
        self.assertTrue(any(k.startswith("settled-TASK-1") for k in keys))

    def test_digest_pages_a_gate_bypass_once(self) -> None:
        marker = self.root / ".git" / "pages"
        self.approve({"paging": {"command": f"echo \"$SOFTORY_TITLE\" >> {marker}", "quiet_hours": []}})
        session = start(self.root, "jade")["COORDINATION_SESSION"]
        coord(self.root, "evidence", "add", "--task", "TASK-1", "--uri", "x", "--type", "commit", "--actor", "jade")
        coord(self.root, "--session", session, "task", "claim", "TASK-1", "--agent", "jade", "--if-revision", revision(self.root, "TASK-1"))
        coord(self.root, "--session", session, "task", "release", "TASK-1", "--to", "review", "--actor", "jade",
              "--if-revision", revision(self.root, "TASK-1"))
        coord(self.root, "task", "status", "TASK-1", "done", "--actor", "jade", "--if-revision", revision(self.root, "TASK-1"))
        softory(self.root, "run", "--dry-run")  # a dry run pages nobody
        self.assertFalse(marker.exists())
        softory(self.root, "run")
        softory(self.root, "run")
        pages = marker.read_text().splitlines()
        self.assertEqual(pages.count("Softory: needs you now"), 1)

    def test_setup_lists_what_is_left(self) -> None:
        steps = json.loads(softory(self.root, "setup").stdout)
        self.assertFalse(next(s for s in steps["steps"] if s["step"] == "charter approved")["done"])
        self.assertTrue(Path(steps["schedule"]["launchd"]).is_file())

    def test_reviews_wait_for_passing_tests_and_a_batch(self) -> None:
        self.approve({"verify": {"command": "true"}, "review_batch": {"min": 1, "max_wait_minutes": 60}})
        sha = self.commit("web/b.js", "x\n")
        self.build("TASK-1", "jade", sha, review=False)
        builder = json.loads(softory(self.root, "pending", "jade", "--since", "2000-01-01", check=False).stdout)
        self.assertIn("tests not passed", json.dumps(builder["reasons"]))
        reviewers = [r for r in DEFAULTS["run"]["roles"] if r != "jade"]
        waiting = lambda: {r for r in reviewers if "reviews waiting" in json.dumps(json.loads(
            softory(self.root, "pending", r, "--since", "2000-01-01", check=False).stdout)["reasons"])}
        self.assertEqual(waiting(), set())
        softory(self.root, "verify", "TASK-1", "--actor", "jade")
        woken = waiting()
        self.assertTrue(woken)
        self.approve({"verify": {"command": "true"}, "review_batch": {"min": 3, "max_wait_minutes": 60}})
        self.assertEqual(waiting(), set())
        held = json.loads(softory(self.root, "pending", sorted(woken)[0], "--since", "2000-01-01", check=False).stdout)
        self.assertEqual(held["batching"]["ids"], ["TASK-1"])

    def test_a_run_gets_the_work_in_its_prompt_and_logs_tokens_and_effort(self) -> None:
        (self.root / ".git/report.json").write_text(json.dumps({"total_cost_usd": 0.5,
                                                                 "usage": {"input_tokens": 10, "output_tokens": 5}}))
        script = ('printf %s "$1" > .git/prompt; echo {effort} > .git/effort; echo "$COORDINATION_SESSION" > .git/session; '
                  'cat .git/report.json')
        self.approve({"run": {"roles": ["jade"], "harnesses": {"fake": ["sh", "-c", script, "sh", "{prompt}"]}},
                      "models": {"jade": {"harness": "fake", "model": "m1", "escalate": None}}})
        ran = json.loads(softory(self.root, "run-role", "jade").stdout)
        self.assertEqual((ran["job"], ran["effort"], ran["usd"], ran["output_tokens"]), ("build", "high", 0.5, 5))
        self.assertEqual((self.root / ".git/effort").read_text().strip(), "high")
        prompt = (self.root / ".git/prompt").read_text()
        self.assertIn("TASK-1 [todo, parent STORY-1] List", prompt)
        self.assertLess(prompt.index("Your session is already open"), prompt.index("Waiting for you"))
        self.assertNotIn("softory start", prompt)  # the runner opened it, whatever the harness does with shells
        self.assertEqual(coord(self.root, "session", "list", "--agent", "jade", "--limit", "5")["data"][0]["status"], "ended")
        self.assertTrue((self.root / ".git/session").read_text().strip().startswith("jade-fake-"))
        self.assertEqual(json.loads(softory(self.root, "usage").stdout)["jade"]["usd"], 0.5)
