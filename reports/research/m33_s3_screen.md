# M33: D6 screen of setup S3, the noise-area breakout (ADR-0021 amendment A3)

Generated 2026-11-16 08:38 UTC by `scripts/m33_screen.py`, code cae2c89ea72b. Registered run `screen_noise_area-861c924a1cfc` (n_trials 44 → 45). Test 3 of the 3 that ADR-0021 D7 allows, the last. Development sessions only; no holdout file was opened.

## Outcome: **AMBIGUOUS**

### Step A: the underlying
- Mean signed return, entry check → exit, over 1,839 ticker-sessions with a signal (640 sessions): **0.0671%**
- One-sided 95% lower bound: **-0.0035%** (not above 0: the setup stops here)
- Two-sided 95% interval: [-0.0152%, 0.1591%]
- Signals: 1,839, of which up 957; underlying exits: OPPOSITE 39, TIME 1,800; left out of Step A for want of an underlying quote at 15:50: 0
- Checks skipped for want of a usable underlying quote: 1

### Step B: the option trades (descriptive only: Step A did not pass)
- Trades: **599** (guard ≥ 60, met); one position at a time; buy at the ask at the signal's check, sell at the bid at the exit; `ibkr_canada` fees
- Mean net P&L per trade as a share of the premium paid: **-6.24%**
- One-sided 98.33% lower bound: **-11.18%** (ADVANCE needs > 0)
- Two-sided 95% interval: [-10.80%, -1.49%]
- Lower bound at the full recorded count (45 trials, one-sided 99.889%): -13.11%
- **Mid fill (KILL row), same trades:** mean -4.04%, two-sided 95% interval [-8.74%, 0.85%] (KILL needs the upper bound < 0)
- Session bootstrap, 20,000 reps, seed 20261007. Sessions are resampled whole, so trades of one day stay together.

Development-data result with its uncertainty. Not a claim of profitability, and not out-of-sample.

## Risk rows (always reported)

- Mean net per trade: $-13.36; total over the period: $-8,000.08 (one contract per trade)
- Winning trades: 39.6%
- Worst trade: SPY 2024-09-11, -92.96% ($-237.05)
- Longest losing run: 10 trades
- Largest drawdown: $8,668.38
- $1,000 total loss cap (reported, the series is not stopped): reached on 2023-05-16
- `PREMIUM_OVER_CAP`: 313; `POSITION_OPEN`: 850
- Option exits: OPPOSITE 18, TIME 581
- Trades with no usable option quote by 15:50 (`UNRESOLVED_DATA`, left out): 0; mean with those counted as a total loss: -6.24%
- Sales made at a later minute than the exit: 0; exits with no bid (sold at 0): 0
- Sessions with a trade: 596; with more than one: 3; most trades in one session: 2; largest premium spent in one session: $689.05 (D2: must not exceed the settled balance)
- Same trades under `webull_canada` fees: mean -6.23%
- Largest distance between a traded strike and the underlying at entry: 1.39% (a check that the listed chain reached the money)

## Signals and trades by check (descriptive only)

| check | signals | trades |
|---|---|---|
| 10:00 | 794 | 358 |
| 10:30 | 350 | 107 |
| 11:00 | 169 | 42 |
| 11:30 | 116 | 24 |
| 12:00 | 84 | 20 |
| 12:30 | 76 | 15 |
| 13:00 | 52 | 3 |
| 13:30 | 47 | 6 |
| 14:00 | 46 | 9 |
| 14:30 | 55 | 7 |
| 15:00 | 50 | 8 |

## Every ticker-session, by result

TRADE = took the position. Everything else is NO_TRADE with its reason.

| ticker | sessions | CORPORATE_ACTION | EARLY_CLOSE | EARNINGS_WINDOW | NO_HISTORY | NO_PREV_CLOSE | NO_SIGNAL | NO_UNDERLYING_QUOTE | POSITION_OPEN | PREMIUM_OVER_CAP | SELECTED_CONTRACT_ILLIQUID | TRADE |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| IWM | 632 | 0 | 6 | 0 | 14 | 0 | 244 | 0 | 247 | 0 | 26 | 95 |
| NVDA | 632 | 1 | 6 | 30 | 14 | 1 | 240 | 1 | 112 | 135 | 3 | 89 |
| QQQ | 756 | 0 | 8 | 0 | 14 | 1 | 313 | 0 | 190 | 8 | 30 | 192 |
| SPY | 632 | 0 | 6 | 0 | 14 | 0 | 240 | 0 | 218 | 5 | 15 | 134 |
| TSLA | 632 | 0 | 6 | 30 | 14 | 0 | 242 | 0 | 83 | 165 | 3 | 89 |

## Per ticker (descriptive only; D6)

