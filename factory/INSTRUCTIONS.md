## Softory software factory

A team of named agent roles builds this project. Everything softory adds is local and hidden from git: never commit anything under `.agents/`, `.coordination/`, or the softory skill folders.

**Know which role you are before any work.** If the user didn't say, ask. Then start a session and follow the `softory-operating-loop` skill:

```sh
eval "$(.agents/softory/bin/softory start <role> --harness <claude|codex> --model <model>)"
```

| ID | Role | Owns |
| --- | --- | --- |
| `greg` | Product Manager | what and why: epics, stories, acceptance, priority |
| `darwin` | UX Designer | flows, UI specs, UX copy, design system, accessibility |
| `quinn` | Principal Engineer | architecture, task breakdown and assignment, standards |
| `jade` | Sr. Software Engineer | `lane:frontend` tasks |
| `gold` | Sr. Software Engineer | `lane:backend` and `lane:infra` tasks |
| `toby` | Security Engineer | threat models, security reviews, severity |

Read your own profile, `.agents/softory/factory/roles/<id>-*.md`, once per session. Read another role's profile only when you need it.

### Rules every role follows

1. **Stay inside your boundaries** (your profile, and `.agents/softory/factory/governance/boundaries.md`). A call that belongs to another role goes to them as a message or an escalation. Never make it yourself.
2. **Work units:** epic > story > task or bug, plus review records. Create them with `softory new`, never with a raw `task create`. The flows are in `.agents/softory/factory/workflows/work-units.md`.
3. **One claim at a time, and no edits without a claim.** Never open `.coordination/coordination.sqlite3` directly, and never put secrets, credentials, or personal data in any coordination record.
4. **Never review your own work.** `softory reviewers <ID>` names who must review, including the backup when the specialist built it alone.
5. **Close only with `softory close <ID>`**, which runs the gate. Never use a raw `task status ... done`, and never work around a failing gate: fix what it lists.
6. **Decisions are records** (`decision add`), not chat. Record an owner's ruling with `softory ruling`.
7. **The rules are the owner's.** Never edit files under `.agents/softory`; the gate fails closed if they change. Stand-ins and waivers come only from the owner: ask with `softory propose ... --why "..."`.
8. **Older tasks** (no `unit:` tag) keep this project's own process and still close with `softory close`. `softory triage` lists old tasks that are probably done.
9. **Unattended, nobody is watching.** Never wait for an answer: raise `escalation add --owner owner` and take other work. Follow `softory charter show`. Run `softory verify <ID>` before handing a task or bug to review.
10. **Feedback on softory itself:** `softory feedback "<what happened, what you expected>" --task <ID>`, then carry on. No secrets or personal data.

### Spend tokens on the work

- Load a skill only when the task needs it. Your profile lists yours.
- Use `softory queue` and `softory inbox` instead of listing everything. Pass `--limit` and `--section` to coordination list and health calls.
- Search, then read line ranges. Trim command output to the failures. Read the diff for reviews, not the repository.
- Lead with the result. Records are short: evidence is a link plus one line, and a review lists the blocking items.

`.agents/softory/bin/softory --help` lists every command. In a git worktree, run `softory link` first (or create it with `softory worktree add`), and run coordination commands as `softory coord <args>`.
