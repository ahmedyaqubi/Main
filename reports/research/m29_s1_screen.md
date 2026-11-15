# M29: D6 screen of setup S1, first 5-minute candle (ADR-0021, amendment A1)

Generated 2026-11-15 09:32 UTC by `scripts/m29_screen.py`, code df742f0885d8. Registered run `screen_orb-7c87b7281f30` (n_trials 42 → 43). Test 1 of the 3 that ADR-0021 D7 allows. Development sessions only; no holdout file was opened.

## Outcome: **AMBIGUOUS**

### Step A: the underlying
- Mean signed return, entry → exit, over 3,130 ticker-sessions with a signal (756 sessions): **0.0439%**
- One-sided 95% lower bound: **0.0058%** (above 0: Step A passes)
- Two-sided 95% interval: [-0.0009%, 0.0907%]

### Step B: the option trades
- Trades: **740** (guard ≥ 60, met); one position at a time; buy at the ask, sell at the bid; `ibkr_canada` fees
- Mean net P&L per trade as a share of the premium paid: **-3.00%**
- One-sided 98.33% lower bound: **-6.65%** (ADVANCE needs > 0)
- Two-sided 95% interval: [-6.40%, 0.61%]
- Lower bound at the full recorded count (42 + 1 trials, one-sided 99.884%): -8.25%
- **Mid fill (KILL row), same trades:** mean -1.67%, two-sided 95% interval [-5.19%, 2.06%] (KILL needs the upper bound < 0)
- Session bootstrap, 20,000 reps, seed 20261007.

Development-data result with its uncertainty. Not a claim of profitability, and not out-of-sample.

## Risk rows (always reported)

- Mean net per trade: $-7.19; total over the period: $-5,320.26 (one contract per trade)
- Winning trades: 21.5%
- Worst trade: QQQ 2025-10-10, -81.45% ($-171.05)
- Longest losing run: 16 trades
- Largest drawdown: $8,359.75
- $1,000 total loss cap (reported, the series is not stopped): reached on 2024-03-26
- `PREMIUM_OVER_CAP`: 589; `POSITION_OPEN`: 1,793
- Exits of the trades taken: {'STOP': 541, 'TIME': 166, 'TARGET': 33}
- Trades with no usable exit quote by the forced exit (`UNRESOLVED_DATA`, left out): 0; mean with those counted as a total loss: -3.00%
- Exits sold later than the trigger minute (no usable quote at it): 0; exits with no bid (sold at 0): 0
- Underlying path minutes with no usable quote (stop and target not checked there): 0
- Same trades under `webull_canada` fees: mean -2.99%
- Largest distance between a traded strike and the underlying at entry: 1.95% (a check that the listed chain reached the money)

## Every ticker-session, by result

TRADE = took the position. Everything else is NO_TRADE with its reason.

| ticker | sessions | EARNINGS_WINDOW | FLAT_FIRST_CANDLE | NO_OPTION_QUOTE | NO_UNDERLYING_QUOTE | POSITION_OPEN | PREMIUM_OVER_CAP | SELECTED_CONTRACT_ILLIQUID | TRADE |
|---|---|---|---|---|---|---|---|---|---|
| IWM | 632 | 0 | 1 | 0 | 37 | 581 | 0 | 3 | 10 |
| NVDA | 632 | 30 | 3 | 0 | 6 | 278 | 247 | 0 | 68 |
| QQQ | 756 | 0 | 2 | 1 | 11 | 343 | 27 | 1 | 371 |
| SPY | 632 | 0 | 1 | 2 | 26 | 356 | 8 | 1 | 238 |
| TSLA | 632 | 30 | 0 | 0 | 7 | 235 | 307 | 0 | 53 |

Underlying exits over all signals (Step A): {'TIME': 816, 'STOP': 2169, 'TARGET': 145}

## Per ticker (descriptive only; D6)

| ticker | trades | calls | mean net / premium | winning | total $ |
|---|---|---|---|---|---|
| IWM | 10 | 5 | -18.42% | 10.0% | -542.55 |
| NVDA | 68 | 38 | -9.81% | 23.5% | -1,609.76 |
| QQQ | 371 | 190 | 1.42% | 26.1% | 1,034.16 |
| SPY | 238 | 124 | -6.65% | 14.3% | -3,000.06 |
| TSLA | 53 | 26 | -5.93% | 20.8% | -1,202.06 |

## Per year (descriptive only)

