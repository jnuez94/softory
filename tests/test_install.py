"""Installing, re-installing, and uninstalling leave the project's git untouched."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.helpers import PINNED, PREVIOUS_SRC, coord, git_project, git_status, install, needs_sources, softory


@needs_sources
class FreshProjectTest(unittest.TestCase):
    def setUp(self) -> None:
        self.holder, self.root = git_project()
        self.addCleanup(self.holder.cleanup)
        self.result = install(self.root)

    def test_git_sees_nothing(self) -> None:
        self.assertEqual(self.result["git_status_changes"], [])
        self.assertEqual(git_status(self.root), "")

    def test_gitignore_is_byte_identical(self) -> None:
        self.assertEqual((self.root / ".gitignore").read_text(), "node_modules/\n")

    def test_instructions_reach_both_harnesses(self) -> None:
        agents = (self.root / "AGENTS.md").read_text()
        local = (self.root / "CLAUDE.local.md").read_text()
        for text in (agents, local):
            self.assertIn("Softory software factory", text)
            self.assertIn("agentic-project-scaffold-lite:start", text)
        self.assertNotIn("@AGENTS.md", local)  # softory owns AGENTS.md, so no import needed

    def test_skills_installed_for_claude_and_codex(self) -> None:
        for root in (".claude/skills", ".agents/skills"):
            self.assertTrue((self.root / root / "softory-code-quality" / "SKILL.md").is_file())

    def test_roles_registered(self) -> None:
        agents = {a["id"]: a for a in coord(self.root, "agent", "list")["data"]}
        self.assertEqual(set(agents), {"owner", "greg", "darwin", "quinn", "jade", "gold", "toby"})
        self.assertEqual(agents["owner"]["name"], "Tester")
        self.assertEqual(agents["owner"]["actor_type"], "human")
        self.assertIn("Reviewing a change they implemented", agents["toby"]["unavailable_for"])

    def test_doctor_passes(self) -> None:
        report = json.loads(softory(self.root, "doctor").stdout)
        self.assertTrue(report["pass"], report)

    def test_reinstall_is_idempotent(self) -> None:
        self.assertIsNone(self.result["scaffold_found"])
        again = install(self.root)
        self.assertEqual(again["scaffold_found"], PINNED)
        self.assertIsNone(again["scaffold_backup"])  # same version: nothing to back up
        self.assertEqual(again["registered"], [])
        self.assertEqual(git_status(self.root), "")
        self.assertEqual((self.root / "AGENTS.md").read_text().count("softory:start"), 1)

    def test_uninstall_keeps_history_and_hides_it(self) -> None:
        softory(self.root, "uninstall")
        self.assertFalse((self.root / ".agents").exists())
        self.assertFalse((self.root / "AGENTS.md").exists())
        self.assertTrue((self.root / ".coordination").is_dir())
        self.assertEqual(git_status(self.root), "")

    def test_uninstall_purge_leaves_nothing(self) -> None:
        softory(self.root, "uninstall", "--purge")
        self.assertFalse((self.root / ".coordination").exists())
        self.assertEqual(git_status(self.root), "")
        exclude = (self.root / ".git/info/exclude").read_text()
        self.assertNotIn("softory", exclude)


@needs_sources
class TrackedInstructionsTest(unittest.TestCase):
    """A project that already commits AGENTS.md keeps it byte-identical."""

    def setUp(self) -> None:
        self.holder, self.root = git_project({"AGENTS.md": "# Team rules\nUse tabs.\n", "README.md": "x\n"})
        self.addCleanup(self.holder.cleanup)
        self.result = install(self.root)

    def test_tracked_agents_md_untouched(self) -> None:
        self.assertEqual((self.root / "AGENTS.md").read_text(), "# Team rules\nUse tabs.\n")
        self.assertEqual(git_status(self.root), "")

    def test_codex_override_carries_both(self) -> None:
        override = (self.root / "AGENTS.override.md").read_text()
        self.assertIn("Use tabs.", override)
        self.assertIn("Softory software factory", override)

    def test_codex_gets_the_installed_scaffold_block(self) -> None:
        """A tracked AGENTS.md with 1.4.0's scaffold block: Codex's copy gets the installed block,
        the tracked file is untouched, and doctor says how to update it."""
        old = ("# Team rules\n\n<!-- agentic-project-scaffold-lite:start -->\nMark the inbox read "
               "(`inbox mark-read --cursor HEAD`).\n<!-- agentic-project-scaffold-lite:end -->\n\nUse tabs.\n")
        holder, root = git_project({"AGENTS.md": old, "README.md": "x\n"})
        self.addCleanup(holder.cleanup)
        install(root)
        override = (root / "AGENTS.override.md").read_text()
        self.assertNotIn("--cursor HEAD", override)
        self.assertIn("`head` number from that same `inbox list` result", override)
        self.assertIn("Use tabs.", override)
        self.assertEqual((root / "AGENTS.md").read_text(), old)
        report = json.loads(softory(root, "doctor").stdout)
        self.assertTrue(report["pass"], report)
        self.assertTrue(any("--cursor HEAD" in w and "scaffold-block.md" in w for w in report["warnings"]), report["warnings"])
        softory(root, "sync")
        self.assertNotIn("--cursor HEAD", (root / "AGENTS.override.md").read_text())
        self.assertEqual(git_status(root), "")

    def test_claude_local_reimports_agents_md(self) -> None:
        self.assertIn("@AGENTS.md", (self.root / "CLAUDE.local.md").read_text())

    def test_sync_picks_up_agents_md_changes(self) -> None:
        (self.root / "AGENTS.md").write_text("# Team rules\nUse spaces.\n")
        stale = json.loads(softory(self.root, "doctor", check=False).stdout)
        self.assertEqual([c["check"] for c in stale["checks"] if not c["pass"]], ["instructions_in_sync"])
        softory(self.root, "sync")
        self.assertIn("Use spaces.", (self.root / "AGENTS.override.md").read_text())
        self.assertTrue(json.loads(softory(self.root, "doctor").stdout)["pass"])


@needs_sources
class ExistingScaffoldTest(unittest.TestCase):
    """A project that already runs the scaffold and commits its block in AGENTS.md."""

    AGENTS = ("# Team\n\n<!-- agentic-project-scaffold-lite:start -->\nUse the CLI.\n"
              "<!-- agentic-project-scaffold-lite:end -->\n\nAvery reviews.\n")

    def setUp(self) -> None:
        self.holder, self.root = git_project({"AGENTS.md": self.AGENTS, "README.md": "x\n"})
        self.addCleanup(self.holder.cleanup)
        install(self.root)

    def test_scaffold_block_is_not_repeated(self) -> None:
        marker = "agentic-project-scaffold-lite:start"
        self.assertEqual((self.root / "AGENTS.override.md").read_text().count(marker), 1)
        local = (self.root / "CLAUDE.local.md").read_text()
        self.assertEqual(local.count(marker), 0)
        self.assertIn("@AGENTS.md", local)  # Claude still gets it, through the import
        self.assertEqual(git_status(self.root), "")


@needs_sources
class PreexistingScaffoldTest(unittest.TestCase):
    """A project that ran the scaffold before softory keeps it after uninstall."""

    def test_uninstall_leaves_the_projects_scaffold(self) -> None:
        from tests.helpers import SCAFFOLD_SRC, run

        holder, root = git_project()
        self.addCleanup(holder.cleanup)
        run([f"{SCAFFOLD_SRC}/scripts/install.sh", "--target", str(root), "--adapter", "sqlite"], root)
        with (root / ".gitignore").open("a") as ignore:
            ignore.write("/.agents/\n")  # as VaultRadar does
        run(["git", "add", ".gitignore", "AGENTS.md"], root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "scaffold"], root)
        self.assertEqual(install(root)["scaffold_found"], PINNED)
        result = json.loads(softory(root, "uninstall").stdout)
        self.assertTrue((root / ".agents/agentic-project-scaffold-lite/bin/coordination").is_file())
        self.assertIn(".agents/agentic-project-scaffold-lite (it was here before softory)", result["kept"])
        self.assertFalse((root / ".agents/softory").exists())
        self.assertEqual(git_status(root), "")


@needs_sources
@unittest.skipUnless(PREVIOUS_SRC, "set SOFTORY_SCAFFOLD_PREVIOUS_SRC to a scaffold 1.4.0 checkout")
class ScaffoldUpgradeTest(unittest.TestCase):
    """A project on an older 1.x scaffold, like Vault Radar on 1.4.0, moves to the pin with a backup first."""

    def test_upgrade_backs_up_then_keeps_every_record(self) -> None:
        from tests.helpers import run

        holder, root = git_project()
        self.addCleanup(holder.cleanup)
        run([f"{PREVIOUS_SRC}/scripts/install.sh", "--target", str(root), "--adapter", "sqlite"], root)
        run(["git", "add", ".gitignore", "AGENTS.md"], root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "scaffold"], root)
        old = coord(root, "version")["data"]["cli_version"]
        coord(root, "agent", "add", "--id", "owner", "--name", "Owner", "--role", "owner", "--actor-type", "human")
        coord(root, "agent", "add", "--id", "dev", "--name", "Dev", "--role", "builder", "--actor-type", "ai", "--actor", "owner")
        coord(root, "task", "create", "--id", "OLD-1", "--title", "Made before the upgrade", "--actor", "dev")

        result = install(root)
        self.assertEqual(result["scaffold_found"], old)
        self.assertTrue(Path(result["scaffold_backup"]).is_file())
        self.assertIn(f"pre-scaffold-{PINNED}-", result["scaffold_backup"])
        self.assertEqual(coord(root, "version")["data"]["cli_version"], PINNED)
        self.assertEqual(coord(root, "task", "show", "OLD-1")["data"]["title"], "Made before the upgrade")
        audited = coord(root, "audit", "list", "--action", "backup")["data"]
        self.assertEqual([row["actor"] for row in audited], ["owner"])
        self.assertNotIn("--cursor HEAD", (root / "AGENTS.override.md").read_text())  # 1.4.0's block, replaced
        self.assertEqual(git_status(root), "")


@needs_sources
class RefusalTest(unittest.TestCase):
    def test_refuses_non_git_directory(self) -> None:
        import tempfile

        from tests.helpers import REPO, SCAFFOLD_SRC, TRACKER_SRC, run

        with tempfile.TemporaryDirectory() as folder:
            result = run([str(REPO / "bin/softory"), "install", "--target", folder,
                          "--scaffold-src", SCAFFOLD_SRC or "", "--tracker-src", TRACKER_SRC or ""], REPO, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not_a_repo", result.stderr)

    def test_refuses_to_downgrade_a_newer_scaffold(self) -> None:
        from tests.helpers import REPO, SCAFFOLD_SRC, TRACKER_SRC, run

        for newer in ("2.0.0", "1.4.9"):
            with self.subTest(newer=newer):
                holder, root = git_project()
                self.addCleanup(holder.cleanup)
                (root / ".agents/agentic-project-scaffold-lite").mkdir(parents=True)
                (root / ".agents/agentic-project-scaffold-lite/VERSION").write_text(newer + "\n")
                result = run([str(REPO / "bin/softory"), "install", "--target", str(root),
                              "--scaffold-src", SCAFFOLD_SRC or "", "--tracker-src", TRACKER_SRC or ""], root, check=False)
                self.assertIn("scaffold_version_conflict", result.stderr)
                self.assertEqual((root / ".agents/agentic-project-scaffold-lite/VERSION").read_text(), newer + "\n")

    def test_refuses_tracked_claude_local(self) -> None:
        holder, root = git_project({"CLAUDE.local.md": "mine\n"})
        self.addCleanup(holder.cleanup)
        from tests.helpers import REPO, SCAFFOLD_SRC, TRACKER_SRC, run

        result = run([str(REPO / "bin/softory"), "install", "--target", str(root),
                      "--scaffold-src", SCAFFOLD_SRC or "", "--tracker-src", TRACKER_SRC or ""], root, check=False)
        self.assertIn("tracked_instruction_file", result.stderr)
        self.assertEqual(git_status(root), "")  # refused before writing anything


if __name__ == "__main__":
    unittest.main()
