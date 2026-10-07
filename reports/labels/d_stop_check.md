# D-label stop/target vs. the empirical option bracket

For C trades that hit the option stop (-20%) or target (+30%) on the bid, the QQQ move from P_T to the exit time. D uses stop 0.19% and target 0.30% of the underlying.

Pre-holdout sessions only (through 2026-04-02); the final holdout is locked.

| side | option outcome | trades | QQQ move p10 | p50 | p90 |
|---|---|---|---|---|---|
| call | LOSS | 22,918 | -0.344% | -0.202% | -0.122% |
| call | WIN | 12,108 | +0.207% | +0.307% | +0.499% |
| put | LOSS | 24,672 | +0.114% | +0.181% | +0.299% |
| put | WIN | 13,348 | -0.470% | -0.302% | -0.210% |

Reading: compare |p50| for LOSS with the D stop (0.19%) and for WIN with the D target (0.30%). A material gap means D does not mirror the option bracket. Changing D's defaults needs an ADR (M6 criterion 4).
