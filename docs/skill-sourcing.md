# Skill sourcing: build or pull

Softory writes its own skills only where the skill encodes **softory's own rules**: roles, gates, the CLI loop, and the quality bar the reviewers enforce. Where a well-maintained open-source skill already does the job, softory **pulls it at a pinned commit** instead of rebuilding it. Nothing is vendored into this repo, so each skill keeps its own license.

```sh
.agents/softory/bin/softory skills list                 # catalog, with what's installed
.agents/softory/bin/softory skills add --recommended    # everything marked recommended
.agents/softory/bin/softory skills add semgrep sharp-edges
```

Pulled skills go into `.claude/skills/` and `.agents/skills/` next to softory's own, are hidden from git the same way, and carry a `SOURCE.txt` with the repository, commit, and license. The pins are in [external-skills.json](../external-skills.json).

## Built by softory (9)

| Skill | Why it's ours |
| --- | --- |
| `softory-operating-loop` | Softory's CLI flow: start, claim, evidence, review, gate, close |
| `softory-code-quality` | The readability, reuse, maintainability, and testability bar the reviewers enforce, with a rubric |
| `softory-testing` | What each unit of work must prove, mapped to the gate's evidence rule |
| `softory-code-review` | Who reviews what, in which order, and how to record it in coordination |
| `softory-secure-coding` | Engineer rules plus Toby's threat-model and review procedure (OWASP Top 10:2025) |
| `softory-design` | Darwin's flow, states, WCAG 2.2 AA, and handoff spec |
| `softory-product-spec` | Greg's briefs, stories, criteria, triage, and acceptance |
| `softory-architecture` | Quinn's ADRs, design docs, lane ownership, and task breakdown |
| `softory-token-economy` | Read-less and write-less habits, tied to softory's CLI |

## Pulled from open source

### Design

| Skill | Source | License | Recommended | Why pull it |
| --- | --- | --- | --- | --- |
| `frontend-design` | [anthropics/skills](https://github.com/anthropics/skills) | Apache-2.0 | Yes | Aesthetic direction for new UI. `softory-design` covers flows, states, and accessibility, but not visual taste. |
| `web-design-guidelines` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) | MIT | Yes | Automated review of built UI against the Web Interface Guidelines. It fetches the rules at run time, so it needs network access. |
| `webapp-testing` | anthropics/skills | Apache-2.0 | Yes | Playwright checks and screenshots, which become evidence for `ui` tasks |
| `react-best-practices` | vercel-labs/agent-skills | MIT | React only | Performance rules for React and Next.js |

### Coding

| Skill | Source | License | Recommended | Why pull it |
| --- | --- | --- | --- | --- |
| `test-driven-development` | [obra/superpowers](https://github.com/obra/superpowers) | MIT | Yes | Enforces the red-green-refactor loop that `softory-testing` asks for |
| `systematic-debugging` | obra/superpowers | MIT | Yes | Root cause before fix, for `BUG` units |
| `verification-before-completion` | obra/superpowers | MIT | Yes | "Run the checks before you claim done." Small (3.6 KB) and matches the gate |
| `ponytail` | [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) | MIT | Yes | The smallest complete change. It reuses what exists and skips speculative code, but never cuts validation, error handling, security, or a test for risky logic. See token savings below. |
| `ponytail-review` | DietrichGebert/ponytail | MIT | Optional | A lean-code lens for peer review: delete, reuse, stdlib, yagni. `softory-code-review` stays the procedure. |
| `receiving-code-review` | obra/superpowers | MIT | Optional | How to weigh review feedback before applying it |
| `property-based-testing` | [trailofbits/skills](https://github.com/trailofbits/skills) | CC-BY-SA-4.0 | Optional | For parsers, serializers, and money or date logic |

### Security

| Skill | Source | License | Recommended | Why pull it |
| --- | --- | --- | --- | --- |
| `differential-review` | trailofbits/skills | CC-BY-SA-4.0 | Yes | Security review of a diff with blast radius. This is Toby's main tool |
| `fp-check` | trailofbits/skills | CC-BY-SA-4.0 | Yes | Verifies a finding is real before Toby blocks on it |
| `supply-chain-risk-auditor` | trailofbits/skills | CC-BY-SA-4.0 | Yes | Backs the `deps` review (OWASP A03:2025) |
| `semgrep` | trailofbits/skills | CC-BY-SA-4.0 | Once installed | Static analysis, when the project has Semgrep |
| `sharp-edges` | trailofbits/skills | CC-BY-SA-4.0 | Optional | Finds footgun APIs in new interfaces |

Trail of Bits skills are CC-BY-SA-4.0, a share-alike license. Pulling them into a project at install time is fine, but copying them into softory itself would put those files under CC-BY-SA. That's one more reason softory pins them instead of vendoring.

## Token savings: what works

The biggest lever is **reading less**, not talking less. `softory-token-economy` covers both, and these choices keep the always-loaded cost down:

- **Instructions stay small.** Softory's block in `AGENTS.md` is under 6 KB. Role profiles, the RACI, and the workflows load only when an agent needs them. Codex stops reading project docs at 32 KiB.
- **Skills load on demand.** Only a skill's name and description sit in context until it's used.
- **The CLI does the filtering.** `softory queue`, `softory tree`, and `softory gate` return just what an agent needs, instead of the agent paging through `task list`, `review list`, and `inbox list`.
- **Write less code.** Pull [Ponytail](https://github.com/DietrichGebert/ponytail)'s `ponytail` skill for the builders. Fewer lines means fewer tokens to write, review, and read again later. Its author's benchmark (39 Claude Code tasks, 5 runs each) reports 45% fewer tokens, 53% less code, and more risky logic shipped with a test. Those numbers are self-reported, and softory hasn't reproduced them. Pull the skill, not the plugin: the plugin adds session hooks, a status band, and a local board. Without them the skill runs at its default `full` level. Where the two disagree, softory's rules win: every bug fix still gets a test that fails first, and the gate still needs evidence.
- **Cherry-pick, don't install whole plugins.** Pulling three superpowers skills costs about 55 KB on disk and nothing in context until used. The full plugin adds a session-start hook that injects instructions into every session.

### Considered and not recommended

| Skill | Why not |
| --- | --- |
| [caveman](https://github.com/JuliusBrussee/caveman) (output compression) | Its own benchmark shows a plain "be concise" rule gets almost all of the output savings, with about 3% more from caveman at the median, while the rules cost about 1,160 input tokens per session. Its input-compression proxy is promising, but it is early and sends data to an external service in some modes. Revisit if input costs dominate. |
| superpowers `using-superpowers` + session hook | Forces a skill check before every response, which costs tokens on every turn and overlaps softory's operating loop |
| superpowers `brainstorming`, `writing-plans`, `subagent-driven-development` | Overlap with Greg's specs and Quinn's task breakdown, and would create a second planning flow that bypasses the roles |
| [ui-ux-pro-max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | Useful style catalog, but about 10 MB of data and its own design-system generator would compete with Darwin's tokens. Optional if Darwin wants a palette and font starting point. |
| anthropics `docx`, `pdf`, `pptx`, `xlsx` | Source-available, not open source, and not needed for building software |
