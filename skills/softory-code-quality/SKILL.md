---
name: softory-code-quality
description: The softory bar for well-structured code, covering readability, reusability, maintainability, testability, error handling, and simplicity, with concrete rules and a review rubric. Use when writing, refactoring, or reviewing any production code in a softory project.
---

# Code quality

Good code is code the next person can change safely. Each rule below serves one of six properties. When two rules conflict, prefer the one higher in this list: **correct, readable, testable, maintainable, reusable, fast**.

## 1. Readability: the code explains itself

- **Names say what, not how.** `unpaidInvoices` beats `filteredList`. Booleans read as questions (`isExpired`, `hasAccess`). Functions are verbs (`sendReminder`). Avoid abbreviations except universal ones (`id`, `url`).
- **One level of abstraction per function.** A function either orchestrates steps or does one step, never both.
- **Short functions, flat control flow.** Aim for under about 30 lines. Return early on guard conditions instead of nesting. More than two levels of nesting is a signal to extract.
- **Make the happy path obvious.** Handle errors and edge cases first, then the main logic at the left margin.
- **Comments say why, not what.** Explain intent, constraints, and non-obvious trade-offs. Delete comments that restate the code. A TODO needs a task ID or it doesn't go in.
- **No magic values.** Name constants and say where they come from.
- **Follow the project's formatter and linter.** Style isn't up for debate in review.

## 2. Reusability: share what is truly shared

- **Rule of three.** Duplicate once, and extract on the third occurrence. Two similar blocks with different reasons to change aren't duplication.
- **Extract by concept, not by coincidence.** A helper has a name the domain would recognize. `formatCurrency` is a concept. `doStuffForPageA` is not.
- **Prefer composition** of small functions and objects over inheritance hierarchies.
- **Small, explicit interfaces.** Take the narrowest input a function needs (an `id`, not the whole `user`), and return plain data.
- **Search before you write.** Check the codebase for an existing utility before adding one (`grep -rn "def format_" src/`).

## 3. Maintainability: change one thing in one place

- **High cohesion, low coupling.** A module owns one responsibility and hides its internals. Other modules use its public interface only.
- **Respect module boundaries and dependency direction** from the ADRs: domain logic must not import from UI or transport layers.
- **Keep files small.** About 300 lines is a soft cap. Past it, split by responsibility.
- **SOLID where it pays:** single responsibility always, and dependency inversion at I/O boundaries. Don't add interfaces with one implementation "for the future".
- **No dead code, no commented-out code, no speculative generality (YAGNI).** Version control remembers.
- **Configuration is data.** Environment-specific values come from config or the environment, never inline.
- **Leave it better, within scope.** Small refactors that touch the code you're changing are welcome. Wider ones become a new task.

## 4. Testability: designed to be tested

- **Functional core, imperative shell.** Keep decisions in pure functions (input → output). Push I/O (network, disk, clock, randomness, environment) to thin outer layers.
- **Inject what varies:** clock, random, HTTP client, and storage are passed in (as parameters or constructor arguments), not reached for globally.
- **Deterministic by default.** No hidden time, ordering, or network dependence in logic.
- **Observable results.** Functions return values or raise errors that can be asserted. Avoid output only through side effects or logs.
- If a unit is hard to test, that's a design smell. Fix the design rather than reaching for heavier mocks.

## 5. Errors: fail loudly, safely, and in the right place

- **Validate at the boundary** (API handler, CLI parser, form) and trust validated data inside.
- **Don't swallow errors.** Either handle one meaningfully (retry, fallback, user message) or let it propagate with context.
- **Errors carry context** (what was attempted, with which ID) and never secrets or personal data.
- **Fail closed** on security-relevant paths.
- **One error style per layer:** exceptions or result types, consistently.

## 6. Simplicity and performance

- **The simplest thing that meets the criteria.** No frameworks, layers, or patterns the task doesn't need.
- **Measure before optimizing,** but don't write the obvious traps: queries inside loops (N+1), unbounded lists, or loading whole files to read one line.

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
