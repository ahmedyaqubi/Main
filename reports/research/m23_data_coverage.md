# M23 Step 0: SPX data coverage (ADR-0014)

Generated 2026-10-10 00:35 UTC by `scripts/m23_coverage.py`, code 554b4aba69c3. Development sessions 2013-04-01 → 2025-10-02 (3148); the holdout (after 2025-10-02) was cleaned but not read.

**Data only:** entry-time quotes and exit-quote availability. No exit price, P&L or outcome; no trial registered.

## 1. Cells at entry (10:00 ET + latency)

- **OK**: a qualifying pair exists, with stored strikes beyond it.
- **AT_BAND_EDGE**: the pair sits at the edge of the downloaded strikes (a NO_TRADE in Step 1).
- **NO_QUALIFYING**: no pair reaches X x W.
- **NO_EXPIRY**: no listed expiry.
- *Gates pass*: every leg passes §4.9 at the **Phase 1 thresholds** (spread ≤ max($0.05, 5% of mid); min bid on short legs only).
- *Exit OK*: every leg has a usable ask at the exit, no older than 5 min.

| cell | target DTE | structure | X | sessions | OK | AT_BAND_EDGE | NO_QUALIFYING | NO_EXPIRY | gates pass (of OK) | exit OK (of OK) | crosses holdout |
|---|---|---|---|---|---|---|---|---|---|---|---|
| L1 | 30 | put | 0.20 | 3148 | 94.0% | 0.0% | 6.0% | 0.0% | 80.5% | 100.0% | 17 |
| L2 | 30 | condor | 0.15 | 3148 | 95.2% | 0.0% | 4.8% | 0.0% | 37.7% | 99.9% | 17 |
| L3 | 7 | put | 0.20 | 3148 | 99.4% | 0.0% | 0.6% | 0.0% | 56.2% | 100.0% | 4 |
| L4 | 7 | condor | 0.15 | 3148 | 99.5% | 0.0% | 0.5% | 0.0% | 18.5% | 99.9% | 4 |

§4.9 failures across OK entries (all cells; one entry can fail several):

- long:SPREAD_TOO_WIDE: 8361 (68.4%)
- short:SPREAD_TOO_WIDE: 6665 (54.6%)

Exit problems (OK entries whose exit is in development data): OK 12169, NOT_STORED 5.

R10 rule (owner, 2026-10-09; entry data only): each leg's spread <= 15% of its mid (no point cap; R10 amended); the other §4.9 gates are unchanged.

| cell | OK entries | pass R10 | fail: spread | fail: other gates |
|---|---|---|---|---|
| L1 | 2958 | 99.8% | 0.2% | 0.0% |
| L2 | 2998 | 89.4% | 10.6% | 0.0% |
| L3 | 3129 | 93.1% | 6.9% | 0.0% |
| L4 | 3131 | 76.8% | 23.2% | 0.0% |

## 2. Picked-leg spreads (all OK entries; median by year), SPX points

