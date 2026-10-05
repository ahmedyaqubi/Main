# QQQ 1DTE Research & Validation Engine

Research software that determines whether a QQQ 1DTE options strategy has a real,
calibrated, cost-adjusted edge. It is NOT a trading bot. Phase 1 never places orders.

## Source of truth
- `docs/MASTER_PROMPT.md` — full requirements (read the relevant section before each milestone).
- `docs/PHASE_1_SPEC.md` — frozen definitions (targets, windows, fills, gates). The constitution.
- `docs/MILESTONES.md` — status, acceptance criteria, what's next.
- `docs/decisions/` — ADRs. Any change to a spec definition requires a new ADR, approved by me.

## Hard rules (never violate)
1. Never place real orders, connect to a live broker order API, or write order-routing code.
2. Never use information not available at prediction time T. Every feature row carries `available_at`; code must enforce `available_at <= T`, not rely on discipline.
3. Never choose option contracts retrospectively. Selection uses only point-in-time quotes via the frozen selection rule.
4. Never use random train/test splits. Chronological walk-forward only, with purge/embargo for overlapping labels.
5. Never tune anything on the final test period.
6. Never call a raw model score "probability" or "confidence" until calibrated on held-out data.
7. Never silently change a definition in PHASE_1_SPEC.md. Stop and propose an ADR instead.
8. Never silently fill, drop, or adjust financial data. Every rejection gets a logged reason.
9. Never assume data exists. Verify it, or stop and flag it.
10. NO_TRADE is a first-class output. Never force CALL/PUT.
11. If something can't be validated, say so and stop. Don't invent a workaround.
12. Do not claim profitability. Report evidence, sample sizes, and uncertainty.

## How to work
- One milestone per session. Start in plan mode: read the spec + milestone criteria, propose a plan, wait for my approval.
- Write tests first for anything numerical (synthetic cases with exactly known answers), then implement.
- Keep changes scoped to the current milestone. Note out-of-scope ideas in `docs/MILESTONES.md` under "Later".
- Parameters live in `configs/*.yaml`, never hard-coded.
- Before saying a task is done: `uv run pytest`, `uv run ruff check .`, `uv run mypy src` all pass, and `docs/MILESTONES.md` is updated.
- When uncertain about market mechanics (expirations, OI timing, data vendor coverage), flag the uncertainty rather than guessing.

## Stack
Python 3.12, uv, polars (pandas where a library requires it), numpy, scikit-learn,
LightGBM, PostgreSQL (SQLAlchemy + Alembic), Parquet (pyarrow), pytest + hypothesis,
ruff, mypy. All timestamps stored as UTC; market logic in America/New_York via `zoneinfo`.

## Layout
```
src/qqq1dte/{core,ingestion,validation,features,labels,models,calibration,regimes,
             backtesting,execution_sim,journal,monitoring}/
configs/   tests/   docs/   data/ (gitignored)   migrations/
```
