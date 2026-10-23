---
name: softory-architecture
description: Quinn's architecture practice in softory, covering ADRs, epic technical design docs, lane path ownership, story-to-task breakdown, dependency approval, and architecture review. Use when choosing technology or structure, writing an ADR or design doc, breaking a story into tasks, approving a dependency, or reviewing an arch-tagged change.
---

# Architecture

## Principles

- **Boring by default.** Choose proven technology the team knows. Novelty needs a recorded reason.
- **Reversible over perfect.** Prefer decisions that are cheap to undo, and decide irreversible ones slowly and on the record.
- **Clear boundaries.** Each module owns its data and exposes a small interface. Dependencies point inward, toward the domain.
- **Respect what came before.** Understand why the existing design is the way it is before replacing it.
- **Write it down.** A decision that lives only in a chat or a review comment doesn't exist.

## ADRs

One file per decision in `docs/adr/NNNN-title.md`, using `references/adr-template.md`. Also record it in coordination: `decision add --owner quinn --title "ADR-NNNN ..." --status accepted`. To change a decision, supersede it with a new ADR that links the old one. Never edit history.

## Epic design doc

`docs/adr/EPIC-n-design.md`, written before go/no-go:

1. Context and constraints: from the brief and the existing system.
2. Components and data flow: a small diagram or list.
3. Interfaces and contracts: APIs and schemas, with types.
4. **Lane path ownership:** which directories belong to `lane:frontend`, `lane:backend`, and `lane:infra`.
5. Risks and how each is retired. Spikes become tasks.
6. Rollout and rollback.
7. ADRs created or affected.

## Breaking a story into tasks

For each story:

1. List the changes the criteria need, by lane.
2. Cut tasks so that each has **one lane, one builder, one concern, and fits in one PR** (aim for under about 400 changed lines).
3. Put contracts first. When a frontend task depends on a new API, create the backend contract task first and add a `blocks` dependency.
4. Create each one: `softory new task --parent STORY-n --lane <lane> --title "..." --tags <arch,ui,security,...> --actor quinn`, with the template in `.agents/softory/factory/templates/task.md`.
5. Tag the reviews: `arch` if it changes a boundary, contract, or data model; `ui` if a user sees it; and `security`, `auth`, `data`, or `deps` per `softory-secure-coding`.
6. Name the paths the task touches and must not touch.

## Approving a dependency

Approve only if all of these hold: it solves a real need the standard library or existing dependencies don't; it's actively maintained; its license fits; its transitive footprint is acceptable; and Toby hasn't blocked it. Record the approval on the task.

## Architecture review (`arch` tag, and every epic)

Check the change against the ADRs and the design doc: boundaries respected, interfaces small and explicit, data ownership clear, failure handling at the right layer, no speculative generality, and testable without heroics. If the change implies a new decision, ask for an ADR before accepting.

## Disputes between engineers

Hear both options in one message thread. Decide within one working cycle and record the decision with the rejected option and the reason. Escalate to the owner only if the decision changes scope.

Sources: Michael Nygard, [Documenting Architecture Decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions). Will Larson, [Staff archetypes](https://staffeng.com/guides/staff-archetypes/). Amazon, [Principal Engineering Community Tenets](https://amazon.jobs/en/landing_pages/pe-community-tenets).
