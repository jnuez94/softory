# Softory

A software factory for Claude Code and Codex that uses the scaffold and tracker repos for coordination and human visibility. Install it into a project and a team of named agent roles builds it, with clear boundaries so they don't collide.

Softory is built on two existing projects. It installs both:

- [agentic-project-scaffold-lite](https://github.com/jnuez94/agentic-project-scaffold-lite) **1.4.1** is the harness-agnostic coordination layer: agents, sessions, tasks, reviews, decisions, escalations, and an audit log in a local SQLite database behind a deterministic CLI.
- [agentic-scaffold-project-task-tracker](https://github.com/jnuez94/agentic-scaffold-project-task-tracker) is a local web console over that database, for tracking decisions, tasks, reviews, escalations, and health.

On top of them, softory adds the team, the rules, and the craft.

## What you get

| | |
| --- | --- |
| **Roles** | Greg (Product Manager), Darwin (UX Designer), Quinn (Principal Engineer), Jade (Sr. SWE, frontend), Gold (Sr. SWE, backend and infra), and Toby (Security Engineer). Each has a profile collated from published role guidelines. See [factory/roles](factory/roles/README.md). |
| **Boundaries** | A [RACI matrix](factory/governance/raci.md) with exactly one accountable role per activity, plus [decision, review, and work boundaries](factory/governance/boundaries.md), lanes, flex rules for when overlap is allowed, and escalation paths. |
| **Units of work** | Epic (project) > story (feature) > task (function) or bug (fix), with templates, a definition of ready and done, and a [flow for each](factory/workflows/work-units.md). |
| **Skills** | Eight skills that load on demand, for Claude Code and Codex: operating loop, code quality, testing, code review, secure coding, design, product spec, and architecture. See [skills/](skills/). There's also a [catalog of open-source skills](docs/skill-sourcing.md) to pull instead of rebuilding. |
| **Gate** | `softory close` refuses to finish a unit until the required reviews are in, nobody reviewed their own work, dependencies and children are done, evidence exists, and the right role is closing. |

Model-agnostic: any role runs on any harness. The defaults pick each role's model by the benchmark that fits its work: **Claude Opus 5.5** for Darwin, Quinn, Jade, and Gold (agent coding and web design), and **Codex with GPT-6 Astra** for Toby and Greg (security review and acceptance), so the gates that decide "safe" and "done" use a different model from the builders. [docs/models.md](docs/models.md) has the benchmarks and prices.

## Requirements

Git, Python 3.10 or newer, and network access to GitHub at install time (or local checkouts of the two dependencies at their pinned commits).

## Install

```sh
git clone https://github.com/jnuez94/softory.git
./softory/install.sh --target /path/to/your/project --owner-name "Your Name"
```

The target must be the root of a git repository. The installer:

1. Clones scaffold 1.4.1 and the tracker at the commits pinned in [dependencies.json](dependencies.json). Use `--scaffold-src` and `--tracker-src` to use local checkouts instead.
2. Runs the scaffold's own installer with the SQLite backend. A project on an older 1.x scaffold, such as 1.4.0, is upgraded in place after a backup to `.coordination/backups/pre-scaffold-<version>-<time>.sqlite3`. A newer scaffold is refused.
3. Copies softory's factory, CLI, and tracker into `.agents/softory/`, and the skills into `.claude/skills/` (Claude Code) and `.agents/skills/` (Codex).
4. Writes the operating instructions where both harnesses read them (below).
5. Registers `owner` (you) and the six roles in the coordination database.
6. Hides all of it from git and checks that `git status` is unchanged.

Re-running it upgrades softory in place and keeps your coordination history.

**Run the installer yourself.** It clones code from GitHub and runs it, so a harness with safety checks (Claude Code's auto mode, for example) blocks an agent from doing it, even when you've said yes in chat. Run the two commands above in your own terminal, then hand over to the agents. If you'd rather an agent ran them, add allow rules for the clone and `install.sh` to the project's `.claude/settings.local.json` first.

## Hidden from git

Everything softory adds is local. Nothing shows in `git status`, and nothing can be committed by accident.

- Softory uses **`.git/info/exclude`**, not `.gitignore`. Exclude rules work the same way but live only in your local `.git` folder, so the project's history and other clones show no trace of the factory. Each clone runs the installer once.
- Softory runs the scaffold's installer with `--no-gitignore`, so it doesn't touch `.gitignore`.
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

Each role starts a session, which records the harness and model, and works through the coordination CLI. The commands you'll use most:

| Command | Does |
| --- | --- |
| `softory tree [ID]` / `softory queue` | The epic > story > task hierarchy; a role's claimed, closable, review, and assigned work |
| `softory new epic\|story\|task\|bug\|review ...` | Creates a unit with the right tags, assignee, and parent link |
| `softory gate <ID>` / `softory close <ID>` | Whether a unit may close, with a reason for every check; close it only if it passes |
| `softory triage` | Finished work nobody closed, older review runs to adopt, stale sessions, and silent roles |
| `softory proposals` / `softory approve <ID> \| --all` | What agents asked you for (stand-ins, waivers, review adoptions); apply them at a terminal |
| `softory standin add <agent> --for <roles> [--task IDs] [--until date]` | Lets an existing agent act for softory roles (owner only, at a terminal) |
| `softory charter show` / `charter approve <file>` | The settings unattended runs follow; approve yours once, at a terminal |
| `softory digest` / `usage` / `pause` / `resume` | What needs you; today's runs against the budget; stop and start unattended runs |
| `softory tracker [--port N] [--open]` | The web console on 127.0.0.1 |
| `softory doctor` | Checks the installation and that nothing leaks into git |

`softory --help` lists every command, and `softory <command> --help` its options.

The CLI lives at `.agents/softory/bin/softory` inside the project. You can alias it as `softory`.

### Running unattended

Softory 0.4.0 runs the team without you up to a pull request. You merge and deploy. Set it up once:

1. Run `softory setup`. It lists each step and checks the ones it can.
2. Write the settings you want to change to a file, starting from `softory charter show`: your `vision`, `verify.command` (your test command), `lanes` paths, `paging.command`, and the `budget`. Approve it in a terminal with `softory charter approve <file>`.
3. Protect your base branch on GitHub and require CI.
4. Load the runner: `softory schedule` writes a launchd job (and prints a cron line) that runs `softory run` every five minutes.

Each tick starts a role only when it has work, is under today's budget, and isn't paused or already running. The budget counts runs and minutes, not dollars, so it holds whatever a model costs: by default 24 runs and 120 minutes a day per role, 30 minutes a run, and tighter for the reviewing roles (Greg 15 minutes a run and 60 a day, Darwin and Toby 20 and 60). `budget.roles` overrides any cap for one role. At 80% you see it in the digest; at 100% the role stops until tomorrow and you're paged. Optional dollar caps sit beside them: `usd_per_run` (Claude Code stops itself there) and `usd_per_role_per_day`, counted from the cost each run reports; both are off at 0.

Each run is shaped to waste as little as possible:

- **Reviewers wake for tested work, in batches.** With `verify.command` set, a reviewer isn't woken for a unit until `softory verify` passed at its commit; the builder is woken to run or fix the tests instead. A reviewer then wakes once `review_batch.min` reviews wait (default 2) or the oldest has waited `review_batch.max_wait_minutes` (default 60), and clears all of them in one run. Keep the tick at five minutes: a tick with nothing to do calls no model.
- **The prompt carries the work.** It lists what is waiting and, for up to five units, the title, acceptance criteria, the changes reviewers asked for, and the files the commit touched, so the agent doesn't spend its first turns looking them up. The rules come first and stay the same between runs, so the provider's prompt cache reuses them.
- **Effort fits the job.** A run that only has reviews, closes, or messages is a review run (`effort.review`, default medium); anything else is a build run (`effort.build`, default high). `models.<role>.effort` overrides either for one role.
- **Real tokens and cost.** Claude Code runs with `--output-format json` and Codex with `--json`; softory reads their usage report and logs input, cached, and output tokens and dollars per run (Codex's dollars are estimated from the charter's `prices`). `softory usage` shows today's totals per role.
 Claude Code roles get a settings file that allows edits only in their lane's paths; Codex runs in its workspace-write sandbox. Either way, the gate's `lane_paths` check fails a diff outside the lane, and `verified` needs `softory verify` to have passed at the commit.

A task that has had `task_caps.escalate_model_after` rounds of requested changes runs on the role's stronger model next time. At `review_rounds` it stops and goes to your digest. Pages go out at once for a unit closed without the gate or a role over budget, outside quiet hours; everything else waits for the daily digest. `softory pause` stops everything, and only you can `softory resume`.

### Upgrading

Pull softory and run the installer again over the project. It keeps the database, your stand-ins, and every agent, and rewrites only softory's own files:

```sh
git -C softory pull
./softory/install.sh --target /path/to/your/project --owner-name "Your Name"
```

Sessions started before an upgrade keep the old rules until they restart; `softory triage` lists them.

The installer replaces the coordination CLI too when softory pins a newer scaffold, so upgrade between runs:

1. Run `softory pause`, and let running sessions finish or end them.
2. Run the installer. When it upgrades the scaffold it backs the database up first and prints the path as `scaffold_backup`.
3. Check `.agents/softory/bin/softory doctor`, then `softory resume`.

If something looks wrong afterwards, restore the backup with no sessions active:

```sh
.agents/agentic-project-scaffold-lite/bin/coordination restore --input <scaffold_backup> --actor owner --force
```

Scaffold 1.4.0 and 1.4.1 share schema version 1, so either CLI can restore it.

### Who changes the rules

The rules are softory's, not the project's. The installer makes `gates.json`, the role files, softory's code, and `local.json` read-only and records their hashes. If any of them changes, the gate fails every unit (`config_intact`) and `softory doctor` names the file, until the file is restored or you reinstall. A change to the rules for every project is a softory release.

Per-project exceptions are yours: a stand-in (`softory standin add`) or a waiver of one review check on one task. Both run only at a terminal, after you type yes, so an agent can't make them from its shell. Agents ask with `softory propose ... --why "..."`, which records a proposed decision and changes nothing; you run `softory approve PROP-n`, or `softory approve --all` for every waiting review adoption (add `--reject` to refuse). `--all` lists anything that doesn't look like a review run first, and never includes stand-ins or waivers. This is a speed bump rather than a lock: an agent that fakes a terminal or edits the files is going around you on purpose, and the gate shows it.

## Projects that already have a team

Softory can join a project that already runs the scaffold, with its own agents and tasks. The installer keeps the database and every agent already registered, and adds only the roles that are missing. It doesn't repeat the scaffold block if the project's `AGENTS.md` already has it.

- **Tasks from before softory** keep the project's own process. `softory close` holds them to a minimum: evidence, and one accepted review from anyone but the builder. `softory adopt` moves one into a story so it gets the full gate.
- **Existing agents can stand in for a role.** `softory standin add avery --for jade,gold` lets Avery review wherever Jade or Gold would. Add `--task` to limit it to named tasks and `--until` to end it on a date. It's recorded as a decision and added to the instructions every agent reads. A role-wide stand-in never reviews the specialist's own work: when Toby wrote the threat model, Quinn reviews it, not Toby's stand-in, unless you scope a stand-in to that task.
- **Review runs kept as tasks become records.** `softory adopt <ID> --unit review` asks the owner to turn one into a review record, and the owner approves every waiting one with `softory approve --all`. A record closes on the reviewer's own verdict, with every requested change filed as a follow-up task, and nobody reviews it again.
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
skills/                  softory's eight skills
lib/softory/             the CLI and installer (Python, standard library only)
docs/                    models.md, sources.md, skill-sourcing.md, gaps.md
dependencies.json        pinned scaffold and tracker commits
external-skills.json     pinned open-source skills
```

## Known gaps upstream

[docs/gaps.md](docs/gaps.md) lists what the scaffold and tracker don't do yet, and how softory works around it. The most important: the coordination CLI lets any actor close any task, so the gate holds only when agents close through `softory close`.

## License

MIT, copyright Joshua Nuez. Pulled open-source skills keep their own licenses, recorded in each skill's `SOURCE.txt`.
