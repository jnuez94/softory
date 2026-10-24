---
name: softory-testing
description: The softory testing bar, covering the test pyramid, test-first loop, what to test, test structure, regression tests for bugs, and flaky-test rules. Use when writing or reviewing tests, deciding what tests a task needs, or fixing a bug.
---

# Testing

Tests are how a softory task proves its acceptance criteria. No test, no evidence, no `done`.

## What each task needs

| Change | Required tests |
| --- | --- |
| New logic (function, class, reducer) | Unit tests: happy path, each edge case in the criteria, each error path |
| New or changed boundary (API endpoint, DB query, external call, CLI) | Integration test against the real boundary or a faithful local fake |
| User-visible criterion | One end-to-end or interaction test per criterion with a user path (not one per edge case) |
| Bug fix | A regression test that **fails before the fix and passes after**, at the lowest level that reproduces it |
| Refactor | Existing tests stay green and unchanged. If they had to change, it wasn't a pure refactor. |

Pyramid shape: many fast unit tests, fewer integration tests, and a handful of end-to-end tests. If the suite is slow, push tests down a level.

## Test-first loop (default for logic and bugs)

1. Write one failing test that encodes one criterion or the bug. Run it and **see it fail for the right reason**.
2. Write the least code that passes it.
3. Refactor with the tests green.
4. Repeat for the next criterion.

Skip test-first only for spikes and pure UI layout. Say so in the task notes.

## Structure

- **One behavior per test,** named for it.
- **Test behavior, not implementation.** Assert on outputs and observable effects. A refactor shouldn't break tests.
- **Mock only boundaries you don't own** (network, clock, third-party APIs), never the unit under test.
- **No logic in tests:** no loops or conditionals that could hide a failure. Use parameterized tests.

## Determinism

- Inject the clock, randomness, and IDs. Never `sleep` to wait, but poll with a timeout or use fake timers.
- Each test sets up and tears down its own state, and tests pass in any order.
- **Flaky test rule:** a flaky test is a bug. File a `BUG` task, tag it with the test's lane, and fix or quarantine it in that task. Never silently retry it.

## Coverage

Every changed line of logic runs in a test. Never add assertion-free tests to raise the number. For money, auth, or parsing, consider property-based or mutation testing.

## Evidence

Attach test output as evidence (`evidence add --type test`). Keep it short: the summary line and any failures, not the full log.

## Review checklist

- Does each acceptance criterion map to at least one test?
- Would the test fail if the code were wrong? Mentally break the code and check.
- Are failure paths tested, not just the happy path?
- Is anything mocked that could be real and fast?
- Is the bug's regression test at the right level?
