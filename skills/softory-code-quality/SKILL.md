---
name: softory-code-quality
description: The softory bar for well-structured code, covering readability, reusability, maintainability, testability, error handling, and simplicity, with concrete rules and a review rubric. Use when writing, refactoring, or reviewing any production code in a softory project.
---

# Code quality

Good code is code the next person can change safely. When two rules conflict, prefer the one higher in this list: **correct, readable, testable, maintainable, reusable, fast**.

## 1. Readability

- **Names say what, not how** (`unpaidInvoices`, not `filteredList`). Booleans read as questions, functions as verbs.
- **One level of abstraction per function,** about 30 lines at most. Return early on guards; more than two levels of nesting means extract.
- **Comments say why, not what.** A TODO needs a task ID or it doesn't go in.
- **No magic values.** Name constants and say where they come from.
- **The formatter and linter settle style.** It isn't up for debate in review.

## 2. Reusability

- **Search before you write.** Check for an existing helper first (`grep -rn "def format_" src/`).
- **Rule of three.** Extract on the third copy, and only for a concept the domain would name. Two blocks with different reasons to change aren't duplication.
- **Narrow interfaces.** Take the smallest input a function needs (an `id`, not the whole `user`), and return plain data.

## 3. Maintainability

- **Respect the module boundaries and dependency direction in the ADRs.** Domain logic never imports from UI or transport layers.
- **Files stay under about 300 lines.** Past that, split by responsibility.
- **No dead code, no commented-out code, no speculative generality.** No interface with one implementation "for the future".
- **Configuration is data,** from config or the environment, never inline.
- **Leave it better, within scope.** Wider refactors become a new task.

## 4. Testability

- **Functional core, imperative shell.** Decisions in pure functions; network, disk, clock, randomness, and environment in thin outer layers.
- **Inject what varies** (clock, random, HTTP client, storage) instead of reaching for globals.
- Hard to test means the design is wrong. Fix the design, not the mocks.

## 5. Errors

- **Validate at the boundary** (handler, CLI parser, form) and trust validated data inside.
- **Never swallow an error.** Handle it meaningfully or let it propagate with context: what was attempted, on which ID, and never secrets or personal data.
- **Fail closed** on security-relevant paths. One error style per layer.

## 6. Simplicity and performance

- **The simplest thing that meets the criteria.** No frameworks, layers, or patterns the task doesn't need.
- **Measure before optimizing,** but never write the known traps: queries in loops (N+1), unbounded lists, whole files read for one line.

## Rubric (for authors and reviewers)

Rate each 0 to 2. Anything at 0 is a requested change.

| Property | 2: good | 0: request changes |
| --- | --- | --- |
| Correct | Criteria met, edge cases handled, tests prove it | A criterion is unmet or untested |
| Readable | Names and structure explain it without the author | Needs the author to explain |
| Testable | Logic is pure or injectable, and the tests are simple | Needs heavy mocking or real I/O to test logic |
| Maintainable | Fits the module boundaries, small cohesive units | Crosses boundaries or adds a god-object |
| Reusable | Uses existing helpers, extracts real concepts | Copy-paste of existing code, or a premature abstraction |
| Simple | Nothing speculative | Unused flexibility, dead code |

Smells and the refactorings that fix them are in `references/smells.md`. Read it when the rubric flags something.
