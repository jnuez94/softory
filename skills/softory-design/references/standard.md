# Softory design standard

Applies to every unit with a `ui` tag or `lane:design`. A project adds its own rules in `docs/design/DESIGN.md` but can't drop these. When two principles conflict, the higher one wins.

## Principles

1. **The user's job beats the look.** Every screen names the one question it answers. A design that can't say it isn't reviewable.
2. **What matters most is loudest, through more than color.** Priority shows through size, weight, position, and shape together. Color alone never carries meaning. One reserved color per project for its most urgent state, named in PRODUCT.md; nothing else uses it.
3. **Calm by default.** Motion only when it explains a change of state: something arrived, moved, or finished. None on keyboard actions, on screens seen many times a day, or for decoration. Every animation has a reduced-motion version.
4. **Design for the worst real data.** Long titles, empty states, huge counts, missing fields, non-Latin text, masked or private items. Each spec lists its worst cases; `docs/design/fixtures/` holds the shared set.
5. **Words are design.** Copy is written in the spec, not invented in code. One wording per state, kept in DESIGN.md's copy table.
6. **Fit the host.** Use the platform's theme variables and conventions, work in light and dark and at every size the host runs at, and load nothing remote the host doesn't allow.
7. **Accessible to WCAG 2.2 AA.** Contrast, visible focus, a keyboard path, labels, and targets of at least 24 by 24 px (DESIGN.md may raise it, for example 44 px on touch). Pass or fail, not opinion.
8. **Honest states.** Never fake a time, a count, or a success. Loading, stale, never synced, failed, and empty each look different.
9. **Fewer, better options.** At most three directions per story, with one recommended. Needing more means the problem isn't defined yet.
10. **No filler.** No default gradients, nested cards, generic icon tiles, or placeholder copy.

## Gates

| Gate | Owner | Passes when |
| --- | --- | --- |
| **Epic: product frame** | Greg; the owner approves once | `docs/product/PRODUCT.md` names users, jobs, non-goals, and the reserved color's meaning. No `ui` story starts without it. |
| **Story: design accepted** | Darwin builds; Greg accepts | The story's design task holds a spec (`docs/design/STORY-n.md`) with every section of the template filled. Greg's review accepts it. The owner is asked only when it adds a new pattern or breaks a DESIGN.md rule. |
| **Task: built to spec** | Jade builds | Build tasks wait until the story's design task is done. `softory verify` passes, including Impeccable's detector on the unit's own UI files (no error or warning) when it's installed. The rendered check against the spec (`ui_reference` evidence) shows the worst-case data without overflow, reduced motion, and the copy table's wording. |
| **Review: matches the spec** | Darwin (the owner for Darwin's own work) | The build matches the accepted spec. A new idea found here becomes a new design task, never an in-place change. |

## Rules for specs

- An accepted spec changes only through a new revision, `STORY-n-r2.md`, that says what changed and why. Never edit an accepted spec in place.
- A design task gets three review rounds, like any task. At the cap, Darwin splits it or asks Greg to cut scope.
- claude.ai artifacts and screenshots are for showing people. The repo files are the source of truth, so every role on every harness reads the same thing.
