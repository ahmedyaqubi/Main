# M11 mechanical diagnostic backtest (NOT a strategy)

Generated 2026-10-07 10:06 UTC, code 579477a0983c, run `diagnostic-09621c5bebe5`. Sessions 756 (2023-03-28 → 2026-04-02, pre-holdout research sessions; holdout after 2026-04-02 not opened).

**What this is.** Until calibration exists (M13) the decision engine must output NO_TRADE (spec §4.1, rule 6). To exercise the backtester on real data, a mechanical signal requests a CALL (separately a PUT) at every prediction timestamp; the §4.7 limits (one open position, at most 3 entries per session), the frozen selection rule (§5), the §4.9 gates and the conservative fill (§6: buy the ask, sell the bid, both rounded against the trader) apply. The P&L below is an **unconditional-entry baseline** for later comparison (gate 14), not evidence of an edge, and not a claim of profitability (rule 12).

## Decisions per signal

| side | signals | ENTERED | BLOCKED_POSITION_OPEN | NO_TRADE (by reason) | UNFILLED |
|---|---|---|---|---|---|
| C | 48,096 | 2,268 | 14,800 | MAX_ENTRIES_PER_DAY 30,972, SELECTED_CONTRACT_ILLIQUID 56 | 0 |
| P | 48,096 | 2,267 | 12,837 | MAX_ENTRIES_PER_DAY 32,929, SELECTED_CONTRACT_ILLIQUID 63 | 0 |

## Reconciliation with the C labels (M6, independent implementation)

Each simulated trade is matched to the C label at the same side and prediction time. Exit timestamps are compared for target/stop exits only: a time exit happens at T_e + 90 min in the backtester (spec §2: entry + max holding) and at T + 90 min in the label (§3), the same 1-minute quote either way.

| side | trades | symbol | outcome | entry | exit price | net P&L | exit ts | all fields |
|---|---|---|---|---|---|---|---|---|
| C | 2,268 | 2,268 | 2,268 | 2,268 | 2,268 | 2,268 | 2,268 | 2,268 |
| P | 2,267 | 2,267 | 2,267 | 2,267 | 2,267 | 2,267 | 2,267 | 2,267 |

Mismatches: 0.

## Unconditional-entry baseline (conservative fill, net of §4.8 costs, per contract)

Mean net P&L CI: session-block bootstrap, 2000 reps, 95%. UNRESOLVED_DATA and UNFILLED trades have no P&L and are counted separately.

| side | trades | WIN | LOSS | BREAKEVEN | TIME_EXIT_PROFIT | TIME_EXIT_LOSS | UNRESOLVED | mean net $ [CI] | median net $ | mean R | median hold (min) | median MFE | median MAE | mean spread cost $ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C | 2,268 | 722 | 1,234 | 35 | 166 | 108 | 3 | -4.45 [-7.50, -1.19] | -34.40 | -0.100 | 24.9 | +0.150 | -0.202 | 2.30 |
| P | 2,267 | 744 | 1,306 | 23 | 84 | 106 | 4 | -5.77 [-9.05, -2.53] | -35.40 | -0.111 | 20.9 | +0.138 | -0.203 | 2.51 |

## Path flags

| side | flag | trades |
|---|---|---|
| C | PATH_GAP | 8 |
| C | NO_BID_AS_ZERO | 1 |
| P | PATH_GAP | 5 |
| P | NO_BID_AS_ZERO | 1 |
