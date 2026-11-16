# ADR-0023: ADR-0022 is withdrawn; M32 stops before session 1; work returns to ADR-0021

- Status: **ACCEPTED** 2026-11-15 by the owner ("Withdraw, back to options").
- Withdraws: ADR-0022 (paper trading of the RSI(2) pullback rule on SPY shares) and its
  amendment A1. Stops: milestone M32.
- Changes no definition in `docs/PHASE_1_SPEC.md`. Changes no rule, threshold or result.

## Why
- ADR-0022 paper trades **SPY shares**. The owner's work is about **options** (owner,
  2026-11-15: "everything we do is revolving around options - not stocks"). The current
  mission, ADR-0021, is research towards an options day-trading agent.
- The mismatch came out when the owner was asked to confirm the share-related P1 rows
  (share commission plan, fees on share sales, settlement of share sales).
- ADR-0022's status line records that the share basis was stated at acceptance. It was not
  stated plainly enough for the owner to see that the whole milestone was off-mission.

## Decision
- **W1. ADR-0022 is WITHDRAWN.** No paper session was run. No instruction was journalled. No
  order was entered by anyone under it.
- **W2. M32 is STOPPED.** `paper_pullback.first_session` stays `null`, so
  `scripts/m32_evening.py` refuses to run except as a dry run. Setting it needs a new ADR.
- **W3. The M32 code stays in the repository, unused.** It is tested, it opens no broker
  connection, and its rule-1 guard tests keep running in CI. Removing it is a separate
  decision.
- **W4. Migration 0004 stays applied.** The owner's database is at revision 0004 (applied
  2026-11-15 with the owner's OK). `paper_signals`, `paper_fills` and `paper_events` are
  empty and stay empty.
- **W5. The RSI(2) result is unchanged.** The M27 holdout stays **PASS (borderline, with the
  ADR-0020 exception)**. ADR-0015 gate 3 (paper trading) was **not attempted**; it was neither
  passed nor failed. Nothing here is evidence for or against the rule.
- **W6. An options version of the RSI(2) signal is not authorised.** The 266-trade backtest
  covers shares only and says nothing about options on the same signal. It would need its own
  ADR, written before any data are examined for it.
- **W7. Work returns to ADR-0021.** State, from the records: S1 AMBIGUOUS (M29), S2 KILL (M30),
  1 of 3 tests left; S3 is reserved and must be specified by an amendment, with its reason,
  before any data are examined for it (ADR-0021 D3). M31 stays reserved by ADR-0021 D11.

## Budget and counts (unchanged)
- Trial count: 44. M32 was not a trial.
- ADR-0015 ledger: 5 of 10 tests used; $36.17 of $100 spent.

## P1 answers received before withdrawal (recorded, not used)
- Account type: cash account, unchanged (owner, 2026-11-15).
- Account currency: USD (owner, 2026-11-15).
- The other six rows were not answered.

## Consequences
- Any future plan that trades the underlying (shares or ETF units) says so in its first line
  and asks the owner to confirm that before anything else.
- Hard rules 1–12 stand unchanged.
