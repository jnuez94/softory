"""Locate the project root and the files softory reads from it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import BUNDLE_DIR, COORDINATION_BIN
from .errors import SoftoryError


class Project:
    """A project that has softory installed."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @classmethod
    def find(cls, start: Path | None = None) -> Project:
        """Walk up from ``start`` (default: cwd) to the first softory install."""
        here = (start or Path.cwd()).resolve()
        for candidate in (here, *here.parents):
            if (candidate / BUNDLE_DIR / "manifest.json").is_file():
                return cls(candidate)
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
        return self.load_json("governance/gates.json")

    def manifest(self) -> dict[str, Any]:
        path = self.bundle / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8"))

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
