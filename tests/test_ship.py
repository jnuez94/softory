"""0.6.0: the scaffold's strict policies, merge on green, a base that stays green, deploys, releases, secrets."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.helpers import REPO, coord, git_project, install, needs_sources, revision, run, softory
from tests.test_workflow import at_terminal, failing, gate, start

sys.path.insert(0, str(REPO / "lib"))
from softory import backups, leaks, parents, perms, runner  # noqa: E402
from softory import charter as charters  # noqa: E402
from softory import deploy as deploys  # noqa: E402
from softory.coordination import Coordination  # noqa: E402
from softory.project import Project  # noqa: E402

DEFAULTS = json.loads((REPO / "factory/governance/charter.json").read_text())
GIT = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]


class LeakUnitTest(unittest.TestCase):
    def test_keys_count_and_placeholders_dont(self) -> None:
        self.assertEqual(leaks._kind('aws = "AKIAABCDEFGHIJKLMNOP"', []), "AWS access key")  # noqa: SLF001
        self.assertEqual(leaks._kind('password = "hunter2hunter2hunter2"', []), "hard-coded secret")  # noqa: SLF001
        self.assertIsNone(leaks._kind('password = "example-password-here"', []))  # noqa: SLF001
        self.assertIsNone(leaks._kind('api_key: "${API_KEY_FROM_ENV}"', []))  # noqa: SLF001
        self.assertIsNone(leaks._kind('aws = "AKIAABCDEFGHIJKLMNOP"', [__import__("re").compile("AKIAABCD")]))  # noqa: SLF001
        self.assertTrue(leaks._secret_file("config/.env"))  # noqa: SLF001
        self.assertFalse(leaks._secret_file(".env.example"))  # noqa: SLF001

    def test_roles_never_push_the_base_when_softory_merges(self) -> None:
        mine = charters.merge(DEFAULTS, {"merge": {"by": "softory", "push": "origin"}})
        deny = perms.settings_for(mine, "gold")["permissions"]["deny"]
        self.assertIn("Bash(git push origin main *)", deny)
        self.assertNotIn("Bash(git push origin main *)", perms.settings_for(DEFAULTS, "gold")["permissions"]["deny"])

    def test_deploy_targets_are_checked(self) -> None:
        bad = charters.merge(DEFAULTS, {"deploy": {"targets": [{"name": "production", "command": "x", "auto": True},
                                                              {"name": "staging"}]}})
        found = deploys.problems(bad)
        self.assertIn("production can't be an auto target: the owner deploys it", found)
        self.assertIn("each deploy target needs a name and a command", found)
        self.assertTrue(any("verify.command" in p for p in found))


@needs_sources
class EnforcementTest(unittest.TestCase):
    """Scaffold 1.4.2's strict closure and dependencies, on, with softory's records, drops, and gate."""

    def setUp(self) -> None:
        self.holder, self.root = git_project()
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps({"simplify": {"process_paths": []}}))
        at_terminal(self.root, "charter", "approve", str(path), "--merge")
        softory(self.root, "new", "epic", "--title", "Radar", "--actor", "greg")
        softory(self.root, "new", "story", "--parent", "EPIC-1", "--title", "See today", "--actor", "greg")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--title", "List", "--actor", "quinn")

    def build(self, task: str, builder: str) -> str:
        session = start(self.root, builder)["COORDINATION_SESSION"]
        coord(self.root, "--session", session, "task", "claim", task, "--agent", builder, "--if-revision",
              revision(self.root, task))
        coord(self.root, "evidence", "add", "--task", task, "--uri", "commit:1", "--type", "commit", "--actor", builder)
        coord(self.root, "--session", session, "task", "release", task, "--to", "review", "--actor", builder,
              "--if-revision", revision(self.root, task))
        return session

    def review(self, task: str, reviewer: str, number: int = 1) -> None:
        coord(self.root, "review", "add", "--id", f"REV-{task}-{reviewer}-{number}", "--task", task, "--reviewer",
              reviewer, "--artifact", "commit:1", "--scope", "test", "--decision", "accepted")

    def test_install_turns_the_policies_on_and_guards_them(self) -> None:
        config = (self.root / ".coordination/config.yml").read_text()
        for line in ("closure_policy: strict", "closure_review_waiver: decision", "closure_exempt_tags: unit:review",
                     "dependency_policy: strict"):
            self.assertIn(line, config)
        (self.root / ".coordination/config.yml").write_text(config.replace("closure_policy: strict", "closure_policy: off"))
        self.assertIn("config_intact", failing(gate(self.root, "TASK-1", "jade")))

    def test_a_raw_close_needs_an_accepted_review(self) -> None:
        self.build("TASK-1", "jade")
        refused = coord(self.root, "task", "status", "TASK-1", "done", "--actor", "jade", "--if-revision",
                        revision(self.root, "TASK-1"), check=False)
        self.assertEqual(refused["error"]["code"], "closure_requires_review")

    def test_greg_closes_the_story_he_accepted(self) -> None:
        session = self.build("TASK-1", "jade")
        self.review("TASK-1", "gold")
        softory(self.root, "close", "TASK-1", "--actor", "jade", env={"COORDINATION_SESSION": session})
        greg = self.build("STORY-1", "greg")
        self.review("STORY-1", "greg")  # his own acceptance, last: the scaffold alone would call it a self-review
        closed = json.loads(softory(self.root, "close", "STORY-1", "--actor", "greg",
                                    env={"COORDINATION_SESSION": greg}).stdout)
        self.assertTrue(closed["closed"])
        story = coord(self.root, "task", "show", "STORY-1")["data"]
        self.assertEqual(story["status"], "done")
        self.assertEqual([d["status"] for d in story["dependencies"]], ["resolved"])
        decisions = coord(self.root, "decision", "list", "--limit", "50")["data"]
        self.assertTrue(any(d["id"].startswith("SOFTORY-DEC-GATE-") for d in decisions))

    def test_blocked_work_cant_be_claimed_but_stacked_work_can(self) -> None:
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--title", "Waits", "--actor", "quinn")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--title", "On top", "--actor", "quinn")
        coord(self.root, "dependency", "add", "--task", "TASK-2", "--depends-on", "TASK-1", "--type", "blocks",
              "--actor", "quinn")
        softory(self.root, "stack", "TASK-1", "TASK-3", "--actor", "jade")
        session = start(self.root, "jade")["COORDINATION_SESSION"]
        blocked = coord(self.root, "--session", session, "task", "claim", "TASK-2", "--agent", "jade",
                        "--if-revision", revision(self.root, "TASK-2"), check=False)
        self.assertEqual(blocked["error"]["code"], "task_blocked")
        stacked = coord(self.root, "task", "show", "TASK-3")["data"]["dependencies"]
        self.assertEqual([(d["depends_on_task_id"], d["dependency_type"]) for d in stacked], [("TASK-1", "informs")])
        coord(self.root, "--session", session, "task", "claim", "TASK-3", "--agent", "jade",
              "--if-revision", revision(self.root, "TASK-3"))

    def test_dropping_blocked_work(self) -> None:
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--title", "Old", "--actor", "quinn")
        coord(self.root, "dependency", "add", "--task", "TASK-2", "--depends-on", "TASK-1", "--type", "blocks",
              "--actor", "quinn")
        session = start(self.root, "quinn")["COORDINATION_SESSION"]
        softory(self.root, "drop", "TASK-2", "--reason", "not needed", "--actor", "quinn",
                env={"COORDINATION_SESSION": session})
        self.assertEqual(coord(self.root, "task", "show", "TASK-2")["data"]["status"], "done")

    def test_parents_show_active_while_children_run(self) -> None:
        project = Project(self.root)
        board = Coordination(project.coordination_bin, self.root)
        self.assertEqual(parents.sync(project, board), {"activated": [], "cleared": []})
        session = start(self.root, "jade")["COORDINATION_SESSION"]
        coord(self.root, "--session", session, "task", "claim", "TASK-1", "--agent", "jade",
              "--if-revision", revision(self.root, "TASK-1"))
        self.assertEqual(parents.sync(project, board)["activated"], ["STORY-1", "EPIC-1"])
        listed = coord(self.root, "task", "list", "--active")["data"]
        self.assertEqual(sorted(t["id"] for t in listed), ["EPIC-1", "STORY-1"])
        self.assertEqual(parents.sync(project, board), {"activated": [], "cleared": []})  # nothing to repeat

    def test_daily_backups_keep_a_week(self) -> None:
        project = Project(self.root)
        board = Coordination(project.coordination_bin, self.root)
        folder = self.root / ".coordination/backups"
        old = folder / f"{backups.PREFIX}2020-01-01.sqlite3"
        folder.mkdir(parents=True, exist_ok=True)
        old.write_text("old")
        made = backups.daily(project, board, DEFAULTS)
        self.assertTrue(made and Path(made).is_file())
        self.assertIsNone(backups.daily(project, board, DEFAULTS))  # once a day
        self.assertFalse(old.exists())
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        self.assertIsNotNone(backups.daily(project, board, DEFAULTS, tomorrow))


@needs_sources
class ShipTest(unittest.TestCase):
    """Merge on green, the red-base rule, auto deploys, releases, and the secret scan, on real commits."""

    def setUp(self) -> None:
        self.holder, self.root = git_project({"README.md": "# app\n", "check.sh": "set -e\ntest ! -f a.txt || test ! -f c.txt\n"
                                              "test ! -f broken\n"})
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        self.base = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], self.root).stdout.strip()
        self.marks = Path(tempfile.mkdtemp(prefix="softory-staging-"))
        self.charter({"simplify": {"process_paths": []}, "git": {"base": self.base},
                      "verify": {"command": "sh check.sh"}, "merge": {"by": "softory"},
                      "deploy": {"targets": [{"name": "staging", "command": f"echo $SOFTORY_DEPLOY_COMMIT >> {self.marks}/log",
                                              "smoke": "test -f README.md", "auto": True}]}})
        softory(self.root, "new", "epic", "--title", "Radar", "--actor", "greg")
        softory(self.root, "new", "story", "--parent", "EPIC-1", "--title", "See today", "--actor", "greg")

    def charter(self, settings: dict) -> None:
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps(settings))
        self.assertTrue(at_terminal(self.root, "charter", "approve", str(path), "--merge")["approved"])

    def commit(self, branch: str, files: dict[str, str], start: str | None = None) -> str:
        run(["git", "checkout", "-q", "-b", branch, start or self.base], self.root)
        for name, text in files.items():
            (self.root / name).write_text(text)
        run(["git", "add", *files], self.root)
        run([*GIT, "commit", "-qm", branch], self.root)
        sha = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        run(["git", "checkout", "-q", self.base], self.root)
        return sha

    def new(self, title: str) -> str:
        return json.loads(softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "backend",
                                  "--title", title, "--actor", "quinn").stdout)["id"]

    def build(self, title: str, files: dict[str, str], on: str | None = None,
              verify: bool = True, task: str | None = None) -> tuple[str, str, dict[str, str]]:
        """A backend task built on its own branch (from ``on``, else the base) and verified, still open."""
        task = task or self.new(title)
        env = {"COORDINATION_SESSION": start(self.root, "gold")["COORDINATION_SESSION"]}
        coord(self.root, "--session", env["COORDINATION_SESSION"], "task", "claim", task, "--agent", "gold",
              "--if-revision", revision(self.root, task))
        sha = self.commit(task.lower(), files, on)
        softory(self.root, "commit", task, sha, "--actor", "gold")
        if verify:
            softory(self.root, "verify", task, "--actor", "gold", env=env)
        return task, sha, env

    def deliver(self, title: str, files: dict[str, str], on: str | None = None) -> str:
        """A backend task built, verified, peer-reviewed, and closed through the gate."""
        task, sha, env = self.build(title, files, on)
        softory(self.root, "handoff", task, "--actor", "gold", env=env)
        coord(self.root, "review", "add", "--id", f"REV-{task}", "--task", task, "--reviewer", "jade",
              "--artifact", sha, "--scope", "test", "--decision", "accepted")
        closed = json.loads(softory(self.root, "close", task, "--actor", "gold", env=env, check=False).stdout)
        self.assertTrue(closed["closed"], closed)
        return task

    def ship(self) -> dict:
        return json.loads(softory(self.root, "ship").stdout)

    def on_base(self, name: str) -> bool:
        return run(["git", "cat-file", "-e", f"{self.base}:{name}"], self.root, check=False).returncode == 0

    def test_finished_units_merge_as_one_verified_candidate_and_deploy(self) -> None:
        first = self.deliver("A", {"a.txt": "a\n"})
        second = self.deliver("B", {"b.txt": "b\n"})
        self.assertEqual([u["id"] for u in json.loads(softory(self.root, "ship", "--dry-run").stdout)["waiting"]],
                         [first, second])
        shipped = self.ship()
        self.assertEqual(shipped["merge"]["merged"], [first, second])
        self.assertTrue(self.on_base("a.txt") and self.on_base("b.txt"))
        head = run(["git", "rev-parse", self.base], self.root).stdout.strip()
        self.assertEqual(shipped["merge"]["base"], head)
        self.assertEqual(shipped["merge"]["deployed"], {"staging": "passed"})
        self.assertEqual((self.marks / "log").read_text().split(), [head])
        self.assertEqual(self.ship()["merge"], {"merged": []})  # nothing left, and the base is known green

    def test_only_the_verified_candidate_is_pushed(self) -> None:
        remote = Path(tempfile.mkdtemp(prefix="softory-remote-"))
        run(["git", "init", "-q", "--bare", str(remote)], self.root)
        run(["git", "remote", "add", "origin", str(remote)], self.root)
        self.charter({"merge": {"by": "softory", "push": "origin"}})
        self.deliver("A", {"a.txt": "a\n"})
        shipped = self.ship()
        self.assertEqual(shipped["merge"]["push"], "pushed")
        pushed = run(["git", "rev-parse", self.base], remote).stdout.strip()
        self.assertEqual(pushed, shipped["merge"]["base"])
        (self.root / "broken").write_text("x\n")  # a failing commit on the base by hand, after a shipment
        run(["git", "add", "broken"], self.root)
        run([*GIT, "commit", "-qm", "broken by hand"], self.root)
        again = self.ship()
        self.assertIsNone(again["push"])
        self.assertFalse(again["base_check"]["green"])
        self.assertEqual(run(["git", "rev-parse", self.base], remote).stdout.strip(), pushed)

    def test_a_paused_project_doesnt_ship(self) -> None:
        self.deliver("A", {"a.txt": "a\n"})
        project = Project(self.root)
        board = Coordination(project.coordination_bin, self.root)
        started: list[str] = []
        softory(self.root, "pause", "--reason", "stop everything")
        with mock.patch.object(runner, "spawn", lambda _project, name, *_: started.append(name)):
            report = runner.tick(project, board)
        self.assertNotIn("ship", report)
        self.assertEqual(started, [])
        self.assertFalse(self.on_base("a.txt"))

    def test_a_unit_built_on_open_work_waits_for_it(self) -> None:
        for verified in (True, False):  # the lower unit recorded its commit, with or without a verify run
            with self.subTest(verified=verified):
                name = "v" if verified else "u"
                below, sha, _ = self.build(f"A{name}", {f"a{name}.txt": "a\n"}, verify=verified)
                above = self.deliver(f"B{name}", {f"b{name}.txt": "b\n"}, on=sha)
                waiting = {u["id"]: u["waits_on"]
                           for u in json.loads(softory(self.root, "ship", "--dry-run").stdout)["waiting"]}
                self.assertEqual(waiting[above], [below])
                self.assertEqual(self.ship()["merge"], {"merged": []})
                self.assertFalse(self.on_base(f"a{name}.txt") or self.on_base(f"b{name}.txt"))

    def test_a_stacked_unit_waits_for_the_open_unit_below_it(self) -> None:
        below, above = self.new("A"), self.new("B")
        softory(self.root, "stack", below, above, "--actor", "quinn")
        self.build("A", {"a.txt": "a\n"}, task=below)
        _, sha, env = self.build("B", {"b.txt": "b\n"}, task=above)  # its own branch: only the stack ties it to A
        softory(self.root, "handoff", above, "--actor", "gold", env=env)
        coord(self.root, "review", "add", "--id", f"REV-{above}", "--task", above, "--reviewer", "jade",
              "--artifact", sha, "--scope", "test", "--decision", "accepted")
        self.assertTrue(json.loads(softory(self.root, "close", above, "--actor", "gold", env=env).stdout)["closed"])
        waiting = json.loads(softory(self.root, "ship", "--dry-run").stdout)["waiting"]
        self.assertEqual([(u["id"], u["waits_on"]) for u in waiting], [(above, [below])])
        self.assertEqual(self.ship()["merge"], {"merged": []})

    def test_a_commit_recorded_after_closing_doesnt_ship(self) -> None:
        task = self.deliver("A", {"a.txt": "a\n"})
        approved = run(["git", "rev-parse", task.lower()], self.root).stdout.strip()
        later = self.commit("later", {"late.txt": "unreviewed\n"}, approved)
        coord(self.root, "evidence", "add", "--task", task, "--uri", f"commit:{later}", "--type", "commit",
              "--actor", "gold")
        self.assertEqual([u["commit"] for u in json.loads(softory(self.root, "ship", "--dry-run").stdout)["waiting"]],
                         [approved])
        self.assertEqual(self.ship()["merge"]["merged"], [task])
        self.assertTrue(self.on_base("a.txt"))
        self.assertFalse(self.on_base("late.txt"))

    def test_a_failing_batch_splits_and_the_unit_that_breaks_it_is_held(self) -> None:
        first = self.deliver("A", {"a.txt": "a\n"})
        second = self.deliver("C", {"c.txt": "c\n"})  # each passes alone; together they fail check.sh
        self.assertTrue(self.ship()["merge"]["split"])
        self.assertEqual(self.ship()["merge"]["merged"], [first])
        held = self.ship()["merge"]["held"]
        self.assertEqual(list(held), [second])
        bug = coord(self.root, "task", "show", held[second])["data"]
        self.assertEqual((bug["priority"], bug["assignees"]), (1, ["gold"]))
        self.assertIn(f"from:{second}", bug["tags"])
        self.assertFalse(self.on_base("c.txt"))

    def test_a_conflict_is_held_with_a_bug(self) -> None:
        first = self.deliver("One", {"b.txt": "one\n"})
        second = self.deliver("Two", {"b.txt": "two\n"})
        merge = self.ship()["merge"]
        self.assertEqual((merge["merged"], list(merge["held"])), ([first], [second]))
        self.assertIn("conflicts in b.txt", coord(self.root, "task", "show", merge["held"][second])["data"]["title"])

    def test_a_red_base_gets_one_bug_and_stops_merging(self) -> None:
        (self.root / "broken").write_text("x\n")
        run(["git", "add", "broken"], self.root)
        run([*GIT, "commit", "-qm", "broken by hand"], self.root)
        state = self.ship()["base_check"]
        self.assertFalse(state["green"])
        self.assertEqual(coord(self.root, "task", "show", state["bug"])["data"]["priority"], 1)
        again = self.ship()
        self.assertEqual(again["base_check"]["bug"], state["bug"])  # one bug, not one per tick
        project = Project(self.root)
        from softory.ship import owner_items  # noqa: PLC0415
        self.assertTrue(any("red" in row["text"] for row in owner_items(project)[0]))

    def test_a_release_closes_after_staging_and_production_is_the_owners(self) -> None:
        self.ship()  # verifies the base, so it can be deployed
        made = json.loads(softory(self.root, "new", "release", "--title", "First", "--actor", "greg").stdout)
        release = made["id"]
        self.assertEqual(coord(self.root, "task", "show", release)["data"]["assignees"], ["gold"])
        env = {"COORDINATION_SESSION": start(self.root, "gold")["COORDINATION_SESSION"]}
        coord(self.root, "--session", env["COORDINATION_SESSION"], "task", "claim", release, "--agent", "gold",
              "--if-revision", revision(self.root, release))
        softory(self.root, "handoff", release, "--actor", "gold", env=env)
        self.assertTrue({"rollback_plan", "staged"} <= failing(gate(self.root, release, "greg")))
        plan = Path(tempfile.mkdtemp()) / "rollback.md"
        plan.write_text("Reinstall the previous build.\n")
        softory(self.root, "report", release, str(plan), "--type", "rollback", "--actor", "gold")
        softory(self.root, "deploy", "staging", "--release", release, "--actor", "gold")
        for reviewer in ("toby", "quinn"):
            coord(self.root, "review", "add", "--id", f"REV-{release}-{reviewer}", "--task", release, "--reviewer",
                  reviewer, "--artifact", made["commit"], "--scope", "release", "--decision", "accepted")
        greg = {"COORDINATION_SESSION": start(self.root, "greg")["COORDINATION_SESSION"]}
        self.assertTrue(json.loads(softory(self.root, "close", release, "--actor", "greg", env=greg).stdout)["closed"])
        self.charter({"deploy": {"targets": [{"name": "production", "command": "true"}]}})
        refused = softory(self.root, "deploy", "production", "--release", release, "--actor", "gold", check=False)
        self.assertIn("owner_terminal_required", refused.stderr)
        other = self.commit("other", {"x.txt": "x\n"})
        swapped = softory(self.root, "deploy", "production", "--release", release, "--commit", other,
                          "--actor", "gold", check=False)
        self.assertIn("deploys only its own commit", swapped.stderr)
        coord(self.root, "evidence", "add", "--task", release, "--uri", f"commit:{other}", "--type", "commit",
              "--actor", "gold")  # recorded after the release closed: production still gets the reviewed commit
        project = Project(self.root)
        row = deploys.run(project, Coordination(project.coordination_bin, self.root), charters.load(project),
                          "production", "owner", release=release, confirm=lambda _question: None)
        self.assertEqual((row["commit"], row["passed"]), (made["commit"], True))
        story = softory(self.root, "deploy", "production", "--release", "STORY-1", "--actor", "gold", check=False)
        self.assertIn("not a release unit", story.stderr)

    def test_a_dropped_release_never_reaches_production(self) -> None:
        self.charter({"deploy": {"targets": [{"name": "production", "command": "true"}]}})
        self.ship()  # verifies the base the releases record
        project = Project(self.root)
        board = Coordination(project.coordination_bin, self.root)
        greg = {"COORDINATION_SESSION": start(self.root, "greg")["COORDINATION_SESSION"]}
        for extra in ([], ["--superseded-by", "STORY-1"]):  # resolution:wont-do, then resolution:superseded
            release = json.loads(softory(self.root, "new", "release", "--title", "Cut", "--actor", "greg").stdout)["id"]
            softory(self.root, "drop", release, "--reason", "not shipping it", *extra, "--actor", "greg", env=greg)
            self.assertEqual(coord(self.root, "task", "show", release)["data"]["status"], "done")
            with self.assertRaises(Exception) as refused:
                deploys.run(project, board, charters.load(project), "production", "owner", release=release,
                            confirm=lambda _question: None)
            self.assertIn("through its gate", str(getattr(refused.exception, "message", refused.exception)))

    def test_a_committed_key_fails_the_gate(self) -> None:
        task = json.loads(softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "backend",
                                  "--title", "Leak", "--actor", "quinn").stdout)["id"]
        sha = self.commit("leak", {"settings.py": 'AWS = "AKIAABCDEFGHIJKLMNOP"\n'})
        softory(self.root, "commit", task, sha, "--actor", "gold")
        check = next(c for c in gate(self.root, task, "gold")["checks"] if c["check"] == "no_secrets")
        self.assertFalse(check["pass"])
        self.assertIn("settings.py:1: AWS access key", check["detail"])

    def test_a_base_git_cant_read_fails_the_scan(self) -> None:
        sha = self.commit("leak", {"settings.py": 'AWS = "AKIAABCDEFGHIJKLMNOP"\n'})
        check = leaks.check(self.root, {"git": {"base": "no-such-branch"}, "secrets": {}}, sha, [])
        self.assertFalse(check["pass"])
        self.assertIn("nothing was scanned", check["detail"])

    def test_a_key_added_while_merging_fails_the_gate(self) -> None:
        task = json.loads(softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "backend",
                                  "--title", "Merge leak", "--actor", "quinn").stdout)["id"]
        self.commit("left", {"l.txt": "l\n"})
        self.commit("right", {"r.txt": "r\n"})
        run(["git", "checkout", "-q", "left"], self.root)
        run([*GIT, "merge", "-q", "--no-commit", "--no-ff", "right"], self.root)
        (self.root / "settings.py").write_text('AWS = "AKIAABCDEFGHIJKLMNOP"\n')  # only the merge adds it
        run(["git", "add", "settings.py"], self.root)
        run([*GIT, "commit", "-qm", "merge right"], self.root)
        sha = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        run(["git", "checkout", "-q", self.base], self.root)
        softory(self.root, "commit", task, sha, "--actor", "gold")
        check = next(c for c in gate(self.root, task, "gold")["checks"] if c["check"] == "no_secrets")
        self.assertFalse(check["pass"])
        self.assertIn("settings.py:1: AWS access key", check["detail"])


if __name__ == "__main__":
    unittest.main()