| ticker | trades | calls | mean net / premium | winning | total $ |
|---|---|---|---|---|---|
| IWM | 95 | 51 | -9.55% | 34.7% | -437.05 |
| NVDA | 89 | 47 | -1.93% | 41.6% | -795.95 |
| QQQ | 192 | 89 | -4.05% | 44.8% | -2,044.72 |
| SPY | 134 | 82 | -12.92% | 34.3% | -3,466.26 |
| TSLA | 89 | 42 | -1.71% | 39.3% | -1,256.09 |

## Per year (descriptive only)

| year | trades | calls | mean net / premium | winning | total $ |
|---|---|---|---|---|---|
| 2023 | 157 | 87 | -6.63% | 39.5% | -3,380.56 |
| 2024 | 228 | 120 | -7.00% | 37.3% | -2,569.55 |
| 2025 | 178 | 88 | -4.77% | 42.1% | -1,070.93 |
| 2026 | 36 | 16 | -7.08% | 41.7% | -979.05 |

## Checks on the saved rows

- one position at a time: yes
- one row per ticker session: yes
- every outlay within the ceiling: yes
- every entry at a check by the last entry check: yes
- every sale by the forced exit: yes
- every signal has a full history: yes
- no session after dev end: yes

## Recomputed by separate code (added after the run; nothing was re-run)

Three trades were recomputed from the cleaned quote files with polars alone, without importing
the project's S3 code: the open at 09:31, the previous close at 15:59, sigma from the row's 14
history dates, both boundaries, the direction, the underlying at the entry check, the option's
ask at entry + 5 s and its bid at the exit + 5 s. Every value matches the saved row.

| ticker | session | check | side | sigma | upper | lower | entry ask | exit | exit bid | net / premium |
|---|---|---|---|---|---|---|---|---|---|---|
| QQQ | 2024-12-30 | 10:00 | put | 0.2424% | 523.5060 | 513.9760 | 3.13 | 15:50 (time) | 0.89 | −72.22% |
| NVDA | 2025-01-07 | 10:00 | put | 0.9068% | 153.5802 | 147.8074 | 2.68 | 15:50 (time) | 5.80 | +115.65% |
| SPY | 2023-05-03 | 10:00 | call | 0.1297% | 412.1037 | 410.6019 | 2.25 | 15:30 (opposite) | 0.59 | −74.69% |

Not covered by this check: that the 14 history dates are the right ones (they were taken from
the row, not chosen again).

## How it was run

- QQQ: 756 development sessions, 2023-03-28 → 2026-04-02
- SPY: 632 development sessions, 2023-03-28 → 2025-10-02
- IWM: 632 development sessions, 2023-03-28 → 2025-10-02
- NVDA: 632 development sessions, 2023-03-28 → 2025-10-02
- TSLA: 632 development sessions, 2023-03-28 → 2025-10-02
- AAPL is out (D1: five earnings dates not verified in advance). NVDA and TSLA earnings sessions, and the session on each side, are `EARNINGS_WINDOW`; they still count as history for later sessions.
- After 2025-10-02 only QQQ has development data, so the pooled sample is uneven in time.
- The underlying is read from 1-minute quotes. Today's open is the quote in force 1 minute after the open; the previous close is the quote in force 1 minute before the previous session's close. Neither is the official opening or closing trade price (`reports/research/m33_quote_survey.md`, measured before the run).
- A signal or an exit needs the whole quote beyond the boundary, so a wide quote gives neither.
- Dividends are not adjusted: on an ex-dividend session the previous close, and with it the upper boundary, is higher by about the dividend. Split sessions are `CORPORATE_ACTION`: NVDA 2024-06-10.
- Declared differences from the paper (A3): options, not shares; one trade per ticker-session, no reversal; the base-model exit; five tickers (the paper: SPY); quotes, not trade bars; exit 15:50; last entry 15:00.
- Owner rulings of 2026-11-16 used by this run:
  - 1_todays_open: mid of the quote in force open_offset_minutes after the open; at most max_quote_age_s old, two-sided, not crossed; none = NO_UNDERLYING_QUOTE
  - 2_previous_close: M30 ruling 1: mid of the quote in force prev_close_offset_minutes before the previous session's close; none = NO_PREV_CLOSE; dividends not adjusted
  - 3_check_prices: the quote in force at each check; boundaries and sigma use mids; call only if bid > upper, put only if ask < lower; exit a call only if ask < lower, a put only if bid > upper; a check with no usable quote is skipped and counted
  - 4_history: the lookback_sessions most recent usable sessions before today; usable = not an early close, with the open quote and every check quote; earnings-window sessions count as history; fewer = NO_HISTORY; split_sessions are CORPORATE_ACTION
  - 5_one_position: signals in time order; a position is open from its entry until its option is sold; a first signal at or before that sale is POSITION_OPEN and the ticker does not trade later that session; same-check ties by cost share, then ticker order
  - 6_step_a: signed mid(exit) / mid(entry check) - 1 on every ticker-session with a signal, before option gates and the one-position rule; no exit quote = left out, counted
  - 7_carried_over: M29 rulings 3-8 and M30 ruling 8
  - early_close: EARLY_CLOSE (A3)

