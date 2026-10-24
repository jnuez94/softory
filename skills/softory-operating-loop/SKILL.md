---
name: softory-operating-loop
description: How a softory role starts, picks up, does, hands off, and closes work through the coordination CLI. Use at the start of every session in a softory project, and whenever you claim, review, block, or close an epic, story, task, or bug.
---

# Softory operating loop

`S=.agents/softory/bin/softory` and `C=.agents/agentic-project-scaffold-lite/bin/coordination` below. Every CLI call prints JSON: branch on `ok` and `error.code`, never on message text. Statuses are `todo`, `in_progress`, `review`, `blocked`, and `done`.

## 1. Start

```sh
eval "$($S start <role> --harness <claude|codex> --model <model>)"   # exports COORDINATION_SESSION and SOFTORY_ROLE
```

Started by the runner? The prompt already lists what is waiting, with each unit's criteria, requested changes, and changed files. Go straight to the work. Otherwise orient in one pass:

```sh
$S inbox                 # unread messages to you or to "team"; then $S inbox --mark-read <N> with the number it printed
$S queue                 # claimed work, what you may close now, reviews waiting on you, assigned work
```

`$S message <ID>` reads one message again. List commands stop at 500 rows; `$S all task list ...` follows every page.

## 2. Pick work

In this order: anything in `ready_to_close`, a review that blocks someone, your claimed work, your assigned `todo` work by priority (1 is highest), then unassigned work in your lane. If the queue is empty, stop. Don't invent work.

Assigned work nobody will build: `$S drop <ID> --reason "..." [--superseded-by <ID>]`. Quinn, Greg, or the owner drops tasks and bugs; Greg or the owner drops stories and epics.

## 3. Claim

```sh
$C task show TASK-7                                          # criteria, tags, revision, dependencies
$C task claim TASK-7 --agent $SOFTORY_ROLE --if-revision <rev>
```

Don't claim while a `blocks` dependency is open: message the owner of the blocking task. Building on a unit that isn't closed yet: `$S stack <bottom-ID> <next-ID> ...`, bottom first.

## 4. Do the work

- Read the parent story, and any linked design spec or ADR, before building.
- A claim is a one-hour lease. During long work: `$C session heartbeat $COORDINATION_SESSION`.
- Before touching a path outside your lane: `$C message send --id MSG-<unique> --sender $SOFTORY_ROLE --recipient <lane owner> --task TASK-7 --body "..."`.
- Anything that changes scope, architecture, design, or security posture: `$C decision add ...`.

## 5. Hand off for review

```sh
$C evidence add --task TASK-7 --uri <commit hash> --type commit --actor $SOFTORY_ROLE
$C evidence add --task TASK-7 --uri <test-output-path> --type test --actor $SOFTORY_ROLE
$S verify TASK-7                    # runs the charter's tests at that commit; the gate needs it to pass
$C task release TASK-7 --to review --actor $SOFTORY_ROLE --if-revision <rev>
$S reviewers TASK-7                 # who must review
$C message send ... --recipient <each reviewer> --task TASK-7 --body "Ready for review: <one line>"
```

## 6. Review someone else's work

Load `softory-code-review`. One review per pass, on the reviewed task. File every required change as a follow-up and list it:

```sh
$S new bug --from TASK-7 --title "..." [--tags security]     # same story and lane as TASK-7
$C review add --id REV-TASK-7-<you>-<n> --task TASK-7 --reviewer $SOFTORY_ROLE \
  --artifact <commit|PR> --scope "<what you checked>" \
  --decision accepted|conditionally_accepted|changes_requested|rejected \
  --required-changes "..." --follow-up-tasks BUG-12,BUG-13 --blocked-claims "Does not approve ..."
```

A follow-up doesn't hold its source open unless you add `--blocks-source`.

**Review records.** To claim, heartbeat, and attach a report for a long review: `$S new review --title "..." --for TASK-7[,BUG-2]`. It closes on your verdict once the report is attached and every change you asked for names a follow-up that exists. Nobody reviews it again. For a review run from before softory: `$S adopt <ID> --unit review`, which asks the owner.

## 7. Close

```sh
$S close TASK-7             # runs the gate; moves to done only if it passes
$S close <top-ID> --stack   # a whole stack, bottom first, or none of it
```

The closer is the assignee for tasks, bugs, and review records, and Greg for stories and epics. A gate rule that truly can't be met goes to the owner: `$S propose waiver <ID> --check <check> --why "..."` or `$S propose standin <agent> --for <role> --task <ID> --until <date> --why "..."`. When the owner rules on something in chat: `$S ruling --title "..." --decision "..." --where "<where and when>"`.

## 8. Block or escalate

- Waiting on something: `$C task release TASK-7 --to blocked --note "<what and who>" ...`, and message whoever can unblock it.
- Two roles both claim a call: `$C escalation add` naming both, routed per `governance/boundaries.md#escalation-paths`.

## 9. End

Release or finish every claim, then `$S end`.

## Never

- Edit `.coordination/coordination.sqlite3` directly.
- Commit any file softory installed. `softory doctor` lists them. They're local by design.
- Put secrets, credentials, or personal data in any coordination record.
