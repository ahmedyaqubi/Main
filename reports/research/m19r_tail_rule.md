# M19R Stage 2 experiments (E5, E6)

Generated 2026-10-08 05:55 UTC, code 2d2d5eb2fdbe; runs E5 `experiment-a4a5672324a1`, E6 `experiment-64105fcb6609`. Walk-forward folds 1-7 (test blocks 2024-05-28 → 2026-02-27); holdout locked (ADR-0011). f3 = f2 + 8 extra features (option mid momentum, put/call imbalance change, quote size imbalances, QQQ NBBO imbalance); OPRA open interest is not on disk for the history and was not used.

Gate 6: raw-score BSS vs conditional Model 0, CI lower bound > 0 and better in ≥ 70% of folds. Gate 12: calibrated test probabilities (M13 recipe, ADR-0009). Lift: observed outcome rate in the top 10% / 2% / 1% of within-fold score ranks vs the median breakeven probability (0.412, M15).

| experiment | target | BSS vs Model 0 [CI] | folds better | gate 6 | ECE | slope | bins failed | gate 12 | top 10% | top 2% | top 1% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E5 | C_put | +0.0076 [-0.0002, +0.0157] | 5/7 | FAIL | 0.0200 | 0.307 | 5/10 | FAIL | 0.361 [0.343, 0.379] | 0.403 [0.363, 0.444] | 0.421 [0.364, 0.480] |
| E6 | C_put | +0.0076 [-0.0002, +0.0157] | 5/7 | FAIL | 0.0200 | 0.307 | 5/10 | FAIL | 0.361 [0.343, 0.379] | 0.403 [0.363, 0.444] | 0.421 [0.364, 0.480] |

## Stage 2b: score-tail trade rule (research test; bypasses the §4.1 rule)

Trade whenever the raw test score >= the fold's calibration-block score quantile (E5 0.98, E6 0.99); each tail timestamp is one trade with the C label's conservative-fill outcome, net of §4.8 costs. Breakeven win rate about 0.412.

| experiment | target | trades | sessions | win rate [Wilson CI] | mean net $ [CI] | median net $ |
|---|---|---|---|---|---|---|
| E5 | C_put | 1,201 | 135 | 0.381 [0.354, 0.409] | +0.57 [-7.25, +8.43] | -35.40 |
| E6 | C_put | 828 | 95 | 0.396 [0.363, 0.430] | +2.27 [-7.71, +11.99] | -35.40 |

Reference (f2, M9 / M13 / M19R D2): C_call BSS +0.0066 [-0.0008, +0.0138], 5/7 folds, top 10% 0.298, top 1% 0.288; C_put BSS +0.0046 [-0.0020, +0.0116], 5/7 folds, top 10% 0.350, top 1% 0.374. Breakeven ≈ 0.41.
