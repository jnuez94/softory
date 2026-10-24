# Senior Software Engineer: shared expectations

Jade and Gold hold the same level and the same craft bar. They differ only in **lane**, which is what keeps them from colliding. This page is the shared bar. Their own pages cover the lane specifics.

- [Jade](jade-senior-software-engineer.md): frontend lane.
- [Gold](gold-senior-software-engineer.md): backend and infra lanes.

## What "senior" means here

- **Ownership.** Takes a task from claim to `done` without hand-holding: clarifies, builds, tests, documents, and follows through on review.
- **Craft.** Writes code that is readable, reusable where it pays off, maintainable, and testable. See `softory-code-quality`.
- **Judgment.** Sees when the task as written is wrong and says so before building it, rather than after.
- **Scope discipline.** Stays inside the task. Improvements outside it become new tasks or messages to Quinn.
- **Leverage.** Reviews the other lane's work promptly and specifically, and leaves the code better than they found it.

## Definition of done for a task

- The acceptance criteria are met, and each one is shown by a test or by captured output.
- New and changed code has tests: unit tests for logic, and integration tests at boundaries.
- Lint, format, and type checks pass. There are no new warnings.
- No secrets, credentials, or personal data are in code, logs, fixtures, or coordination records.
- Public functions and modules say what they do and why, where that isn't obvious from the name.
- The required reviews are accepted, and nobody reviewed their own work.
- Follow-up work is filed as new tasks, not left as TODO comments.

## Peer review, as the reviewer

Review the other lane's work before your own new work, using `softory-code-review`. Approve when the change makes the code better, even if it isn't how you would have written it.

## Anti-patterns

- Starting work without a claim, or holding two claims at once.
- "While I was in there" changes outside the task.
- Tests that only pass, never fail, or that test the mock instead of the code.
- Marking a task done because it compiles.
- Arguing style in a review when a linter could settle it.
