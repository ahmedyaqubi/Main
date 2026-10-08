# M19R Stage 2 experiments (E1-E4)

Generated 2026-10-08 05:31 UTC, code 2d2d5eb2fdbe; runs E1 `experiment-d878fa4dade5`, E2 `experiment-204b18b73d79`, E3 `experiment-77f47aa007f9`, E4 `experiment-e4ace04b0c76`. Walk-forward folds 1-7 (test blocks 2024-05-28 → 2026-02-27); holdout locked (ADR-0011). f3 = f2 + 8 extra features (option mid momentum, put/call imbalance change, quote size imbalances, QQQ NBBO imbalance); OPRA open interest is not on disk for the history and was not used.

Gate 6: raw-score BSS vs conditional Model 0, CI lower bound > 0 and better in ≥ 70% of folds. Gate 12: calibrated test probabilities (M13 recipe, ADR-0009). Lift: observed outcome rate in the top 10% / 2% / 1% of within-fold score ranks vs the median breakeven probability (0.412, M15).

| experiment | target | BSS vs Model 0 [CI] | folds better | gate 6 | ECE | slope | bins failed | gate 12 | top 10% | top 2% | top 1% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E1 | C_call | +0.0091 [+0.0032, +0.0154] | 5/7 | PASS | 0.0137 | 0.818 | 2/10 | FAIL | 0.297 [0.280, 0.314] | 0.315 [0.278, 0.355] | 0.255 [0.208, 0.310] |
| E1 | C_put | +0.0060 [-0.0011, +0.0134] | 5/7 | FAIL | 0.0205 | 0.691 | 3/10 | FAIL | 0.348 [0.331, 0.366] | 0.349 [0.310, 0.389] | 0.360 [0.306, 0.418] |
| E2 | C_call | +0.0041 [-0.0035, +0.0124] | 4/7 | FAIL | 0.0158 | 0.651 | 2/10 | FAIL | 0.307 [0.290, 0.325] | 0.284 [0.248, 0.323] | 0.273 [0.224, 0.329] |
| E2 | C_put | +0.0076 [-0.0002, +0.0157] | 5/7 | FAIL | 0.0200 | 0.307 | 5/10 | FAIL | 0.361 [0.343, 0.379] | 0.403 [0.363, 0.444] | 0.421 [0.364, 0.480] |
| E3 | C_call | -0.0034 [-0.0119, +0.0054] | 5/7 | FAIL | 0.0267 | 0.478 | 4/10 | FAIL | 0.315 [0.298, 0.333] | 0.356 [0.317, 0.397] | 0.360 [0.306, 0.418] |
| E3 | C_put | +0.0061 [-0.0020, +0.0148] | 6/7 | FAIL | 0.0164 | 0.741 | 2/10 | FAIL | 0.369 [0.351, 0.387] | 0.372 [0.333, 0.413] | 0.392 [0.337, 0.451] |
| E4 | C_put | +0.0060 [-0.0011, +0.0134] | 5/7 | FAIL | 0.0205 | 0.691 | 3/10 | FAIL | 0.348 [0.331, 0.366] | 0.349 [0.310, 0.389] | 0.360 [0.306, 0.418] |

Reference (f2, M9 / M13 / M19R D2): C_call BSS +0.0066 [-0.0008, +0.0138], 5/7 folds, top 10% 0.298, top 1% 0.288; C_put BSS +0.0046 [-0.0020, +0.0116], 5/7 folds, top 10% 0.350, top 1% 0.374. Breakeven ≈ 0.41.
