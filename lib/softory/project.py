"""Locate the project root and the files softory reads from it."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from typing import Any

from . import BUNDLE_DIR, COORDINATION_BIN, grants
from .errors import SoftoryError
from .gitlocal import main_checkout

#: Bundle folders whose files are softory's rules and code. The installer
#: records their hashes and makes them read-only; the gate fails closed if
#: they change. local.json (the owner's stand-ins and waivers) is checked too.
PROTECTED_DIRS = ("factory/governance", "factory/roles", "lib/softory", "bin")


class Project:
    """A project that has softory installed."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @classmethod
    def find(cls, start: Path | None = None) -> Project:
        """The softory install for ``start`` (default: cwd).

        Walks up to the first install. In a linked git worktree, where the
        bundle is a symlink or missing, it answers with the main checkout, so
        every command uses the one coordination database.
        """
        here = (start or Path.cwd()).resolve()
        for candidate in (here, *here.parents):
            bundle = candidate / BUNDLE_DIR
            if (bundle / "manifest.json").is_file():
                return cls(bundle.resolve().parents[1])
        main = main_checkout(here)
        if main is not None and (main / BUNDLE_DIR / "manifest.json").is_file():
            return cls(main)
        raise SoftoryError(
            "No softory installation found here or in any parent directory.",
            "not_installed",
        )

    @property
    def bundle(self) -> Path:
        return self.root / BUNDLE_DIR

    @property
    def coordination_bin(self) -> Path:
        return self.root / COORDINATION_BIN

    def factory_file(self, relative: str) -> Path:
        return self.bundle / "factory" / relative

    def load_json(self, relative: str) -> Any:
        path = self.factory_file(relative)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SoftoryError(f"Cannot read {path}: {error}", "configuration_error") from error

    def roster(self) -> dict[str, Any]:
        return self.load_json("roles/roster.json")

    def gates(self) -> dict[str, Any]:
        """gates.json plus this project's stand-ins and waivers, today's date, and the integrity check."""
        gates = self.load_json("governance/gates.json")
        settings = self.local()
        gates["stand_ins"] = grants.normalize_stand_ins(settings.get("stand_ins"))
        gates["waivers"] = grants.normalize_waivers(settings.get("waivers"))
        gates["today"] = grants.today()
        changed = self.integrity_changes()
        if changed is not None:
            gates["integrity"] = {"changed": changed}
        return gates

    def stand_ins(self) -> list[dict[str, Any]]:
        return grants.normalize_stand_ins(self.local().get("stand_ins"))

    @property
    def local_path(self) -> Path:
        """Settings for this project only. Upgrades never overwrite them."""
        return self.bundle / "local.json"

    def local(self) -> dict[str, Any]:
        if not self.local_path.is_file():
            return {}
        try:
            return json.loads(self.local_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SoftoryError(f"Cannot read {self.local_path}: {error}", "configuration_error") from error

    def save_local(self, settings: dict[str, Any]) -> None:
        """Write local.json and record its hash. Refuses if it was edited by hand since softory last wrote it."""
        if "local.json" in (self.integrity_changes() or []):
            raise SoftoryError(
                f"{self.local_path} was edited outside softory. Restore it, or reinstall softory to accept it as is.",
                "configuration_tampered",
            )
        write_protected(self.local_path, json.dumps(settings, indent=2, sort_keys=True) + "\n")
        manifest = self.manifest()
        if "integrity" in manifest:
            manifest["integrity"]["local.json"] = file_hash(self.local_path)
            self.save_manifest(manifest)

    def manifest(self) -> dict[str, Any]:
        path = self.bundle / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def save_manifest(self, manifest: dict[str, Any]) -> None:
        write_protected(self.bundle / "manifest.json", json.dumps(manifest, indent=2) + "\n")

    def proposals_path(self) -> Path:
        """Changes agents propose for the owner to approve. Proposing grants nothing."""
        return self.bundle / "proposals.json"

    def integrity_changes(self) -> list[str] | None:
        """Protected files that differ from the install, or None for an install from before 0.3.0."""
        recorded = self.manifest().get("integrity")
        if recorded is None:
            return None
        current = integrity_hashes(self.bundle)
        names = sorted(set(recorded) | set(current))
        return [name for name in names if recorded.get(name) != current.get(name)]

    def role_ids(self) -> list[str]:
        roster = self.roster()
        return [roster["owner"]["id"], *(role["id"] for role in roster["roles"])]

    def role(self, role_id: str) -> dict[str, Any]:
        roster = self.roster()
        if role_id == roster["owner"]["id"]:
            return roster["owner"]
        for role in roster["roles"]:
            if role["id"] == role_id:
                return role
        raise SoftoryError(
            f"Unknown role {role_id!r}. Known roles: {', '.join(self.role_ids())}",
            "invalid_arguments",
        )


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def integrity_hashes(bundle: Path) -> dict[str, str]:
    """The hash of every protected file in an installed bundle, by relative path."""
    hashes = {}
    for folder in PROTECTED_DIRS:
        for path in sorted((bundle / folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                hashes[path.relative_to(bundle).as_posix()] = file_hash(path)
    if (bundle / "local.json").is_file():
        hashes["local.json"] = file_hash(bundle / "local.json")
    return hashes


def make_read_only(path: Path) -> None:
    """Drop every write bit. Editing it then takes a deliberate chmod first."""
    mode = path.stat().st_mode
    path.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def write_protected(path: Path, text: str) -> None:
    """Rewrite a file softory keeps read-only, and make it read-only again."""
    if path.exists():
        path.chmod(path.stat().st_mode | stat.S_IWUSR)
    path.write_text(text, encoding="utf-8")
    make_read_only(path)
