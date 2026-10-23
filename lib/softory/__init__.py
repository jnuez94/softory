"""Softory: a software factory layered on agentic-project-scaffold-lite."""

from __future__ import annotations

__version__ = "0.2.0"

#: Folder, relative to a project root, that holds the installed softory bundle.
BUNDLE_DIR = ".agents/softory"
#: Folder, relative to a project root, that holds the scaffold's managed bundle.
SCAFFOLD_DIR = ".agents/agentic-project-scaffold-lite"
#: The coordination CLI the scaffold installs.
COORDINATION_BIN = SCAFFOLD_DIR + "/bin/coordination"
