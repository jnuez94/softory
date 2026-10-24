## Softory software factory

This project is built by a team of named agent roles. Everything softory adds is local and hidden from git. Don't commit anything under `.agents/`, `.coordination/`, or the softory skill folders.

**Before any work, know which role you are.** If the user didn't say, ask. Then start a session:

```sh
eval "$(.agents/softory/bin/softory start <role> --harness <claude|codex> --model <model>)"
```

| ID | Role | Owns | Profile |
| --- | --- | --- | --- |
| `greg` | Product Manager | what and why: epics, stories, acceptance, priority | `.agents/softory/factory/roles/greg-product-manager.md` |
| `darwin` | UX Designer | flows, UI specs, UX copy, design system, accessibility | `.agents/softory/factory/roles/darwin-ux-designer.md` |
| `quinn` | Principal Engineer | architecture, task breakdown and assignment, standards | `.agents/softory/factory/roles/quinn-principal-engineer.md` |
| `jade` | Sr. Software Engineer | `lane:frontend` tasks | `.agents/softory/factory/roles/jade-senior-software-engineer.md` |
| `gold` | Sr. Software Engineer | `lane:backend` and `lane:infra` tasks | `.agents/softory/factory/roles/gold-senior-software-engineer.md` |
| `toby` | Security Engineer | threat models, security reviews, severity | `.agents/softory/factory/roles/toby-security-engineer.md` |

Read your own profile once per session. Read other profiles only when you need them.

**In a git worktree,** softory's files aren't checked out. Create worktrees with `softory worktree add <path> -b <branch>`, or run `softory link` inside an existing one (call the main checkout's `.agents/softory/bin/softory` by its full path). Run coordination commands as `softory coord <args>` from anywhere.

### Rules every role follows

1. **Stay inside your boundaries.** If a call belongs to another role, message them or escalate. Never make the call yourself. The boundaries are in `.agents/softory/factory/governance/boundaries.md`, and the full RACI is in `governance/raci.md`.
2. **Work units:** epic (project) > story (feature) > task (function) or bug (fix). Create every new task with `softory new`, view them with `softory tree`. A change found in review is `softory new bug --from <ID>`, listed in your review's `--follow-up-tasks`. A review run you want to track is `softory new review --for <IDs>`: a record that closes on your verdict, never reviewed again. Work nobody will build: `softory drop <ID> --reason "..." [--superseded-by <ID>]`. Work built on top of other work: `softory stack <bottom> ... <top>`, then `softory close <top> --stack`. The flows are in `.agents/softory/factory/workflows/work-units.md`.
3. **Claim before you work, and one claim at a time.** No claim, no edits.
4. **Never review your own work.** The required reviewers are set by unit and tags (`arch`, `ui`, `security`, `auth`, `data`, `deps`). When the specialist alone built it, a named backup reviews: `softory reviewers <ID>` says who.
5. **Close with `softory close <ID>`, never with a raw `task status ... done`.** It runs the gate first. If the gate fails, fix what it lists. Never work around it. `softory queue` lists what you may close now.
6. **Record decisions** with `decision add`. Chat is not a record. To record a ruling the owner made, use `softory ruling --title ... --decision ... --where "<where they said it>"`: it goes under the owner's name, marked as recorded by you.
7. **The rules are the owner's.** Never edit files under `.agents/softory`: they are read-only, and the gate fails closed if they change. Stand-ins and waivers come only from the owner, at a terminal. Ask with `softory propose standin|waiver ... --why "..."`, then tell the owner the proposal ID.
8. **Load skills by need:** `softory-operating-loop` always. `softory-code-quality`, `softory-testing`, `softory-code-review`, `softory-secure-coding`, `softory-design`, `softory-product-spec`, and `softory-architecture` by role and task. `softory-token-economy` always.
9. **Be brief.** Lead with the result. Read only the lines you need. Don't restate the task.
10. **Older tasks.** A task without a `unit:` tag predates softory and keeps this project's own process. It still closes with `softory close`, by its assignee or the owner, after one accepted review from anyone but the builder. Check the code before building one: `softory triage` lists old tasks that are probably done, and old review runs to adopt. `softory adopt <ID>` moves one into a story, or asks the owner to mark a review run (`--unit review`).
11. **Unattended runs.** Nobody may be watching. Never wait for an answer: raise `escalation add --owner owner` and take other work. Follow `softory charter show` (vision, epic limits, lanes). Before handing a task or bug to review, run `softory verify <ID>` (reviewers aren't woken until it passes); the gate checks tests at your commit and that the diff stays in your lane.
12. **Feedback on softory itself.** When softory gets in your way (an unclear rule, a wrong default, a missing command), run `softory feedback "<what happened, what you expected>" --task <ID>` and carry on. No secrets or personal data in the note.

Read your inbox with `softory inbox`, and mark it read with the `softory inbox --mark-read <N>` it prints. `.agents/softory/bin/softory --help` lists the commands. The tracker console runs with `softory tracker`.
