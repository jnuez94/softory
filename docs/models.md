# Which model for each role

Chosen on 2026-10-24. Each role is matched to the benchmark that measures its own kind of work, not one general coding score, and to the harness that is strongest at it. Cost is a tiebreaker, not the goal. The defaults are in [factory/governance/charter.json](../factory/governance/charter.json) under `models`; override any of them in your charter, and check `softory usage` after a week to see what each role actually spends.

## The picks

| Role | Harness and model | The benchmark that fits the work | Why |
| --- | --- | --- | --- |
| Darwin (UX) | Claude Code, `claude-opus-5-5` | WebDev Arena, people voting on interfaces models build: Opus 5.5 1807, GPT-6 Astra 1775, Sonnet 5.5 1768, GPT-6.1 Sol 1749 | First on design quality, and Claude is the stronger design harness. Same model as Jade, so spec and build share context. |
| Jade (frontend) | Claude Code, `claude-opus-5-5` | WebDev Arena (above), and Terminal-Bench 4.0 for agent work: Opus 5.5 64.8%, GPT-6.1 Sol and Astra 58.2% | First on both the look and the engineering of web work. |
| Gold (backend, infra) | Claude Code, `claude-opus-5-5` | Terminal-Bench 4.0 (above); SWE-bench Pro: Opus 5.5 89.9% (unconfirmed), Sonnet 5.5 81.3%, no GPT-6 score | Terminal-heavy work is exactly what Terminal-Bench measures, and Opus leads it by 6.6 points. |
| Quinn (architecture) | Claude Code, `claude-opus-5-5` | Terminal-Bench 4.0 and SWE-bench Pro (above) | Architecture and task breakdown decide everyone's rework, so it gets the strongest engineering model. |
| Toby (security) | Codex, `gpt-6-astra` | SEC-Bench Pro: Astra 85.4%, Sol 78.8%. CWE-bench defensive patching: Astra 68%, Opus 5.5 67%. ExploitGym: Astra 42.4%, Sol 35.1% | Leads or ties the defensive-security benchmarks, Codex is the stronger security harness, and every builder runs on Claude, so each security review is a different model's view. |
| Greg (product) | Codex, `gpt-6-astra` | AA-Briefcase, long-horizon knowledge work: Astra about 90 Elo above GPT-5.6 Sol; hallucination rate down from 92% to 51% | Acceptance decides "done", so it gets a strong, careful model on a different family from the builders. |

This matches the 2026-10-21 split (Claude for Darwin, Quinn, Jade, and Gold; Codex for Greg and Toby), now with the strongest model in each harness.

## What it costs, and the cheaper option

On Terminal-Bench 4.0 the full run cost $4.7k with Opus 5.5 (8.0B tokens), $3.3k with GPT-6 Astra (1.5B), and $0.6k with GPT-6.1 Sol (1.5B). Astra's list price is higher than Opus's ($10 / $50 against $4 / $20 per million tokens), but it used about a fifth of the tokens, so per task it is cheaper. The runner's `pending` check, budgets, and review caps keep idle and stuck roles from spending. The budget is in runs and minutes, so moving from Sol to Opus 5.5 or Astra raises the cost of each minute, not the number of minutes. That's why the defaults are 24 runs and 120 minutes a day per role (60 for Greg, Darwin, and Toby), down from the 48 and 240 first proposed.

If the budget is tight, the best trade is Gold and Greg on `gpt-6.1-sol` with `escalate` set to `claude-opus-5-5` (Gold) or `gpt-6-astra` (Greg). Sol scores the same as Astra on Terminal-Bench 4.0 at a fifth of the cost, and the escalation moves a task to the stronger model after two rounds of requested changes. Keep Toby, Darwin, and Quinn on the defaults; those are the specialist calls.

Models with no role: Sonnet 5.5 scores below Opus 5.5 everywhere above and used 2.4 times the tokens on Terminal-Bench 4.0, so it costs more per task. GPT-6 Luna (16.4% on Terminal-Bench 4.0) and Haiku 5.5 (no agent benchmark yet) are too weak or too new.

## Caveats

- **Prompt injection.** Gray Swan's indirect prompt injection test succeeds 1% of the time against Opus 5.5 and 8.5% against GPT-6 Astra (15 attempts, lower is better). Toby and Greg read code and text other agents wrote, so they run in Codex's workspace sandbox, and nothing they read can change the gate.
- **Vals CyberBench is left out.** It is an offensive, capture-the-flag style test where refusals drive the scores: Opus 5.5 scores 55.4% normally and 74.6% under the cyber verification program, and Astra scores 41.1%. It doesn't measure defensive review.
- **Aggregators disagree.** Anthropic's own run puts Sonnet 5.5 at 70.6% on Terminal-Bench 4.0, and Artificial Analysis's harness ranks it above Opus 5.5. The table uses tbench.ai's like-for-like board. Opus 5.5's 89.9% on SWE-bench Pro isn't in Anthropic's launch table.
- **Benchmark cost isn't your cost.** Subscriptions bill differently from the API.

## Sources

- [WebDev Arena leaderboard](https://www.benchleader.com/benchmarks/lmarena_webdev) (results of 2026-10-22) and [Arena's note on Opus 5.5](https://x.com/arena/status/2103110782540255504)
- [Terminal-Bench 4.0 leaderboard summary](https://codingfleet.com/blog/terminal-bench-4-leaderboard-2026/) (tbench.ai board, updated 2026-10-23), [release notes](https://www.tbench.ai/news/terminal-bench-4-0), and [Artificial Analysis's run](https://artificialanalysis.ai/evaluations/terminalbench-v4-0)
- [BenchLM cybersecurity benchmarks](https://benchlm.ai/cybersecurity) (refreshed 2026-10-23): SEC-Bench Pro, CWE-bench, ExploitGym, Gray Swan
- [Vals AI CyberBench](https://www.vals.ai/benchmarks/cyber) (2026-10-12)
- [BenchLM coding leaderboard](https://benchlm.ai/coding) (SWE-bench Pro, refreshed 2026-10-23)
- [Artificial Analysis on GPT-6 Astra](https://artificialanalysis.ai/es/articles/benchmarking-gpt-6-astra) (2026-09-09): AA-Briefcase, AA-Omniscience
- [OpenAI API pricing](https://developers.openai.com/api/docs/pricing) and [Claude 5.5 prices](https://www.usagepricing.com/blueprint/activity/anthropic-2026-10-05-opus-5-5-price-cut)
