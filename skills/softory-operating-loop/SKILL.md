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
$C inbox list --limit 20                          # messages to you or to "team"
$S queue                                          # your claimed and assigned work, plus review requests for your role
$C health --section stale_claims --limit 10       # only if you suspect stuck work
```

After you act on the inbox: `$C inbox mark-read --cursor HEAD`.

## 2. Pick work

Take work in this order: a review that is blocking someone, then your claimed work, then your assigned `todo` work by priority (1 is highest), then unassigned work in your lane.

Never take work outside your boundaries. If the queue is empty, tell the owner. Don't invent work.

## 3. Claim

```sh
$C task show TASK-7                                  # read the criteria, tags, revision, and dependencies
$C task claim TASK-7 --agent $SOFTORY_ROLE --if-revision <rev>
```

One claim at a time. If a `blocks` dependency isn't done, don't claim. Message the owner of the blocking task instead.

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

Load `softory-code-review`. Record exactly one review per pass:

```sh
$C review add --id REV-TASK-7-<you>-<n> --task TASK-7 --reviewer $SOFTORY_ROLE \
  --artifact <commit|PR> --scope "<what you checked>" \
  --decision accepted|conditionally_accepted|changes_requested|rejected \
  --required-changes "..." --blocked-claims "Does not approve ..."
```

## 7. Close

```sh
$S close TASK-7             # runs the gate, then moves to done only if it passes
```

Never close with a raw `task status ... done`. Only the closer named in `governance/gates.json` closes: the assignee for tasks and bugs, and Greg for stories and epics. If the gate fails, fix what it lists. Never work around it.

## 8. Block or escalate

- Waiting on something: `$C task release TASK-7 --to blocked --note "<what and who>" ...`, and message whoever can unblock it.
- Two roles both claim a call, or a dispute can't be settled: `$C escalation add` naming both, routed per `governance/boundaries.md#escalation-paths`.

## 9. End

Release or finish every claim, then `$C session end $COORDINATION_SESSION`.

## Never

- Edit `.coordination/coordination.sqlite3` directly.
- Commit any file softory installed. `softory doctor` lists them. They're local by design.
- Put secrets, credentials, or personal data in any coordination record.
