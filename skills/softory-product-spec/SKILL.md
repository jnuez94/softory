---
name: softory-product-spec
description: Greg's product practice in softory, covering epic briefs, user stories, testable acceptance criteria, backlog prioritization, bug triage, and acceptance reviews. Use when creating or refining epics and stories, ordering the backlog, triaging bugs, or accepting finished work.
---

# Product specs

## Epic brief

Create it with `softory new epic --title "<outcome, not feature>" --actor greg --description "$(cat brief.md)"`, using the template in `.agents/softory/factory/templates/epic.md`.

- **Problem:** who has what problem today. Use evidence if you have it.
- **Outcome:** what is true for the user when the epic is done.
- **Success metric:** one measurable signal and a target.
- **Scope and non-goals:** the non-goals stop scope creep later.
- **Risks:** one line each for value, usability, feasibility, and security, so Darwin, Quinn, and Toby know where to look.

Get the owner's go/no-go and record it: `decision add --owner greg --title "EPIC-n go" ...`.

## Stories

Create each with `softory new story --parent EPIC-n --title "<user can ...>"`.

- Format: **As a** user, **I can** do something, **so that** I get a benefit.
- **INVEST:** independent, negotiable, valuable, estimable, small (1 to 6 tasks), and testable.
- **Split by user value,** not by layer. Never write a "backend story" and a "frontend story". Split by workflow step, by rule, by data variation, or by happy path first and edge cases next.
- Tag it `ui` if a user sees it. Darwin then designs and reviews it.

## Acceptance criteria

- Write **Given / When / Then**, one observable result per criterion.
- Cover the happy path, the important edge cases, and the error the user will actually hit.
- Every criterion must be checkable by a test or a demo. Banned words: "intuitive", "fast", "user-friendly", unless you give a number.
- Criteria are frozen once a task is claimed. Changing them means a decision record and a message to the assignee.

## Prioritization

Order the backlog by **outcome per effort**: value (how much it moves the success metric) × confidence ÷ effort (Quinn's estimate). Break ties by risk, because riskier assumptions get tested earlier. Use the priority field: 1 means now, 2 next, 3 soon, 4 later, and 5 maybe.

## Bug triage

On each new `BUG`:

1. Confirm it reproduces, or ask the reporter for steps.
2. Set **priority** (when to fix) from user impact and frequency.
3. Quinn sets **severity** and the lane, and Toby rates security severity.
4. Decide whether it blocks the current release. Record that if it does.

## Acceptance review

For a story or epic in `review`:

1. Go through the criteria one by one against the evidence: demo, test output, screenshots.
2. Mark each criterion met or not met.
3. Record it: `review add --reviewer greg --decision accepted|changes_requested --accepted-items "<met criteria>" --required-changes "<unmet>" --blocked-claims "Does not approve production release"`.
4. Close it with `softory close <ID>`, which runs the gate first.

Don't accept partial work as done. Split the remainder into a new story instead.
