# M28 step 4: QQQ data check (ADR-0021 D5, D8; rule 9)

Generated 2026-11-14 05:28 UTC by `scripts/m28_verify_qqq.py`. Development sessions 2023-03-28 → 2026-04-02 only; no holdout file was opened. No signal or return was computed: calls and puts were checked alike.

## Holdout access log

`final_test_access_log` has **2** entries:

| id | run | ADR | accessed at | justification |
|---|---|---|---|---|
| 1 | `screen_pullback_holdout-b47cc1560348` | ADR-0019 | 2026-10-13 03:23:03.681528-06:00 | M27 gate 2: one holdout confirmation of the ADR-0018 rule |
| 2 | `screen_pullback_holdout-7e393c248e95` | ADR-0020 | 2026-10-13 04:29:28.556896-06:00 | M27 gate 2 rerun under ADR-0020 (Shiller partial-month exception) |

QQQ accesses: **0**.

## Coverage

- Sessions checked: **756**; passing every check: **753** (99.60%). Line: 95% → **COMPLETE**.
- Mean underlying coverage: 0.9974.
- Mean held-contract coverage, entry → exit: S1 call 0.9996, S1 put 0.9996, S2 call 1.0000, S2 put 1.0000.
- S2 has no entry on 8 early-close sessions (15:30 is after the forced exit).
- Descriptive, not a data check: share of sessions where the ATM contract passes the §4.9 liquidity gates at entry: S1 call 99.7%, put 99.7%; S2 call 100.0%, put 100.0%.

## Gaps

- S1_C_HELD_COVERAGE: 1 sessions
- S1_C_NO_ENTRY_QUOTE: 1 sessions
- S1_P_HELD_COVERAGE: 2 sessions
- S1_P_NO_ENTRY_QUOTE: 1 sessions

| session | ADR-resolved (dq.resolved_critical) | reasons |
|---|---|---|
| 2023-07-05 | no | S1_C_NO_ENTRY_QUOTE; S1_P_NO_ENTRY_QUOTE |
| 2024-02-06 | yes | S1_P_HELD_COVERAGE 0.941 |
| 2026-03-10 | yes | S1_C_HELD_COVERAGE 0.928; S1_P_HELD_COVERAGE 0.926 |

Per-session table: `data/research/m28/qqq_step4_sessions.parquet` (not committed; `data/`).

