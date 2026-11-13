"""Softory: a software factory layered on agentic-project-scaffold-lite."""

from __future__ import annotations

__version__ = "0.6.5"

#: Folder, relative to a project root, that holds the installed softory bundle.
BUNDLE_DIR = ".agents/softory"
#: Folder, relative to a project root, that holds the scaffold's managed bundle.
SCAFFOLD_DIR = ".agents/agentic-project-scaffold-lite"
#: Folder, relative to a project root, for everything softory writes while it runs: the run log, the
#: verify ledger, escalations, proposals, feedback, sessions. It sits beside the coordination database,
#: which every harness's sandbox already lets roles write, because sandboxes protect .agents/ (Codex).
STATE_DIR = ".coordination/softory"
#: The coordination CLI the scaffold installs.
COORDINATION_BIN = SCAFFOLD_DIR + "/bin/coordination"
