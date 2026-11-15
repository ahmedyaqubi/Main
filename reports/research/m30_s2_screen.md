# M30: D6 screen of setup S2, the first half-hour predicts the last (ADR-0021 D3)

Generated 2026-11-15 10:17 UTC by `scripts/m30_screen.py`, code d212c86f0cc4. Registered run `screen_half_hour-ffe57c6e1184` (n_trials 43 → 44). Test 2 of the 3 that ADR-0021 D7 allows. Development sessions only; no holdout file was opened.

## Outcome: **KILL**

### Step A: the underlying
- Mean signed return, 15:30 → 15:50, over 3,110 ticker-sessions with a direction (746 sessions): **-0.0070%**
- One-sided 95% lower bound: **-0.0201%** (not above 0: the setup stops here)
- Two-sided 95% interval: [-0.0227%, 0.0083%]
- Directions: 3,110, of which up 1,735; left out of Step A for want of an underlying quote at 15:50: 0

### Step B: the option trades (descriptive only: Step A did not pass)
- Trades: **743** (guard ≥ 60, met); one position at a time; buy at the ask at 15:30, sell at the bid at 15:50; `ibkr_canada` fees
- Mean net P&L per trade as a share of the premium paid: **-3.63%**
- One-sided 98.33% lower bound: **-4.86%** (ADVANCE needs > 0)
- Two-sided 95% interval: [-4.76%, -2.46%]
- Lower bound at the full recorded count (44 trials, one-sided 99.886%): -5.40%
- **Mid fill (KILL row), same trades:** mean -2.25%, two-sided 95% interval [-3.39%, -1.05%] (KILL needs the upper bound < 0)
- Session bootstrap, 20,000 reps, seed 20261007.

Development-data result with its uncertainty. Not a claim of profitability, and not out-of-sample.

## Risk rows (always reported)

- Mean net per trade: $-7.98; total over the period: $-5,926.35 (one contract per trade)
- Winning trades: 35.0%
- Worst trade: QQQ 2024-05-31, -59.27% ($-93.05)
- Longest losing run: 21 trades
- Largest drawdown: $6,096.59
- $1,000 total loss cap (reported, the series is not stopped): reached on 2023-07-17
- `PREMIUM_OVER_CAP`: 458; `POSITION_OPEN`: 1,909
- Trades with no usable option quote at 15:50 (`UNRESOLVED_DATA`, left out): 0; mean with those counted as a total loss: -3.63%
- Exits with no bid (sold at 0): 0
- Same trades under `webull_canada` fees: mean -3.62%
- Largest distance between a traded strike and the underlying at entry: 1.48% (a check that the listed chain reached the money)

## Every ticker-session, by result

TRADE = took the position. Everything else is NO_TRADE with its reason.

| ticker | sessions | CORPORATE_ACTION | EARLY_CLOSE | EARNINGS_WINDOW | FLAT_MOVE | NO_PREV_CLOSE | NO_UNDERLYING_QUOTE | POSITION_OPEN | PREMIUM_OVER_CAP | TRADE |
|---|---|---|---|---|---|---|---|---|---|---|
| IWM | 632 | 0 | 6 | 0 | 17 | 1 | 1 | 602 | 0 | 5 |
| NVDA | 632 | 1 | 6 | 30 | 13 | 2 | 1 | 259 | 204 | 116 |
| QQQ | 756 | 0 | 8 | 0 | 11 | 2 | 0 | 401 | 9 | 325 |
| SPY | 632 | 0 | 6 | 0 | 17 | 1 | 0 | 468 | 6 | 134 |
| TSLA | 632 | 0 | 6 | 30 | 14 | 1 | 0 | 179 | 239 | 163 |

## Per ticker (descriptive only; D6)

| ticker | trades | calls | mean net / premium | winning | total $ |
|---|---|---|---|---|---|
| IWM | 5 | 3 | -14.57% | 0.0% | -184.28 |
| NVDA | 116 | 63 | -2.72% | 31.9% | -857.47 |
| QQQ | 325 | 183 | -3.75% | 36.0% | -2,295.99 |
| SPY | 134 | 74 | -4.83% | 35.8% | -1,139.32 |
| TSLA | 163 | 77 | -2.73% | 35.6% | -1,449.30 |

## Per year (descriptive only)

| year | trades | calls | mean net / premium | winning | total $ |
|---|---|---|---|---|---|
| 2023 | 189 | 104 | -6.83% | 29.1% | -2,715.50 |
| 2024 | 249 | 135 | -1.26% | 41.0% | -632.83 |
| 2025 | 243 | 130 | -3.71% | 30.5% | -2,067.52 |
| 2026 | 62 | 31 | -3.11% | 46.8% | -510.50 |

