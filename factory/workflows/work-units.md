# Units of Work

Softory works in three sizes. All three are tasks in the coordination database. The tags and the ID prefix say which kind each one is.

| Unit | Means | ID | Required tags | Owner (A) | Typical size |
| --- | --- | --- | --- | --- | --- |
| **Epic** | A project: an outcome that needs several features | `EPIC-n` | `unit:epic` | Greg | Days to weeks, 2 to 10 stories |
| **Story** | A feature: one user-visible increment | `STORY-n` | `unit:story`, `parent:EPIC-n` (optional) | Greg | 1 to 6 tasks |
| **Task** | A function: one change by one engineer | `TASK-n` | `unit:task`, `parent:STORY-n`, one `lane:*` | Lane owner | One pull request |
| **Bug** | A bug fix: a task that restores intended behavior | `BUG-n` | `unit:bug`, one `lane:*`, `parent:` optional | Lane owner | One pull request |

Review tags add required reviewers: `arch` (Quinn), `ui` (Darwin), and `security`, `auth`, `data`, or `deps` (Toby).

## Hierarchy

The parent is stored twice, so both people and the CLI can see it:

1. The child carries a `parent:<ID>` tag.
2. The parent has a `blocks` dependency on each child, so it can't pass `softory gate` until every child is done.

`softory new` does both. `softory tree EPIC-n` prints the hierarchy.

## Lifecycle

All units use the scaffold's five statuses: `todo`, `in_progress`, `review`, `blocked`, and `done`. The extra meaning per unit:

| Status | Epic | Story | Task or bug |
| --- | --- | --- | --- |
| `todo` | Brief written, and stays here while its stories are built | Written, and stays here while its tasks are built | Ready to claim |
| `in_progress` | Briefly claimed by Greg to assemble evidence before review | Briefly claimed by Greg to assemble evidence before review | Claimed by the builder |
| `review` | Waiting for Greg, Quinn, and Toby sign-off | Waiting for Greg's acceptance (and Darwin's, if `ui`) | Waiting for the peer review and any tag reviews |
| `blocked` | Waiting on the owner or an escalation | Waiting on a design, a decision, or a dependency | Waiting on another task or an answer |
| `done` | Accepted, after `softory gate` passes | Accepted, after `softory gate` passes | Reviewed, after `softory gate` passes |

Epics and stories don't sit in `in_progress` while children are built. A claim is a one-hour lease, and the scaffold's session sweep blocks tasks whose session goes quiet. `softory tree` shows progress instead.

## Epic flow

1. **Greg** writes the brief: `softory new epic --title ... --actor greg`. The description holds the problem, the user, the outcome, the success metric, and the non-goals. Use [templates/epic.md](../templates/epic.md).
2. **Darwin** adds UX direction. **Quinn** writes the ADRs and a design doc, including which paths each lane owns. **Toby** writes the threat model. Each one is recorded as an artifact and linked with `evidence add`.
3. **Owner** gives go/no-go. Greg records it as a decision.
4. **Greg** writes the stories: `softory new story --parent EPIC-n`.
5. The stories run (below).
6. When every story is done, Greg claims the epic, adds evidence, and releases it to `review`. **Quinn** (architecture) and **Toby** (security) review it, then **Greg** records the acceptance review.
7. Greg closes it with `softory close EPIC-n`.

## Story flow

1. **Greg** writes the story and its criteria with [templates/story.md](../templates/story.md).
2. If the story touches UI, **Darwin** writes the design spec in `docs/design/STORY-n.md` and links it as evidence.
3. **Quinn** breaks it into tasks: `softory new task --parent STORY-n --lane frontend|backend|infra [--tags arch,ui,...]`. Quinn sets `blocks` dependencies between tasks that must happen in order.
4. The tasks run (below).
5. When every task is done, Greg claims the story, adds evidence, and releases it to `review`. Darwin reviews it if it's tagged `ui`. **Greg** records acceptance.
6. Greg closes it with `softory close STORY-n`.

## Task flow (function or bug fix)

1. **Quinn** creates and assigns it. A bug can be filed by anyone with `softory new bug`. Greg sets its priority and Quinn sets its lane and assignee.
2. **The builder** (Jade or Gold) starts a session, claims the task, and follows the engineer's loop: plan, test first, build, verify, and add evidence.
3. The builder moves it to `review` and messages the peer reviewer plus any tag reviewers.
4. **Reviewers** record `review add --task TASK-n` with a decision. A `changes_requested` review sends it back to `in_progress` when the builder reclaims it.
5. **The builder** closes it with `softory close TASK-n`.

A bug fix always includes a test that fails before the fix and passes after it.

## Tasks from before softory

When softory joins a project that already has tasks, those tasks have no `unit:` tag. They keep the project's own process, and `softory tree` leaves them out unless you pass `--all`.

- `softory close` still works on them, under the minimum rule in `gates.json` (`legacy`): evidence, resolved blocking dependencies, no open rejection, and one accepted review from anyone but the builder. The assignee or the owner closes.
- To give one the full gate, Quinn adopts it into a story: `softory adopt VR-12 --unit task --parent STORY-3 --lane backend [--tags data] [--assignee gold]`. It keeps its ID and history, gains the unit tags, and the story then waits for it.
- If the project already has an agent doing a softory role's job, the owner names it a stand-in, for example `softory standin add avery --for jade,gold`.

## Definition of ready

| Unit | Ready when |
| --- | --- |
| Epic | The brief is complete, the owner said go, and the design doc and threat model exist |
| Story | INVEST is met, the criteria are testable, there's a design spec if `ui`, and Quinn has created the tasks |
| Task | It has one lane and an assignee, its criteria are checkable, its paths are named, and its blocking tasks are done |

## Definition of done

| Unit | Done when (all checked by `softory gate`) |
| --- | --- |
| Epic | Every story is done. Accepted reviews from Greg, Quinn, and Toby. Evidence exists. |
| Story | Every task is done. Accepted review from Greg, plus Darwin if `ui`. Evidence exists. |
| Task or bug | Evidence exists (PR or commit, test output). An accepted peer review from the other engineer, plus tag reviews. No self-review. |
