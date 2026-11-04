"""How the owner gives direction: once at kickoff, then one line per new idea.

``softory kickoff`` writes Greg's interview prompt and prints the command that opens it in the owner's
harness. Greg asks about the vision, what is out of scope, the environment, and every account or
credential the plan will need, and writes the answers as a charter draft the owner approves with
``softory charter approve``. ``softory feature "<idea>"`` files the idea as a story for Greg to shape;
the runner wakes him.
"""

from __future__ import annotations

import json
import shlex
from typing import Any

from . import charter as charters
from .coordination import Coordination
from .errors import SoftoryError
from .project import Project
from .runstate import state_dir

MAX_TITLE = 100
KICKOFF_KEYS = ("vision", "out_of_scope", "environment", "epics", "verify", "lanes", "git", "paging")


def feature(project: Project, coord: Coordination, idea: str) -> dict[str, Any]:
    from .work import new_unit  # noqa: PLC0415 - work imports most of softory

    idea = " ".join(idea.split())
    if not idea:
        raise SoftoryError("Say what you want built", "invalid_arguments")
    title = idea if len(idea) <= MAX_TITLE else idea[: MAX_TITLE - 1].rsplit(" ", 1)[0] + "…"
    owner = project.roster()["owner"]["id"]
    made = new_unit(project, coord, "story", {
        "title": title, "actor": owner, "tags": "idea", "assignee": "greg",
        "description": f"The owner's idea, as given: {idea}\n\nGreg: shape it into a story inside the charter's "
                       "vision (criteria, an epic, --design if it has UI) or split it, then carry on. Raise an "
                       "escalation only if it falls outside the vision or the out-of-scope list."})
    made.pop("warning", None)
    return {**made, "next": "Greg picks it up on the runner's next tick."}


def kickoff(project: Project) -> dict[str, Any]:
    charter = charters.load(project)
    draft = project.root / ".git" / "softory-charter-draft.json"
    current = {k: charter.get(k) for k in KICKOFF_KEYS}
    prompt = (
        "You are Greg (greg), the product manager, running softory's kickoff with the owner, who is here. "
        "Interview them once, a few questions at a time, so the team can work for days without asking again. "
        "Cover: the vision (what you may plan without asking), what is out of scope, the environment (networks, "
        "accounts, devices, whether a desktop session stays unlocked, what is not available), every account, "
        "credential, paid tier, or sign-off any likely plan will need and whether they'll provide it, the test "
        "command, the base branch, the lanes' paths, and how to page them. Note which decisions they're happy "
        "for the team to take on its own. Then write the answers as JSON with only these keys: "
        f"{', '.join(KICKOFF_KEYS)} to {draft}, show it, and tell them to run: "
        f".agents/softory/bin/softory charter approve {draft} --merge\n\n"
        f"The charter now:\n{json.dumps(current, indent=2)}"
    )
    path = state_dir(project) / "kickoff-prompt.md"
    path.write_text(prompt + "\n", encoding="utf-8")
    pick = charters.model_for(charter, "greg", False)
    binary = charter["run"]["harnesses"].get(pick["harness"], ["claude"])[0]
    return {"prompt": str(path), "draft": str(draft),
            "run": f"{binary} \"$(cat {shlex.quote(str(path))})\"",
            "next": "Run that in a terminal at the project root, answer Greg's questions, then approve the draft."}
