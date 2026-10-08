# M15 decision engine and NO_TRADE analysis (spec §4.1)

Generated 2026-10-08 01:16 UTC, code 6ff546396309, run `decision-8a5f9559f8c4`. Test blocks 2024-05-28 → 2026-02-27 (440 sessions, 27,944 prediction timestamps); final holdout not opened.

**Rule.** Model family `gbm_m2` with its M13 calibrators (test-block probabilities from features only). Per side: calibrated P(WIN) - p_breakeven > 0.03 and EV > 0 at the moderate entry fill (alpha = 0.5), binary-conservative EV (every non-WIN outcome = full -20% stop), §4.9 gates at T_e, and (ADR-0010) at least 200 calibration-block rows with a raw score at or above the current one. Both sides qualifying: higher EV. Blocked regime cells: none.

## Decisions

| final decision | timestamps | share |
|---|---|---|
| NO_TRADE | 27,944 | 100.00% |

## Rule decision vs engine outcome

CALL / PUT decisions pass through the event engine (one open position, at most 3 entries per session); NO_TRADE there is MAX_ENTRIES_PER_DAY.

| rule decision | engine outcome | timestamps |
|---|---|---|
| NO_TRADE | NO_TRADE | 27,944 |

## NO_TRADE by reason (per side; rule-level NO_TRADE only)

| reason | timestamps |
|---|---|
| CALL:BELOW_BREAKEVEN_MARGIN | 25,459 |
| PUT:BELOW_BREAKEVEN_MARGIN | 24,644 |
| PUT:INSUFFICIENT_CALIBRATION_SUPPORT | 3,147 |
| CALL:INSUFFICIENT_CALIBRATION_SUPPORT | 2,338 |
| PUT:SELECTED_CONTRACT_ILLIQUID | 153 |
| CALL:SELECTED_CONTRACT_ILLIQUID | 147 |

## NO_TRADE rate by regime cell (R1)

| cell | timestamps | NO_TRADE | rate |
|---|---|---|---|
| HIGH/CHOP/MACRO | 960 | 960 | 100.00% |
| HIGH/CHOP/NORMAL | 8,440 | 8,440 | 100.00% |
| HIGH/TREND/MACRO | 896 | 896 | 100.00% |
| HIGH/TREND/NORMAL | 4,352 | 4,352 | 100.00% |
| LOW/CHOP/NORMAL | 476 | 476 | 100.00% |
| LOW/TREND/MACRO | 320 | 320 | 100.00% |
| LOW/TREND/NORMAL | 2,204 | 2,204 | 100.00% |
| NORMAL/CHOP/MACRO | 704 | 704 | 100.00% |
| NORMAL/CHOP/NORMAL | 5,532 | 5,532 | 100.00% |
| NORMAL/TREND/MACRO | 476 | 476 | 100.00% |
| NORMAL/TREND/NORMAL | 3,584 | 3,584 | 100.00% |

## Distance from the decision threshold

margin = calibrated P(WIN) - p_breakeven; a side needs margin > 0.03. Quantiles 5% / 50% / 95% over timestamps where the side's selection passed.

| side | calibrated P(WIN) 5/50/95% | p_breakeven 5/50/95% | margin 5/50/95% | timestamps with margin > 0 | > edge margin |
|---|---|---|---|---|---|
| CALL | +0.112 / +0.257 / +0.349 (max +1.000) | +0.406 / +0.412 / +0.420 (max +0.458) | -0.299 / -0.155 / -0.063 (max +0.595) | 315 | 175 |
| PUT | +0.203 / +0.280 / +0.347 (max +0.453) | +0.406 / +0.412 / +0.420 (max +0.443) | -0.211 / -0.132 / -0.066 (max +0.041) | 73 | 2 |

## Gate 13 (regime behaviour) and gate 14 (NO_TRADE validated)

- Traded timestamps (entered trades with a P&L): **0**.
- Gate 13: not evaluable: no traded regime cell (0 trades).
- Gate 14: **not evaluable: 0 traded timestamps** (rule 11; nothing to compare the NO_TRADE counterfactual with).
- Counterfactual at NO_TRADE timestamps (higher-EV side simulated anyway, one independent trade each, moderate fill, net of costs): 27,827 trades, mean net $-2.97 [-5.37, -0.71], median $-28.40.

Not a claim of profitability (rule 12): these are research decisions on pre-holdout test blocks.
