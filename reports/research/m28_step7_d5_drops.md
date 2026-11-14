# M28 step 7: what the ADR-0021 D5 rules drop (not a trial)

2026-11-14. Inputs:
- the cost map in `reports/research/m28_step6_cost_map.md` (`scripts/m28_cost_map.py`);
- the data built by `scripts/m28_build_data.py` from the step 5 purchase.

Development sessions only. No signal or setup return was computed.

## Result

**Nothing is dropped.** Every ticker passes D5 rule 1 for both setups, under both brokers'
fees, and under both ways of counting the time decay. D5 rule 2 is not applied (amendment A2).
Both setups therefore go forward to D6 on all six tickers.

The table shows each setup's median break-even move and the 75th percentile of the absolute
move over its holding window. The break-even move is shown under two time counts: calendar time
/ trading hours only. IBKR fees are shown; Webull's differ by at most 0.03 percentage points.

| ticker | S1 break-even | S1 75th pct move | S2 break-even | S2 75th pct move |
|---|---|---|---|---|
| QQQ | 0.13% / 0.31% | 0.91% | 0.02% / 0.04% | 0.15% |
| SPY | 0.09% / 0.22% | 0.64% | 0.02% / 0.03% | 0.12% |
| IWM | 0.17% / 0.40% | 1.01% | 0.05% / 0.07% | 0.19% |
| NVDA | 0.27% / 0.64% | 2.29% | 0.07% / 0.10% | 0.36% |
| TSLA | 0.32% / 0.74% | 2.75% | 0.08% / 0.11% | 0.43% |
| AAPL | 0.17% / 0.38% | 1.09% | 0.06% / 0.07% | 0.21% |

**What rule 1 does not show.** Passing rule 1 means only that the median contract does not need an
unusually large move to cover its costs. It says nothing about whether either setup predicts
direction. That is the D6 screen's job. Costs remain material:
- the median round trip is 1.8–4.1% of the premium paid;
- IWM is the costliest, at 3.8% (S1) and 4.1% (S2).

## The $500 ceiling limits NVDA and TSLA

| | QQQ | SPY | IWM | NVDA | TSLA | AAPL |
|---|---|---|---|---|---|---|
| S1: sessions with the ATM contract under $500 | 96.6% | 98.5% | 100% | 57.7% | 47.3% | 98.5% |
| S2: same | 98.7% | 99.0% | 100% | 63.6% | 57.8% | 99.1% |

- On the other sessions, NVDA and TSLA are NO_TRADE with reason `PREMIUM_OVER_CAP` (D2).
- Tradeable sessions per side for S1: NVDA 364 and TSLA 298, against 618–729 for the others.

The cause is the expiry schedule. NVDA, TSLA and AAPL list only weekly (Friday) expirations in
this window, measured from the purchased definitions:
- only 21% of their sessions have an expiry on the next session;
- the D2 contract is up to 5 sessions out, so its premium is larger.

This settles the step 3 question about expirations:

| ticker | expiry on the next session |
|---|---|
| QQQ, SPY | every session |
| IWM | every session from 2024-04-18 on |
| NVDA, TSLA, AAPL | 21% of sessions; weeklies only throughout |

## Required edge (information only, amendment A2)

- **Level:** the D7 ADVANCE level of 98.33%, one-sided.
- **Expected trades,** pooled over the six tickers: S1 3,258, S2 3,356.
- **Required mean net return per trade:** about **0.98% of the premium (S1)** and **0.96%
  (S2)**.

These are too low, especially for S1. The spread of returns comes from M11 trades, which target
and stop exits closed after a median of about 20–25 minutes (spread 0.26). S1 holds 09:35 →
15:50 with no such limit.

## Data gaps found (development sessions, all tickers)

All the gaps leave the affected setup with no usable quote at entry. Under the frozen rules that
is NO_TRADE. No data was altered or filled.

| session | ticker | setup | what is missing |
|---|---|---|---|
| 2023-07-05 | QQQ, SPY (call and put); IWM, AAPL (call) | S1 | 09:35 option quotes rejected as crossed (`BID_GT_ASK`): the same event as QQQ's step 4 gap |
| 2025-04-07 | SPY | S1 | 09:34–09:36 option quotes rejected as crossed (the tariff sell-off open) |
| 2024-05-28 | AAPL, NVDA | S1, S2 | **Databento delivered almost no underlying quotes** (3 and 2 records, none in regular hours); SPY and TSLA are complete that day |

**Days Databento marks as reduced quality:**
- 2 days in OPRA and 15 days in EQUS.MINI, most of the EQUS.MINI days in 2025;
- every D2 contract was priced on each of them;
- the list is in the step 6 report.

**Records rejected while cleaning** (M4 rules, with the M23 precedent for the non-QQQ roots):

| ticker | option quotes rejected | of | underlying quotes rejected |
|---|---|---|---|
| SPY | 1,675 | 5.56M | 0 |
| IWM | 398 | 4.58M | 1 |
| NVDA | 2,538 | 5.39M | 1 |
| TSLA | 55,862 | 5.16M | 0 |
| AAPL | 236 | 3.69M | 0 |

Of TSLA's rejections, 55,238 are `NONSTANDARD_STRIKE`. They are the legacy strikes left by the
2022 3-for-1 split, such as 206.67 and 213.33, which appear on monthly expiries. They are not
on the $0.50 grid and are excluded, as QQQ's are.

## Open items (not decided here)

- **Earnings sessions (D1)** are not yet excluded for NVDA, TSLA and AAPL:
  - no point-in-time earnings calendar has been verified (step 3);
  - by D1, without one the single stocks are dropped before any trial;
  - the cost map above includes their earnings sessions.
- **S2's paper** is still unverified (step 3). It must be confirmed before S2's test is
  registered.
- **The AAPL/NVDA gap on 2024-05-28:** owner, 2026-11-14, "Keep as NO_TRADE". The
  session stays in, unchanged.
- **The break-even move assumes Black-Scholes** with r = 0 and an unchanged implied volatility.
  It does not include latency or the rounding of fills against the trader. The trading-hours
  time count is the stricter one; the two counts agree for every ticker and setup.

## What was bought (step 5)

- **Approved:** $7.66.
- **Priced files:** 9,280 at $7.6608, all on disk, no request unresolved.
- **Re-downloads:** after a restart, a few partly downloaded files were fetched again, adding
  about $0.002 at most. Databento's account page shows the final charge.
- **Holdout files** (2025-10-03 → 2026-10-02) are stored as delivered and were not opened.
