# Changelog

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
