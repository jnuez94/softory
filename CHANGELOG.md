# Changelog

## [0.1.0] - 2026-10-21

First release.

- Six roles with decision, review, and work boundaries: Greg (Product Manager), Darwin (UX Designer), Quinn (Principal Engineer), Jade and Gold (Senior Software Engineers, frontend and backend/infra lanes), and Toby (Security Engineer).
- RACI matrix with one accountable role per activity, flex rules for allowed overlap, and escalation paths.
- Units of work: epic (project), story (feature), task (function), and bug (fix), with templates and flows.
- Nine skills: operating loop, code quality, testing, code review, secure coding, design, product spec, architecture, and token economy.
- `softory` CLI: `start`, `new`, `tree`, `adopt`, `queue`, `reviewers`, `gate`, `close`, `standin`, `roles`, `doctor`, `tracker`, `sync`, `skills`, `uninstall`.
- Installer that adds scaffold 1.4.0 (SQLite) and the tracker, registers the roles, and hides everything with `.git/info/exclude`.
- A catalog of recommended open-source skills, pulled at pinned commits.
- Joining a project that already has a team: `softory standin` for existing agents, a minimum `legacy` gate for tasks created before softory, `softory adopt` to move them into a story, and no repeated scaffold block when the project's `AGENTS.md` already has it.
