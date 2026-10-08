# M18 drift monitoring (spec Phase 1Q, gate 18)

Generated 2026-10-08 03:25 UTC, code 12e79be6a990, run `monitoring-6455ec4d4e17`. Predictions: journal run `journal-4a7a186908c7`. Reference: test blocks of folds [1, 2, 3, 4] (250 sessions). Final holdout not opened.

Monitors over the last 10 sessions: feature PSI (max over 27 features) and prediction PSI, with thresholds calibrated to no-drift noise (owner, M18 option A): WARN above the 99.0% and PAPER_ONLY above the 99.9% quantile of the monitor's PSI over 5,000 random 10-session windows of the reference, each compared with the reference without its own sessions (reference thresholds: features 4.962 / 5.714, predictions 1.103 / 1.832, regimes WARN 2.396); calibration z = mean(observed - predicted) / reference session-clustered SE, per decision target and combined (any |z| > 2.0 WARN; DISABLED only when the combined |z| > 3.0); expectancy (>= 20 trades); regime-cell PSI over 20 sessions (WARN only). DISABLED latches until a named human re-enables; `decide` returns NO_TRADE DRIFT_DISABLED while disabled.

## Gate 18: synthetic drift injection (replay)

20 replays per injection; the reference sessions in seeded random order (seed 20261010; stationary by construction), injection from session 30. Pass: right alert within 10 sessions in every replay and at most 1 replay(s) escalating (PAPER_ONLY / DISABLED) before injection.

| injection | expected alert | detected | delay (sessions) min / median / max | false-alarm replays | result |
|---|---|---|---|---|---|
| features +1 SD | PAPER_ONLY | 20/20 | 5 / 10 / 10 | 1 | PASS |
| 50% of WINs -> LOSS (both sides) | DISABLED | 20/20 | 4 / 8 / 10 | 0 | PASS |

Known limit: a calibration degradation on only one decision target moves the combined gap half as much; such a change reaches WARN (single-target |z| about 2.3 after 10 sessions for the same 50% flip) rather than DISABLED within 10 sessions.

## Chronological monitoring (information): remaining folds vs the reference

181 rolling windows (2025-06-10 → 2026-02-27).

| state (latched) | windows |
|---|---|
| WARN | 92 |
| PAPER_ONLY | 85 |
| OK | 4 |

| monitor | OK | WARN | PAPER_ONLY | DISABLED |
|---|---|---|---|---|
| features | 75 | 44 | 62 | 0 |
| predictions | 46 | 93 | 42 | 0 |
| calibration | 167 | 14 | 0 | 0 |
| expectancy | 181 | 0 | 0 | 0 |
| regimes | 12 | 169 | 0 | 0 |

First DISABLED: never.

Most frequent max-PSI features in escalated windows: vix_prev_close (105), overnight_gap (1).

Expectancy is not evaluable: the current decision configuration (ADR-0010) makes no trades.