## How it was run

- QQQ: 756 development sessions, 2023-03-28 → 2026-04-02
- SPY: 632 development sessions, 2023-03-28 → 2025-10-02
- IWM: 632 development sessions, 2023-03-28 → 2025-10-02
- NVDA: 632 development sessions, 2023-03-28 → 2025-10-02
- TSLA: 632 development sessions, 2023-03-28 → 2025-10-02
- AAPL is out (D1: five earnings dates not verified in advance). NVDA and TSLA earnings sessions, and the session on each side, are `EARNINGS_WINDOW`.
- After 2025-10-02 only QQQ has development data, so the pooled sample is uneven in time.
- The underlying is read from 1-minute quotes. The previous close is the quote in force 1 minute before the previous session's close, not the official closing trade price (which this project does not hold for four of the five tickers). The quote stamped at the close itself is wide on NVDA and TSLA (`reports/research/m30_quote_survey.md`, measured before the run).
- A direction needs the two quotes not to overlap, so small moves and wide quotes are `FLAT_MOVE`. The paper goes short on a move that is not positive; here that is NO_TRADE.
- Dividends are not adjusted: on an ex-dividend session the move from the previous close is lower by the dividend. Split sessions are `CORPORATE_ACTION`: NVDA 2024-06-10.
- Declared differences from the paper (D3): exit 15:50, not 16:00; options, not ETF shares; NVDA and TSLA are single stocks, outside the paper.
- Owner rulings of 2026-11-15 used by this run:
  - 1_previous_close: mid of the quote in force prev_close_offset_minutes before the previous session's close; at most max_quote_age_s old, two-sided, not crossed
  - 2_signal_price: the quote in force at signal_time, same checks
  - 3_direction: up only if the signal bid > previous-close ask; down only if the signal ask < previous-close bid; otherwise FLAT_MOVE
  - 4_no_previous_close: first session, a previous session excluded by an ADR, or no usable quote there: NO_PREV_CLOSE
  - 5_corporate_actions: split_sessions are CORPORATE_ACTION; dividends are not adjusted
  - 6_step_a: signed mid(exit_time) / mid(entry_time) - 1 on every ticker-session with a direction, before option gates; no entry quote = NO_UNDERLYING_QUOTE; no exit quote = left out and counted
  - 7_m29_rulings_2_to_8: unchanged; the exit is the forced exit, so no usable option quote at exit_time + latency = UNRESOLVED_DATA
  - 8_full_count: the descriptive bound uses the registry's n_trials after registration
  - early_close: EARLY_CLOSE (owner, 2026-11-14)


## Checks on the saved rows (added by hand, 2026-11-15; no statistic above was changed)

On `data/research/m30/s2_rows.parquet` (3,284 ticker-sessions):
- No session after each ticker's last development day (QQQ 2026-04-02; the others 2025-10-02).
- At most one trade per session (743 trades on 743 sessions); every outlay is at or under $500
  (largest $496.03); every trade was sold at 15:50.
- The NO_TRADE sessions behave as ruled: `NO_PREV_CLOSE` on 2023-03-28 (all five), QQQ
  2023-12-28 (the day after the ADR-0006 session) and NVDA 2024-05-29; `NO_UNDERLYING_QUOTE`
  on NVDA 2024-05-28 and IWM 2025-09-26 (no usable 10:00 quote); `CORPORATE_ACTION` on NVDA
  2024-06-10.
- **The quotes behind the directions.** Over the 3,110 rows with a direction, the median
  spread of the previous-close quote is 0.002–0.016% and of the 10:00 quote 0.006–0.062%. On
  62 rows one of the two quotes is over 0.2% wide (largest 2.4%, IWM at 10:00); the direction
  is still certain there, because the two quotes do not overlap (ruling 3). 72 rows are
  `FLAT_MOVE`, 22 of them with a quote over 0.2% wide.
- Three rows were recomputed from the raw quote files by separate code (SPY 2024-03-05, TSLA
  2025-01-10, QQQ 2026-03-03): the two quotes and the direction match the run.

**Reading the result.** Step A alone stops S2: on these sessions the underlying did not move
in the morning's direction between 15:30 and 15:50 (mean −0.007%, interval [−0.023%, +0.008%],
against the paper's +0.026% on SPY for 1993–2013). The KILL comes from Step B: with no
directional move to collect, each trade pays the spread and the fees, and the loss is clear
even at the mid fill. This is a development-data result for this rule as frozen, with the
declared differences from the paper (exit at 15:50, options, quotes not trades, single
stocks). It is not evidence about any other version of the rule.
