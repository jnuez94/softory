# Which model for each role

Chosen on 2026-10-24 from public benchmarks and list prices. The defaults are in [factory/governance/charter.json](../factory/governance/charter.json) under `models`; override any of them in your charter. Re-check when a new model ships or after your own trial, since `softory usage` and `.agents/softory/run/runs.jsonl` show what each role actually spends.

## The evidence

The most useful public benchmark for agents that work through a terminal is Terminal-Bench 4.0, run like-for-like on tbench.ai (five trials, eight-hour timeout). SWE-bench Verified and Terminal-Bench 2.x are saturated and archived, so they no longer separate today's models.

| Harness + model | Terminal-Bench 4.0 | Cost of the full run | Tokens used | List price, $ per 1M in / out |
| --- | --- | --- | --- | --- |
| Claude Code + Claude Opus 5.5 | 64.8% ±3.1 | $4.7k | 8.0B | 4 / 20 |
| Claude Sonnet 5.5 | 61.8% ±2.9 | $7.3k | 19.4B | 2 / 10 |
| Codex + GPT-6.1 Sol | 58.2% ±3.1 | $0.6k | 1.5B | 2 / 10 |
| Codex + GPT-6 Astra | 58.2% ±2.8 | $3.3k | 1.5B | 10 / 50 |
| GPT-6 Luna | 16.4% | $0.1k | not stated | 0.10 / 0.50 |

What it says:

- **Opus 5.5 is the strongest agent**, about 6.6 points ahead of GPT-6.1 Sol, which is roughly two standard errors.
- **GPT-6.1 Sol gives the most per dollar and per token.** It costs about an eighth of Opus 5.5 for the same tasks and uses about a fifth of the tokens.
- **Sonnet 5.5 costs more than Opus 5.5 in agent runs**, despite half the token price, because it used 2.4 times the tokens. It has no role here.
- **GPT-6 Astra matches Sol's score at 5.5 times the cost**, so it has no role either.
- **Luna and Haiku 5.5 are too weak or too new.** Luna is far behind on agent work. Haiku 5.5 ($0.10 / $0.50) has no agent benchmark yet. It's worth a trial for Greg once one appears.

On SWE-bench Pro, BenchLM lists Opus 5.5 at 89.9% (not in Anthropic's own launch table, so treat it as unconfirmed) and Sonnet 5.5 at 81.3%, with no GPT-6 scores. That doesn't change the picture.

## The picks

| Role | Default | Escalates to | Why |
| --- | --- | --- | --- |
| Quinn | Claude Code, `claude-opus-5-5` | – | Few runs, high leverage: architecture and task breakdown decide everyone else's rework. Pay for the strongest model here. |
| Jade | Claude Code, `claude-opus-5-5` | – | One builder on the strongest model. Jade and Gold review each other, so putting them on different models makes every peer review cross-model. |
| Gold | Codex, `gpt-6.1-sol` | Opus 5.5 | Most of the terminal-heavy work (backend, CI, infra) at the best cost per task. |
| Greg | Codex, `gpt-6.1-sol` | Opus 5.5 | Mostly writing and acceptance, and the role that wakes most often. Different from Jade, so acceptance gets a second model's view. |
| Darwin | Codex, `gpt-6.1-sol` | Opus 5.5 | No public benchmark measures UX work. Sol is cheap, and Darwin reviews Jade's UI, so a different model reads it. |
| Toby | Codex, `gpt-6.1-sol` | Opus 5.5 | Security review on a different model from Jade's and Quinn's. Gold's work is the same model family, so Quinn's architecture review and the CI check matter more there. |

**Escalation:** once a task has had `task_caps.escalate_model_after` rounds of requested changes (default 2), the runner runs that role on its `escalate` model for the next run. Cheap by default, strong when the cheap model is stuck. At `review_rounds` (default 3) the task stops and goes to your digest.

There's no vendor preference in this. Four roles run on Codex because GPT-6.1 Sol is the cost leader, and the two roles where quality pays most run on Opus 5.5 because it's the score leader.

## Caveats

- The numbers come from aggregators that disagree with each other. Anthropic's own run puts Sonnet 5.5 at 70.6%, and Artificial Analysis's mini-SWE-agent run ranks Sonnet 5.5 above Opus 5.5. The table above uses tbench.ai's like-for-like board.
- Benchmark cost isn't your cost. Subscriptions (Claude Pro or Max, ChatGPT Plus or Pro) bill differently from the API. Use a week of `softory usage` in Vault Radar to set the budget.

## Sources

- [Terminal-Bench 4.0 leaderboard summary](https://codingfleet.com/blog/terminal-bench-4-leaderboard-2026/) (tbench.ai board, updated 2026-10-23) and [Terminal-Bench 4.0 release notes](https://www.tbench.ai/news/terminal-bench-4-0)
- [Artificial Analysis, Terminal-Bench 4.0](https://artificialanalysis.ai/evaluations/terminalbench-v4-0)
- [BenchLM coding leaderboard](https://benchlm.ai/coding) (refreshed 2026-10-23)
- [OpenAI API pricing](https://developers.openai.com/api/docs/pricing)
- [Claude Opus 5.5 price cut and Claude 5.5 prices](https://www.usagepricing.com/blueprint/activity/anthropic-2026-10-05-opus-5-5-price-cut)
- [Vals AI: SWE-bench Verified](https://www.vals.ai/benchmarks/swebench) and [Terminal-Bench 2.0](https://www.vals.ai/benchmarks/terminal-bench-2), both archived
- [Morph's coding agent leaderboard](https://www.morphllm.com/best-ai-coding-agents-2026) (2026-10-06; Morph sells coding tools, so it was used only to cross-check)
