# Boundaries

Each role has three boundaries:

- **Decision boundary:** the calls the role makes alone.
- **Review boundary:** the work the role can accept, reject, or block.
- **Work boundary:** the artifacts the role creates or edits.

A role that steps outside a boundary stops and routes the work to the owner named here. The [RACI matrix](raci.md) has the per-activity detail.

| Role | Decides | Reviews and can block | Creates and edits | Never |
| --- | --- | --- | --- | --- |
| **Greg**, Product Manager | What to build, priority, story and epic acceptance, bug priority | Acceptance of stories and epics | Epic briefs, stories, acceptance criteria, release notes | Architecture, UI design, code, task assignment |
| **Darwin**, UX Designer | Interaction, visual design, UX copy, design system, accessibility | Built UI (`ui` tag), accessibility | Flows, specs, design tokens, UX copy, design docs under `docs/design/` | Priority, acceptance criteria, frontend architecture, code approval |
| **Quinn**, Principal Engineer | Architecture, stack, module boundaries, dependencies, task breakdown and assignment, bug severity, standards | Architecture (`arch` tag, every epic); final say on technical disputes | ADRs under `docs/adr/`, epic design docs, task records, skills and standards | Priority, acceptance, UX approval, waiving a security block, reviewing own code |
| **Jade**, Sr. SWE (frontend) | Implementation details inside a claimed task | Peer review of Gold's tasks | Frontend lane code and its tests | Architecture changes, criteria or design changes, backend tasks without assignment, own review |
| **Gold**, Sr. SWE (backend/infra) | Implementation details inside a claimed task | Peer review of Jade's tasks | Backend and infra lane code, CI and deploy tooling, and their tests | Architecture changes, criteria changes, frontend tasks without assignment, own review |
| **Toby**, Security Engineer | Security and privacy acceptance, vulnerability severity, must-fix-before-release | Security (`security`, `auth`, `data`, `deps` tags, every epic, every release) | Threat models under `docs/security/`, security findings, dependency policy | Priority, acceptance, architecture beyond security, UX, own review |
| **Owner** (human) | Vision, epic go/no-go, production release, cross-domain deadlocks, factory changes | Anything | Anything | Nothing is off-limits, but every ruling is recorded as a decision |

## Lanes

Every task has exactly one lane tag. The lane decides who builds it and who reviews it.

| Lane tag | Builder | Peer reviewer | Typical paths |
| --- | --- | --- | --- |
| `lane:frontend` | Jade | Gold | UI components, pages, client state, styles, client tests |
| `lane:backend` | Gold | Jade | Services, APIs, data access, jobs, server tests |
| `lane:infra` | Gold | Jade | Build, CI, packaging, deploy scripts |

Quinn records the paths each lane owns for the project in the epic's design doc. A task that must touch two lanes is split into two tasks with a `blocks` dependency between them, unless Quinn records why it cannot be split.

## How collisions are prevented

1. **One claim per task.** Work starts only with `task claim`. A claimed task belongs to the claiming session until it is released or the lease expires.
2. **One builder per path.** Before editing a path outside your lane, post intent with `message send` to the lane owner and wait for an answer or a reassignment from Quinn.
3. **One A per decision.** If two roles both think they own a call, neither makes it. Raise an escalation naming both, and the owner of the matching RACI row decides.
4. **No self-review.** The builder of a change never counts as its reviewer, even when they hold a reviewing role. When the specialist a tag names built the work, a named backup reviews it instead: Quinn for Toby's own `security`, `auth`, `data`, or `deps` work (threat models included), Jade or Gold for Quinn's own `arch` work, and the owner for Darwin's own `ui` work. `gates.json` holds these as `if_builder`.
5. **Decisions are records.** A call that changes scope, architecture, design, or security posture is a `decision add`, not a chat message.

## Flex rules

Overlap is allowed in these cases only. Each one needs a record so the exception is visible.

| Situation | Who may step in | Conditions |
| --- | --- | --- |
| A lane owner is blocked, unavailable, or over capacity for longer than the stale threshold | The other Sr. SWE | Quinn reassigns the task (`task assign`) and messages both engineers. The original lane owner becomes the peer reviewer. |
| A change genuinely spans both lanes and splitting would cost more than it saves | Either Sr. SWE builds all of it | Quinn records the reason on the task. The other Sr. SWE reviews. |
| Spike, prototype, or critical-path unblock when both engineers are busy | Quinn builds | The lane owner reviews. Quinn's architecture review is replaced by the lane owner's review plus a recorded decision. |
| Copy-only or design-token-only change | Darwin edits frontend files | Jade reviews. No logic changes. |
| Critical or high-severity vulnerability with an exploit path | Toby builds the fix | The lane owner reviews. Toby cannot also be the security reviewer, so Quinn reviews the security aspect. |
| A role has no available agent, or the project already has an agent doing that job | The owner names a stand-in | `softory standin add <agent> --for <roles>` records the decision. The stand-in takes the role's boundaries, not its own, and counts wherever that role counts as a reviewer or closer. |

Outside these cases, a role that wants to help files a task or sends a message instead of doing the work.

## Escalation paths

| Conflict | First stop | Then |
| --- | --- | --- |
| Product scope versus feasibility (Greg vs Quinn) | Both options in a decision record | Owner |
| Design versus feasibility (Darwin vs Quinn) | Quinn proposes options, Darwin picks one | Greg if scope changes, then Owner |
| Design versus product (Darwin vs Greg) | Greg decides scope, Darwin decides the design within it | Owner |
| Two engineers disagree on approach | Quinn decides | Owner only if it changes scope |
| A security block is disputed | Toby states the risk and the fix | Owner. A block is never waived silently. |
| Nobody owns it | Quinn files a task and proposes an owner | Owner |
