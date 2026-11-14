"""0.6.4: records refuse wrong input, and the owner's word in a session counts."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO, coord, git_project, install, needs_sources, run, softory

sys.path.insert(0, str(REPO / "lib"))
from softory.coordination import Coordination, transient  # noqa: E402
from tests.test_workflow import start  # noqa: E402

SIDECAR = ('{"ok": false, "error": {"code": "database_configuration_error", '
           '"message": "SQLite operational sidecars must be regular files"}}')


class TransientTest(unittest.TestCase):
    def test_only_the_path_checks_own_race_is_transient(self) -> None:
        self.assertTrue(transient(SIDECAR))
        self.assertTrue(transient("FileNotFoundError: [Errno 2] No such file: '.coordination/coordination.db-wal'"))
        self.assertFalse(transient('{"ok": false, "error": {"code": "not_found", "message": "task TASK-9"}}'))
        self.assertFalse(transient('{"ok": false, "error": {"code": "database_configuration_error", '
                                   '"message": "Coordination database must be a regular file"}}'))

    def test_a_transient_failure_is_run_once_more(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            binary = root / "coordination"
            binary.write_text(f"#!/bin/sh\necho x >> {root}/calls\n"
                              f"if [ $(wc -l < {root}/calls) -lt \"$FAILS\" ]; then echo '{SIDECAR}' >&2; exit 4; fi\n"
                              "echo '{\"ok\": true, \"data\": 1}'\n")
            binary.chmod(0o755)
            os.environ["FAILS"] = "2"
            self.addCleanup(os.environ.pop, "FAILS", None)
            self.assertEqual(Coordination(binary, root).run("task", "list"), 1)
            self.assertEqual(len((root / "calls").read_text().splitlines()), 2)
            (root / "calls").unlink()
            os.environ["FAILS"] = "9"  # it keeps failing: one retry, then the error
            self.assertFalse(Coordination(binary, root).call("task", "list")["ok"])
            self.assertEqual(len((root / "calls").read_text().splitlines()), 2)


@needs_sources
class RecordsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.holder, self.root = git_project({"README.md": "# app\n"})
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        self.sha = run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()
        softory(self.root, "new", "story", "--title", "Today", "--actor", "greg")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--title", "Today list",
                "--actor", "quinn")
        self.jade = {**os.environ, **start(self.root, "jade")}

    def review(self, *args: str, env: dict[str, str] | None = None):
        return softory(self.root, "coord", "review", "add", "--task", "TASK-1", "--scope", "all",
                       "--decision", "accepted", *args, env=env or self.jade, check=False)

    def test_a_message_or_review_under_another_roles_name_is_refused(self) -> None:
        sent = softory(self.root, "coord", "message", "send", "--id", "M-1", "--sender", "gold", "--recipient",
                       "quinn", "--body", "ready", env=self.jade, check=False)
        self.assertNotEqual(sent.returncode, 0)
        self.assertIn("You are jade", sent.stderr)
        self.assertIn("--sender jade", sent.stderr)
        softory(self.root, "coord", "message", "send", "--id", "M-1", "--sender", "jade", "--recipient", "quinn",
                "--body", "ready", env=self.jade)
        other = self.review("--id", "REV-1", "--reviewer", "gold", "--artifact", f"commit:{self.sha}")
        self.assertIn("You are jade", other.stderr)
        owner = self.review("--id", "REV-1", "--reviewer", "owner", "--artifact", f"commit:{self.sha}")
        self.assertIn("softory ruling --review", owner.stderr)
        self.assertEqual(coord(self.root, "task", "show", "TASK-1")["data"]["reviews"], [])

    def test_a_review_of_a_commit_git_does_not_have_is_refused(self) -> None:
        missing = self.review("--id", "REV-1", "--reviewer", "jade", "--artifact", "commit:" + "ab12" * 10)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("is not a commit in this repository", missing.stderr)
        bare = self.review("--id", "REV-1", "--reviewer", "jade", "--artifact", "ab12" * 10)
        self.assertIn("is not a commit in this repository", bare.stderr)
        made = self.review("--id", "REV-1", "--reviewer", "jade", "--artifact", f"commit:{self.sha}")
        self.assertEqual(made.returncode, 0, made.stderr)
        prose = self.review("--id", "REV-2", "--reviewer", "jade", "--artifact", "docs/design/today.md")
        self.assertEqual(prose.returncode, 0, prose.stderr)

    def test_the_owners_approval_in_a_session_becomes_their_review(self) -> None:
        softory(self.root, "commit", "TASK-1", self.sha, "--actor", "jade")
        made = json.loads(softory(self.root, "ruling", "--title", "Today list approved", "--decision",
                                  "Approved as built", "--where", "Darwin's session, 13 Nov 14:02",
                                  "--review", "TASK-1", "--actor", "darwin").stdout)
        review = coord(self.root, "task", "show", "TASK-1")["data"]["reviews"][-1]
        self.assertEqual((review["reviewer_id"], review["decision"], review["id"]), ("owner", "accepted", made["review"]))
        full = coord(self.root, "review", "show", made["review"])["data"]
        self.assertEqual(full["artifact_uri"], f"commit:{self.sha}")
        self.assertIn("Recorded by darwin", full["scope"])
        self.assertIn(made["decision"], full["scope"])
        digest = json.loads(softory(self.root, "digest").stdout)["digest"]
        row = next(r for r in digest if r["key"] == f"on-behalf-{made['decision']}")
        self.assertIn("darwin recorded your approval of TASK-1", row["text"])
        self.assertIn("Darwin's session", row["text"])
        missing = softory(self.root, "ruling", "--title", "x", "--decision", "y", "--where", "z", "--review",
                          "TASK-99", "--actor", "darwin", check=False)
        self.assertNotEqual(missing.returncode, 0)

    def escalate(self, ask: str):
        return softory(self.root, "escalate", "--issue", "The outline rows are 20px tall.", "--ask", ask,
                       "--recommend", "Yes, 24px for both", "--reversible", "no", "--tasks", "TASK-1",
                       "--actor", "darwin", check=False)

    def test_the_owner_is_not_asked_the_same_question_twice(self) -> None:
        first = json.loads(self.escalate("Does the 24px minimum cover calendar events too?").stdout)["escalation"]
        again = self.escalate("does the 24px minimum  cover calendar events too?")
        self.assertNotEqual(again.returncode, 0)
        self.assertIn(first, again.stderr)
        self.assertEqual(len(coord(self.root, "escalation", "list", "--status", "open")["data"]), 1)
        other = self.escalate("Does the 24px minimum cover the toolbar too?")
        self.assertEqual(other.returncode, 0, other.stderr)

    def test_a_ruling_that_names_an_escalation_closes_it(self) -> None:
        asked = json.loads(self.escalate("Does the 24px minimum cover calendar events too?").stdout)["escalation"]
        made = json.loads(softory(self.root, "ruling", "--title", "24px covers calendar events", "--decision",
                                  "Yes, 24px for both", "--where", "project chat, 13 Nov 17:29Z",
                                  "--escalation", asked, "--actor", "greg").stdout)
        shown = coord(self.root, "escalation", "show", asked)["data"]
        self.assertEqual((shown["status"], shown["resolution"]), ("resolved", "Yes, 24px for both"))
        self.assertEqual(made["escalation"], asked)
        inbox = coord(self.root, "inbox", "list", "--agent", "darwin")["data"]
        messages = inbox.get("messages", []) if isinstance(inbox, dict) else inbox
        self.assertTrue(any("recorded by greg" in m["body"] for m in messages))
        digest = json.loads(softory(self.root, "digest").stdout)["digest"]
        self.assertTrue(any(f"your answer to {asked}" in r["text"] for r in digest))
        twice = softory(self.root, "ruling", "--title", "x", "--decision", "No", "--where", "z", "--escalation",
                        asked, "--actor", "greg", check=False)
        self.assertNotEqual(twice.returncode, 0)
        self.assertIn("already resolved", twice.stderr)

    def test_a_correction_writes_no_decision(self) -> None:
        softory(self.root, "commit", "TASK-1", self.sha, "--actor", "jade")
        row = coord(self.root, "task", "show", "TASK-1")["data"]["evidence"][-1]
        before = len(coord(self.root, "decision", "list")["data"])
        softory(self.root, "supersede", "TASK-1", str(row["id"]), "--reason", "base,\n not head", "--actor", "jade")
        self.assertEqual(len(coord(self.root, "decision", "list")["data"]), before)
        marker = coord(self.root, "task", "show", "TASK-1")["data"]["evidence"][-1]["uri"]
        self.assertEqual(marker, f"softory-supersedes:{row['id']}:base, not head")


if __name__ == "__main__":
    unittest.main()
