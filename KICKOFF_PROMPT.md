Paste this into Claude Code (in plan mode) for the first session.

---

Read CLAUDE.md, docs/MASTER_PROMPT.md, and docs/MILESTONES.md. We are starting Milestone 1 only.

Do the following, then stop for my review. Do not write application code beyond the repo skeleton.

1. Restate the architecture in your own words (short).
2. Draft docs/PHASE_1_SPEC.md covering every item in Phase 1A. Where the master prompt leaves a value
   open, propose a default, mark it PROPOSED, and give a one-line rationale.
3. Add an "Open Decisions" section to the spec. At minimum include:
   - Definition of 1DTE given QQQ's expiration history (daily expirations only since ~late 2022 — verify), and the resulting usable history window
   - Intraday-only exits vs overnight holds
   - The frozen mechanical option-selection rule used for option-outcome labels
   - Prediction cadence vs effective sample size given overlapping labels; how one-position-at-a-time interacts with 5-minute signals
   - Numeric thresholds for every Phase 1V gate (min samples, max ECE, min paper-trading duration, etc.)
   - Definition of the "moderate" fill model
   - How OI (daily, prior-day) and vendor IV/Greeks are treated
   - Logging of every configuration tested, for multiple-testing correction
   - Initial coarse regime set sized to the available sample
4. Draft docs/ARCHITECTURE.md: modules, data flow, where point-in-time enforcement lives in code.
5. Propose the initial database schema (tables from Phase 1C) as a reviewable SQL/markdown draft, not migrations yet.
6. Propose the first test suite (names + what each proves), especially leakage and timestamp tests.
7. Fill in acceptance criteria for M3–M22 in docs/MILESTONES.md.
8. Create the repo skeleton with uv, pyproject.toml, ruff, mypy, pytest, and a GitHub Actions CI workflow.

Ask me about the Open Decisions before treating anything in the spec as final.
