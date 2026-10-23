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

**Run the installer yourself.** It clones code from GitHub and runs it, so a harness with safety checks (Claude Code's auto mode, for example) blocks an agent from doing it, even when you've said yes in chat. Run the two commands above in your own terminal, then hand over to the agents. If you'd rather an agent ran them, add allow rules for the clone and `install.sh` to the project's `.claude/settings.local.json` first.

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
| `softory end [--session ID]` | Ends the session, so its claims don't go stale |
| `softory new epic\|story\|task\|bug --title ... [--parent ID] [--lane ...] [--tags ...]` | Creates a unit with the right tags, assignee, and parent link |
| `softory new bug --from <ID> --title ... [--blocks-source]` | Files a follow-up from a review: same story and lane, linked back to the source. The source waits for it only with `--blocks-source` |
| `softory new review --for <IDs> --title ...` | Keeps a review run as its own task, a record. It closes on the reviewer's verdict once every change it asks for has a follow-up task |
| `softory drop <ID> --reason ... [--superseded-by ID]` | Closes a unit nobody will build, as won't do or superseded, with a recorded decision |
| `softory stack <bottom> ... <top>` / `softory close <top> --stack` | Groups work built on other unfinished work, then closes the whole stack together, or none of it |
| `softory tree [ID] [--all]` | Shows the epic > story > task hierarchy |
| `softory queue` | Your claimed work, what you may close now, the reviews waiting on you, and your assigned work |
| `softory pending [role]` | Exits 0 if the role has something to do and 3 if not, without starting a session. For schedulers |
| `softory silent [--hours 12] [--notify]` | Exits 0 if any role has work waiting and no session for that long, and with `--notify` messages the owner once a day per role |
| `softory inbox` / `--mark-read N` / `softory message <ID>` | Unread messages and the number that marks exactly those read; one message by ID |
| `softory all <entity> list [filters]` | A coordination list command with every page, past the 500-row limit |
| `softory reviewers <ID>` | Who must review it, and where each review stands |
| `softory gate <ID>` | Whether it may close, with a reason for every check |
| `softory close <ID>` | Runs the gate, then moves it to done only if it passes |
| `softory adopt <ID> --unit task --parent STORY-n --lane ...` | Brings a task created before softory into a story. `--unit review` marks an older review run, reading what it reviewed from its `informs` links (or `--for <IDs>`) |
| `softory standin add <agent> --for toby [--task IDs] [--until YYYY-MM-DD]` | Owner only, at a terminal. Lets an existing agent act for softory roles, everywhere or on named tasks, until a date, and records the decision |
| `softory propose standin\|waiver ... --why ...` / `softory proposals` / `softory approve <ID>` | Agents ask; the owner approves at a terminal. A waiver lets one review check pass on one task |
| `softory ruling --title ... --decision ... --where ...` | Records a decision the owner made, under the owner's name, marked with who recorded it and where the owner said it |
| `softory feedback "<note>" [--task ID]` / `--list` | Records friction with softory itself in a hidden local log, for whoever maintains softory |
| `softory triage` | Lists finished work nobody closed, older review runs to adopt, sessions to end or restart, and silent roles |
| `softory worktree add <path> -b <branch> [--share .web/node_modules]` / `softory link [path]` | Creates a git worktree with softory linked in, or links an existing one. `--share` links more untracked paths, such as installed dependencies |
| `softory coord <args>` | Runs the coordination CLI against the main checkout's database, from any worktree |
| `softory tracker [--port N] [--open]` | Runs the web console on 127.0.0.1 |
| `softory skills list\|add [--recommended]` | Pulls open-source skills at pinned commits |
| `softory doctor` / `roles` / `sync` / `uninstall [--purge]` | Maintenance |

The CLI lives at `.agents/softory/bin/softory` inside the project. You can alias it as `softory`.

### Running roles on a schedule

A role on a timer usually wakes to nothing. In the Vault Radar pilot, 165 of Greg's 188 five-minute runs read the inbox and stopped. Put `softory pending` in front of the run so an idle role costs no model call:

```sh
cd ~/workspace/my-project && .agents/softory/bin/softory pending greg >/dev/null && codex exec "You are Greg. ..."
```

It exits 0 when the role has unread messages, something to close, or reviews or assigned work that changed since its last finished session started. So that a crashed or cut-short run can't strand work, any waiting work also counts once four hours pass without a run (`--retry-hours`). It exits 3 when there's nothing, or when the role already has a session that was active in the last 30 minutes.

To hear when a role stops running while work waits, schedule `softory silent` hourly. On macOS, with launchd or cron:

```sh
cd ~/workspace/my-project && .agents/softory/bin/softory silent --hours 12 --notify >/tmp/softory-silent.json \
  && osascript -e 'display notification "A role has gone quiet with work waiting. Run softory silent." with title "Softory"'
```

`--notify` also leaves a message in the owner's inbox, once a day per silent role.

### Upgrading

Pull softory and run the installer again over the project. It keeps the database, your stand-ins, and every agent, and rewrites only softory's own files:

```sh
git -C softory pull
./softory/install.sh --target /path/to/your/project --owner-name "Your Name"
```

Sessions started before an upgrade keep the old rules until they restart; `softory triage` lists them.

### Who changes the rules

The rules are softory's, not the project's. The installer makes `gates.json`, the role files, softory's code, and `local.json` read-only and records their hashes. If any of them changes, the gate fails every unit (`config_intact`) and `softory doctor` names the file, until the file is restored or you reinstall. A change to the rules for every project is a softory release.

Per-project exceptions are yours: a stand-in (`softory standin add`) or a waiver of one review check on one task. Both run only at a terminal, after you type yes, so an agent can't make them from its shell. Agents ask with `softory propose ... --why "..."`, which records a proposed decision and changes nothing; you run `softory approve PROP-n` (or `--reject`). This is a speed bump rather than a lock: an agent that fakes a terminal or edits the files is going around you on purpose, and the gate shows it.

## Projects that already have a team

Softory can join a project that already runs the scaffold, with its own agents and tasks. The installer keeps the database and every agent already registered, and adds only the roles that are missing. It doesn't repeat the scaffold block if the project's `AGENTS.md` already has it.

- **Tasks from before softory** keep the project's own process. `softory close` holds them to a minimum: evidence, and one accepted review from anyone but the builder. `softory adopt` moves one into a story so it gets the full gate.
- **Existing agents can stand in for a role.** `softory standin add avery --for jade,gold` lets Avery review wherever Jade or Gold would. Add `--task` to limit it to named tasks and `--until` to end it on a date. It's recorded as a decision and added to the instructions every agent reads. A role-wide stand-in never reviews the specialist's own work: when Toby wrote the threat model, Quinn reviews it, not Toby's stand-in, unless you scope a stand-in to that task.
- **Review runs kept as tasks become records.** `softory adopt <ID> --unit review` turns one into a review record. It closes on the reviewer's own verdict, with every requested change filed as a follow-up task, and nobody reviews it again.
- **Old "todo" tasks are often finished.** In the Vault Radar pilot, four of four sampled todo tasks were already fixed, merged, and accepted, but never closed. Run `softory triage` before planning new work.
- **Run the installer on the machine that runs the agents.** The coordination database uses SQLite's WAL mode, which isn't safe to share between a VM or container and the host through a mounted folder.

## Git worktrees

Softory's files are untracked, so a new git worktree has none of them: no instructions, no skills, no CLI. `softory worktree add <path> -b <branch>` creates a worktree and symlinks softory in. For a worktree made some other way, such as by Claude Code, run `softory link <path>` from the main checkout. The links are hidden by the same exclude rules. The database isn't linked, because the scaffold refuses a symlinked `.coordination`, so use `softory coord <args>` for coordination commands in a worktree. Codex reads instructions from the worktree's own root, so link the worktree before starting Codex in it.

## Uninstall

```sh
.agents/softory/bin/softory uninstall           # keeps .coordination (your history) and any scaffold you had before
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
