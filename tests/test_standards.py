"""Standards the owner set in Tablet, carried into softory (0.6.1): compare options before choosing, Sage
looks for the simplest path before the build, no package for a review, a peer review rotation, and doctor
naming installed text someone edited."""

from __future__ import annotations

import json
import sys
import unittest

from tests.helpers import REPO, coord, git_project, install, needs_sources, softory
from tests.test_workflow import at_terminal

sys.path.insert(0, str(REPO / "lib"))
from softory import gate  # noqa: E402


class TextTest(unittest.TestCase):
    def read(self, name: str) -> str:
        return (REPO / name).read_text(encoding="utf-8")

    def test_design_choices_compare_at_least_three_options(self) -> None:
        for name in ("skills/softory-design/references/standard.md", "skills/softory-design/SKILL.md",
                     "skills/softory-architecture/SKILL.md", "skills/softory-product-spec/SKILL.md"):
            self.assertIn("at least three", self.read(name), name)
        for name in ("skills/softory-design", "skills/softory-architecture", "factory/roles"):
            for path in (REPO / name).rglob("*.md"):
                self.assertNotIn("most three", path.read_text(encoding="utf-8").lower(), path)

    def test_both_templates_keep_the_options_and_compare_by_requirement(self) -> None:
        for name in ("skills/softory-design/references/spec-template.md",
                     "skills/softory-architecture/references/adr-template.md"):
            text = self.read(name)
            self.assertIn("## Options considered", text, name)
            self.assertIn("## Requirements comparison", text, name)
            self.assertIn("stays after the choice", text, name)
            self.assertNotIn("Delete this section", text, name)

    def test_sage_looks_for_the_simplest_path_before_the_build(self) -> None:
        profile = self.read("factory/roles/sage-software-development-manager.md")
        for phrase in ("## Simplest path first", "first use", "whether it is needed", "to its source",
                       "Judge the options", "Greg", "Never add a checklist"):
            self.assertIn(phrase, profile)
        sage = next(r for r in json.loads(self.read("factory/roles/roster.json"))["roles"] if r["id"] == "sage")
        self.assertIn("simplest path", " ".join(sage["responsibilities"]))
        # Sage challenges; the owning role still decides.
        self.assertIn("the role that owns the call decides", self.read("factory/governance/boundaries.md"))

    def test_a_review_never_needs_a_package(self) -> None:
        self.assertIn("A review or trial never needs a package", self.read("factory/INSTRUCTIONS.md"))


class RotationTest(unittest.TestCase):
    def test_the_unit_number_picks_a_place_in_the_rotation(self) -> None:
        order = ["gold", "jade", "avery"]
        picked = [gate.ask(["jade", "gold", "avery"], {}, order, f"TASK-{n}") for n in (3, 4, 5)]
        self.assertEqual(picked, ["gold", "jade", "avery"])

    def test_builders_are_skipped_and_an_earlier_reviewer_keeps_the_unit(self) -> None:
        self.assertEqual(gate.ask(["gold", "avery"], {}, ["gold", "jade", "avery"], "BUG-7"), "avery")
        self.assertEqual(gate.ask(["gold", "avery"], {"gold": {"decision": "changes_requested"}},
                                  ["gold", "jade", "avery"], "BUG-7"), "gold")

    def test_no_rotation_uses_the_gates_order_and_no_candidate_asks_nobody(self) -> None:
        self.assertEqual(gate.ask(["jade", "gold"], {}, [], "TASK-2"), "jade")
        self.assertEqual(gate.ask(["jade", "gold"], {}, ["toby"], "TASK-3"), "gold")
        self.assertIsNone(gate.ask([], {}, [], "TASK-1"))


@needs_sources
class InstalledTest(unittest.TestCase):
    def setUp(self) -> None:
        self.holder, self.root = git_project()
        self.addCleanup(self.holder.cleanup)
        install(self.root)

    def test_reviewers_names_who_to_ask_from_the_owners_rotation(self) -> None:
        softory(self.root, "new", "story", "--title", "Ship it", "--actor", "greg")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "design", "--title", "Spec",
                "--actor", "quinn")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "infra", "--title", "Build",
                "--actor", "quinn")
        coord(self.root, "agent", "add", "--id", "avery", "--name", "Avery", "--role", "Reviewer", "--actor", "owner")
        at_terminal(self.root, "standin", "add", "avery", "--for", "jade")
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps({"review": {"rotation": ["avery", "jade"]}}))
        at_terminal(self.root, "charter", "approve", str(path), "--merge")
        rows = json.loads(softory(self.root, "reviewers", "TASK-2").stdout)["requirements"]
        peer = next(r for r in rows if r["why"].startswith("peer code review"))
        self.assertEqual(peer["reviewers"], ["jade", "avery"])  # gold built it; either may still review
        self.assertEqual(peer["ask"], "avery")  # TASK-2: place 0 of avery, jade
        design = json.loads(softory(self.root, "reviewers", "TASK-1").stdout)["requirements"]
        self.assertNotIn("ask", design[0])  # one candidate needs no pick

    def test_doctor_names_installed_text_someone_edited_without_failing(self) -> None:
        clean = json.loads(softory(self.root, "doctor").stdout)
        self.assertFalse([w for w in clean["warnings"] if "differ from softory" in w])
        for name in (".claude/skills/softory-design/SKILL.md", ".agents/softory/factory/templates/epic.md"):
            path = self.root / name
            path.chmod(0o644)
            path.write_text(path.read_text(encoding="utf-8") + "\nA local rule.\n", encoding="utf-8")
        report = json.loads(softory(self.root, "doctor").stdout)
        self.assertTrue(report["pass"])  # the gate doesn't read these, so work goes on
        warning = next(w for w in report["warnings"] if "differ from softory" in w)
        self.assertIn(".claude/skills/softory-design/SKILL.md", warning)
        self.assertIn(".agents/softory/factory/templates/epic.md", warning)
        install(self.root, "--owner-name", "Owner")  # a reinstall restores the release's text
        again = json.loads(softory(self.root, "doctor").stdout)
        self.assertFalse([w for w in again["warnings"] if "differ from softory" in w])


if __name__ == "__main__":
    unittest.main()
