# Changelog

## [0.3.0] - 2026-10-23

From the owner's eight points after a week in Vault Radar, and an independent review of 0.2.0. Don't install 0.2.0; install this.

- **Review records.** A review run kept as a task is a record of the reviewer's output. Its own verdicts never block it, nobody reviews it again unless a tag on it needs a reviewer its author isn't (a `security` record by Avery needs Toby's sign-off, unless Avery stands in for Toby), and a "changes requested" on it counts as handled once it names follow-up tasks that exist, or its reviewer later accepts. It must hold reports and no code, name what it reviewed, and not review its reviewer's own work. It closes from review, blocked, or todo. On a copy of Vault Radar's database from 2026-10-23, 28 of the 34 open review runs pass the gate after `adopt`. Five link to nothing they reviewed and need `--for` (three of those look like ordinary tasks, not review runs), and one holds on a product objection with no follow-up task.
- `softory adopt <ID> --unit review` reads what a run reviewed from its `informs` links, leaving out other review runs and the reviewer's own work. Only the run's reviewer or the owner may ask, a task with code evidence is refused, and nothing changes until the owner approves: `softory approve --all` takes every waiting adoption after one typed yes and records one decision for the batch. The prompt lists anything not tagged or named as a review run first, and stand-ins and waivers are never part of `--all`. Otherwise a builder could relabel their own unreviewed fix as a review and close it.
- **Named backups can't be gamed.** The backup reviewer applies only when the specialist alone built the work. Adding Toby as a co-assignee no longer moves the security review to Quinn. A role-wide stand-in for the specialist doesn't count on the specialist's own work; one scoped to that task does. (In Vault Radar, Avery's role-wide stand-in for Toby had silently become the reviewer of Toby's own threat model.)
- **Scoped stand-ins.** `softory standin add <agent> --for <roles> [--task IDs] [--until YYYY-MM-DD]`. Grants that name tasks apply only there, and an end date lapses on its own. `standin list` shows each grant and whether it's active; `standin remove <agent> [--for roles]` takes back some or all. Older `local.json` files still read.
- **Dropped work.** `softory drop <ID> --reason ... [--superseded-by ID]` closes a unit nobody will build, with a decision, evidence pointing to it, and `resolution:` tags. Droppers are in `gates.json`. `softory tree` shows `done: won't do` or `done: superseded by ...`.
- **Stacks.** `softory stack <bottom> ... <top>` groups work built on other unfinished work. `softory close <top> --stack` checks every member's gate with the other members counted as done, and closes them bottom first only if all pass. The coordination CLI has no transactions, so if a close call itself fails partway, softory stops and reports what it closed (`closed_before_error`).
- **Follow-ups don't block their source.** `softory new bug --from <ID>` links back with `informs`. `--blocks-source` keeps the 0.2.0 behaviour when it's needed.
- **Silent roles.** `softory silent [--hours 12] [--notify]` lists roles with work waiting and no session for that long, or ever, and messages the owner once a day per role. `triage` includes it. The README shows a launchd or cron line with a desktop notification.
- `softory pending` no longer strands work after a crashed run: any waiting work counts again once `--retry-hours` (default 4) pass without a run.
- **Owner rulings.** `softory ruling --title ... --decision ... --where ...` records a decision under the owner's name, marked "recorded by <role>" with the session and where the owner said it.
- **Owner approval.** `standin add|remove` and `softory approve [IDs | --all]` run only at a terminal, after a typed yes. Agents ask with `softory propose standin|waiver ... --why ...`, which records a proposed decision and grants nothing. A waiver lets one review check pass on one task, and the gate shows it.
- **Rules don't drift by accident.** The installer makes `gates.json`, the role files, softory's code, and `local.json` read-only and records their hashes. The gate fails closed (`config_intact`) and `doctor` names the file when one changes. This catches mistakes, not a determined agent: the hashes sit in `manifest.json`, and a terminal can be simulated.
- **CLI.** `softory inbox` lists unread messages with the number that marks exactly those read (`--mark-read N`); the operating-loop skill no longer says `--cursor HEAD`, which the scaffold rejects. `softory message <ID>` shows one message. `softory all <entity> list` follows every page past 500 rows, and the gate's review lookups page too.
- `triage` recognises `code-review` and `independent-review` tags as review runs, and suggests each run's adopt command.

## [0.2.0] - 2026-10-23

From two days of agents using softory in Vault Radar.

- `softory queue` lists `ready_to_close`: your tasks in review that pass the gate and that you may close. Sixteen such tasks sat unclosed in Vault Radar, EPIC-1 among them.
- Named backup reviewers: when the specialist a tag names built the work, the tag's `if_builder` reviewers review it. Quinn backs up Toby on `security`, `auth`, `data`, and `deps`; Jade or Gold back up Quinn on `arch`; the owner backs up Darwin on `ui`. The owner chose this on 2026-10-23.
- Review units: `softory new review --for <IDs>` keeps a review run as its own task. It closes once its reviewer has recorded a verdict on each reviewed task, with no tag reviews and no review of the review. `softory adopt <ID> --unit review --for <IDs>` converts an older review run.
- Follow-ups: `softory new bug --from <ID>` inherits the source's story and lane, tags `from:<ID>`, and makes an open source task wait for the fix.
- `softory pending [role]` exits 0 when a role has work and 3 when it doesn't, without starting a session, so a scheduler can skip idle runs.
- `softory triage` also lists older review runs to adopt, sessions silent for a day, and sessions started before the last install or upgrade.
- `softory tree` groups stories and bugs that aren't under an epic, and `softory new story` warns when there's no `--parent`.
- The instructions tell agents to file every new task through `softory new`, follow-ups with `--from`.

## [0.1.0] - 2026-10-21

First release.

- Six roles with decision, review, and work boundaries: Greg (Product Manager), Darwin (UX Designer), Quinn (Principal Engineer), Jade and Gold (Senior Software Engineers, frontend and backend/infra lanes), and Toby (Security Engineer).
- RACI matrix with one accountable role per activity, flex rules for allowed overlap, and escalation paths.
- Units of work: epic (project), story (feature), task (function), and bug (fix), with templates and flows.
- Nine skills: operating loop, code quality, testing, code review, secure coding, design, product spec, architecture, and token economy.
- `softory` CLI: `start`, `new`, `tree`, `adopt`, `queue`, `reviewers`, `gate`, `close`, `standin`, `triage`, `link`, `worktree`, `coord`, `end`, `feedback`, `roles`, `doctor`, `tracker`, `sync`, `skills`, `uninstall`.
- Installer that adds scaffold 1.4.0 (SQLite) and the tracker, registers the roles, and hides everything with `.git/info/exclude`.
- A catalog of recommended open-source skills, pulled at pinned commits.
- Git worktrees: `softory worktree add` and `softory link` symlink softory into a worktree, hidden by the shared exclude rules; `--share` links installed dependencies too; `softory coord` runs the coordination CLI against the main database from anywhere; `softory end` ends a session; the CLI finds the main checkout from any worktree.
- `softory feedback` lets agents log friction with softory itself to `.agents/softory/feedback.jsonl`, and the instructions ask them to.
- `softory triage` lists open tasks that already have an accepted review. `softory doctor` flags an `AGENTS.override.md` that is out of date. The installer reports an existing scaffold and refuses to downgrade a 2.x one, and `uninstall` leaves a scaffold the project had before softory.
- Joining a project that already has a team: `softory standin` for existing agents, a minimum `legacy` gate for tasks created before softory, `softory adopt` to move them into a story, and no repeated scaffold block when the project's `AGENTS.md` already has it.