| year | trades | calls | mean net / premium | winning | total $ |
|---|---|---|---|---|---|
| 2023 | 192 | 115 | -0.19% | 21.9% | -402.56 |
| 2024 | 251 | 122 | -3.62% | 21.1% | -1,625.92 |
| 2025 | 242 | 115 | -6.72% | 20.2% | -4,336.59 |
| 2026 | 55 | 31 | 6.37% | 27.3% | 1,044.80 |

## How it was run

- QQQ: 756 development sessions, 2023-03-28 → 2026-04-02
- SPY: 632 development sessions, 2023-03-28 → 2025-10-02
- IWM: 632 development sessions, 2023-03-28 → 2025-10-02
- NVDA: 632 development sessions, 2023-03-28 → 2025-10-02
- TSLA: 632 development sessions, 2023-03-28 → 2025-10-02
- AAPL is out (D1: five earnings dates not verified in advance). NVDA and TSLA earnings sessions, and the session on each side, are `EARNINGS_WINDOW`.
- After 2025-10-02 only QQQ has development data, so the pooled sample is uneven in time.
- The underlying is the mid of 1-minute quotes. The candle's high and low are the highest and lowest of the mids stamped 09:30 to 09:35, so moves inside a minute are not seen; the same holds for the stop and the target.
- The candle's open is the last quote at or before 09:30:00 (a pre-open quote), at most 60 seconds old; the record stamped 09:30:00 is missing on 1 to 27 sessions per ticker.
- Owner rulings of 2026-11-15 used by this run:
  - 1_candle_high_low: max/min of the 1-minute quote mids stamped candle_start..candle_end
  - 2_step_a_population: every ticker-session with a signal, before option gates and D3
  - 3_d3_competitors: only contracts passing every gate; ties by ticker order
  - 4_decision_fees: ibkr_canada
  - 5_return_denominator: entry fill x 100, fees in the numerator only
  - 6_kill_at_mid: the conservative run's trades repriced at the mid, with fees
  - 7_exit_quote: first later minute with a usable quote; none by forced exit = unresolved
  - 8_loss_cap: drawdown and cap date reported; the series is not stopped
  - 9_candle_open: latest quote at or before 09:30:00, at most max_quote_age_s old (pre-open quotes allowed); none = NO_UNDERLYING_QUOTE

## Found after the run (added by hand, 2026-11-15; no statistic above was changed)

**The candle's open is often a wide pre-open quote.** Ruling 9 takes the open from the last
quote at or before 09:30:00. That quote is a pre-market one, and the underlying has no spread
gate (only "two-sided, not crossed, not stale"). Measured after the run, on the 3,130 signal
rows, spread of that quote as a share of its mid:

| ticker | median | 90th percentile | largest | rows over 0.2% |
|---|---|---|---|---|
| QQQ | 0.013% | 0.06% | 200% | 29 of 743 |
| SPY | 0.010% | 0.018% | 6.0% | 12 of 605 |
| IWM | 0.027% | 0.037% | 10.0% | 6 of 594 |
| NVDA | 0.34% | 0.97% | 7.5% | 445 of 593 |
| TSLA | 0.27% | 0.86% | 2.8% | 396 of 595 |

- For NVDA and TSLA the typical open spread (about 0.3%) is of the same size as a 5-minute
  candle, so on most of their rows the direction and the stop rest on a noisy open.
- Of the 740 trades, 115 had an open spread over 0.2% and 184 over 0.05%.
- Example: the worst trade (QQQ 2025-10-10) had an open quote 3.1% wide, giving a stop 1.5%
  from the entry.
- **Effect on the result:** the run tested S1 with this open, not the paper's opening trade
  price. Noise in the open should weaken a real effect, not create one, but that is an
  expectation, not a measurement. No result was sliced by this spread, and no second version
  was run: that would be a new variant, which D6 does not allow without the owner's decision.

**Other checks on the saved rows** (`data/research/m29/s1_rows.parquet`):
- At most one trade per session (740 trades on 740 sessions); every outlay is at or under
  $500 (largest $497.03); no session after 2026-04-02.
- The owner's NO_TRADE sessions behave as ruled: 2023-07-05 QQQ and SPY `NO_OPTION_QUOTE`
  (rejected quote); SPY 2025-04-07 `NO_OPTION_QUOTE`; NVDA 2024-05-28 `NO_UNDERLYING_QUOTE`.
  IWM had a usable quote on 2023-07-05 (M28 found only its call rejected) and was a
  candidate that day.
- Distance from the traded strike to the underlying: at most 0.4% for QQQ, SPY and IWM; up to
  1.4% (NVDA) and 2.0% (TSLA), in line with their wider strike spacing.
