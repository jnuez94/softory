---
name: softory-design
description: Darwin's UX design practice in softory, covering user flows, screen states, UX copy, design tokens and the design system, WCAG 2.2 AA accessibility, the handoff spec, and design review. Use when designing or reviewing any user-facing feature, writing a design spec, or adding to the design system.
---

# UX design

## Order of work for a story with a `ui` tag

Read `references/standard.md` (softory's ten principles and four design gates) and the project's `docs/product/PRODUCT.md` and `docs/design/DESIGN.md` first. If either project file is missing, write DESIGN.md from `.agents/softory/factory/templates/DESIGN.md` (Greg writes PRODUCT.md) before the first `ui` story.

1. **Understand.** Read the story, its criteria, and the epic's UX direction. Name the one question the screen answers.
2. **Flow.** List the steps from entry to goal, plus every exit: cancel, error, and back. Keep the flow short, and remove steps before polishing them.
3. **States.** For every screen or component in the flow, design these states: **empty, loading, partial, success, error, stale, and no-permission**. Add offline if the app works offline.
4. **Worst-case data.** List the worst real data for each screen and check the design against it, using `docs/design/fixtures/`.
5. **Layout and components.** Use existing design-system components and tokens first. A new component needs a reason in the spec. Show at most three directions, with one recommended.
6. **Copy.** Write every label, button, empty state, error, and confirmation (rules below), and add new wording to DESIGN.md's copy table.
7. **Accessibility.** Bake it into each decision (checklist below). It's not a final pass.
8. **Spec.** Write `docs/design/STORY-n.md` using `references/spec-template.md`, and link it as evidence on the design task. After acceptance, revise with `STORY-n-r2.md`, never in place.

## Heuristics to check every design against

From Nielsen's ten usability heuristics:

1. Show system status, so the user always knows what is happening.
2. Match the real world, using the user's words rather than internal jargon.
3. Give users control and freedom, with undo and cancel and no dead ends.
4. Be consistent: same thing, same name, same place.
5. Prevent errors with constraints, defaults, and confirmation for destructive actions.
6. Prefer recognition over recall, so options are visible.
7. Offer flexibility, such as shortcuts for frequent actions.
8. Keep it minimal, showing only what the task needs.
9. Help users recover from errors: say what happened and how to fix it.
10. Provide help in context where it's needed.

## UX copy rules

- Use the user's words. Put the action first on buttons: "Save draft", not "OK".
- Errors say what happened and what to do, without blame or codes: "That date is in the past. Pick today or later."
- Empty states say what goes here and how to add the first one.
- Keep sentence case and consistent terms. Pick one word per concept and keep it.

## Accessibility checklist (WCAG 2.2 AA)

- Text contrast is at least 4.5:1, or 3:1 for large text, UI component borders, and focus indicators.
- Everything works with a keyboard, the focus order follows the visual order, and focus is always visible and never hidden behind sticky UI.
- Targets are at least 24 by 24 CSS pixels, or DESIGN.md's size if it sets a larger one.
- Every input has a visible label. Errors are announced and tied to their field.
- Color is never the only signal.
- Motion respects reduced-motion preferences. Nothing flashes more than 3 times per second.
- Dynamic updates such as toasts and loading are announced to screen readers.
- No drag-only interaction. Offer a single-pointer alternative.

## Design system

- **Tokens are the source of truth** for color, type scale, spacing, radius, shadow, and motion. Code uses tokens, never raw values.
- A component entry documents its purpose, variants, states, props, accessibility notes, and do/don't examples.
- Change the system in its own task, tagged `ui`, so the change is reviewed once and reused everywhere.

## Pulled design skills (when installed)

Emil Kowalski's skills (`softory skills add prototype break-ui emil-design-eng review-animations remove-animations`) fit inside softory's rules. Where they differ, the standard, DESIGN.md, and your lane win. `prototype` and `review-animations` are manual-only in Claude, so read their `SKILL.md` from `.claude/skills/` (Codex: `.agents/skills/`).

- **`prototype` (Darwin):** use its static-file branch. Build the directions in one HTML file at `docs/design/STORY-n/directions.html`, never in app code. Show at most three, and recommend one, which overrides its "never pre-pick" rule. Greg chooses at acceptance, and the file stays as part of the spec.
- **`break-ui`:** Darwin lists each value's worst case and writes `docs/design/fixtures/`. Jade wires the dev-only toggle in a `frontend` task and attaches the report as `visual` evidence.
- **`emil-design-eng`, `review-animations` (Jade, Darwin):** Jade checks against them while building and before review. Darwin uses `review-animations` in design review.
- **`remove-animations` (Jade):** only in a `frontend` task, and only to remove motion the standard rules out.

## Design review (when built UI reaches `review`)

Compare the built UI to the accepted spec and DESIGN.md, and run `review-animations` on any motion if it's installed. Request changes for a missing state, an accessibility failure, hard-coded values, or copy drift. Accept visual differences only if they're recorded and agreed. A new idea becomes a new design task, not a change to this one. Attach screenshots of what you checked.
