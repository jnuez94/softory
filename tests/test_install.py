"""Installing, re-installing, and uninstalling leave the project's git untouched."""

from __future__ import annotations

import json
import unittest

from tests.helpers import coord, git_project, git_status, install, needs_sources, softory


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
        again = install(self.root)
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

    def test_claude_local_reimports_agents_md(self) -> None:
        self.assertIn("@AGENTS.md", (self.root / "CLAUDE.local.md").read_text())

    def test_sync_picks_up_agents_md_changes(self) -> None:
        (self.root / "AGENTS.md").write_text("# Team rules\nUse spaces.\n")
        softory(self.root, "sync")
        self.assertIn("Use spaces.", (self.root / "AGENTS.override.md").read_text())


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
