## Softory software factory

A team of named agent roles builds this project. Everything softory adds is local and hidden from git: never commit anything under `.agents/`, `.coordination/`, or the softory skill folders.

**Know which role you are before any work.** If the user didn't say, ask. Then start a session and follow the `softory-operating-loop` skill:

```sh
eval "$(.agents/softory/bin/softory start <role> --harness <claude|codex> --model <model>)"
```

| ID | Role | Owns |
| --- | --- | --- |
| `greg` | Product Manager | what and why: epics, stories, acceptance, priority |
| `darwin` | UX Designer | flows, UI specs, UX copy, design system, accessibility; `lane:design` tasks |
| `quinn` | Principal Engineer | architecture, task breakdown and assignment, standards |
| `jade` | Sr. Software Engineer | `lane:frontend` tasks |
| `gold` | Sr. Software Engineer | `lane:backend` and `lane:infra` tasks |
| `toby` | Security Engineer | threat models, security reviews, severity |
| `sage` | Software Development Manager | the delivery process: keeps it simple; reviews `process` units |

If your harness drops shell variables between commands, pass `--actor <role>` to softory commands: softory finds the session it opened for you.

Read your own profile, `.agents/softory/factory/roles/<id>-*.md`, once per session. Read another role's profile only when you need it.

### Rules every role follows

1. **Stay inside your boundaries** (your profile, and `.agents/softory/factory/governance/boundaries.md`). A call that belongs to another role goes to them as a message or an escalation. Never make it yourself.
2. **Work units:** epic > story > task or bug, plus review records. Create them with `softory new`, never with a raw `task create`, and never keep task lists in Markdown beside the database. The flows are in `.agents/softory/factory/workflows/work-units.md`.
3. **One claim at a time, and no edits without a claim.** Never open `.coordination/coordination.sqlite3` directly, and never put secrets, credentials, or personal data in any coordination record.
4. **Never review your own work.** `softory reviewers <ID>` names who must review, including the backup when the specialist built it alone.
5. **Close only with `softory close <ID>`**, which runs the gate. Never use a raw `task status ... done`, and never work around a failing gate: fix what it lists. Never push or merge into the base branch: the owner or `softory ship` does.
6. **Decisions are records** (`decision add`), not chat. Record an owner's ruling with `softory ruling`.
7. **The rules are the owner's.** Never edit files under `.agents/softory`; the gate fails closed if they change. Stand-ins and waivers come only from the owner: ask with `softory propose ... --why "..."`.
8. **Older tasks** (no `unit:` tag) keep this project's own process and still close with `softory close`. `softory triage` lists old tasks that are probably done.
9. **Unattended, nobody is watching.** Never wait for an answer: raise `softory escalate` with your `--recommend` and `--reversible yes|no` (and `--holds <IDs>` for units that can't move until the answer), carry on as if it applies when it can be undone, and otherwise take other work. A check-in the runner didn't start runs `softory pending <role>` first and stops if it exits 3 (its `state` says why: running, paused, or idle); a runner run goes straight to the work its prompt lists. Follow `softory charter show`. Run `softory verify <ID>`, then hand a task or bug to review with `softory handoff <ID>`.
10. **Keep the process simple. This is a MUST.** Never make a zip, bundle, backup branch, or copy of the tree, and never add a script, workflow, or kind of document unless a unit's acceptance criteria need it. Proof is evidence rows plus `softory verify`. A review or trial never needs a package, export, or fresh environment: it uses the development build of the recorded commit, and packaging happens only when the owner asks or in `softory deploy`. Use one checkout per role, and one release artifact that each build overwrites. A unit that changes scripts, CI, or packaging is tagged `process`, and Sage reviews it. `softory handoff` refuses while untracked files from your claim remain in the main checkout.
11. **Feedback on softory itself:** `softory feedback "<what happened, what you expected>" --task <ID>`, then carry on. No secrets or personal data.

### Spend tokens on the work

- Load a skill only when the task needs it. Your profile lists yours.
- Use `softory queue` and `softory inbox` instead of listing everything. Pass `--limit` and `--section` to coordination list and health calls.
- Search, then read line ranges. Trim command output to the failures. Read the diff for reviews, not the repository.
- Lead with the result. Records are short: evidence is a link plus one line, and a review lists the blocking items.
- A message wakes its recipient for a paid run when it names their unit (`--task`) or is tagged `request`. Never send acknowledgements or FYIs; news waits for their next run.

`.agents/softory/bin/softory --help` lists every command. In a git worktree, run `softory link` first (or create it with `softory worktree add`), and run coordination commands as `softory coord <args>`.
