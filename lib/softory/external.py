"""Pull recommended open-source skills at their pinned commits."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from . import gitlocal
from .errors import SoftoryError
from .install import SKILL_ROOTS, exclude_patterns
from .project import Project
from .sources import clone_at


def catalog(project: Project) -> dict[str, Any]:
    return json.loads((project.bundle / "external-skills.json").read_text(encoding="utf-8"))


def add(project: Project, names: list[str], recommended: bool) -> list[str]:
    """Install the named (or all recommended) external skills. Returns names added."""
    data = catalog(project)
    by_name = {skill["name"]: skill for skill in data["skills"]}
    wanted = [s["name"] for s in data["skills"] if s["recommended"]] if recommended else names
    unknown = [n for n in wanted if n not in by_name]
    if unknown or not wanted:
        raise SoftoryError(f"Unknown or no skills: {', '.join(unknown) or '(none)'}. See `softory skills list`.", "invalid_arguments")
    manifest = project.manifest()
    ours = set(manifest.get("skills", [])) | set(manifest.get("external_skills", []))
    with tempfile.TemporaryDirectory(prefix="softory-skills-") as scratch:
        clones: dict[str, Path] = {}
        for name in wanted:
            skill = by_name[name]
            source = data["sources"][skill["source"]]
            if skill["source"] not in clones:
                clones[skill["source"]] = clone_at(source["repository"], source["commit"], Path(scratch) / skill["source"].replace("/", "_"))
            origin = clones[skill["source"]] / skill["path"]
            if not (origin / "SKILL.md").is_file():
                raise SoftoryError(f"{name}: no SKILL.md at {skill['path']} in {skill['source']}", "not_found")
            for root in SKILL_ROOTS:
                destination = project.root / root / name
                if destination.exists() and name not in ours:
                    raise SoftoryError(f"{root}/{name} already exists and wasn't installed by softory", "skill_conflict")
                if destination.exists():
                    shutil.rmtree(destination)
                shutil.copytree(origin, destination)
                (destination / "SOURCE.txt").write_text(
                    f"{source['repository']} @ {source['commit']}\npath: {skill['path']}\nlicense: {source['license']}\n",
                    encoding="utf-8",
                )
    manifest["external_skills"] = sorted(set(manifest.get("external_skills", [])) | set(wanted))
    _save(project, manifest)
    return wanted


def _save(project: Project, manifest: dict[str, Any]) -> None:
    skills = manifest.get("skills", []) + manifest.get("external_skills", [])
    manifest["exclude_patterns"] = exclude_patterns(skills, manifest.get("owned_files", []))
    gitlocal.write_exclude_block(project.root, manifest["exclude_patterns"])
    (project.bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def listing(project: Project) -> str:
    data = catalog(project)
    installed = set(project.manifest().get("external_skills", []))
    rows = []
    for skill in data["skills"]:
        mark = "installed" if skill["name"] in installed else ("recommended" if skill["recommended"] else "optional")
        rows.append(f"{skill['name']:<30} {mark:<12} {skill['source']:<24} roles: {','.join(skill['roles'])}")
    return "\n".join(rows) + "\n"
