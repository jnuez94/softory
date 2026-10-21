# Working on softory itself

This file is for agents changing the softory repository. It is not installed into projects. `factory/INSTRUCTIONS.md` is what projects get.

- **Standard library only.** The CLI and installer must run on a clean Python 3.10+, like the scaffold and the tracker.
- **Never open the coordination database.** Go through the CLI wrapper in `lib/softory/coordination.py`.
- **Keep governance consistent.** A role change touches `factory/roles/roster.json`, the role's profile, `governance/raci.md`, `governance/boundaries.md`, and possibly `governance/gates.json`. `tests/test_governance.py` checks the parts that can be checked.
- **Keep `factory/INSTRUCTIONS.md` small.** It is loaded into every session (under 6 KB, tested). Detail belongs in profiles, workflows, and skills, which load on demand.
- **Never write to a tracked file in a target project.** The installer's promise is an unchanged `git status`. The integration tests check this.
- **Run the tests** before committing:

  ```sh
  SOFTORY_SCAFFOLD_SRC=../agentic-project-scaffold-lite SOFTORY_TRACKER_SRC=../agentic-scaffold-project-task-tracker \
    python3 -m unittest discover -s tests -t .
  ```

- Keep modules under about 250 lines, one concern each, like the scaffold.
