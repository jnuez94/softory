# Design spec: STORY-n <title>

Revision: r1 · Changes from the last revision: <none, or what changed and why>

## The question this screen answers
<One sentence, in the user's words.>

## Flow
1. <Entry point>
2. <Step>
3. <Goal reached>
- Exits: <cancel, back, error>

## Options considered
At least three materially different options, including the simplest existing, native, or manual one. No renamed variants. This section stays after the choice.

| Option | How it works | Pros | Cons |
| --- | --- | --- | --- |
| A (RECOMMENDED) | | | |
| B | | | |
| C | | | |

## Requirements comparison
One row per requirement, stated as a user outcome, never as a technology. Each cell says Meets, Partly, Fails, or Unknown, then how and on what evidence. Unknown stays unknown, with no invented scores. A failed Must is never traded for other strengths.

| Requirement (ID, Must or Should, source, target) | A | B | C |
| --- | --- | --- | --- |
| FR-1 <behavior> | | | |
| NFR-1 <quality: privacy, reliability, speed, setup, upkeep, reversibility> | | | |

**Recommendation:** <the option, why by requirement ID, and what evidence would change the choice>

## Screens and components

### <Screen or component name>
| State | What the user sees | Copy |
| --- | --- | --- |
| Empty | | |
| Loading | | |
| Success | | |
| Stale | | |
| Error | | |
| No permission | | |

Components and tokens: <existing names. Mark new ones NEW, with the reason. A new pattern needs the owner's OK.>

## Worst-case data
| Case | Expected result |
| --- | --- |
| Longest real title | |
| Empty | |
| Largest count | |
| Missing field | |
| Non-Latin text | |
| Masked or private item | |

## Interaction
- Clickable or focusable elements, and keyboard behavior
- Focus after each action
- What animates and why (a change of state only), and its reduced-motion version

## Responsive
- <Behavior at each size the host runs at, including phone if it does>

## Accessibility notes
- Roles, labels, live announcements, contrast pairs used, target size

## Out of scope
- <What this spec doesn't cover>
