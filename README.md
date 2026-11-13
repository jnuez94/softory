# Softory

A software factory for Claude Code and Codex that uses the scaffold and tracker repos for coordination and human visibility. Install it into a project and a team of named agent roles builds it, with clear boundaries so they don't collide.

Softory is built on two existing projects. It installs both:

- [agentic-project-scaffold-lite](https://github.com/jnuez94/agentic-project-scaffold-lite) **1.4.2** is the harness-agnostic coordination layer: agents, sessions, tasks, reviews, decisions, escalations, and an audit log in a local SQLite database behind a deterministic CLI.
- [agentic-scaffold-project-task-tracker](https://github.com/jnuez94/agentic-scaffold-project-task-tracker) is a local web console over that database, for tracking decisions, tasks, reviews, escalations, and health.

On top of them, softory adds the team, the rules, and the craft.

## What you get

| | |
| --- | --- |
| **Roles** | Greg (Product Manager), Darwin (UX Designer), Quinn (Principal Engineer), Jade (Sr. SWE, frontend), Gold (Sr. SWE, backend and infra), Toby (Security Engineer), and Sage (Software Development Manager, who keeps the delivery process simple). Each has a profile collated from published role guidelines. See [factory/roles](factory/roles/README.md). |
| **Boundaries** | A [RACI matrix](factory/governance/raci.md) with exactly one accountable role per activity, plus [decision, review, and work boundaries](factory/governance/boundaries.md), lanes, flex rules for when overlap is allowed, and escalation paths. |
| **Units of work** | Epic (project) > story (feature) > task (function) or bug (fix), plus releases, with templates, a definition of ready and done, and a [flow for each](factory/workflows/work-units.md). |
| **Skills** | Eight skills that load on demand, for Claude Code and Codex: operating loop, code quality, testing, code review, secure coding, design, product spec, and architecture. See [skills/](skills/). There's also a [catalog of open-source skills](docs/skill-sourcing.md) to pull instead of rebuilding. |
| **Gate** | `softory close` refuses to finish a unit until the required reviews are in, nobody reviewed their own work, dependencies and children are done, evidence exists, no secret was committed, and the right role is closing. The scaffold enforces the basics too, so a raw close can't skip them. |
| **Shipping** | With `merge.by softory`, softory merges finished units onto the base only when its tests pass there, keeps the base green, deploys each merge to staging with a smoke test, and gates releases. Production stays yours. |

Model-agnostic: any role runs on any harness. The defaults pick each role's model by the benchmark that fits its work: **Claude Opus 5.5** for Darwin, Quinn, Jade, Gold, and Sage (agent coding, web design, and process), and **Codex with GPT-6 Astra** for Toby and Greg (security review and acceptance), so the gates that decide "safe" and "done" use a different model from the builders. [docs/models.md](docs/models.md) has the benchmarks and prices.

## Requirements

Git, Python 3.10 or newer, and network access to GitHub at install time (or local checkouts of the two dependencies at their pinned commits).

## Install

```sh
git clone https://github.com/jnuez94/softory.git
./softory/install.sh --target /path/to/your/project --owner-name "Your Name"
```

The target must be the root of a git repository. The installer:

1. Clones scaffold 1.4.2 and the tracker at the commits pinned in [dependencies.json](dependencies.json). Use `--scaffold-src` and `--tracker-src` to use local checkouts instead.
2. Runs the scaffold's own installer with the SQLite backend, and turns on its strict closure and dependency policies in `.coordination/config.yml`. A project on an older 1.x scaffold, such as 1.4.1, is upgraded in place after a backup to `.coordination/backups/pre-scaffold-<version>-<time>.sqlite3`. A newer scaffold is refused.
3. Copies softory's factory, CLI, and tracker into `.agents/softory/`, and the skills into `.claude/skills/` (Claude Code) and `.agents/skills/` (Codex).
4. Writes the operating instructions where both harnesses read them (below).
5. Registers `owner` (you) and the seven roles in the coordination database.
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

Each role starts a session, which records the harness and model, and works through the coordination CLI. The commands they use, which you can use too:

| Command | Does |
| --- | --- |
| `softory start <role> [--harness codex] [--model m]` | Starts a session. Use it with `eval "$(...)"`. Without `--harness` or `--model`, the charter's choice for the role is recorded. Softory also remembers the session for the role, so a harness that runs each command in a fresh shell only needs `--actor <role>` on later commands |
| `softory end [--session ID] [--actor role]` | Ends the session, so its claims don't go stale |
| `softory new epic\|story\|task\|bug --title ... [--parent ID] [--lane ...] [--tags ...]` | Creates a unit with the right tags, assignee, and parent link. Lanes: `frontend`, `backend`, `infra`, and `design` (Darwin builds, Greg reviews) |
| `softory new story ... --design` | Also files the story's `lane:design` task for Darwin, so design starts before Quinn's breakdown |
| `softory new bug --type functional\|visual [--found-at stage] ...` | A bug says what kind of finding it is and where it was found (`build`, `verify`, `review`, `acceptance`, `staging`, `production`), so escaped defects can be counted |
| `softory new bug --type ... --from <ID> --title ... [--blocks-source]` | Files a follow-up from a review: same story and lane, linked back to the source. The source waits for it only with `--blocks-source` |
| `softory new review --for <IDs> --title ...` | Keeps a review run as its own task, a record. It closes on the reviewer's verdict once every change it asks for has a follow-up task |
| `softory new release --title ... [--commit sha]` | Opens a release of the base's head (or the commit given). It closes when Toby and Quinn accepted it, it has a rollback plan (`softory report <ID> <file> --type rollback`), and every target but production passed at its commit |
| `softory drop <ID> --reason ... [--superseded-by ID] [--withdrawn]` | Closes a unit nobody will build, as won't do or superseded, with a recorded decision. `--withdrawn` marks a bug that turned out not to be a defect |
| `softory stack <bottom> ... <top>` / `softory close <top> --stack` | Groups work built on other unfinished work, then closes the whole stack, or none of it if any member fails its gate, tests and lane included |
| `softory tree [ID] [--all]` | Shows the epic > story > task hierarchy |
| `softory queue` | Your claimed work, what you may close now, the reviews waiting on you, your assigned work, unread messages sent to you, the verify queue, and for Quinn the feasibility checks that are due |
| `softory pending [role]` | Exits 0 if the role has something to do and 3 if not, without starting a session. Its `state` says `work`, `running`, `paused`, or `idle`. The runner uses it each tick, and a session you opened uses it to check on itself |
| `softory silent [--hours 12]` | Exits 0 if any role has work waiting and no session for that long. The digest lists these roles too |
| `softory inbox` / `--mark-read N` / `softory message <ID>` | Unread messages and the number that marks exactly those read; one message by ID |
| `softory all <entity> list [filters]` | A coordination list command with every page, past the 500-row limit |
| `softory handoff <ID>` | Moves your claimed unit to review once it has evidence and, for a `ui` unit, its check against the design reference. Refuses while untracked files that appeared during your claim sit in the main checkout |
| `softory report <ID> <file> [--type T] [--keep]` | Files a report or screenshot under `.coordination/softory/evidence/<ID>/` and records it as evidence. An untracked file is moved, so the main checkout stays clean |
| `softory workspace <role> [commit]` | The role's reusable checkout of a commit for reviews, with `verify.share` folders linked from the main checkout. A worktree where git allows it, a snapshot where a sandbox protects `.git` |
| `softory reviewers <ID>` | Who must review it, where each review stands, and who to `ask` when several may give it |
| `softory gate <ID>` | Whether it may close, with a reason for every check |
| `softory close <ID>` / `close --ready` | Runs the gate, then moves it to done only if it passes. `--ready` closes every unit you may close that passes now |
| `softory commit <ID> <sha> [--base <sha>]` | Records the commit a unit delivered by its full hash, with its base kept apart, so `verify` tests the right one |
| `softory supersede <ID> <evidence> --reason ...` | Retracts a wrong evidence row (its adder, Quinn, or the owner). The row and its audit stay, with the reason on the retraction; the gate and `verify` read past it |
| `softory escalate --issue ... --ask "...?" [--tasks IDs] [--owner who]` | Raises an escalation, to the owner by default. Refuses text the owner can't read at a glance: more than one question, too long, or words fused with numbers |
| `softory adopt <ID> --unit task --parent STORY-n --lane ...` | Brings a task created before softory into a story. `--unit review` asks the owner to mark an older review run as a record, reading what it reviewed from its `informs` links (or `--for <IDs>`) |
| `softory standin add <agent> --for toby [--task IDs] [--until YYYY-MM-DD]` | Owner only, at a terminal. Lets an existing agent act for softory roles, everywhere or on named tasks, until a date, and records the decision |
| `softory propose standin\|waiver ... --why ...` / `softory proposals` / `softory approve <ID> \| --all` | Agents ask (review adoptions ask too); the owner approves at a terminal. A waiver lets one review check pass on one task |
| `softory ruling --title ... --decision ... --where ... [--review ID] [--escalation ESC]` | Records a decision the owner made, under the owner's name, marked with who recorded it and where the owner said it. `--review` also records it as the owner's accepted review of that unit, and `--escalation` closes that open escalation with it; the digest lists both |
| `softory feedback "<note>" [--task ID]` / `--list` | Records friction with softory itself in a hidden local log, for whoever maintains softory |
| `softory triage` | Lists finished work nobody closed, older review runs to adopt, sessions to end or restart, and silent roles |
| `softory worktree add <path> -b <branch> [--share .web/node_modules]` / `softory link [path]` | Creates a git worktree with softory linked in, or links an existing one. `--share` links more untracked paths, such as installed dependencies |
| `softory coord <args>` | Runs the coordination CLI against the main checkout's database, from any worktree |
| `softory tracker [--port N] [--open]` | Runs the web console on 127.0.0.1 |
| `softory skills list\|add [--recommended]` | Pulls open-source skills at pinned commits |
| `softory charter show` / `charter approve <file> [--merge]` | The settings unattended runs follow; the owner approves them at a terminal, seeing only what changes. `--merge` adds to the approved settings instead of replacing them |
| `softory kickoff` | Writes Greg's one-time interview and prints the command that opens it: vision, scope, environment, and accounts, saved as a charter draft you approve |
| `softory feature "<idea>"` | Files an idea as a story for Greg to shape; the runner wakes him |
| `softory setup` | The owner's one-time checklist, with each step checked |
| `softory setup --load-schedule` | Loads the runner's launchd job after you type yes (owner, at a terminal) |
| `softory run [--dry-run]` / `run-role <role>` / `run-check <STORY>` | One runner tick: frees silent sessions' claims, applies escalation defaults that are due, starts each role that has work inside the budget, and starts one feasibility check when a story needs one |
| `softory escalate --issue ... --ask "...?" --recommend ... --reversible yes\|no [--holds IDs]` | Asks the owner one question, with the option the role would take. One that can be undone applies after `decisions.default_after_hours` (24) with no answer. `--holds` takes units off every queue until the answer, which wakes their builders |
| `softory defer <ID> --decision <id> [--until YYYY-MM-DD]` / `--lift` | Takes a unit off every queue on an owner's decision (an answer, or a `softory ruling`), until the date or until lifted |
| `softory answer <ESC> "<answer>"` | Answers an escalation, or replaces one that defaulted; the role that asked is told (owner, at a terminal) |
| `softory settle <ID> retry\|split\|drop --reason ... [--into IDs]` | Quinn settles a unit stopped at the review cap: one more round (once per unit), a split, or a drop. The owner settles the rest with `--actor owner` |
| `softory feasible <STORY> --pass \| --needs "..." [--plan <hash>]` | The feasibility check's verdict, for the plan it read. Until a pass, the story's todo tasks wait; a new task or changed requirements after a pass are checked again; needs becomes a provisioning request in your digest |
| `softory pause [--role r]` / `resume [--role r]` / `resume --task ID [--roles a,b]` | Stops unattended runs (anyone may); starts them again (owner, at a terminal). `--task` keeps the pause but lets the named roles work on that one task. In attended mode a pause stops only the runner: sessions you opened keep seeing their work |
| `softory ship [--dry-run]` | Checks the base (a red base gets a priority 1 bug), merges finished units on green as one candidate commit, and deploys the result to the `auto` targets. The runner starts it each tick; `--dry-run` lists what waits to merge |
| `softory deploy <target> [--release ID] [--commit sha]` | Deploys a tested commit to one of the charter's targets and runs its smoke test. `production` takes a closed release, by you at a terminal |
| `softory verify <ID> [--fresh]` | Runs the charter's tests at the unit's commit in a clean worktree, for the gate. A commit that already passed with the same settings isn't tested again unless `--fresh`. One at a time per project; kept awake on macOS; setup failures reported apart from test failures; failure logs and `verify.keep` artifacts kept |
| `softory digest [--send]` / `usage [--team [--days N]]` / `schedule` | What needs the owner, plus the last 7 days' spend, spend per closed unit, and the share of runs that changed nothing; today's runs and sessions against the budget, or with `--team` sessions and messages per delivered task and each reviewer's rate of requests that led to new code; the launchd job and cron line |
| `softory clutter [--idle-days 14]` | Lists untracked files, archives (ignored folders included), duplicate archives, extra worktrees, and merged or idle branches. Read-only; exits 2 when it finds any |
| `softory flow [--days 7] [--record]` | The process's numbers over the window: time to delivery, review rounds, runs, minutes, tokens and dollars per delivered unit, the share of runs that changed nothing, and disk. `--record` keeps a snapshot; the next report lists what got `worse` since. While sessions opened outside the runner worked in the window, the run numbers are left empty (`unmeasured`), since nothing logged them. Sage's check-in starts here |
| `softory gc [--days 14] [--dry-run]` | Removes workspaces unused for that long, old run and verify logs, and verify trees a crashed run left in the temp folder |
| `softory attach` | Watch attended runs: attaches to the tmux session where each running role has a window, or says where they open |
| `softory doctor` / `roles` / `sync` / `uninstall [--purge]` | Maintenance |

`softory <command> --help` gives each command's options. The CLI lives at `.agents/softory/bin/softory` inside the project. You can alias it as `softory`.

### Running unattended

Softory runs the team without you up to a pull request. You merge and deploy. From 0.5.0, nothing waits on you mid-flight except what can't be undone. Set it up once:

1. Run `softory setup`. It lists each step and checks the ones it can. Start with `softory kickoff`: Greg interviews you once about the vision, what's out of scope, the environment agents can reach, and the accounts the work will need.
2. Write the settings you want to change to a file, starting from `softory charter show`: your `vision`, `verify.command` (your test command), `lanes` paths, `paging.command`, and the `budget`. Approve it in a terminal with `softory charter approve <file>`.
3. Protect your base branch on GitHub and require CI.
4. Load the runner: turn off any other scheduler for the project first, such as an app's scheduled check-ins, then run `softory setup --load-schedule` and type yes. It loads a launchd job that runs `softory run` every five minutes (`softory schedule` prints a cron line for other systems). The runner should be the only thing that starts roles; otherwise roles run twice and the budget can't see half of them. `softory doctor` warns while no scheduler is loaded, when the runner has stopped ticking, and when sessions started outside the runner in the last day.

Each tick starts a role only when it has work, is under today's budget, and isn't paused or already running. The budget counts runs and minutes, not dollars, so it holds whatever a model costs: by default 24 runs and 120 minutes a day per role, 30 minutes a run, and tighter for the reviewing roles (Greg 15 minutes a run and 60 a day, Darwin and Toby 20 and 60). `budget.roles` overrides any cap for one role. At 80% you see it in the digest; at 100% the role stops until tomorrow and you're paged. Optional dollar caps sit beside them: `usd_per_run` (Claude Code stops itself there) and `usd_per_role_per_day`, counted from the cost each run reports; both are off at 0.

### Watching runs (attended mode)

By default the runner starts each role headless (`claude -p`, `codex exec`), so runs don't show in the Claude or Codex apps and you can't step in while one works. To watch them, set `run.mode` to `attended` in the charter (`softory charter approve --merge` a file with `{"run": {"mode": "attended"}}`). The runner still decides who to wake and when, but opens each role's interactive harness (`run.attended`) where you can see it:

- **tmux**, if it is installed: one window per running role in the session `softory-<project>-<hash>`. `softory attach` attaches to it; `Ctrl-b w` lists the roles and `Ctrl-b d` leaves them running.
- **Terminal**, on a Mac without tmux: one window per role. macOS asks once to let softory control Terminal.

Type into any window to steer the role. A run ends when the role runs `softory end`, when you quit the harness or close the window, or at `minutes_per_run`; the runner then hands back unfinished claims as usual. Interactive harnesses don't report tokens or cost, so in attended mode the budget counts runs and minutes only. The run's log keeps a copy of the window. Set `run.mode` back to `unattended` to return to headless runs.

Each run is shaped to waste as little as possible:

- **Reviewers wake for tested work, in batches.** With `verify.command` set, a reviewer isn't woken for a unit until `softory verify` passed at its commit; the builder is woken to run or fix the tests instead. When several reviewers may give the same review, `softory reviewers` names one to `ask`; set `review.rotation` (for example `["gold", "jade", "avery"]`) to spread requests in that order. A reviewer then wakes once `review_batch.min` reviews wait (default 2) or the oldest has waited `review_batch.max_wait_minutes` (default 60), and clears all of them in one run. Keep the tick at five minutes: a tick with nothing to do calls no model.
- **The prompt carries the work.** It lists what is waiting and, for up to five units, the title, acceptance criteria, the changes reviewers asked for, and the files the commit touched, so the agent doesn't spend its first turns looking them up. The rules come first and stay the same between runs, so the provider's prompt cache reuses them.
- **Messages wake only for action.** A role wakes for a message from you, one tagged `request`, `question`, `ruling`, `answer`, `blocker`, or `urgent`, or one that names a unit it builds, holds, reviewed, or owes a review or close on. Anything else (acknowledgements, news) waits for its next run, or wakes it after `retry_hours` (4) with no run. In Tablet, unread messages started 66% of runs and half of those changed nothing.
- **Reviewers see only reviews they owe.** A requirement another listed reviewer already accepted drops off everyone else's queue, and a reviewer who asked for changes isn't woken again until new evidence lands.
- **Effort fits the job.** A run that only has reviews, closes, or messages is a review run (`effort.review`, default medium); anything else is a build run (`effort.build`, default high). `models.<role>.effort` overrides either for one role.
- **Real tokens and cost.** Claude Code runs with `--output-format json` and Codex with `--json`; softory reads their usage report and logs input, cached, and output tokens and dollars per run (Codex's dollars are estimated from the charter's `prices`). `softory usage` shows today's totals per role. Each run also logs how many records it changed besides opening its session and reading messages, so the digest can show what share of runs bought nothing.
 Claude Code roles get a settings file that allows edits only in their lane's paths; Codex runs in its workspace-write sandbox. Either way, the gate's `lane_paths` check fails a unit whose own commits reach outside the lane (work below it that another unit verified doesn't count against it), unless it's tagged `cross-lane` and Quinn accepted it, or Jade or Gold when Quinn built it, and `verified` needs `softory verify` to have passed at the commit.

A task that has had `task_caps.escalate_model_after` rounds of requested changes runs on the role's stronger model next time. At `review_rounds` it stops, and Quinn settles it: one more round (once per unit), a split, or a drop. You see what he chose in the digest; a unit Quinn built, or one whose extra round is spent, comes to you. Review records never count, and the first request whose every item is labelled `evidence:` is free (`free_evidence_rounds`). The digest also flags an open unit whose record changed `waste.revision` times (default 30) without closing, a sign a role is looping on its own tooling. Pages go out at once for a unit closed without the gate or a role over budget, outside quiet hours; everything else waits for the daily digest. `softory pause` stops everything, and only you can `softory resume`.

### Sessions you open yourself (0.6.2)

You can also run the team as sessions you open in the Claude or Codex app, each checking in on a timer, with no runner starting anything. Set `run.mode` to `attended` and, if a runner is loaded, `softory pause` it. Each session runs `softory pending <role>` and works when it exits 0.

- A pause then stops only the runner. A session checking on itself still hears about its work; `softory resume --task` still narrows a role to named tasks.
- A session sees every unread message sent to its role, tagged or not, and Quinn's session sees the feasibility checks that are due and runs each with `softory run-check STORY-n`.
- Softory can't see what these sessions cost. `softory usage`, the budget caps, and the run numbers in `softory flow` cover runner runs only, and `softory flow` says so instead of showing partial numbers.
- An agent with a stand-in grant, such as a second reviewer, starts with `softory start <agent>` like any role.

### What doesn't wait for you (0.5.0)

- **Escalations default.** Each one names the option the role would take and whether it can be undone. If it can, the runner applies it after `decisions.default_after_hours` (24) with no answer, as a decision you can still replace with `softory answer`. If it can't, it waits, and the role carries on with work that doesn't depend on it.
- **Feasibility before work starts.** Once a story has tasks, the runner starts a Quinn run on a different model (`feasibility.harness` and `model`, Codex by default) that reads only the plan, your vision and `out_of_scope`, and the declared `environment`. A pass lets the tasks start. Anything missing (a sign-in, a paid tier, an unlocked desktop) becomes a provisioning request in your digest, and Greg and Quinn re-plan around what's reachable; the check runs again after the change. Softory never enforces the environment; your harness does.
- **Recovery.** Each tick ends sessions silent for twice the longest run (at least an hour) and puts what they claimed back to todo, so a crash or a sleeping Mac doesn't strand work.
- **A `ui` unit needs one check against its reference** (evidence of type `reference`, `screenshot`, or `visual`) before it closes, since a green suite can miss a screen that never renders.
- **Story progress** shows in `softory tree` as done of total, counted from the children.

Not yet: compact typed handoffs, shorter queue output, and tokens per accepted unit wait for a week of runner logs from the pilot. What you say in a session counts when the role records it with `softory ruling --review` or `--escalation` (0.6.4); your digest lists each one, and `softory answer` at a terminal replaces it.

### How design works (0.5.1)

Each project keeps two files you approve once: `docs/product/PRODUCT.md` (Greg: who it's for, their jobs, non-goals, the one reserved color) and `docs/design/DESIGN.md` (Darwin: project rules, host tokens, motion, one wording per state, banned patterns). Templates are in `factory/templates/` (installed at `.agents/softory/factory/templates/`). Softory's own [design standard](skills/softory-design/references/standard.md) sits under both: ten ranked principles and four gates.

For a story with UI, Darwin writes the spec under its design task, with the question the screen answers, every state, worst-case data, exact copy, and at least three options compared against the requirements. Greg accepts it. You're asked only when a design adds a new pattern or breaks DESIGN.md. Changes after acceptance go in a new revision, never in place.

From 0.5.2, Emil Kowalski's design skills are in the catalog: `prototype` and `break-ui` for Darwin, and `emil-design-eng`, `review-animations`, and `remove-animations` for Jade. Pull them with `softory skills add --recommended`. `softory-design` says how each fits the lanes.

From 0.5.3, UI build tasks wait until their story's design task is done. With `impeccable` installed (`softory skills add impeccable`), `softory verify` also runs its design detector on a UI task's changed files, and an error or warning on a line the task changed blocks the close (from 0.6.3, findings on lines it didn't change are only counted).

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

Scaffolds 1.4.0 to 1.4.2 share schema version 1, so any of their CLIs can restore it.

### Who changes the rules

The rules are softory's, not the project's. The installer makes `gates.json`, the role files, softory's code, and `local.json` read-only and records their hashes. If any of them changes, the gate fails every unit (`config_intact`) and `softory doctor` names the file, until the file is restored or you reinstall. A change to the rules for every project is a softory release. Softory's skills, templates, and workflows aren't part of the gate, but `softory doctor` warns when an installed one differs from the release, and a reinstall restores it.

Per-project exceptions are yours: a stand-in (`softory standin add`) or a waiver of one review check on one task. Both run only at a terminal, after you type yes, so an agent can't make them from its shell. Agents ask with `softory propose ... --why "..."`, which records a proposed decision and changes nothing; you run `softory approve PROP-n`, or `softory approve --all` for every waiting review adoption (add `--reject` to refuse). `--all` lists anything that doesn't look like a review run first, and never includes stand-ins or waivers. This is a speed bump rather than a lock: an agent that fakes a terminal or edits the files is going around you on purpose, and the gate shows it.

## Projects that already have a team

Softory can join a project that already runs the scaffold, with its own agents and tasks. The installer keeps the database and every agent already registered, and adds only the roles that are missing. It doesn't repeat the scaffold block if the project's `AGENTS.md` already has it.

- **Tasks from before softory** keep the project's own process. `softory close` holds them to a minimum: evidence, and one accepted review from anyone but the builder. `softory adopt` moves one into a story so it gets the full gate.
- **Existing agents can stand in for a role.** `softory standin add avery --for jade,gold` lets Avery review wherever Jade or Gold would. Add `--task` to limit it to named tasks and `--until` to end it on a date. It's recorded as a decision and added to the instructions every agent reads. A role-wide stand-in never reviews the specialist's own work: when Toby wrote the threat model, Quinn reviews it, not Toby's stand-in, unless you scope a stand-in to that task.
- **Review runs kept as tasks become records.** `softory adopt <ID> --unit review` asks the owner to turn one into a review record, and the owner approves every waiting one with `softory approve --all`. A record closes on the reviewer's own verdict, with every requested change filed as a follow-up task, and nobody reviews it again.
- **Old "todo" tasks are often finished.** In the Vault Radar pilot, four of four sampled todo tasks were already fixed, merged, and accepted, but never closed. Run `softory triage` before planning new work.
- **Run the installer on the machine that runs the agents.** The coordination database uses SQLite's WAL mode, which isn't safe to share between a VM or container and the host through a mounted folder.

### Any harness, one loop (0.5.4)

Softory assumes nothing about a harness beyond its command line in `run.harnesses`:

- **The runner owns the session.** It opens the role's session before starting the harness, passes `COORDINATION_SESSION` and `SOFTORY_ROLE` in the harness's environment, and ends the session when the run exits or times out. The run's prompt is the same for every harness.
- **Sessions survive fresh shells.** Claude Code runs each command in a new shell, so exported variables are gone by the next one. `softory start` remembers the session for the role; any `softory` command with `--actor <role>`, and `softory coord` commands that name `--agent` or `--actor`, find it. An ended session is never reused.
- **Runtime state lives in `.coordination/softory/`**, beside the database: the run log, verify ledger and logs, escalations, proposals, feedback, and sessions. Codex's `workspace-write` sandbox protects `.agents/`, so a Codex role couldn't record feedback there. Rules stay in `.agents/softory`, read-only for every harness. The installer moves an older install's files over; reload the runner afterwards (`softory setup --load-schedule`) so its log follows.
- **Verify doesn't need to write `.git`.** If `git worktree add` is refused (Codex protects `.git` too), verify checks out every tracked file of the commit through a temporary index outside `.git`. It doesn't use `git archive`, which honors `export-ignore`.
- **The charter names each role's harness.** `softory start <role> --harness X` refuses a harness the charter doesn't run the role on. The owner allows more in `models.<role>.also`.

### Waiting on the owner, and reviewing (0.5.5)

- **Held work wakes nobody.** `softory escalate --holds TASK-n,...` takes those units off every queue, ready-to-close and `pending` while the escalation is open. The answer, or the default for an undoable one, releases them and wakes their builders. `softory defer <ID> --decision <id>` does the same on an owner's decision, until `--until` or `--lift`. `softory queue` lists held units with why.
- **One workspace per reviewer.** `softory workspace <role> <commit>` replaces copies in /tmp. The verify ledger is the test proof, so reviewers don't rerun the suite.
- **Reports live outside the checkout.** `softory report` files them under `.coordination/softory/evidence/<ID>/`, and `softory verify` warns when the main checkout has changed or untracked paths.
- **A ui unit reaches review with its reference check.** `softory handoff` refuses without it, as does `softory coord task release ... --to review`. A ui unit in review without one wakes its builder, not its reviewers.
- **`softory gc`** removes unused workspaces, old logs and leftover verify trees.

Adding a harness takes one template line in the charter's `run.harnesses`, plus a parser in `usage.py` if you want its token counts.

### Keeping the process simple (0.5.10)

Tablet's agents made their own process: 11 copies of the same plugin zip, one folder per commit they wanted to prove, 66 untracked review documents in the main checkout, four leftover worktrees, a backup branch, and a 390-line installer for a feature that installs nothing. Nothing asked for any of it, and nobody could say no.

- **Simplicity is a rule every role follows.** No zip, bundle, backup branch, or copy of the tree, and no new script, workflow, or kind of document, unless a unit's acceptance criteria need it. Proof is evidence rows and `softory verify`. One checkout per role, and one release artifact that each build overwrites.
- **Sage, the Software Development Manager, owns it.** Sage decides whether a new workflow, script, packaging step, generated artifact, or kind of document exists, reviews units tagged `process`, and checks in on the team's process. Sage fixes the cause, such as the script that zips every commit, by filing a `simplify` unit for the lane owner. Sage never chooses architecture or assigns work (Quinn), sets priority (Greg), drops a security step (Toby), writes product code, or deletes your files. Deletes come to you as an escalation that names the exact paths.
- **The gate holds it.** A unit whose commits change `simplify.process_paths` (scripts, `bin/`, CI, Makefiles, Dockerfiles) needs the `process` tag, so Sage reviews it. `softory handoff` refuses while untracked files from the claim sit in the main checkout.
- **Sage's operating loop.** The runner wakes Sage for a check-in at most once a day (`simplify.checkin_hours`), and only when the team ran, filed feedback, or left clutter since the last one. Each check-in runs `softory flow --record`, which shows time to delivery, runs, minutes and tokens per delivered unit, idle runs, and disk, compared with the last check-in. It then reads `softory clutter`, the feedback, and new process work, and files a `simplify` unit for the one or two biggest causes, each naming the number it should move. Sage is capped at 4 runs and 40 minutes a day, and the digest has a clutter line.
- **Simplest path first (0.6.1).** Sage also reads new epics, stories, designs, and ADRs as they appear, and challenges anything that isn't the simplest path to the user's outcome: whether the work is needed at all, where each constraint came from, and what every added step or dependency is for. Sage raises it with Greg or Quinn, who decide. Nothing is added to the process for this.
- **Upgrading:** if your charter sets `run.roles`, add `sage` to it. Clean up what's already there first, or Sage's first check-in will list it all.

### Merging and shipping on its own (0.6.0)

Until 0.6.0 every finished unit waited for you to merge it. Now, if you choose, softory merges, keeps the base green, and ships to staging. Production stays yours.

- **Turn it on** with `softory charter approve <file> --merge` and a file holding `{"merge": {"by": "softory"}}`. Add `"push": "origin"` to push the base after each merge. It needs `verify.command`, since softory merges only what it saw pass.
- **Merge on green.** Each tick, `softory ship` takes the units that closed through the gate since you turned it on, up to `merge.batch_max` (5), merges them into one candidate commit in a throwaway worktree, and moves the base only if `softory verify` passes there. A batch that fails is retried one unit at a time. A unit that conflicts or fails alone stays off the base, and its builder gets a priority 1 bug.
- **The base stays green.** Whenever the base moves, by softory or by you, softory verifies it. A red base gets one priority 1 bug for Gold, pages you, and nothing else merges until that fix does. Roles may push their own branches but never the base.
- **Staging.** Declare targets in `deploy.targets`, each `{"name", "command", "smoke", "auto"}`. Commands run in a clean checkout of the commit. An `auto` target gets every merge; a failed deploy or smoke test files a priority 1 bug. For an Obsidian plugin, staging can build the plugin and copy it into a dev vault, with a smoke test that checks the files landed.
- **Releases.** Greg asks, Gold opens `softory new release`, attaches the rollback plan, Toby and Quinn sign off, and Greg closes it once every target but production passed at its commit. Then you run `softory deploy production --release RELEASE-n` at a terminal.
- **Secrets.** The gate's `no_secrets` check scans the lines a unit adds for keys, tokens, private keys, and files like `.env` or `*.pem`. Declare where secrets live and who reads them in `secrets.stores`; softory never stores or fetches one. Add known safe matches to `secrets.allow`, or waive a false positive on one unit.
- **Backups.** The runner copies the coordination database once a day to `.coordination/backups/softory-daily-<date>.sqlite3` and keeps `backups.keep_days` (7).
- **The scaffold enforces the basics.** Strict closure and strict dependencies are on: no `done` without an accepted review from someone other than a builder, and no claim on work with an open `blocks` dependency. Review records, drops, and units whose softory gate passed close as before. Stacked units are linked with `informs`, which never blocks a claim. Stories and epics show as active while their children run.

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
  templates/             epic, story, and task descriptions; PRODUCT.md and DESIGN.md
skills/                  softory's eight skills
lib/softory/             the CLI and installer (Python, standard library only)
docs/                    models.md, sources.md, skill-sourcing.md, gaps.md
dependencies.json        pinned scaffold and tracker commits
external-skills.json     pinned open-source skills
```

## Known gaps upstream

[docs/gaps.md](docs/gaps.md) lists what the scaffold and tracker don't do yet, and how softory works around it. Since 0.6.0 the scaffold itself refuses a close without an accepted review or with open blocking work, so softory's gate is no longer honor-system on those points; its finer rules (tag reviews, lanes, verify) still hold only through `softory close`.

## License

MIT, copyright Joshua Nuez. Pulled open-source skills keep their own licenses, recorded in each skill's `SOURCE.txt`.
