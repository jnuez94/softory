# Softory

A software factory for Claude Code and Codex that uses the scaffold and tracker repos for coordination and human visibility. Install it into a project and a team of named agent roles builds it, with clear boundaries so they don't collide.

Softory is built on two existing projects. It installs both:

- [agentic-project-scaffold-lite](https://github.com/jnuez94/agentic-project-scaffold-lite) **1.4.0** is the harness-agnostic coordination layer: agents, sessions, tasks, reviews, decisions, escalations, and an audit log in a local SQLite database behind a deterministic CLI.
- [agentic-scaffold-project-task-tracker](https://github.com/jnuez94/agentic-scaffold-project-task-tracker) is a local web console over that database, for tracking decisions, tasks, reviews, escalations, and health.

On top of them, softory adds the team, the rules, and the craft.

## What you get

| | |
| --- | --- |
| **Roles** | Greg (Product Manager), Darwin (UX Designer), Quinn (Principal Engineer), Jade (Sr. SWE, frontend), Gold (Sr. SWE, backend and infra), and Toby (Security Engineer). Each has a profile collated from published role guidelines. See [factory/roles](factory/roles/README.md). |
| **Boundaries** | A [RACI matrix](factory/governance/raci.md) with exactly one accountable role per activity, plus [decision, review, and work boundaries](factory/governance/boundaries.md), lanes, flex rules for when overlap is allowed, and escalation paths. |
| **Units of work** | Epic (project) > story (feature) > task (function) or bug (fix), with templates, a definition of ready and done, and a [flow for each](factory/workflows/work-units.md). |
| **Skills** | Nine skills that load on demand, for Claude Code and Codex: operating loop, code quality, testing, code review, secure coding, design, product spec, architecture, and token economy. See [skills/](skills/). There's also a [catalog of open-source skills](docs/skill-sourcing.md) to pull instead of rebuilding. |
| **Gate** | `softory close` refuses to finish a unit until the required reviews are in, nobody reviewed their own work, dependencies and children are done, evidence exists, and the right role is closing. |

Model-agnostic: any role runs on any harness. The defaults recommend **Claude** for Darwin, Quinn, Jade, and Gold, and **Codex** for Greg and Toby, so acceptance and security review use a different model from the one that wrote the code.

## Requirements

Git, Python 3.10 or newer, and network access to GitHub at install time (or local checkouts of the two dependencies at their pinned commits).

## Install

```sh
git clone https://github.com/jnuez94/softory.git
./softory/install.sh --target /path/to/your/project --owner-name "Your Name"
```

The target must be the root of a git repository. The installer:

1. Clones scaffold 1.4.0 and the tracker at the commits pinned in [dependencies.json](dependencies.json). Use `--scaffold-src` and `--tracker-src` to use local checkouts instead.
2. Runs the scaffold's own installer with the SQLite backend.
3. Copies softory's factory, CLI, and tracker into `.agents/softory/`, and the skills into `.claude/skills/` (Claude Code) and `.agents/skills/` (Codex).
4. Writes the operating instructions where both harnesses read them (below).
5. Registers `owner` (you) and the six roles in the coordination database.
6. Hides all of it from git and checks that `git status` is unchanged.

Re-running it upgrades softory in place and keeps your coordination history.

## Hidden from git

Everything softory adds is local. Nothing shows in `git status`, and nothing can be committed by accident.

- Softory uses **`.git/info/exclude`**, not `.gitignore`. Exclude rules work the same way but live only in your local `.git` folder, so the project's history and other clones show no trace of the factory. Each clone runs the installer once.
- The scaffold's installer edits `.gitignore`. Softory restores the file byte for byte afterwards.
- Softory never edits a file the project tracks. If the project commits its own `AGENTS.md`, softory leaves it alone and writes `AGENTS.override.md`, which Codex reads instead. It holds a copy of your `AGENTS.md` plus softory's block, and `softory sync` refreshes it. For Claude Code, softory writes `CLAUDE.local.md`, which imports `@AGENTS.md` when your project relies on it.
- `softory doctor` checks all of this and lists every installed path.

## Use it

Open the project in Claude Code or Codex and tell the agent which role it is. The instructions it loads explain the rest.

```text
You are Greg. Write the epic for a daily to-do radar over my Obsidian vault, then its first stories.
You are Quinn. Break STORY-1 into tasks.
You are Jade. Pick up your next task.
You are Toby. Review whatever is waiting for security review.
```

Each role starts a session, which records the harness and model, and works through the coordination CLI. The commands they use, which you can use too:

| Command | Does |
| --- | --- |
| `softory start <role> [--harness codex] [--model m]` | Starts a session. Use it with `eval "$(...)"` |
| `softory new epic\|story\|task\|bug --title ... [--parent ID] [--lane ...] [--tags ...]` | Creates a unit with the right tags, assignee, and parent link |
| `softory tree [ID] [--all]` | Shows the epic > story > task hierarchy |
| `softory queue` | Your claimed work, the reviews waiting on you, and your assigned work |
| `softory reviewers <ID>` | Who must review it, and where each review stands |
| `softory gate <ID>` | Whether it may close, with a reason for every check |
| `softory close <ID>` | Runs the gate, then moves it to done only if it passes |
| `softory adopt <ID> --unit task --parent STORY-n --lane ...` | Brings a task created before softory into a story |
| `softory standin add <agent> --for jade,gold` | Lets an existing agent act for softory roles, and records the decision |
| `softory tracker [--port N] [--open]` | Runs the web console on 127.0.0.1 |
| `softory skills list\|add [--recommended]` | Pulls open-source skills at pinned commits |
| `softory doctor` / `roles` / `sync` / `uninstall [--purge]` | Maintenance |

The CLI lives at `.agents/softory/bin/softory` inside the project. You can alias it as `softory`.

## Projects that already have a team

Softory can join a project that already runs the scaffold, with its own agents and tasks. The installer keeps the database and every agent already registered, and adds only the roles that are missing. It doesn't repeat the scaffold block if the project's `AGENTS.md` already has it.

- **Tasks from before softory** keep the project's own process. `softory close` holds them to a minimum: evidence, and one accepted review from anyone but the builder. `softory adopt` moves one into a story so it gets the full gate.
- **Existing agents can stand in for a role.** `softory standin add avery --for jade,gold` lets Avery review wherever Jade or Gold would. It's recorded as a decision and added to the instructions every agent reads.
- **Run the installer on the machine that runs the agents.** The coordination database uses SQLite's WAL mode, which isn't safe to share between a VM or container and the host through a mounted folder.

## Uninstall

```sh
.agents/softory/bin/softory uninstall           # keeps .coordination (your history), still hidden
.agents/softory/bin/softory uninstall --purge   # removes everything
```

## Develop softory

```sh
SOFTORY_SCAFFOLD_SRC=../agentic-project-scaffold-lite \
SOFTORY_TRACKER_SRC=../agentic-scaffold-project-task-tracker \
python3 -m unittest discover -s tests -t .
```

Both checkouts must be at the pinned commits. Without the variables, the integration tests skip and the unit and governance tests still run. The governance tests check that every RACI row has exactly one accountable role, that every reviewer in `gates.json` is a real role, that the skills are well formed, and that every relative link resolves.

## Layout

```
factory/
  INSTRUCTIONS.md        the block every agent loads (kept small)
  roles/                 profiles and roster.json (what gets registered)
  governance/            raci.md, boundaries.md, gates.json
  workflows/             units of work and their flows
  templates/             epic, story, and task descriptions
skills/                  softory's nine skills
lib/softory/             the CLI and installer (Python, standard library only)
docs/                    skill-sourcing.md, gaps.md
dependencies.json        pinned scaffold and tracker commits
external-skills.json     pinned open-source skills
```

## Known gaps upstream

[docs/gaps.md](docs/gaps.md) lists what the scaffold and tracker don't do yet, and how softory works around it. The most important: the coordination CLI lets any actor close any task, so the gate holds only when agents close through `softory close`.

## License

MIT, copyright Joshua Nuez. Pulled open-source skills keep their own licenses, recorded in each skill's `SOURCE.txt`.
