Work on milestone $ARGUMENTS of the QQQ 1DTE project.

1. Read `docs/MILESTONES.md` for this milestone's scope, dependencies, and acceptance criteria. If any dependency is not marked done, stop and tell me.
2. Read the relevant sections of `docs/MASTER_PROMPT.md` and `docs/PHASE_1_SPEC.md`.
3. List anything ambiguous or any spec definition this milestone would need to change. Ask me before proceeding if there is anything.
4. Propose a plan: files to create/modify, tests to write first, and how each acceptance criterion will be demonstrated. Wait for my approval.
5. Implement tests first, then code. Keep scope to this milestone only.
6. Run `uv run pytest`, `uv run ruff check .`, `uv run mypy src`. Fix failures.
7. Update `docs/MILESTONES.md`: mark criteria met with evidence (test names, report paths), note open issues.
8. Summarize what was done, what wasn't, and any risks discovered.
