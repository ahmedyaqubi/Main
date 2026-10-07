# M12 execution sensitivity of the mechanical baseline (NOT a strategy)

Generated 2026-10-07 10:28 UTC, code 3e5ecc8b4106, run `sensitivity-f6b5dad8437b`. Sessions 756 (2023-03-28 → 2026-04-02, pre-holdout research sessions; holdout after 2026-04-02 not opened).

**What this is.** The M11 mechanical signal (CALL at every prediction timestamp; separately PUT; one open position, ≤ 3 entries per session) re-simulated in full under each execution assumption. Target and stop are set from each model's own entry fill and always trigger on the bid (§6). It measures how much the unconditional-entry baseline depends on execution assumptions. It is not evidence of an edge and makes no claim of profitability (rule 12).

**Gate 9.** Every dollar figure is net of §4.8 commissions and fees and of the spread paid through the fill (`NetPnl` type; `backtesting/reporting.py`). Mean net P&L per trade, per contract, with session-block bootstrap 2000-rep 95% CIs. (+) = CI above 0, (-) = CI below 0.

**Known limitations.** Fill probability is assumed to be 1 whenever the §4.9 gates pass (spec §6). Option quotes are 1-minute snapshots, so latencies of 0 s and 5 s see the same quote; only 60 s moves entry (and selection) to the next snapshot. Latency slippage = entry fill at T_e minus the same model's fill on the quote in force at T.

## Three fill models side by side (latency 5 s, costs x1, moderate alpha = 0.5)

| side | model | trades | WIN | LOSS | time exits (BE / +/ -) | unresolved | mean net $ [CI] | median net $ | mean R | mean spread cost $ |
|---|---|---|---|---|---|---|---|---|---|---|
| C | CONSERVATIVE | 2,268 | 722 | 1,234 | 35 / 166 / 108 | 3 | -4.45 [-7.50, -1.19] | -34.40 | -0.100 | 2.30 |
| C | MODERATE | 2,268 | 723 | 1,231 | 35 / 166 / 110 | 3 | -4.19 [-7.20, -0.94] | -34.40 | -0.096 | 2.04 |
| C | OPTIMISTIC | 2,268 | 740 | 1,220 | 30 / 168 / 107 | 3 | -2.39 [-5.41, +0.77] | -33.40 | -0.062 | 0.42 |
| P | CONSERVATIVE | 2,267 | 744 | 1,306 | 23 / 84 / 106 | 4 | -5.77 [-9.05, -2.53] | -35.40 | -0.111 | 2.51 |
| P | MODERATE | 2,267 | 750 | 1,302 | 23 / 84 / 104 | 4 | -5.06 [-8.38, -1.76] | -35.40 | -0.100 | 2.12 |
| P | OPTIMISTIC | 2,267 | 767 | 1,285 | 20 / 86 / 105 | 4 | -3.09 [-6.48, +0.16] | -33.40 | -0.059 | 0.42 |

## Grid: mean net $ per trade, CALL side (moderate alpha; alpha = 1 prices like conservative, alpha = 0 like optimistic)

| alpha | latency 0 s, costs x1 | latency 0 s, costs x1.5 | latency 5 s, costs x1 | latency 5 s, costs x1.5 | latency 60 s, costs x1 | latency 60 s, costs x1.5 |
|---|---|---|---|---|---|---|
| 0 | -2.39 [-5.41, +0.77] | -3.09 [-6.11, +0.07] | -2.39 [-5.41, +0.77] | -3.09 [-6.11, +0.07] | -3.74 [-6.95, -0.57] | -4.44 [-7.65, -1.27] |
| 0.25 | -3.85 [-6.85, -0.61] | -4.55 [-7.55, -1.31] | -3.85 [-6.85, -0.61] | -4.55 [-7.55, -1.31] | -4.87 [-8.02, -1.71] | -5.57 [-8.72, -2.41] |
| 0.5 | -4.19 [-7.20, -0.94] | -4.89 [-7.90, -1.64] | -4.19 [-7.20, -0.94] | -4.89 [-7.90, -1.64] | -5.31 [-8.43, -2.19] | -6.01 [-9.13, -2.89] |
| 0.75 | -4.42 [-7.46, -1.17] | -5.12 [-8.16, -1.87] | -4.42 [-7.46, -1.17] | -5.12 [-8.16, -1.87] | -5.52 [-8.57, -2.38] | -6.22 [-9.27, -3.08] |
| 1 | -4.45 [-7.50, -1.19] | -5.15 [-8.20, -1.89] | -4.45 [-7.50, -1.19] | -5.15 [-8.20, -1.89] | -5.60 [-8.65, -2.48] | -6.30 [-9.35, -3.18] |

## Grid: mean net $ per trade, PUT side (moderate alpha; alpha = 1 prices like conservative, alpha = 0 like optimistic)

