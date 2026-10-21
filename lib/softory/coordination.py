"""Thin wrapper over the scaffold's coordination CLI.

Softory never opens the database. Every read and write goes through the CLI,
which keeps sole responsibility for validation, locking, and audit.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .errors import SoftoryError

MAX_PAGE = 500


class Coordination:
    """Run coordination CLI commands from a project root and parse their JSON."""

    def __init__(self, binary: Path, root: Path, session: str | None = None) -> None:
        self.binary = Path(binary)
        self.root = Path(root)
        self.session = session if session is not None else os.environ.get("COORDINATION_SESSION")

    def run(self, *args: str, session: bool = False) -> Any:
        """Run one command and return its ``data``, or raise ``SoftoryError``."""
        envelope = self.call(*args, session=session)
        if not envelope.get("ok"):
            error = envelope.get("error") or {}
            raise SoftoryError(
                error.get("message", "coordination command failed"),
                error.get("code", "coordination_error"),
                error.get("details"),
            )
        return envelope.get("data")

    def call(self, *args: str, session: bool = False) -> dict[str, Any]:
        """Run one command and return the raw envelope, failed or not."""
        if not self.binary.is_file():
            raise SoftoryError(f"Coordination CLI not found at {self.binary}", "not_installed")
        command = [str(self.binary)]
        if session:
            if not self.session:
                raise SoftoryError(
                    "No active session. Run: eval \"$(softory start <role>)\"",
                    "session_required",
                )
            command += ["--session", self.session]
        command += list(args)
        env = dict(os.environ)
        env.pop("COORDINATION_SESSION", None)  # only pass the session we were told to
        completed = subprocess.run(  # noqa: S603 - fixed binary, argument list, no shell
            command, cwd=self.root, env=env, capture_output=True, text=True, check=False
        )
        output = completed.stdout.strip() or completed.stderr.strip()  # errors go to stderr
        try:
            return json.loads(output)
        except json.JSONDecodeError as error:
            raise SoftoryError(
                f"Coordination CLI returned non-JSON output: {completed.stderr.strip()[:300]}",
                "coordination_error",
            ) from error

    def all_tasks(self, *filters: str) -> list[dict[str, Any]]:
        """Every task matching ``filters``, following pages to the end."""
        tasks: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.run(
                "task", "list", *filters, "--limit", str(MAX_PAGE), "--offset", str(offset)
            )
            tasks.extend(page)
            if len(page) < MAX_PAGE:
                return tasks
            offset += MAX_PAGE

    def task(self, task_id: str) -> dict[str, Any]:
        return self.run("task", "show", task_id)

    def agent_exists(self, agent_id: str) -> bool:
        envelope = self.call("agent", "show", agent_id)
        if envelope.get("ok"):
            return True
        if (envelope.get("error") or {}).get("code") == "not_found":
            return False
        raise SoftoryError(envelope["error"]["message"], envelope["error"]["code"])