| year | cell | entries | median spread | median spread / mid | median W | median strike step at pick | median DTE | entries with both roots |
|---|---|---|---|---|---|---|---|---|
| 2013 | L1 | 192 | 0.65 | 4.2% | 10 | 5 | 30 | 0 |
| 2013 | L2 | 192 | 0.55 | 6.5% | 10 | 5 | 30 | 0 |
| 2013 | L3 | 192 | 0.35 | 5.7% | 10 | 5 | 8 | 0 |
| 2013 | L4 | 192 | 0.30 | 7.8% | 10 | 5 | 8 | 0 |
| 2014 | L1 | 252 | 0.70 | 3.9% | 10 | 5 | 30 | 0 |
| 2014 | L2 | 252 | 0.55 | 6.3% | 10 | 5 | 30 | 0 |
| 2014 | L3 | 252 | 0.45 | 6.2% | 10 | 5 | 8 | 0 |
| 2014 | L4 | 252 | 0.31 | 8.4% | 10 | 5 | 8 | 0 |
| 2015 | L1 | 245 | 1.25 | 4.3% | 10 | 5 | 30 | 0 |
| 2015 | L2 | 246 | 1.00 | 7.6% | 10 | 5 | 30 | 0 |
| 2015 | L3 | 248 | 0.90 | 7.1% | 10 | 5 | 8 | 0 |
| 2015 | L4 | 248 | 0.75 | 11.4% | 10 | 5 | 8 | 0 |
| 2016 | L1 | 237 | 0.85 | 3.4% | 10 | 5 | 29 | 0 |
| 2016 | L2 | 242 | 0.65 | 5.7% | 10 | 5 | 29 | 0 |
| 2016 | L3 | 251 | 0.55 | 6.6% | 10 | 5 | 7 | 0 |
| 2016 | L4 | 252 | 0.45 | 9.0% | 10 | 5 | 7 | 0 |
| 2017 | L1 | 243 | 0.45 | 2.8% | 10 | 5 | 30 | 16 |
| 2017 | L2 | 241 | 0.35 | 4.6% | 10 | 5 | 30 | 16 |
| 2017 | L3 | 251 | 0.35 | 5.8% | 10 | 5 | 7 | 8 |
| 2017 | L4 | 251 | 0.30 | 7.5% | 10 | 5 | 7 | 8 |
| 2018 | L1 | 250 | 0.55 | 2.4% | 15 | 5 | 30 | 25 |
| 2018 | L2 | 251 | 0.45 | 3.6% | 15 | 5 | 30 | 25 |
| 2018 | L3 | 251 | 0.40 | 4.1% | 15 | 5 | 7 | 12 |
| 2018 | L4 | 251 | 0.30 | 5.5% | 15 | 5 | 7 | 12 |
| 2019 | L1 | 251 | 0.45 | 1.7% | 15 | 5 | 30 | 28 |
| 2019 | L2 | 252 | 0.40 | 3.1% | 15 | 5 | 30 | 28 |
| 2019 | L3 | 252 | 0.35 | 3.4% | 15 | 5 | 7 | 13 |
| 2019 | L4 | 252 | 0.30 | 5.0% | 15 | 5 | 7 | 13 |
| 2020 | L1 | 216 | 0.70 | 1.4% | 15 | 5 | 29 | 25 |
| 2020 | L2 | 223 | 0.65 | 2.4% | 15 | 5 | 29 | 25 |
| 2020 | L3 | 246 | 0.45 | 2.3% | 15 | 5 | 7 | 10 |
| 2020 | L4 | 246 | 0.38 | 3.5% | 15 | 5 | 7 | 10 |
| 2021 | L1 | 241 | 0.60 | 1.2% | 20 | 5 | 29 | 25 |
| 2021 | L2 | 245 | 0.50 | 2.4% | 20 | 5 | 29 | 25 |
| 2021 | L3 | 252 | 0.38 | 2.2% | 20 | 5 | 7 | 12 |
| 2021 | L4 | 251 | 0.30 | 3.8% | 20 | 5 | 7 | 12 |
| 2022 | L1 | 223 | 0.70 | 1.2% | 20 | 5 | 29 | 27 |
| 2022 | L2 | 229 | 0.65 | 1.9% | 20 | 5 | 29 | 28 |
| 2022 | L3 | 247 | 0.45 | 2.0% | 20 | 5 | 7 | 13 |
| 2022 | L4 | 250 | 0.40 | 3.1% | 20 | 5 | 7 | 13 |
| 2023 | L1 | 216 | 0.55 | 1.4% | 20 | 5 | 30 | 24 |
| 2023 | L2 | 222 | 0.50 | 2.2% | 20 | 5 | 30 | 24 |
| 2023 | L3 | 249 | 0.40 | 2.7% | 20 | 5 | 7 | 12 |
| 2023 | L4 | 248 | 0.30 | 3.7% | 20 | 5 | 7 | 12 |
| 2024 | L1 | 232 | 0.65 | 1.5% | 25 | 5 | 30 | 25 |
| 2024 | L2 | 236 | 0.60 | 2.1% | 25 | 5 | 30 | 25 |
| 2024 | L3 | 251 | 0.40 | 2.4% | 25 | 5 | 7 | 12 |
| 2024 | L4 | 251 | 0.30 | 3.4% | 25 | 5 | 7 | 12 |
| 2025 | L1 | 160 | 0.80 | 1.2% | 30 | 5 | 30 | 18 |
| 2025 | L2 | 167 | 0.70 | 1.8% | 30 | 5 | 30 | 18 |
| 2025 | L3 | 187 | 0.40 | 1.7% | 30 | 5 | 7 | 10 |
| 2025 | L4 | 187 | 0.30 | 2.5% | 30 | 5 | 7 | 10 |

## 3. Minimum detectable effect (R5; outcome-free)

A one-sided test at alpha = 0.05 with power 80%, on the mean net P&L per trade. The P&L range per spread is at most W x 100 (credit to -(W - credit)), so sigma <= W x 50 (Popoviciu). n_eff = development sessions ÷ median holding period (sessions), the number of independent holding periods.

These are **upper bounds**: the true MDE is smaller if P&L is less dispersed than the worst case. In units of the median conservative credit, an MDE above 1 means the screen cannot detect an effect as large as the whole credit.

| cell | median W | median hold (sessions) | n_eff | MDE $/trade (≤) | median credit $ | MDE / credit |
|---|---|---|---|---|---|---|
| L1 | 15 | 20 | 157 | 149 | 300 | 0.50 |
| L2 | 15 | 20 | 157 | 149 | 480 | 0.31 |
| L3 | 15 | 4 | 787 | 66 | 320 | 0.21 |
| L4 | 15 | 4 | 787 | 66 | 490 | 0.14 |

## 4. Cleaning (M4 rules, SPX config copy per root)

| year | raw quotes | rejected | rate |
|---|---|---|---|
| 2013 | 241,454 | 0 | 0.0% |
| 2014 | 403,164 | 0 | 0.0% |
| 2015 | 490,392 | 3 | 0.0% |
| 2016 | 517,050 | 0 | 0.0% |
| 2017 | 602,158 | 0 | 0.0% |
| 2018 | 749,498 | 0 | 0.0% |
| 2019 | 786,600 | 0 | 0.0% |
| 2020 | 845,986 | 17 | 0.0% |
| 2021 | 1,007,602 | 12 | 0.0% |
| 2022 | 997,603 | 4 | 0.0% |
| 2023 | 929,390 | 0 | 0.0% |
| 2024 | 1,080,980 | 0 | 0.0% |
| 2025 | 836,561 | 0 | 0.0% |

Rejection reasons: BID_GT_ASK 36, NONPOSITIVE_PRICE 36.

## 5. Open items for Step 1 (owner decides; no definition changed here)

- **Liquidity gates for SPX:** see §1-§2. The Phase 1 thresholds were calibrated on QQQ (M4); SPX thresholds need an ADR before Step 1.
- **Root on shared expiry dates:** this report used SPXW when SPX and SPXW list the same date (see 'entries with both roots').
- **Power:** see §3.

