# M15 decision engine and NO_TRADE analysis (spec §4.1)

Generated 2026-10-07 23:40 UTC, code c4e1bddabeef, run `decision-747dec735c50`. Test blocks 2024-05-28 → 2026-02-27 (440 sessions, 27,944 prediction timestamps); final holdout not opened.

**Rule.** Model family `gbm_m2` with its M13 calibrators (test-block probabilities from features only). Per side: calibrated P(WIN) - p_breakeven > 0.03 and EV > 0 at the moderate entry fill (alpha = 0.5), binary-conservative EV (every non-WIN outcome = full -20% stop), §4.9 gates at T_e. Both sides qualifying: higher EV. Blocked regime cells: none.

## Decisions

| final decision | timestamps | share |
|---|---|---|
| NO_TRADE | 27,795 | 99.47% |
| BLOCKED_POSITION_OPEN | 103 | 0.37% |
| CALL | 45 | 0.16% |
| PUT | 1 | 0.00% |

## Rule decision vs engine outcome

CALL / PUT decisions pass through the event engine (one open position, at most 3 entries per session); NO_TRADE there is MAX_ENTRIES_PER_DAY.

| rule decision | engine outcome | timestamps |
|---|---|---|
| CALL | BLOCKED_POSITION_OPEN | 102 |
| CALL | CALL | 45 |
| CALL | NO_TRADE | 28 |
| NO_TRADE | NO_TRADE | 27,767 |
| PUT | BLOCKED_POSITION_OPEN | 1 |
| PUT | PUT | 1 |

## NO_TRADE by reason (per side; rule-level NO_TRADE only)

| reason | timestamps |
|---|---|
| CALL:BELOW_BREAKEVEN_MARGIN | 27,620 |
| PUT:BELOW_BREAKEVEN_MARGIN | 27,614 |
| PUT:SELECTED_CONTRACT_ILLIQUID | 153 |
| CALL:SELECTED_CONTRACT_ILLIQUID | 147 |

## NO_TRADE rate by regime cell (R1)

| cell | timestamps | NO_TRADE | rate |
|---|---|---|---|
| HIGH/CHOP/MACRO | 960 | 943 | 98.23% |
| HIGH/CHOP/NORMAL | 8,440 | 8,361 | 99.06% |
| HIGH/TREND/MACRO | 896 | 889 | 99.22% |
| HIGH/TREND/NORMAL | 4,352 | 4,348 | 99.91% |
| LOW/CHOP/NORMAL | 476 | 476 | 100.00% |
| LOW/TREND/MACRO | 320 | 293 | 91.56% |
| LOW/TREND/NORMAL | 2,204 | 2,204 | 100.00% |
| NORMAL/CHOP/MACRO | 704 | 688 | 97.73% |
| NORMAL/CHOP/NORMAL | 5,532 | 5,514 | 99.67% |
| NORMAL/TREND/MACRO | 476 | 473 | 99.37% |
| NORMAL/TREND/NORMAL | 3,584 | 3,578 | 99.83% |

## Distance from the decision threshold

margin = calibrated P(WIN) - p_breakeven; a side needs margin > 0.03. Quantiles 5% / 50% / 95% over timestamps where the side's selection passed.

| side | calibrated P(WIN) 5/50/95% | p_breakeven 5/50/95% | margin 5/50/95% | timestamps with margin > 0 | > edge margin |
|---|---|---|---|---|---|
| CALL | +0.112 / +0.257 / +0.349 (max +1.000) | +0.406 / +0.412 / +0.420 (max +0.458) | -0.299 / -0.155 / -0.063 (max +0.595) | 315 | 175 |
| PUT | +0.203 / +0.280 / +0.347 (max +0.453) | +0.406 / +0.412 / +0.420 (max +0.443) | -0.211 / -0.132 / -0.066 (max +0.041) | 73 | 2 |

## Gate 13 (regime behaviour) and gate 14 (NO_TRADE validated)

- Traded timestamps (entered trades with a P&L): **46**.
- Gate 13: cells with >= 100 trades are listed in the run metrics (none expected).
- Gate 14: traded - NO_TRADE counterfactual mean net +14.95 [-11.52, +42.94]: would FAIL
- Counterfactual at NO_TRADE timestamps (higher-EV side simulated anyway, one independent trade each, moderate fill, net of costs): 27,650 trades, mean net $-2.96 [-5.32, -0.70], median $-28.40.

Not a claim of profitability (rule 12): these are research decisions on pre-holdout test blocks.
