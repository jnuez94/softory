# Units of Work

Softory works in three sizes, plus review records and releases. All of them are tasks in the coordination database. The tags and the ID prefix say which kind each one is.

| Unit | Means | ID | Required tags | Owner (A) | Typical size |
| --- | --- | --- | --- | --- | --- |
| **Epic** | A project: an outcome that needs several features | `EPIC-n` | `unit:epic` | Greg | Days to weeks, 2 to 10 stories |
| **Story** | A feature: one user-visible increment | `STORY-n` | `unit:story`, `parent:EPIC-n` (optional) | Greg | 1 to 6 tasks |
| **Task** | A function: one change by one engineer | `TASK-n` | `unit:task`, `parent:STORY-n`, one `lane:*` | Lane owner | One pull request |
| **Bug** | A bug fix: a task that restores intended behavior | `BUG-n` | `unit:bug`, one `lane:*`, `parent:` optional | Lane owner | One pull request |
| **Release** | One commit of the base on its way to production | `RELEASE-n` | `unit:release` | Gold builds, Greg closes | One base commit |

Review tags add required reviewers: `arch` (Quinn), `ui` (Darwin), and `security`, `auth`, `data`, or `deps` (Toby), and `process` (Sage) for a new or changed workflow, script, packaging step, or generated artifact.

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

Epics and stories don't sit in `in_progress` while children are built. A claim is a one-hour lease, and the scaffold's session sweep blocks tasks whose session goes quiet. Instead the runner marks a story or epic **active** once one of its children has started (`task list --active`), with no claim and nothing for the sweep to block, and `done` clears it. `softory tree` shows progress.

The scaffold enforces the basics itself (strict closure and dependencies): no `done` without an accepted review from someone other than a builder, and no claim on work with an open `blocks` dependency. Review records are exempt, a drop cites its decision, and `softory close` cites the gate's verdict where softory's rules differ, as when Greg accepts the story he owns.

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
2. If the story touches UI, Greg creates it with `--design`, which files a `lane:design` task for **Darwin** right away. Darwin writes the design spec in `docs/design/STORY-n.md` under that task, before Quinn's breakdown, following the design standard (the `softory-design` skill's `references/standard.md`) and the project's PRODUCT.md and DESIGN.md. Greg's review of the design task is the design acceptance; the owner is asked only for a new pattern or a break from DESIGN.md.
3. **Quinn** breaks it into tasks: `softory new task --parent STORY-n --lane frontend|backend|infra|design [--tags arch,ui,...]`. Quinn sets `blocks` dependencies between tasks that must happen in order.
4. The tasks run (below).
5. When every task is done, Greg claims the story, adds evidence, and releases it to `review`. Darwin reviews it if it's tagged `ui`. **Greg** records acceptance.
6. Greg closes it with `softory close STORY-n`.

To amend a story's criteria after work started, Greg records the decision first (`softory ruling` for the owner's word, else `decision add`), then runs `task update STORY-n --acceptance "..." --if-revision <rev> --actor greg`. No claim is needed, and the change runs the feasibility check again.

## Task flow (function or bug fix)

1. **Quinn** creates and assigns it. A bug can be filed by anyone with `softory new bug --type functional|visual [--found-at build|verify|review|acceptance|staging|production]`. A bug that turns out not to be a defect is dropped with `softory drop BUG-n --withdrawn --reason ...`. Greg sets its priority and Quinn sets its lane and assignee.
2. **The builder** (Jade or Gold) starts a session, claims the task, and follows the engineer's loop: plan, test first, build, verify, and add evidence.
3. The builder moves it to `review` and messages the peer reviewer plus any tag reviewers.
4. **Reviewers** record `review add --task TASK-n` with a decision. A `changes_requested` review sends it back to `in_progress` when the builder reclaims it.
5. **The builder** closes it with `softory close TASK-n`.

A bug fix always includes a test that fails before the fix and passes after it.

`softory queue` lists your tasks in review that pass the gate under `ready_to_close`. Close those first.

## Follow-ups from a review

A required change found in review becomes its own unit: `softory new bug --type functional|visual --from TASK-7 --title "..."`. It inherits the source's story and lane, carries a `from:TASK-7` tag, and links back to the source with an `informs` dependency. The source doesn't wait for it, so a chain of fixes never holds up the work above it. Add `--blocks-source` when the source truly can't close first. List the follow-ups in the review's `--follow-up-tasks`. Don't file follow-ups with plain `task create`: they would miss the story and close under the lighter rule for older tasks.

## Review runs

A reviewer who wants to claim a long review, heartbeat through it, and attach a report keeps the run as a review record: `softory new review --title "..." --for TASK-7,BUG-2`. A record is the reviewer's output, so:

