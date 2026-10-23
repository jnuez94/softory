#!/bin/sh
# Install softory, agentic-project-scaffold-lite 1.4.0, and the task tracker
# into a git project, hidden from git through .git/info/exclude.
#
#   ./install.sh --target /path/to/project [--owner-name "Your Name"]
#
# Run ./install.sh --help for every option.
set -eu

command -v python3 >/dev/null 2>&1 || { echo "softory needs Python 3.10 or newer" >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "softory needs git" >&2; exit 1; }

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec python3 -I "$here/bin/softory" install "$@"
