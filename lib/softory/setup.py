"""``softory setup``: the owner's one sitting, as a checklist softory checks."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from . import charter as charters
from . import perms, runner, verify
from .project import Project


def checklist(project: Project) -> dict[str, Any]:
    charter = charters.load(project)
    steps = []

    def step(name: str, done: bool, how: str) -> None:
        steps.append({"step": name, "done": bool(done), "how": "" if done else how})

    step("charter approved", charter.get("approved"),
         "Write your overrides to a file (start from `softory charter show`), then run "
         "`softory charter approve <file>` in a terminal.")
    step("vision written", charter.get("vision"), "Set `vision` in the charter: what Greg may plan without asking you.")
    step("tests command", charter["verify"]["command"],
         "Set `verify.command` (for example `npm test` or `pytest -q`), so the gate checks tests at each commit.")
    base = charter["git"]["base"]
    step("base branch", verify.git(project.root, "rev-parse", "--verify", "--quiet", base).returncode == 0,
         f"Set `git.base` to the branch work merges into; `{base}` doesn't exist here.")
    unscoped = perms.unscoped(charter)
    step("lane paths", not unscoped,
         f"Set `lanes` paths for {', '.join(unscoped)}, so Claude Code roles edit only their own lane.")
    step("paging", charter["paging"].get("command"),
         "Set `paging.command`, a shell command that reads $SOFTORY_TITLE and $SOFTORY_MESSAGE, for example "
         "`osascript -e \"display notification \\\"$SOFTORY_MESSAGE\\\" with title \\\"$SOFTORY_TITLE\\\"\"`, "
         "or a curl to a push service. Then test it with `softory digest --send`.")
    harnesses = {charters.model_for(charter, role, False)["harness"] for role in charter["run"]["roles"]}
    for name in sorted(harnesses):
        binary = charter["run"]["harnesses"][name][0]
        step(f"{name} installed", shutil.which(binary), f"Install `{binary}` and sign in, on this Mac.")
    step("branch protection", False,
         "Manual: protect the base branch on GitHub and require CI. softory can't check this from here.")
    plan = runner.schedule(project)
    state = runner.scheduler_state(project)
    step("schedule loaded", state["loaded"], "Last: turn off any other scheduler for this project (such as an "
         "app's scheduled check-ins), then run `softory setup --load-schedule` in a terminal"
         + ("" if sys.platform == "darwin" else f", or add this cron line: {plan['cron']}"))
    open_steps = [s for s in steps if not s["done"]]
    return {"done": len(steps) - len(open_steps), "of": len(steps), "steps": steps, "schedule": plan,
            "next": open_steps[0]["how"] if open_steps else "All set."}


def load_schedule(project: Project, confirm: Callable[[str], None]) -> dict[str, Any]:
    """Copy the runner's launchd job into ~/Library/LaunchAgents and load it, after the owner types yes."""
    if sys.platform != "darwin":
        return {"loaded": False, "why": "launchd is macOS only; add the cron line instead",
                "cron": runner.schedule(project)["cron"]}
    plan = runner.schedule(project)
    label = runner.scheduler_state(project)["label"]
    target = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    confirm(f"Load {label}: the runner will tick every 5 minutes and start roles that have work, inside the "
            "charter's budget. Turn off any other scheduler for this project first (such as an app's check-ins).")
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["launchctl", "unload", str(target)], capture_output=True, check=False)  # reload a changed job
    target.write_text(Path(plan["launchd"]).read_text(encoding="utf-8"), encoding="utf-8")
    loaded = subprocess.run(["launchctl", "load", str(target)], capture_output=True, text=True, check=False)
    return {"loaded": loaded.returncode == 0, "plist": str(target), "label": label,
            "error": loaded.stderr.strip()[:300] if loaded.returncode else None}
