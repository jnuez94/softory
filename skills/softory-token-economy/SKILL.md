---
name: softory-token-economy
description: Habits that cut token use in coding sessions without lowering quality, covering searching before reading, reading line ranges, terse output, diffs over rewrites, trimmed command output, and lean coordination calls. Use in every softory session, and especially on large codebases or long-running tasks.
---

# Token economy

Most tokens are spent on **input**: files, logs, and tool output the model reads. Output is the smaller lever. Optimize in that order.

## Read less

- **Search, then read.** Use `grep -rn` or `rg` for a symbol or string, and glob for file names. Open only the files that matched.
- **Read ranges, not files.** Use `sed -n '120,180p' file` or your tool's offset and limit. Read a whole file only when you'll edit most of it.
- **Don't re-read** a file you just read or wrote. Your edit tool already confirms the change.
- **Trim command output.** Pipe through `tail -n 40`, `grep -E "FAIL|Error"`, or `head`. Run tests in quiet or failing-only mode (`pytest -q`, `--reporter=dot`) and re-run only the failing test while iterating.
- **Use limits on coordination calls:** `inbox list --limit 20`, `task list --assignee <you> --status todo`, and `health --section <one>`. Use `softory queue` instead of listing everything.
- **Load skills by need.** Your role profile lists them. Don't load every skill at session start.
- **Read the diff for reviews,** not the whole repository. Pull in the surrounding code only where the diff calls it.

## Write less

- **Lead with the result.** No preamble, and no restating the task or the plan you're about to follow.
- **Edit, don't rewrite.** Use targeted edits (old string to new string) instead of regenerating whole files.
- **No narration of routine steps.** Report decisions, blockers, and results.
- **Short records.** Evidence is a link plus one line. A review lists the blocking items, not a summary of the diff.
- Being concise gets most of the savings. Benchmarks of extreme compression styles show only small extra gains over plain "be concise", and code, commands, and error text must stay verbatim anyway.

## Plan to avoid rework

The most expensive tokens are the ones spent redoing work.

- Read the criteria, the design spec, and the relevant ADR **before** writing code.
- Ask one precise question when a criterion is ambiguous, instead of building two versions.
- Keep tasks small (one PR). Big diffs cost tokens to write, to review, and to fix.

## Session hygiene

- One task per session where you can. Start a fresh session for unrelated work instead of carrying stale context.
- When context gets long, write the state to the task's `--next-steps` field and start a new session that reads only that.
- Delegate wide, shallow searches to a cheaper subagent or model if your harness supports it, and keep the conclusions, not the dumps.

## Anti-patterns

- `cat` on a large file or a full log.
- Listing all tasks, all messages, or the full audit log to find one thing.
- Re-running the whole test suite after every one-line change.
- Pasting tool output back into a message.
- Long "here's what I did" summaries the evidence already shows.