| alpha | latency 0 s, costs x1 | latency 0 s, costs x1.5 | latency 5 s, costs x1 | latency 5 s, costs x1.5 | latency 60 s, costs x1 | latency 60 s, costs x1.5 |
|---|---|---|---|---|---|---|
| 0 | -3.09 [-6.48, +0.16] | -3.79 [-7.18, -0.54] | -3.09 [-6.48, +0.16] | -3.79 [-7.18, -0.54] | -3.78 [-6.91, -0.63] | -4.48 [-7.61, -1.33] |
| 0.25 | -4.72 [-8.05, -1.42] | -5.42 [-8.75, -2.12] | -4.72 [-8.05, -1.42] | -5.42 [-8.75, -2.12] | -5.18 [-8.39, -2.02] | -5.88 [-9.09, -2.72] |
| 0.5 | -5.06 [-8.38, -1.76] | -5.76 [-9.08, -2.46] | -5.06 [-8.38, -1.76] | -5.76 [-9.08, -2.46] | -5.56 [-8.74, -2.40] | -6.26 [-9.44, -3.10] |
| 0.75 | -5.46 [-8.78, -2.17] | -6.16 [-9.48, -2.87] | -5.46 [-8.78, -2.17] | -6.16 [-9.48, -2.87] | -5.63 [-8.84, -2.38] | -6.33 [-9.54, -3.08] |
| 1 | -5.77 [-9.05, -2.53] | -6.47 [-9.75, -3.23] | -5.77 [-9.05, -2.53] | -6.47 [-9.75, -3.23] | -5.75 [-8.97, -2.50] | -6.45 [-9.67, -3.20] |

## Latency slippage and spread cost (grid, costs x1)

| side | alpha | latency s | trades | mean latency slippage $ (n known) | mean spread cost $ |
|---|---|---|---|---|---|
| C | 0 | 0 | 2,268 | +0.00 (2,265) | 0.42 |
| P | 0 | 0 | 2,267 | +0.00 (2,263) | 0.42 |
| C | 0 | 5 | 2,268 | +0.00 (2,265) | 0.42 |
| P | 0 | 5 | 2,267 | +0.00 (2,263) | 0.42 |
| C | 0 | 60 | 2,268 | -0.57 (2,196) | 0.44 |
| P | 0 | 60 | 2,266 | -1.26 (2,173) | 0.42 |
| C | 0.25 | 0 | 2,268 | +0.00 (2,265) | 1.68 |
| P | 0.25 | 0 | 2,267 | +0.00 (2,263) | 1.73 |
| C | 0.25 | 5 | 2,268 | +0.00 (2,265) | 1.68 |
| P | 0.25 | 5 | 2,267 | +0.00 (2,263) | 1.73 |
| C | 0.25 | 60 | 2,268 | -0.64 (2,196) | 1.68 |
| P | 0.25 | 60 | 2,266 | -1.35 (2,171) | 1.74 |
| C | 0.5 | 0 | 2,268 | +0.00 (2,265) | 2.04 |
| P | 0.5 | 0 | 2,267 | +0.00 (2,263) | 2.12 |
| C | 0.5 | 5 | 2,268 | +0.00 (2,265) | 2.04 |
| P | 0.5 | 5 | 2,267 | +0.00 (2,263) | 2.12 |
| C | 0.5 | 60 | 2,268 | -0.67 (2,196) | 2.07 |
| P | 0.5 | 60 | 2,266 | -1.42 (2,171) | 2.16 |
| C | 0.75 | 0 | 2,268 | +0.00 (2,265) | 2.25 |
| P | 0.75 | 0 | 2,267 | +0.00 (2,263) | 2.40 |
| C | 0.75 | 5 | 2,268 | +0.00 (2,265) | 2.25 |
| P | 0.75 | 5 | 2,267 | +0.00 (2,263) | 2.40 |
| C | 0.75 | 60 | 2,268 | -0.68 (2,196) | 2.29 |
| P | 0.75 | 60 | 2,266 | -1.41 (2,171) | 2.45 |
| C | 1 | 0 | 2,268 | +0.00 (2,265) | 2.30 |
| P | 1 | 0 | 2,267 | +0.00 (2,263) | 2.51 |
| C | 1 | 5 | 2,268 | +0.00 (2,265) | 2.30 |
| P | 1 | 5 | 2,267 | +0.00 (2,263) | 2.51 |
| C | 1 | 60 | 2,268 | -0.70 (2,196) | 2.37 |
| P | 1 | 60 | 2,266 | -1.42 (2,171) | 2.57 |

## Sign summary

- Configurations with mean net > 0: 0 of 66 (side x configuration).
- Configurations whose CI lies above 0: 0.
- The sign of the mean does not depend on the execution assumptions in this grid.