- Nobody reviews it again, unless a tag on it needs a reviewer its author isn't. A `security` record by Toby (or Toby's stand-in) stands on its own; one by anyone else needs Toby to accept it. So relabelling your own security fix as a review never skips Toby.
- Its own verdicts never block it. The reviewer may record the verdict on the record or on each reviewed task.
- A "changes requested" on it counts as handled when it names follow-up tasks that exist, or when that reviewer later accepts.
- It holds reports, not code, and its reviewer didn't build what it reviewed.
- Its reviewer or the owner closes it, from review, blocked, or todo.

For a review run from before softory, its reviewer (or the owner) runs `softory adopt VR-REVIEW-12 --unit review`. It reads what the run reviewed from its `informs` links, leaving out other review runs and the reviewer's own work; add `--for BUG-3` when the run has no links. That only asks: a record closes on its author's own verdict, so turning existing work into one would let a builder close their own work unreviewed. The owner checks the list, where anything not tagged or named as a review run comes first, and approves it in one go with `softory approve --all` at a terminal.

## Work nobody will build

Plans change. A unit that won't be built closes as dropped, with a reason and a decision record: `softory drop TASK-9 --reason "..."`, or `--superseded-by TASK-12` when another unit replaces it. Quinn, Greg, or the owner drops tasks and bugs; Greg or the owner drops stories and epics. A unit with open children can't be dropped. `softory tree` shows it as `done: won't do` or `done: superseded by TASK-12`, and its parent stops waiting for it.

## Stacked work

When a fix has to build on another unit that isn't closed yet, the engineer branches from it and records the stack, bottom first: `softory stack BUG-5 BUG-15`. That links each member to the one below with an `informs` dependency, which means "built on" and never blocks a claim; `blocks` means "can't start until". Each member keeps its own reviews. `softory close BUG-15 --stack` checks every open member's gate, counting the other members as done, and closes them all bottom first, or none if any fails its gate. If a close call itself fails partway, softory stops and reports what it closed.

## Merging and shipping

With the charter's `merge.by` set to `softory`, nobody merges by hand and no role pushes to the base branch. `softory ship`, which the runner starts each tick, merges the units that closed through the gate: up to `merge.batch_max` of them become one candidate commit, and the base moves only when `softory verify` passes there. A batch that fails is tried one unit at a time. A unit that conflicts or fails on its own stays off the base, and its builder gets a priority 1 bug to fix it on top of the base. A unit built on another unit's work waits until that unit closes.

**The base stays green.** Whenever the base moves, softory verifies it. A red base gets one priority 1 bug for Gold, and nothing else merges until that bug's fix does.

After each merge, softory deploys the new base to every `auto` target in the charter (`deploy.targets`, for example a preview or staging environment) and runs the target's smoke test. A failure files a priority 1 bug.

**Releases.** Gold opens a release when Greg asks for one: `softory new release --title "..."` records the base commit it ships. Gold attaches the rollback plan (`softory report RELEASE-n plan.md --type rollback`) and hands it off. Toby and Quinn review it, and Greg closes it once every target but production passed at that commit (`softory deploy staging --release RELEASE-n` if it never deployed). Production is the owner's: `softory deploy production --release RELEASE-n`, at a terminal, after the release closes.

## Tasks from before softory

When softory joins a project that already has tasks, those tasks have no `unit:` tag. They keep the project's own process, and `softory tree` leaves them out unless you pass `--all`.

- **Triage before planning.** Many old open tasks are finished work nobody closed. `softory triage` lists open tasks that already have an accepted review, older review runs to adopt, sessions to end or restart, and roles that have gone silent. Check each task against the code, and close what's done or drop what won't be built.
- `softory close` still works on them, under the minimum rule in `gates.json` (`legacy`): evidence, resolved blocking dependencies, no open rejection, and one accepted review from anyone but the builder. The assignee or the owner closes.
- To give one the full gate, Quinn adopts it into a story: `softory adopt VR-12 --unit task --parent STORY-3 --lane backend [--tags data] [--assignee gold]`. It keeps its ID and history, gains the unit tags, and the story then waits for it.
- If the project already has an agent doing a softory role's job, the owner names it a stand-in, for example `softory standin add avery --for jade,gold`. A stand-in can be limited to tasks (`--task VR-SEC-1,VR-SEC-2`) and given an end date (`--until 2026-10-31`). Agents ask for one with `softory propose standin`; the owner applies it with `softory approve`.

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
| Task or bug | Evidence exists (PR or commit, test output). An accepted peer review from the other engineer, plus tag reviews. No self-review. Its own commits add no secrets. |
| Review run | Evidence exists (the report), and no code evidence. Each review tag on it (`security`, `ui`, ...) is covered by its author or signed off by that tag's reviewer. It names what it reviewed (`for:`), which its reviewer didn't build. The reviewer's verdict is on the record or on every reviewed task. Every "changes requested" on it names follow-up tasks that exist. |
| Release | Accepted reviews from Toby and Quinn. A rollback plan in its evidence. Every deploy target but production passed its deploy and smoke test at the release's commit. |
| Dropped | A recorded decision says won't do or superseded, by an allowed dropper, with no open children. |
