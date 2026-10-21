---
name: softory-code-review
description: How softory roles request, perform, and record code reviews, including what each reviewer type checks, the order to check it, comment labels, and turnaround. Use when a task is in review and you are a required reviewer, or when you are the author preparing or answering a review.
---

# Code review

The goal of review is that the codebase is **better after the change than before**, not that the change is perfect.

## Who reviews what

`softory reviewers <ID>` prints the required reviewers. Stay inside your scope:

| Reviewer | Checks | Doesn't check |
| --- | --- | --- |
| Peer (Jade ↔ Gold) | Correctness, tests, readability, fit with the code around it | Product scope, visual design |
| Quinn (`arch`) | Module boundaries, interfaces, data model, dependencies, simplicity | Naming nits (that's the peer's job) |
| Darwin (`ui`) | Matches the spec, every state, accessibility, copy, tokens | Code structure |
| Toby (`security`, `auth`, `data`, `deps`) | The security checklist in `softory-secure-coding` | Style, product |
| Greg (stories, epics) | Each acceptance criterion against the evidence | Code |

## As the reviewer: the order to look

1. **Context.** Read the task's criteria and the parent story. What should this change do?
2. **Design.** Does the approach make sense here? Is it in the right place?
3. **Correctness.** Does it do what the criteria say, including the edge and error cases? Look for off-by-one errors, nulls, races, and unhandled failures.
4. **Tests.** Would they fail if the code were wrong? Do they cover the criteria?
5. **Readability and maintainability.** Use the rubric in `softory-code-quality`.
6. **Nits.** Only after the above, and labeled as nits.

Read the diff, not the whole repo. Pull in surrounding code only where the diff calls it.

## Comment labels

Prefix every comment so the author knows what's blocking:

- **`blocking:`** must change before acceptance. Always say why and suggest a fix.
- **`question:`** you need an answer, and it may become blocking.
- **`suggestion:`** better, but optional.
- **`nit:`** trivial and optional. Never block on nits.
- **`praise:`** call out what's done well. Use it sparingly and specifically.

## Recording the outcome

One `review add` per review pass:

- `accepted`: no blocking comments.
- `conditionally_accepted`: small blocking fixes the author can make without another review. List them in `--required-changes`.
- `changes_requested`: needs another pass. List every blocking item.
- `rejected`: the approach is wrong. Say what to do instead, and loop in Quinn.

Always fill `--blocked-claims` with what the review doesn't approve, for example "Does not approve the API contract change. Needs Quinn."

## Turnaround

Review within one working cycle of being asked. A review blocks someone else, so it comes before your own new work. If you can't review in time, say so and name who should.

## As the author

- Keep the change small, one concern per review. Split it if the diff is over about 400 changed lines.
- Self-review the diff before asking. Remove debug code and stray files.
- Write the review request in three lines: what changed, why, and how it was verified, with evidence links.
- Answer every comment: fixed, or why not. Don't argue nits. Take them or leave them.
- Never mark your own review, and always close with `softory close`, never with a raw `task status done`.

Sources: Google, [Engineering Practices: The Standard of Code Review](https://google.github.io/eng-practices/review/reviewer/standard.html) and [What to look for in a code review](https://google.github.io/eng-practices/review/reviewer/looking-for.html). [Conventional Comments](https://conventionalcomments.org/).
