"""The roles, RACI, gates, and skills stay consistent with each other."""

from __future__ import annotations

import json
import re
import unittest

from tests.helpers import REPO

ROSTER = json.loads((REPO / "factory/roles/roster.json").read_text())
GATES = json.loads((REPO / "factory/governance/gates.json").read_text())
ROLE_IDS = {role["id"] for role in ROSTER["roles"]}
RACI = (REPO / "factory/governance/raci.md").read_text()


def raci_rows() -> list[list[str]]:
    rows = []
    for line in RACI.splitlines():
        if line.startswith("| ") and not line.startswith(("| Activity", "| ---")):
            rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


class RosterTest(unittest.TestCase):
    def test_the_six_named_roles(self) -> None:
        names = {role["id"]: (role["name"], role["title"]) for role in ROSTER["roles"]}
        self.assertEqual(names["greg"], ("Greg", "Product Manager"))
        self.assertEqual(names["darwin"], ("Darwin", "UX Designer"))
        self.assertEqual(names["quinn"], ("Quinn", "Principal Engineer"))
        self.assertTrue(names["jade"][1].startswith("Senior Software Engineer"))
        self.assertTrue(names["gold"][1].startswith("Senior Software Engineer"))
        self.assertEqual(names["toby"], ("Toby", "Security Engineer"))

    def test_recommended_harnesses(self) -> None:
        harness = {role["id"]: role["recommended_harness"] for role in ROSTER["roles"]}
        self.assertEqual({r for r, h in harness.items() if h == "codex"}, {"greg", "toby"})
        self.assertEqual({r for r, h in harness.items() if h == "claude"}, {"darwin", "quinn", "jade", "gold"})

    def test_every_role_has_all_three_boundaries(self) -> None:
        for role in ROSTER["roles"]:
            for field in ("decision_authority", "review_authority", "unavailable_for", "responsibilities"):
                self.assertTrue(role[field], f"{role['id']} lacks {field}")
            self.assertTrue((REPO / role["profile"]).is_file(), role["profile"])

    def test_lanes_do_not_overlap(self) -> None:
        lanes = [role["lane"] for role in ROSTER["roles"]]
        self.assertEqual(len(lanes), len(set(lanes)))


class RaciTest(unittest.TestCase):
    def test_exactly_one_accountable_per_row(self) -> None:
        for row in raci_rows():
            accountable = [cell for cell in row[1:] if "**A" in cell]
            self.assertEqual(len(accountable), 1, f"row {row[0]!r} has {len(accountable)} A")

    def test_columns_cover_every_role_and_owner(self) -> None:
        header = next(line for line in RACI.splitlines() if line.startswith("| Activity"))
        for name in ("Greg", "Darwin", "Quinn", "Jade", "Gold", "Toby", "Owner"):
            self.assertIn(name, header)


class GatesTest(unittest.TestCase):
    def test_reviewers_are_real_roles(self) -> None:
        reviewers = [r for unit in GATES["units"].values() for entry in unit["required_reviews"] for r in entry["reviewers"]]
        reviewers += [r for entry in GATES["tag_reviews"].values() for r in entry["reviewers"]]
        self.assertTrue(set(reviewers) <= ROLE_IDS, set(reviewers) - ROLE_IDS)

    def test_units_cover_the_three_sizes(self) -> None:
        self.assertEqual(set(GATES["units"]), {"epic", "story", "task", "bug"})

    def test_default_assignees_are_lane_owners(self) -> None:
        lanes = {role["lane"]: role["id"] for role in ROSTER["roles"]}
        for unit in ("task", "bug"):
            by_lane = GATES["units"][unit]["default_assignee_by_lane"]
            self.assertEqual(by_lane["frontend"], lanes["frontend"])
            self.assertEqual(by_lane["backend"], lanes["backend"])


class SkillsTest(unittest.TestCase):
    def test_frontmatter(self) -> None:
        for skill in sorted((REPO / "skills").iterdir()):
            text = (skill / "SKILL.md").read_text()
            match = re.match(r"^---\nname: (.+)\ndescription: (.+)\n---\n", text)
            self.assertIsNotNone(match, skill.name)
            assert match
            self.assertEqual(match.group(1), skill.name)
            self.assertLess(len(match.group(2)), 1024)

    def test_skills_named_in_profiles_exist(self) -> None:
        names = {p.name for p in (REPO / "skills").iterdir()}
        for profile in (REPO / "factory/roles").glob("*.md"):
            for name in re.findall(r"`(softory-[a-z-]+)`", profile.read_text()):
                self.assertIn(name, names, f"{profile.name} names {name}")

    def test_external_skill_catalog(self) -> None:
        data = json.loads((REPO / "external-skills.json").read_text())
        for skill in data["skills"]:
            self.assertIn(skill["source"], data["sources"])
            self.assertTrue(set(skill["roles"]) <= ROLE_IDS)

    def test_instruction_block_is_small(self) -> None:
        # Codex stops reading project docs at 32 KiB; keep softory's share small.
        self.assertLess(len((REPO / "factory/INSTRUCTIONS.md").read_bytes()), 6 * 1024)


class LinksTest(unittest.TestCase):
    def test_relative_markdown_links_resolve(self) -> None:
        for path in REPO.rglob("*.md"):
            if ".git" in path.parts:
                continue
            for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", path.read_text()):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                self.assertTrue((path.parent / target).exists(), f"{path.relative_to(REPO)} -> {target}")


if __name__ == "__main__":
    unittest.main()
