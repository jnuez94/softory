# RACI Matrix

Who does what, so two roles never own the same call.

- **R** (Responsible): does the work.
- **A** (Accountable): owns the outcome and makes the final call. Every row has exactly one A.
- **C** (Consulted): gives input before the call. A **C!** is consulted *with a block*: that role can stop the work on its own domain's grounds (see [boundaries](boundaries.md)), but cannot make the call.
- **I** (Informed): is told after the call.

`Owner` is the human project owner. `Lane owner` means Jade for the frontend lane and Gold for the backend and infra lanes.

## Product and planning

| Activity | Greg | Darwin | Quinn | Jade | Gold | Toby | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Project vision and goals | R | C | C | I | I | C | **A** |
| Epic brief: problem, outcome, success metric | **A/R** | C | C | I | I | C | I |
| Epic go/no-go before work starts | R | C | C! | I | I | C! | **A** |
| Backlog priority and sequencing | **A/R** | C | C | I | I | C | I |
| User stories and acceptance criteria | **A/R** | C | C | I | I | C | – |
| Bug priority (when to fix) | **A/R** | I | C | I | I | C | – |
| Bug severity (how bad) | C | C | **A/R** | C | C | C! | – |
| Story acceptance (story → done) | **A/R** | C! | I | I | I | I | – |
| Epic acceptance (epic → done) | **A/R** | C | C! | I | I | C! | I |
| Dropping a story or epic (won't do, superseded) | **A/R** | I | C | I | I | I | I |

## Design

| Activity | Greg | Darwin | Quinn | Jade | Gold | Toby | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| User flows and research | C | **A/R** | I | I | – | – | – |
| Interaction, layout, and visual design | C | **A/R** | C | C | – | – | – |
| UX copy | C | **A/R** | – | I | – | – | – |
| Design system: tokens, components, patterns | I | **A/R** | C | C | – | – | – |
| Accessibility standard and acceptance | I | **A/R** | C | C | – | – | – |
| Design review of built UI | I | **A/R** | – | I | – | – | – |

## Architecture and engineering

| Activity | Greg | Darwin | Quinn | Jade | Gold | Toby | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Architecture, stack, data model (ADRs) | I | I | **A/R** | C | C | C! | – |
| Epic technical design doc | I | C | **A/R** | C | C | C | – |
| Story breakdown into tasks | C | C | **A/R** | C | C | I | – |
| Task lane and assignment | I | – | **A/R** | I | I | – | – |
| Dropping a task or bug (won't do, superseded) | C | – | **A/R** | I | I | – | – |
| Coding standards, skills, test strategy | – | – | **A/R** | C | C | C | I |
| Adding a third-party dependency | – | – | **A** | R | R | C! | – |
| Technical disputes between engineers | – | – | **A/R** | C | C | C | – |

## Build

| Activity | Greg | Darwin | Quinn | Jade | Gold | Toby | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Frontend lane task (UI, client state) | I | C | C | **A/R** | – | – | – |
| Backend lane task (services, APIs, data) | I | – | C | – | **A/R** | C | – |
| Infra lane task (build, CI, deploy tooling) | – | – | C | I | **A/R** | C | – |
| Frontend bug fix | I | C | C | **A/R** | – | – | – |
| Backend or infra bug fix | I | – | C | – | **A/R** | C | – |
| Spikes and prototypes | I | C | **A/R** | C | C | – | – |

Tests are part of the task: whoever is A/R for a task writes and owns its tests.

## Review and security

| Activity | Greg | Darwin | Quinn | Jade | Gold | Toby | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Peer code review (the other lane reviews) | – | – | **A** | R (Gold's tasks) | R (Jade's tasks) | C | – |
| Architecture review (`arch` tag, every epic) | – | – | **A/R** | I | I | – | – |
| Design review (`ui` tag) | I | **A/R** | – | I | – | – | – |
| Threat model per epic | I | – | C | I | C | **A/R** | – |
| Security review (`security`, `auth`, `data`, `deps` tags) | – | – | I | I | I | **A/R** | – |
| Secrets and sensitive-data rules | I | – | C | I | I | **A/R** | I |
| Vulnerability severity and must-fix | C | – | C | I | I | **A/R** | I |

## Release and coordination

| Activity | Greg | Darwin | Quinn | Jade | Gold | Toby | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Release readiness checklist | C | C | **A/R** | C | C | C! | I |
| Release go/no-go recommendation | **A/R** | C | C! | I | I | C! | I |
| Production release and external sharing | C | – | C | I | R | C! | **A** |
| Cross-domain deadlock | C | C | C | C | C | C | **A** |
| Changes to roles, RACI, gates, skills | C | C | R | C | C | C | **A** |

## Reading the matrix

- **One A per row.** If two roles seem to own the same call, the row is missing a split. Add one, don't share the A.
- **C! is a block, not a vote.** Toby can stop a release on security grounds but cannot decide to release. Quinn can stop an epic on feasibility but cannot decide it is worth doing.
- **A without R** (Quinn on dependencies) means the A approves and an engineer does the work.
- Where the matrix says `–`, the role stays out unless a [flex rule](boundaries.md#flex-rules) applies.

Machine-checked parts of this matrix live in [gates.json](gates.json) and are enforced by `softory gate`.
