"""0.6.5: a handoff asks every reviewer at once, a correction is re-reviewed on its change, one verdict covers a stack."""

from __future__ import annotations

import json
import os
import unittest

from tests.helpers import coord, git_project, install, needs_sources, revision, run, softory
from tests.test_unattended import at_terminal
from tests.test_workflow import start


@needs_sources
class HandoffTest(unittest.TestCase):
    def setUp(self) -> None:
        self.holder, self.root = git_project({"README.md": "# app\n"})
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        self.base = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        softory(self.root, "new", "story", "--title", "Today", "--actor", "greg")
        softory(self.root, "feasible", "STORY-1", "--pass", "--actor", "quinn")
        self.jade = {**os.environ, **start(self.root, "jade")}

    def new(self, unit: str, *args: str) -> str:
        made = softory(self.root, "new", unit, "--parent", "STORY-1", "--lane", "frontend", *args, "--actor", "quinn")
        return json.loads(made.stdout)["id"]

    def commit(self, name: str, *tasks: str) -> str:
        (self.root / name).write_text(name)
        run(["git", "add", name], self.root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", name], self.root)
        sha = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        for task in tasks:
            softory(self.root, "commit", task, sha, "--base", self.base, "--actor", "jade")
        return sha

    def claim(self, task: str) -> None:
        coord(self.root, "--session", self.jade["COORDINATION_SESSION"], "task", "claim", task, "--agent", "jade",
              "--if-revision", revision(self.root, task))

    def handoff(self, task: str, *args: str) -> dict:
        return json.loads(softory(self.root, "handoff", task, *args, "--actor", "jade", env=self.jade).stdout)

    def inbox(self, agent: str) -> list[dict]:
        found = coord(self.root, "inbox", "list", "--agent", agent)["data"]
        return found.get("messages", []) if isinstance(found, dict) else found

    def test_a_handoff_asks_every_required_reviewer_at_once(self) -> None:
        task = self.new("task", "--tags", "security", "--title", "Sign in")
        self.claim(task)
        sha = self.commit("a.txt", task)
        result = self.handoff(task, "--note", "Start with the token check.")
        self.assertEqual(sorted(a["reviewer"] for a in result["asked"]), ["gold", "toby"])
        for reviewer in ("gold", "toby"):
            asked = [m for m in self.inbox(reviewer) if m.get("task_id") == task]
            self.assertEqual(len(asked), 1)
            self.assertIn(f"Commit {sha}, built on {self.base}", asked[0]["body"])
            self.assertIn("Start with the token check.", asked[0]["body"])
            self.assertIn("request", asked[0]["tags"])
        self.assertNotIn("warnings", result)

    def test_a_correction_is_re_reviewed_on_what_changed(self) -> None:
        task = self.new("task", "--title", "Today list")
        self.claim(task)
        first = self.commit("a.txt", task)
        self.handoff(task)
        gold = {**os.environ, **start(self.root, "gold")}
        softory(self.root, "coord", "review", "add", "--id", "REV-1", "--task", task, "--reviewer", "gold",
                "--artifact", f"commit:{first}", "--scope", "all", "--decision", "changes_requested",
                "--required-changes", "Handle the empty list", env=gold)
        second = self.commit("b.txt", task)
        row = next(r for r in json.loads(softory(self.root, "queue", "--agent", "gold").stdout)["reviews_waiting"]
                   if r["id"] == task)
        self.assertEqual(row["re_review"]["diff"], f"git diff {first[:12]}..{second[:12]}")
        self.assertEqual(row["re_review"]["you_asked"], "Handle the empty list")
        self.assertIn("What you accepted stands", row["re_review"]["scope"])

    def test_a_re_review_starts_at_the_commit_the_review_named(self) -> None:
        task = self.new("task", "--title", "Today list")
        self.claim(task)
        first = self.commit("a.txt", task)
        self.handoff(task)
        gold = {**os.environ, **start(self.root, "gold")}

        def sent_back(review_id: str, artifact: str, then: str) -> tuple[str, dict]:
            softory(self.root, "coord", "review", "add", "--id", review_id, "--task", task, "--reviewer", "gold",
                    "--artifact", artifact, "--scope", "all", "--decision", "changes_requested",
                    "--required-changes", "Handle the empty list", env=gold)
            fixed = self.commit(then, task)
            rows = json.loads(softory(self.root, "queue", "--agent", "gold").stdout)["reviews_waiting"]
            return fixed, next(r for r in rows if r["id"] == task)["re_review"]

        second, row = sent_back("REV-1", "reports/20261120/review.md", "b.txt")
        self.assertNotIn("diff", row)  # a date in a report's path is not a commit
        third, row = sent_back("REV-2", f"base={first};head={second}", "c.txt")
        self.assertEqual(row["diff"], f"git diff {second[:12]}..{third[:12]}")  # the head it reviewed, not the base

    def test_a_request_names_the_base_of_the_standing_evidence(self) -> None:
        other = self.commit("c.txt")
        task = self.new("task", "--title", "Today list")
        self.claim(task)
        sha = self.commit("a.txt", task)
        wrong = coord(self.root, "evidence", "add", "--task", task, "--uri", f"commit:{sha};base={other}",
                      "--type", "commit", "--actor", "jade")["data"]
        softory(self.root, "supersede", task, str(wrong["id"]), "--reason", "wrong base", "--actor", "jade")
        self.handoff(task)
        asked = [m for m in self.inbox("gold") if m.get("task_id") == task]
        self.assertIn(f"Commit {sha}, built on {self.base}.", asked[0]["body"])

    def test_a_handoff_warns_when_the_tests_have_not_passed(self) -> None:
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps({"verify": {"command": "true"}, "git": {"base": self.base}}))
        at_terminal(self.root, "charter", "approve", str(path))
        task = self.new("task", "--title", "Today list")
        self.claim(task)
        self.commit("a.txt", task)
        result = self.handoff(task)
        self.assertEqual(result["status"], "review")
        self.assertIn("softory verify is not run", result["warnings"][0])

    def test_a_request_wakes_no_reviewer_before_the_tests_pass_and_the_batch_is_ready(self) -> None:
        path = self.root / ".git" / "charter.json"

        def approve(least: int) -> None:
            path.write_text(json.dumps({"verify": {"command": "true"}, "git": {"base": self.base},
                                        "review_batch": {"min": least, "max_wait_minutes": 60}}))
            at_terminal(self.root, "charter", "approve", str(path))

        def pending() -> dict:
            return json.loads(softory(self.root, "pending", "gold", "--since", "2000-01-01", check=False).stdout)

        approve(2)
        task = self.new("task", "--title", "Today list")
        self.claim(task)
        self.commit("a.txt", task)
        self.assertEqual([a["reviewer"] for a in self.handoff(task)["asked"]], ["gold"])
        self.assertEqual(len([m for m in self.inbox("gold") if m.get("task_id") == task]), 1)  # asked, and it waits
        self.assertFalse(pending()["pending"])  # the tests haven't passed
        softory(self.root, "verify", task, "--actor", "jade")
        held = pending()
        self.assertFalse(held["pending"])  # one verified review, and the batch is two
        self.assertEqual(held["batching"]["ids"], [task])
        approve(1)
        self.assertIn("reviews waiting", json.dumps(pending()["reasons"]))

    def test_a_request_for_a_task_from_before_softory_still_wakes_its_reviewer(self) -> None:
        coord(self.root, "task", "create", "--id", "OLD-1", "--title", "Rotate the keys", "--actor", "greg",
              "--tags", "security", "--assignee", "jade")
        self.claim("OLD-1")
        self.commit("a.txt", "OLD-1")
        self.assertIn("toby", [a["reviewer"] for a in self.handoff("OLD-1")["asked"]])
        queue = json.loads(softory(self.root, "queue", "--agent", "toby").stdout)
        self.assertEqual(queue["reviews_waiting"], [])  # the review queue doesn't list it, so the request must
        found = json.loads(softory(self.root, "pending", "toby", "--since", "2000-01-01", check=False).stdout)
        self.assertIn("messages that need you", json.dumps(found["reasons"]))

    def test_one_verdict_covers_a_stack_of_small_bugs_at_one_commit(self) -> None:
        bugs = [self.new("bug", "--type", "functional", "--title", f"Bug {n}") for n in (1, 2, 3)]
        for bug in bugs:
            self.claim(bug)
        sha = self.commit("a.txt", bugs[0], bugs[1])
        self.commit("b.txt", bugs[2])  # a later commit: the verdict on the first doesn't reach it
        softory(self.root, "stack", *bugs, "--actor", "jade", env=self.jade)
        for bug in bugs:
            self.handoff(bug)
        gold = {**os.environ, **start(self.root, "gold")}
        alone = softory(self.root, "coord", "review", "add", "--id", "REV-A", "--task", bugs[0], "--reviewer", "gold",
                        "--artifact", f"commit:{sha}", "--scope", "this fix", "--decision", "changes_requested",
                        "--required-changes", "x", env=gold)
        self.assertNotIn("same verdict", alone.stderr)
        self.assertEqual(coord(self.root, "task", "show", bugs[1])["data"]["reviews"], [])
        both = softory(self.root, "coord", "review", "add", "--id", "REV-B", "--task", bugs[0], "--reviewer", "gold",
                       "--artifact", f"commit:{sha}", "--scope", f"both fixes, stack:{bugs[0]}", "--decision",
                       "accepted", env=gold)
        self.assertIn(f"recorded on {bugs[1]} ", both.stderr)
        second = coord(self.root, "task", "show", bugs[1])["data"]["reviews"]
        self.assertEqual([(r["reviewer_id"], r["decision"], r["id"]) for r in second],
                         [("gold", "accepted", f"REV-B-{bugs[1]}")])
        self.assertEqual(coord(self.root, "task", "show", bugs[2])["data"]["reviews"], [])

    def test_a_stack_verdict_does_not_reach_a_bug_that_moved_on(self) -> None:
        bugs = [self.new("bug", "--type", "functional", "--title", f"Bug {n}") for n in (1, 2, 3)]
        for bug in bugs:
            self.claim(bug)
        seen = self.commit("a.txt", *bugs)
        softory(self.root, "stack", *bugs, "--actor", "jade", env=self.jade)
        for bug in bugs:
            self.handoff(bug)
        newer = self.commit("b.txt", bugs[0], bugs[1])  # the builder moves two of them on before the verdict
        gold = {**os.environ, **start(self.root, "gold")}
        late = softory(self.root, "coord", "review", "add", "--id", "REV-C", "--task", bugs[0], "--reviewer", "gold",
                       "--artifact", f"commit:{seen}", "--scope", f"all three, stack:{bugs[0]}", "--decision",
                       "accepted", env=gold)
        self.assertEqual(late.returncode, 0, late.stderr)
        self.assertEqual(coord(self.root, "task", "show", bugs[1])["data"]["reviews"], [])  # at the newer commit
        third = coord(self.root, "task", "show", bugs[2])["data"]["reviews"]
        self.assertEqual([r["id"] for r in third], [f"REV-C-{bugs[2]}"])  # still at the commit that was reviewed
        named = softory(self.root, "coord", "review", "add", "--id", "REV-D", "--task", bugs[0], "--reviewer",
                        "gold", "--artifact", "reports/20261120/review.md", "--scope", f"stack:{bugs[0]}",
                        "--decision", "accepted", env=gold)
        self.assertNotIn("same verdict", named.stderr)  # no commit named: nothing to match the others against
        self.assertNotEqual(newer, seen)

    def test_flow_reports_how_delivered_units_went_through_review(self) -> None:
        path = self.root / ".git" / "charter.json"  # the secret scan needs a base this repository has
        path.write_text(json.dumps({"git": {"base": self.base}}))
        at_terminal(self.root, "charter", "approve", str(path))
        report = json.loads(softory(self.root, "flow").stdout)
        for key in ("first_verdict_hours", "handoff_to_close_hours", "fix_bugs_per_unit"):
            self.assertIn(key, report)
        task = self.new("task", "--title", "Today list")
        self.claim(task)
        sha = self.commit("a.txt", task)
        self.handoff(task)
        gold = {**os.environ, **start(self.root, "gold")}
        softory(self.root, "coord", "review", "add", "--id", "REV-1", "--task", task, "--reviewer", "gold",
                "--artifact", f"commit:{sha}", "--scope", "all", "--decision", "accepted", env=gold)
        closed = json.loads(softory(self.root, "close", task, "--actor", "jade", env=self.jade, check=False).stdout)
        self.assertTrue(closed["closed"], closed)
        softory(self.root, "new", "bug", "--from", task, "--lane", "frontend", "--type", "functional", "--title",
                "Empty list", "--actor", "gold")
        report = json.loads(softory(self.root, "flow").stdout)
        self.assertEqual(report["closed"], 1)
        self.assertEqual(report["first_verdict_hours"], 0.0)
        self.assertEqual(report["handoff_to_close_hours"], 0.0)
        self.assertEqual(report["fix_bugs_per_unit"], 1.0)

    # 0.6.12: whoever built a follow-up a task can't close without isn't its independent peer, and a commit
    # recorded on the base branch is pointed out.

    def test_the_builder_of_a_blocking_follow_up_is_not_asked_to_review_its_source(self) -> None:
        task = self.new("task", "--title", "Today list")
        self.claim(task)
        self.commit("a.txt", task)
        self.handoff(task)
        self.assertEqual(json.loads(softory(self.root, "reviewers", task).stdout)["requirements"][0]["reviewers"], ["gold"])
        bug = json.loads(softory(self.root, "new", "bug", "--from", task, "--blocks-source", "--type", "functional", "--title", "Parser cap",
                                 "--assignee", "gold", "--actor", "quinn").stdout)["id"]
        gold = {**os.environ, **start(self.root, "gold")}
        coord(self.root, "--session", gold["COORDINATION_SESSION"], "task", "claim", bug, "--agent", "gold",
              "--if-revision", revision(self.root, bug))
        (self.root / "b.txt").write_text("b")
        run(["git", "add", "b.txt"], self.root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "b"], self.root)
        softory(self.root, "commit", bug, "HEAD", "--base", self.base, "--actor", "gold")
        result = json.loads(softory(self.root, "handoff", bug, "--actor", "gold", env=gold).stdout)
        self.assertIn(f"{task} is tagged built-by:gold", result["built_by"][0])
        found = json.loads(softory(self.root, "reviewers", task).stdout)
        self.assertEqual(found["builders"], ["gold", "jade"])
        self.assertEqual(found["requirements"][0]["reviewers"], [])
        refused = softory(self.root, "close", task, "--actor", "gold", env=gold, check=False)
        self.assertNotEqual(refused.returncode, 0)  # built-by makes Gold a builder for reviews, not a holder who may close

    def test_a_follow_up_that_does_not_block_its_source_tags_nothing(self) -> None:
        task = self.new("task", "--title", "Today list")
        self.claim(task)
        self.commit("a.txt", task)
        self.handoff(task)
        bug = json.loads(softory(self.root, "new", "bug", "--from", task, "--type", "functional", "--title", "Later polish",
                                 "--assignee", "gold", "--actor", "quinn").stdout)["id"]
        gold = {**os.environ, **start(self.root, "gold")}
        coord(self.root, "--session", gold["COORDINATION_SESSION"], "task", "claim", bug, "--agent", "gold",
              "--if-revision", revision(self.root, bug))
        softory(self.root, "commit", bug, "HEAD", "--base", self.base, "--actor", "gold")
        result = json.loads(softory(self.root, "handoff", bug, "--actor", "gold", env=gold).stdout)
        self.assertNotIn("built_by", result)
        self.assertEqual(json.loads(softory(self.root, "reviewers", task).stdout)["builders"], ["jade"])

    def test_a_change_request_from_someone_who_then_built_part_of_it_passes_to_the_next_reviewer(self) -> None:
        task = self.new("task", "--title", "Today list")
        self.claim(task)
        sha = self.commit("a.txt", task)
        self.handoff(task)
        gold = {**os.environ, **start(self.root, "gold")}
        softory(self.root, "coord", "review", "add", "--id", "REV-1", "--task", task, "--reviewer", "gold",
                "--artifact", f"commit:{sha}", "--scope", "all", "--decision", "changes_requested",
                "--required-changes", "Cap the parser", env=gold)
        bug = json.loads(softory(self.root, "new", "bug", "--from", task, "--blocks-source", "--type", "functional",
                                 "--title", "Parser cap", "--assignee", "gold", "--actor", "quinn").stdout)["id"]
        coord(self.root, "--session", gold["COORDINATION_SESSION"], "task", "claim", bug, "--agent", "gold",
              "--if-revision", revision(self.root, bug))
        softory(self.root, "commit", bug, "HEAD", "--base", self.base, "--actor", "gold")
        softory(self.root, "handoff", bug, "--actor", "gold", env=gold)
        coord(self.root, "agent", "add", "--id", "avery", "--name", "Avery", "--role", "Reviewer", "--actor", "owner")
        at_terminal(self.root, "standin", "add", "avery", "--for", "jade,gold")

        def rejections() -> dict:
            report = json.loads(softory(self.root, "gate", task, "--actor", "jade", check=False).stdout)
            return next(c for c in report["checks"] if c["check"] == "no_open_rejections")

        self.assertFalse(rejections()["pass"])  # Gold's request stands until someone independent answers it
        self.assertFalse([r for r in json.loads(softory(self.root, "queue", "--agent", "gold").stdout)["reviews_waiting"]
                          if r["id"] == task])
        row = next(r for r in json.loads(softory(self.root, "queue", "--agent", "avery").stdout)["reviews_waiting"]
                   if r["id"] == task)
        self.assertEqual((row["takes_over"][0]["from"], row["takes_over"][0]["asked"]), ("gold", "Cap the parser"))
        avery = {**os.environ, **dict(line.removeprefix("export ").split("=", 1) for line in softory(
            self.root, "start", "avery", "--harness", "codex").stdout.splitlines())}
        softory(self.root, "coord", "review", "add", "--id", "REV-2", "--task", task, "--reviewer", "avery",
                "--artifact", f"commit:{sha}", "--scope", "all", "--decision", "accepted", env=avery)
        settled = rejections()
        self.assertTrue(settled["pass"], settled)
        self.assertIn("gold asked for changes, then built part of it", settled["detail"])
        softory(self.root, "coord", "review", "add", "--id", "REV-3", "--task", task, "--reviewer", "gold",
                "--artifact", f"commit:{sha}", "--scope", "all", "--decision", "changes_requested",
                "--required-changes", "Still wrong", env=gold)
        self.assertFalse(rejections()["pass"])  # a request made after the acceptance is a new one

    def test_a_request_that_was_taken_over_stops_holding_the_task_everywhere(self) -> None:
        path = self.root / ".git" / "charter.json"  # the secret scan needs a base this repository has
        path.write_text(json.dumps({"git": {"base": self.base}}))
        at_terminal(self.root, "charter", "approve", str(path))
        coord(self.root, "agent", "add", "--id", "avery", "--name", "Avery", "--role", "Reviewer", "--actor", "owner")
        at_terminal(self.root, "standin", "add", "avery", "--for", "jade,gold")
        avery = {**os.environ, **dict(line.removeprefix("export ").split("=", 1) for line in softory(
            self.root, "start", "avery", "--harness", "codex").stdout.splitlines())}
        task = self.new("task", "--title", "Today list")
        self.claim(task)
        sha = self.commit("a.txt", task)
        self.handoff(task)
        gold = {**os.environ, **start(self.root, "gold")}
        softory(self.root, "coord", "review", "add", "--id", "REV-1", "--task", task, "--reviewer", "gold",
                "--artifact", f"commit:{sha}", "--scope", "all", "--decision", "changes_requested",
                "--required-changes", "Cap the parser", env=gold)
        bug = json.loads(softory(self.root, "new", "bug", "--from", task, "--blocks-source", "--type", "functional",
                                 "--title", "Parser cap", "--assignee", "gold", "--actor", "quinn").stdout)["id"]
        coord(self.root, "--session", gold["COORDINATION_SESSION"], "task", "claim", bug, "--agent", "gold",
              "--if-revision", revision(self.root, bug))
        (self.root / "fix.txt").write_text("fix")
        run(["git", "add", "fix.txt"], self.root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "fix"], self.root)
        fix = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        softory(self.root, "commit", bug, fix, "--base", sha, "--actor", "gold")
        softory(self.root, "handoff", bug, "--actor", "gold", env=gold)
        softory(self.root, "coord", "review", "add", "--id", "REV-2", "--task", bug, "--reviewer", "jade",
                "--artifact", f"commit:{fix}", "--scope", "all", "--decision", "accepted", env=self.jade)
        closed = json.loads(softory(self.root, "close", bug, "--actor", "gold", env=gold, check=False).stdout)
        self.assertTrue(closed["closed"], closed)

        def view() -> tuple[bool, list, list]:
            ready = [r["id"] for r in json.loads(softory(self.root, "queue", "--agent", "jade").stdout)["ready_to_close"]]
            pending = json.loads(softory(self.root, "pending", "jade", check=False).stdout)
            asked = [i for reason in pending["reasons"] if reason["why"] == "changes requested" for i in reason["ids"]]
            gate = json.loads(softory(self.root, "gate", task, "--actor", "jade", check=False).stdout)
            return gate["pass"], ready, asked

        self.assertEqual(view(), (False, [], [task]))  # Gold's request still holds it
        softory(self.root, "coord", "review", "add", "--id", "REV-3", "--task", task, "--reviewer", "avery",
                "--artifact", f"commit:{sha}", "--scope", "all", "--decision", "accepted", env=avery)
        self.assertEqual(view(), (True, [task], []))  # Avery took it over: the gate, the queue and pending agree
        done = json.loads(softory(self.root, "close", "--ready", "--actor", "jade", env=self.jade).stdout)
        self.assertEqual(done["closed"], [task])

    def test_a_builder_cannot_settle_their_own_change_request(self) -> None:
        coord(self.root, "agent", "add", "--id", "avery", "--name", "Avery", "--role", "Reviewer", "--actor", "owner")
        at_terminal(self.root, "standin", "add", "avery", "--for", "jade,gold")
        avery = {**os.environ, **dict(line.removeprefix("export ").split("=", 1) for line in softory(
            self.root, "start", "avery", "--harness", "codex").stdout.splitlines())}
        task = self.new("task", "--title", "Today list")
        self.claim(task)
        sha = self.commit("a.txt", task)
        self.handoff(task)
        gold = {**os.environ, **start(self.root, "gold")}

        def review(number: int, who: str, env: dict, decision: str, *more: str) -> None:
            softory(self.root, "coord", "review", "add", "--id", f"REV-{number}", "--task", task, "--reviewer", who,
                    "--artifact", f"commit:{sha}", "--scope", "all", "--decision", decision, *more, env=env)

        def rejections() -> dict:
            report = json.loads(softory(self.root, "gate", task, "--actor", "jade", check=False).stdout)
            return next(c for c in report["checks"] if c["check"] == "no_open_rejections")

        review(1, "avery", avery, "accepted")
        review(2, "gold", gold, "changes_requested", "--required-changes", "Cap the parser")
        bug = json.loads(softory(self.root, "new", "bug", "--from", task, "--blocks-source", "--type", "functional",
                                 "--title", "Parser cap", "--assignee", "gold", "--actor", "quinn").stdout)["id"]
        coord(self.root, "--session", gold["COORDINATION_SESSION"], "task", "claim", bug, "--agent", "gold",
              "--if-revision", revision(self.root, bug))
        softory(self.root, "commit", bug, "HEAD", "--base", self.base, "--actor", "gold")
        softory(self.root, "handoff", bug, "--actor", "gold", env=gold)
        review(3, "gold", gold, "accepted")  # Gold built part of it: this verdict is not independent
        held = rejections()
        self.assertFalse(held["pass"], held)
        self.assertIn("gold", held["detail"])
        row = next(r for r in json.loads(softory(self.root, "queue", "--agent", "avery").stdout)["reviews_waiting"]
                   if r["id"] == task)
        self.assertEqual(row["takes_over"][0]["asked"], "Cap the parser")
        review(4, "avery", avery, "accepted")
        self.assertTrue(rejections()["pass"])

    def test_an_acceptance_of_another_commit_takes_over_no_change_request(self) -> None:
        for agent in ("avery", "blair"):
            coord(self.root, "agent", "add", "--id", agent, "--name", agent.title(), "--role", "Reviewer",
                  "--actor", "owner")
            at_terminal(self.root, "standin", "add", agent, "--for", "jade,gold")

        def session(agent: str) -> dict:
            exports = softory(self.root, "start", agent, "--harness", "codex").stdout.splitlines()
            return {**os.environ, **dict(line.removeprefix("export ").split("=", 1) for line in exports)}

        def review(number: int, who: str, env: dict, sha: str, decision: str, *more: str) -> None:
            softory(self.root, "coord", "review", "add", "--id", f"REV-{number}", "--task", task, "--reviewer", who,
                    "--artifact", f"commit:{sha}", "--scope", "all", "--decision", decision, *more, env=env)

        task = self.new("task", "--title", "Today list")
        self.claim(task)
        old = self.commit("a.txt", task)
        current = self.commit("b.txt", task)
        self.handoff(task)
        gold = {**os.environ, **start(self.root, "gold")}
        review(1, "avery", session("avery"), current, "accepted")
        review(2, "gold", gold, current, "changes_requested", "--required-changes", "Cap the parser")
        bug = json.loads(softory(self.root, "new", "bug", "--from", task, "--blocks-source", "--type", "functional",
                                 "--title", "Parser cap", "--assignee", "gold", "--actor", "quinn").stdout)["id"]
        coord(self.root, "--session", gold["COORDINATION_SESSION"], "task", "claim", bug, "--agent", "gold",
              "--if-revision", revision(self.root, bug))
        softory(self.root, "commit", bug, current, "--base", self.base, "--actor", "gold")
        softory(self.root, "handoff", bug, "--actor", "gold", env=gold)
        blair = session("blair")
        review(3, "blair", blair, old, "accepted")  # after Gold's request, but of a commit the task no longer delivers

        def checks() -> dict:
            report = json.loads(softory(self.root, "gate", task, "--actor", "jade", check=False).stdout)
            return {c["check"]: c["pass"] for c in report["checks"]}

        self.assertTrue(checks()["reviews_cover_commit"])  # Avery's earlier acceptance covers the commit
        self.assertFalse(checks()["no_open_rejections"])  # nobody independent accepted it after Gold's request
        waiting = json.loads(softory(self.root, "queue", "--agent", "blair").stdout)["reviews_waiting"]
        self.assertEqual(next(r for r in waiting if r["id"] == task)["takes_over"][0]["from"], "gold")
        review(4, "blair", blair, current, "accepted")
        self.assertTrue(checks()["no_open_rejections"])

    def test_a_follow_up_whose_block_was_resolved_tags_nothing(self) -> None:
        task = self.new("task", "--title", "Today list")
        self.claim(task)
        self.commit("a.txt", task)
        self.handoff(task)
        bug = json.loads(softory(self.root, "new", "bug", "--from", task, "--blocks-source", "--type", "functional",
                                 "--title", "Parser cap", "--assignee", "gold", "--actor", "quinn").stdout)["id"]
        coord(self.root, "dependency", "resolve", "--task", task, "--depends-on", bug, "--type", "blocks",
              "--actor", "quinn")  # the fix was put off: the task no longer waits on it
        gold = {**os.environ, **start(self.root, "gold")}
        coord(self.root, "--session", gold["COORDINATION_SESSION"], "task", "claim", bug, "--agent", "gold",
              "--if-revision", revision(self.root, bug))
        softory(self.root, "commit", bug, "HEAD", "--base", self.base, "--actor", "gold")
        result = json.loads(softory(self.root, "handoff", bug, "--actor", "gold", env=gold).stdout)
        self.assertNotIn("built_by", result)
        found = json.loads(softory(self.root, "reviewers", task).stdout)
        self.assertEqual((found["builders"], found["requirements"][0]["reviewers"]), (["jade"], ["gold"]))

    def test_a_commit_recorded_on_the_base_branch_is_pointed_out(self) -> None:
        branch = run(["git", "branch", "--show-current"], self.root).stdout.strip()
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps({"git": {"base": branch}}))
        at_terminal(self.root, "charter", "approve", str(path))
        task = self.new("task", "--title", "Today list")
        self.claim(task)
        (self.root / "a.txt").write_text("a")
        run(["git", "add", "a.txt"], self.root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "a"], self.root)
        on_base = json.loads(softory(self.root, "commit", task, "HEAD", "--actor", "jade").stdout)
        self.assertIn(f"is already on {branch}, the base branch", on_base["warning"])
        run(["git", "switch", "-qc", "jade/today"], self.root)
        (self.root / "b.txt").write_text("b")
        run(["git", "add", "b.txt"], self.root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "b"], self.root)
        on_branch = json.loads(softory(self.root, "commit", task, "HEAD", "--actor", "jade").stdout)
        self.assertNotIn("warning", on_branch)


if __name__ == "__main__":
    unittest.main()
