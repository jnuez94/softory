---
name: softory-operating-loop
description: How a softory role starts, picks up, does, hands off, and closes work through the coordination CLI. Use at the start of every session in a softory project, and whenever you claim, review, block, or close an epic, story, task, or bug.
---

# Softory operating loop

`S=.agents/softory/bin/softory` and `C=.agents/agentic-project-scaffold-lite/bin/coordination` below. Every CLI call prints JSON. Branch on `ok` and `error.code`, never on message text.

## 1. Start

```sh
eval "$($S start <role> --harness <claude|codex> --model <model>)"   # exports COORDINATION_SESSION and SOFTORY_ROLE
```

Then orient yourself in one pass. Don't page through everything:

```sh
$S inbox                                          # unread messages to you or to "team", oldest first
$S queue                                          # claimed work, what you may close now, reviews waiting on you, assigned work
$C health --section stale_claims --limit 10       # only if you suspect stuck work
```

After you act on the inbox: `$S inbox --mark-read <N>`, with the `read_through` number the listing printed. Messages that arrived since stay unread. To read one message again: `$S message <ID>`. List commands stop at 500 rows; `$S all task list --status todo` follows every page.

## 2. Pick work

Take work in this order: anything in `ready_to_close` (run `$S close <ID>`), a review that is blocking someone, then your claimed work, then your assigned `todo` work by priority (1 is highest), then unassigned work in your lane.

If assigned work will never be built (the plan changed, or another unit replaced it), whoever may drop it says so: `$S drop <ID> --reason "..." [--superseded-by <ID>]`. Droppers are in `gates.json`: Quinn, Greg, or the owner for tasks and bugs; Greg or the owner for stories and epics.

Never take work outside your boundaries. If the queue is empty, tell the owner. Don't invent work.

## 3. Claim

```sh
$C task show TASK-7                                  # read the criteria, tags, revision, and dependencies
$C task claim TASK-7 --agent $SOFTORY_ROLE --if-revision <rev>
```

One claim at a time. If a `blocks` dependency isn't done, don't claim. Message the owner of the blocking task instead.

**Stacked work.** When a fix has to build on another unit that isn't closed yet, branch from it and say so: `$S stack <bottom-ID> <next-ID> ...` (bottom first). Each member still gets its own reviews. When every member is in review and accepted, `$S close <top-ID> --stack` closes them all, bottom first, or none if any member fails its gate.

## 4. Do the work

- Read the parent story and any linked design spec or ADR before building.
- Heartbeat during long work: `$C session heartbeat $COORDINATION_SESSION`. A claim is a one-hour lease.
- Post intent before you touch a path outside your lane: `$C message send --id MSG-<unique> --sender $SOFTORY_ROLE --recipient <owner> --task TASK-7 --body "..."`.
- Record anything that changes scope, architecture, design, or security posture: `$C decision add ...`.

## 5. Hand off for review

```sh
$C evidence add --task TASK-7 --uri <commit|PR|path> --type commit --actor $SOFTORY_ROLE
$C evidence add --task TASK-7 --uri <test-output-path> --type test --actor $SOFTORY_ROLE
$C task release TASK-7 --to review --actor $SOFTORY_ROLE --if-revision <rev>
$S reviewers TASK-7                 # who must review, from the unit and tags
$C message send ... --recipient <each reviewer> --task TASK-7 --body "Ready for review: <one line>"
```

## 6. Review someone else's work

Load `softory-code-review`. Record exactly one review per pass. Put the verdict on the reviewed task, and list every change you require as a follow-up unit:

```sh
$S new bug --from TASK-7 --title "..." [--tags security]     # one per required change; same story and lane as TASK-7
$C review add --id REV-TASK-7-<you>-<n> --task TASK-7 --reviewer $SOFTORY_ROLE \
  --artifact <commit|PR> --scope "<what you checked>" \
  --decision accepted|conditionally_accepted|changes_requested|rejected \
  --required-changes "..." --follow-up-tasks BUG-12,BUG-13 --blocked-claims "Does not approve ..."
```

A follow-up links back to its source but doesn't hold it open. Add `--blocks-source` only when the source must not close before the fix.

**Review runs.** To claim a long review, heartbeat through it, and attach the report, keep the run as a review record: `$S new review --title "..." --for TASK-7[,BUG-2]`. Record your verdict on the record itself or on each reviewed task; either works. A record is never reviewed again, and its own "changes requested" never blocks it: it closes, from review, blocked, or todo, once you've recorded a verdict, attached the report, and every change you asked for names a follow-up task that exists. It holds reports, not code, and you can't review work you built. For a review run from before softory, its reviewer runs `$S adopt <ID> --unit review` (it reads what the run reviewed from its `informs` links; add `--for <IDs>` otherwise). That asks the owner, who approves every waiting one with `softory approve --all`; nothing changes until then.

## 7. Close

```sh
$S close TASK-7             # runs the gate, then moves to done only if it passes
```

Never close with a raw `task status ... done`. Only the closer named in `governance/gates.json` closes: the assignee for tasks and bugs and review records, and Greg for stories and epics. If the gate fails, fix what it lists. Never work around it, and never edit softory's files: the gate fails closed if they change.

If a gate rule truly can't be met (the only possible reviewer built the work, say), ask the owner: `$S propose waiver <ID> --check review:tag:security --why "..."` or `$S propose standin <agent> --for toby --task <ID> --until <date> --why "..."`. Nothing changes until the owner runs `softory approve` at a terminal. When the owner rules on something in chat, record it under their name: `$S ruling --title "..." --decision "..." --where "<thread or message, and when>"`.

## 8. Block or escalate

- Waiting on something: `$C task release TASK-7 --to blocked --note "<what and who>" ...`, and message whoever can unblock it.
- Two roles both claim a call, or a dispute can't be settled: `$C escalation add` naming both, routed per `governance/boundaries.md#escalation-paths`.

## 9. End

Release or finish every claim, then `$S end`.

## Never

- Edit `.coordination/coordination.sqlite3` directly.
- Commit any file softory installed. `softory doctor` lists them. They're local by design.
- Put secrets, credentials, or personal data in any coordination record.
