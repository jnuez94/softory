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

Every harness gets the same loop. If yours runs each command in a fresh shell, pass `--actor <role>` to `$S` commands and run coordination commands as `$S coord ...` instead of `$C ...`: softory adds the session it opened for the role the command names.

Started by the runner? Your session is already open, so skip `start`, and skip `end` unless your prompt says the owner is watching. The prompt lists what is waiting, with each unit's criteria, requested changes, and changed files. Go straight to the work. Otherwise orient in one pass:

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

A claim on ui work that `softory queue` marks as waiting for design is refused (`waits_for_design`). Don't claim a todo task that `softory queue` marks as waiting for its story's feasibility check, or while a `blocks` dependency is open (the claim fails with `task_blocked`): message the owner of the blocking task. Building on a unit that isn't closed yet: `$S stack <bottom-ID> <next-ID> ...`, bottom first.

## 4. Do the work

- Read the parent story, and any linked design spec or ADR, before building.
- A claim is a one-hour lease. During long work: `$C session heartbeat $COORDINATION_SESSION`.
- Before touching a path outside your lane: `$C message send --id MSG-<unique> --sender $SOFTORY_ROLE --recipient <lane owner> --task TASK-7 --body "..."`.
- Anything that changes scope, architecture, design, or security posture: `$C decision add ...`.

## 5. Hand off for review

```sh
$S commit TASK-7 <commit hash> [--base <hash>]   # full hash, base kept apart, so verify tests the right one
$C evidence add --task TASK-7 --uri <test-output-path> --type test --actor $SOFTORY_ROLE
$S verify TASK-7                    # runs the charter's tests at that commit, once per commit; the gate needs it to pass
$S report TASK-7 <screenshot or diff> --type reference   # ui units: one rendered check against the design; files go outside the checkout
$S handoff TASK-7 [--note "<one line>"]   # to review, and asks every reviewer it needs; refuses without evidence, or a ui unit's reference check
```

## 6. Review someone else's work

Load `softory-code-review`. One review per pass, on the reviewed task. File every required change as a follow-up and list it:

```sh
$S new bug --type functional|visual --from TASK-7 --title "..."   # same story and lane as TASK-7
$C review add --id REV-TASK-7-<you>-<n> --task TASK-7 --reviewer $SOFTORY_ROLE \
  --artifact <commit|PR> --scope "<what you checked>" \
  --decision accepted|conditionally_accepted|changes_requested|rejected \
  --required-changes "..." --follow-up-tasks BUG-12,BUG-13 --blocked-claims "Does not approve ..."
```

A follow-up doesn't hold its source open unless you add `--blocks-source`.

A unit you sent back returns with `re_review` in your queue: check what you asked for against its `diff`. What you accepted stands, and a new finding outside the change is a new bug. Several small bugs of one stack at one commit take one verdict: review one and put `stack:<name>` in `--scope`.

**Review records.** To claim, heartbeat, and attach a report for a long review: `$S new review --title "..." --for TASK-7[,BUG-2]`. It closes on your verdict once the report is attached and every change you asked for names a follow-up that exists. Nobody reviews it again.

## 7. Close

```sh
$S close TASK-7             # runs the gate; moves to done only if it passes
$S close <top-ID> --stack   # a whole stack, bottom first, or none of it
```

The closer is the assignee for tasks, bugs, and review records, and Greg for stories, epics, and releases. Push your branch with `$S push`. Never merge or push to the base branch: with `merge.by softory` in the charter, `softory ship` merges what closed. Releases: `softory new release --title "..."` (Gold), a rollback plan with `$S report RELEASE-n <file> --type rollback`, and `$S deploy <target> --release RELEASE-n` for a target it never reached. A gate rule that truly can't be met goes to the owner: `$S propose waiver <ID> --check <check> --why "..."` or `$S propose standin <agent> --for <role> --task <ID> --until <date> --why "..."`. When the owner rules on something in chat: `$S ruling --title "..." --decision "..." --where "<where and when>"`.

## 8. Block or escalate

- Waiting on something: `$C task release TASK-7 --to blocked --note "<what and who>" ...`, and message whoever can unblock it.
- Two roles both claim a call, or only the owner can decide: `$S escalate --issue "<plain sentences>" --ask "<one question>?" --recommend "<the option you'd take>" --reversible yes|no --tasks TASK-7`. If it can be undone, carry on as if your recommendation applies: it does after the charter's timeout unless the owner answers. If it can't, name the units that must wait in `--holds TASK-7,TASK-8` (they leave every queue and wake their builders on the answer), and finish what doesn't depend on it. When the owner rules that a unit waits, record it with `$S ruling`, then hold it with `$S escalate --reversible no --holds <ID>` that asks when it resumes: it stays off every queue until the owner answers. Route it per `governance/boundaries.md#escalation-paths` (`--owner quinn` for a call Quinn makes). It refuses text the owner can't read at a glance; rewrite it, don't work around it.
- A plan needs something the charter's `environment` doesn't declare (a sign-in, a paid tier, an unlocked desktop): don't start it. Re-plan around what is reachable (a fake provider, a headless check) and let the feasibility check run again.
- A unit at the review cap waits for the owner, who sees it in the digest. Don't work on it, and never reassign it.
- Wrong evidence on a unit: `$S supersede TASK-7 <evidence number> --reason "..."`. The row stays in the audit; the gate reads past it.

## Writing records

A message, review, decision, description, or note is read later by the owner and by roles that never saw your session. Write it so either can act on it without asking you.

- **Order:** what happened or what you need, then why, then what happens next and who does it.
- **Plain full sentences**, one point each. No telegraphic strings, and no labels you made up in this session ("ordinary release", "revision-bound claim", "final source"): say the thing itself.
- **Name things once, exactly.** A unit is its ID, with its title the first time: `BUG-267` (probe-loop test). A file, command, check, or value goes in backticks. A role is named as a word of its own.
- **Leave out** how you got there, what you ruled out, and rules the reader already follows (the gate, no waivers, no extra claims). Link a file for detail.
- **Length:** a message is one to five sentences. If it needs more, it is a report: file it with `$S report` and send the link.

Hard to read:

> BUG267 sole test-only follow-up, blocks265, backend lane assignedJade through narrow cross-lane flex. CurrentJade owns265: retain2a5checkpoint; ordinaryrelease265 then revision-bound267claim.

Readable:

> `BUG-267` is a test-only follow-up that blocks `BUG-265`. Jade, please take it: it changes only `tests/integrations/google-feed.test.mjs`, which Quinn has approved as a cross-lane edit. Keep your `BUG-265` work at commit `2a5`, release `BUG-265`, then claim `BUG-267`. Quinn and a peer review `BUG-267`; Darwin still accepts the `BUG-265` UI.

## 9. End

Release or finish every claim, then `$S end`.

## Never

- Edit `.coordination/coordination.sqlite3` directly.
- Commit any file softory installed. `softory doctor` lists them. They're local by design.
- Put secrets, credentials, or personal data in any coordination record.
