# ADR-0001 — Phase 1 specification baseline

- Status: **ACCEPTED** (2026-10-05)
- Date: 2026-10-05
- Milestone: M1

## Context
MASTER_PROMPT Phase 1A requires a frozen specification before any modelling. Several values are
left open: the 1DTE definition, holding period, selection rule, fill model, gate thresholds, and
regimes. QQQ has listed expirations every weekday only since 2022-11-14 (Tue) / 2022-11-16 (Thu).
Before that, 1DTE contracts existed on at most 3 of 5 weekdays.

## Decision (proposed)
Adopt `docs/PHASE_1_SPEC.md` v0.1, with the Open Decisions OD-1…OD-12 resolved by the owner, as
the frozen Phase 1 constitution. The main points:
1. 1DTE = the expiration on the next XNYS session after D, confirmed in the point-in-time chain.
2. Option-label/backtest history starts 2022-11-14.
3. Intraday-only, flat by 15:50, max holding 90 min, 1 position, ≤ 3 entries/day.
4. Frozen selection: ATM/first-OTM strike at `T + latency`, no fallback.
5. Moderate fill α = 0.5; stop/target triggers on the bid in all fill models.
6. Numeric gates per spec §11.

## Consequences
- ~980 sessions of option-era history. Effective sample sizes are session-limited, which is why
  every CI uses a session-block bootstrap.
- Any later change to these definitions needs a new ADR that supersedes the relevant part.
- The owner's answers to OD-1…OD-12 are recorded below before Status → ACCEPTED.

## Owner resolutions (2026-10-05)
The owner accepted every recommendation in PHASE_1_SPEC §12:

| ID | Resolution |
|---|---|
| OD-1 | 1DTE = expiration on the next XNYS session, confirmed in the PIT chain; history from 2022-11-14 for everything. Earlier underlying-only history is a later experiment that counts toward `n_trials`. |
| OD-2 | Intraday-only; flat by 15:50; max holding 90 min. Thesis under test: 1DTE for its lower intraday gamma/theta noise vs 0DTE, not overnight exposure. |
| OD-3 | ATM/first-OTM strike at `T + latency`, no fallback. |
| OD-4 | 5-min prediction cadence; trading judged on trades/sessions; session-block bootstrap for all CIs. |
| OD-5 | Gate thresholds as in spec §11. |
| OD-6 | Moderate fill α = 0.5; stop/target triggers on the bid in every fill model. |
| OD-7 | OI: prior-day only, available 09:30 D, feature only, never a gate. IV/Greeks computed in-house from NBBO mid (European BSM + discrete dividend, ex-div −1 sessions flagged); vendor values stored but unused. |
| OD-8 | Run registry (`validation_runs`) logs every configuration; DSR + PBO use `n_trials`. |
| OD-9 | 12 regime cells (vol 3 × trend 2 × event 2), LOW_SUPPORT flagging. |
| OD-10 | Magnitude primary 0.25%, secondary 0.50%. |
| OD-11 | Add `src/qqq1dte/core/` (calendar, clock, PIT reader, config); CLAUDE.md layout updated. |
| OD-12 | Early-close sessions included with shifted times; options quotes after 16:00 ignored. |
