# ADR-0006 — Closing the M4 CRITICAL data-quality sessions

- Status: **ACCEPTED** (owner, 2026-10-06)
- Date: 2026-10-06
- Milestone: M4 (gate 2)

## Context
The full-history DQ run (`reports/dq/full_history.md`, DQ rules v2) found 4 sessions whose share
of prediction timestamps with a valid frozen-rule call **and** put was below 95%
(`CHAIN_COVERAGE_LOW`, CRITICAL). Gate 2 requires 0 open CRITICAL events. All other gate-2 and
gate-1 criteria pass.

| Session | Valid share | Diagnosis |
|---|---|---|
| 2023-12-27 | 0/64 | Ex-date of OCC #53847 (ADR-0005). Databento lists the new adjusted series (x.78, real quotes) **and** the superseded pre-adjustment symbols, which are quoted 0/0 all day. The put side's "highest strike ≤ spot" lands on a superseded symbol. From 2023-12-28 the superseded symbols are gone. |
| 2024-02-06 | 56/64 | ~12:05–12:50 ET: ATM put crossed/missing (2,311 crossed records rejected that day) |
| 2025-10-22 | 60/64 | ~13:30–13:45 ET: ATM call/put crossed, locked, or missing |
| 2026-03-10 | 58/64 | ~10:15–10:40 ET: ATM contracts crossed or missing |

## Decision
1. **Exclude 2023-12-27** from all research use (labels, features, backtests, gates):
   `history.excluded_sessions` in `configs/phase1.yaml`. `TradingCalendar.in_research_window` and
   `research_sessions` enforce it, and every exclusion carries its ADR and reason. The session's
   CRITICAL events are closed by this ADR.
2. **Keep 2024-02-06, 2025-10-22 and 2026-03-10.** Their `CHAIN_COVERAGE_LOW` events are closed
   by this ADR (`dq.resolved_critical`). At the affected timestamps the data correctly shows no
   valid quote, and crossed/rejected records block fallback to older quotes, so downstream
   selection yields NO_TRADE there by construction. Nothing is filled.

## Consequences
- Research window: 882 sessions (2023-03-28 → 2026-10-02 minus 2023-12-27).
- `data_quality_events.resolved_by_adr = 'ADR-0006'` on the four events. Gate 2 counts only
  events without it.
- Any future CRITICAL event needs its own ADR. Nothing is closed by default.
