# M19T Step 0: data coverage (ADR-0013, PROPOSED)

Generated 2026-10-08 21:33 UTC by `scripts/m19t_coverage.py`, code 96199080ef92. Development sessions 2020-01-02 → 2026-04-02 only. Sessions after 2026-04-02 (ADR-0011 holdout) were stored and cleaned (`scripts/m19t_build_data.py`) and are not read here (the loader refuses them).

**Data only.** Entry-time quotes and quote availability. No exit price, P&L or outcome is computed. No trial is registered (n_trials stays 38).

Sources: `0dte` = Step-0 expiry-day contracts (sessions from 2023-03-28); `ext` = Step-0 D2 extension (contracts expiring D and D+1, 2020-01-02 → 2023-03-27); `m4` = the M4 1DTE store (contracts expiring D+1, used for 1DTE entries from 2023-03-28).

## 1. Sessions per era and weekday

Eras are inferred from the listings: Mon and Wed expirations are continuous from **2021-05-05**, Tue and Thu from **2022-11-17**. Isolated sessions inside a run with no listed whole-dollar contract expiring that day: none (see §5). A session counts for 0DTE if a standard contract expiring that day is listed, and for 1DTE if one expiring on the next session is listed. Excluded sessions (ADR-0006) are counted separately.

| era | weekday | sessions | excluded | with 0DTE expiry | with next-session expiry |
|---|---|---|---|---|---|
| 1 Friday-only | Mon | 64 | 0 | 1 | 2 |
| 1 Friday-only | Tue | 70 | 0 | 2 | 4 |
| 1 Friday-only | Wed | 69 | 0 | 2 | 6 |
| 1 Friday-only | Thu | 69 | 0 | 5 | 64 |
| 1 Friday-only | Fri | 65 | 0 | 65 | 1 |
| 2 Mon/Wed/Fri | Mon | 71 | 0 | 71 | 1 |
| 2 Mon/Wed/Fri | Tue | 80 | 0 | 10 | 80 |
| 2 Mon/Wed/Fri | Wed | 81 | 0 | 81 | 7 |
| 2 Mon/Wed/Fri | Thu | 79 | 0 | 5 | 79 |
| 2 Mon/Wed/Fri | Fri | 78 | 0 | 78 | 78 |
| 3 daily | Mon | 157 | 0 | 157 | 157 |
| 3 daily | Tue | 175 | 0 | 175 | 175 |
| 3 daily | Wed | 173 | 1 | 172 | 172 |
| 3 daily | Thu | 168 | 0 | 168 | 168 |
| 3 daily | Fri | 172 | 0 | 172 | 172 |

| era | sessions | 0DTE sessions | 1DTE entry sessions |
|---|---|---|---|
| 1 Friday-only | 337 | 75 | 77 |
| 2 Mon/Wed/Fri | 389 | 245 | 245 |
| 3 daily | 845 | 844 | 844 |
| all | 1571 | 1164 | 1166 |

Sessions from 2023 on with a 0DTE expiry: 814; with a next-session expiry: 814 (D4 guard: ≥ 150). Friday→Monday and pre-holiday 1DTE entries are counted in the 1DTE column; D4 reports them as descriptive rows only.

## 2. Expiry-day quotes at the forced exit (15:50 ET; close - 10 min on early closes)

Every standard contract expiring that day in the stored band. *Ask usable*: the latest record at exit + latency (5 s) is not rejected, has ask > 0 and is at most 5 min old (D1.c; a missing ask → UNRESOLVED_DATA). *Reaches exit*: the contract file has records at or after the exit time.

| era | expiry sessions | early closes | contractsxsessions | ask usable | bid > 0 | sessions reaching exit | worst session (ask usable) |
|---|---|---|---|---|---|---|---|
| 1 Friday-only | 75 | 2 | 5,086 | 100.00% | 60.89% | 75/75 | 2020-01-03 100.0% |
| 2 Mon/Wed/Fri | 245 | 1 | 19,644 | 100.00% | 58.53% | 245/245 | 2021-05-05 100.0% |
| 3 daily | 844 | 9 | 90,446 | 99.93% | 59.46% | 844/844 | 2025-11-20 92.3% |

Sessions with ask usable for < 95% of stored contracts: 3: 2025-10-17 (94%), 2025-11-19 (95%), 2025-11-20 (92%).

## 3. Strike coverage for the credit-fraction rule (D1.a)

At every entry timestamp T in the cell windows (0DTE 09:45-10:30, 1DTE 13:00-14:30 ET, every 5 min, T_e = T + 5 s): short = furthest-OTM strike with short bid - long ask ≥ X x $1, long = short ∓ $1, using only quotes in force at T_e (not rejected, ≤ 60 s old). Puts at X = 0.2, 0.33; calls at X = 0.2 (condor call side).

- **OK**: a qualifying pair exists and stored strikes lie beyond its long leg.
- **AT_BAND_EDGE**: the long leg is the outermost stored strike. A further pair outside the download band cannot be ruled out (coverage failure).
- **NO_QUALIFYING**: no pair reaches X (D1.a NO_TRADE).
- *beyond p5*: 5th percentile of stored strikes beyond the long leg (margin to the band edge).
- *both legs pass §4.9*: `liquidity_failures` (spread, min bid $0.20, size, freshness) on both legs as ADR-0013 D1.b requires.
- *exit usable*: both legs have a usable ask at the expiry-day exit (as §2). *gap > 5 min*: a leg has no usable record for longer than that during the hold (RTH only; the overnight close is not a gap).

| tenor | side | X | era | entries | OK | AT_BAND_EDGE | NO_QUALIFYING | beyond p5 | both legs pass §4.9 | exit legs stored | exit usable | gap > 5 min |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0dte | C | 0.20 | 1 Friday-only | 750 | 98.00% | 0.00% | 2.00% | 9.0 | 74.56% | 100.00% | 100.00% | 0.00% |
| 0dte | C | 0.20 | 2 Mon/Wed/Fri | 2,450 | 99.88% | 0.00% | 0.12% | 12.0 | 84.76% | 100.00% | 100.00% | 0.20% |
| 0dte | C | 0.20 | 3 daily | 8,440 | 99.94% | 0.00% | 0.06% | 14.0 | 93.42% | 100.00% | 100.00% | 0.91% |
| 0dte | P | 0.20 | 1 Friday-only | 750 | 97.20% | 0.00% | 2.80% | 11.0 | 83.40% | 100.00% | 100.00% | 0.00% |
| 0dte | P | 0.20 | 2 Mon/Wed/Fri | 2,450 | 99.67% | 0.00% | 0.33% | 12.0 | 92.10% | 100.00% | 100.00% | 0.29% |
| 0dte | P | 0.20 | 3 daily | 8,440 | 99.92% | 0.00% | 0.08% | 15.0 | 97.55% | 100.00% | 100.00% | 0.55% |
| 0dte | P | 0.33 | 1 Friday-only | 750 | 96.40% | 0.00% | 3.60% | 12.0 | 79.53% | 100.00% | 100.00% | 0.00% |
| 0dte | P | 0.33 | 2 Mon/Wed/Fri | 2,450 | 99.02% | 0.00% | 0.98% | 14.0 | 91.26% | 100.00% | 100.00% | 0.29% |
| 0dte | P | 0.33 | 3 daily | 8,440 | 99.47% | 0.00% | 0.53% | 16.0 | 97.72% | 100.00% | 100.00% | 0.62% |
| 1dte | C | 0.20 | 1 Friday-only | 1,463 | 97.74% | 0.00% | 2.26% | 9.0 | 88.53% | 100.00% | 100.00% | 0.00% |
| 1dte | C | 0.20 | 2 Mon/Wed/Fri | 4,636 | 100.00% | 0.00% | 0.00% | 11.0 | 99.22% | 100.00% | 100.00% | 1.23% |
| 1dte | C | 0.20 | 3 daily | 15,827 | 99.95% | 0.00% | 0.05% | 12.0 | 99.71% | 99.91% | 99.75% | 1.75% |
| 1dte | P | 0.20 | 1 Friday-only | 1,463 | 97.68% | 0.00% | 2.32% | 9.0 | 95.73% | 100.00% | 100.00% | 0.00% |
| 1dte | P | 0.20 | 2 Mon/Wed/Fri | 4,636 | 100.00% | 0.00% | 0.00% | 10.0 | 99.70% | 99.96% | 99.96% | 1.23% |
| 1dte | P | 0.20 | 3 daily | 15,827 | 99.91% | 0.00% | 0.09% | 13.0 | 99.75% | 99.90% | 99.90% | 0.75% |
| 1dte | P | 0.33 | 1 Friday-only | 1,463 | 96.58% | 0.00% | 3.42% | 12.0 | 97.17% | 100.00% | 100.00% | 0.00% |
| 1dte | P | 0.33 | 2 Mon/Wed/Fri | 4,636 | 100.00% | 0.00% | 0.00% | 13.0 | 98.81% | 100.00% | 100.00% | 1.47% |
| 1dte | P | 0.33 | 3 daily | 15,827 | 99.77% | 0.00% | 0.23% | 15.0 | 99.88% | 100.00% | 100.00% | 0.92% |

§4.9 failures on the picked legs (share of picked entries; one entry can fail several checks):

| tenor | side | X | leg | check | share |
|---|---|---|---|---|---|
| 0dte | C | 0.20 | long | BID_BELOW_MIN | 6.71% |
| 0dte | C | 0.20 | long | SPREAD_TOO_WIDE | 1.74% |
| 0dte | C | 0.20 | short | SPREAD_TOO_WIDE | 2.46% |
| 0dte | P | 0.20 | long | SPREAD_TOO_WIDE | 2.36% |
| 0dte | P | 0.20 | long | BID_BELOW_MIN | 0.78% |
| 0dte | P | 0.20 | short | SPREAD_TOO_WIDE | 2.86% |
| 0dte | P | 0.33 | long | SPREAD_TOO_WIDE | 2.91% |
| 0dte | P | 0.33 | long | BID_BELOW_MIN | 0.14% |
| 0dte | P | 0.33 | short | SPREAD_TOO_WIDE | 3.71% |
| 1dte | C | 0.20 | long | BID_BELOW_MIN | 0.62% |
| 1dte | C | 0.20 | long | SPREAD_TOO_WIDE | 0.38% |
| 1dte | C | 0.20 | short | SPREAD_TOO_WIDE | 0.38% |
| 1dte | P | 0.20 | long | SPREAD_TOO_WIDE | 0.37% |
| 1dte | P | 0.20 | long | BID_BELOW_MIN | 0.05% |
| 1dte | P | 0.20 | short | SPREAD_TOO_WIDE | 0.36% |
| 1dte | P | 0.33 | long | SPREAD_TOO_WIDE | 0.25% |
| 1dte | P | 0.33 | short | SPREAD_TOO_WIDE | 0.44% |

Sessions with at least one OK pick in the window:

| tenor | side | X | era | sessions | with an OK pick |
|---|---|---|---|---|---|
| 0dte | C | 0.20 | 1 Friday-only | 75 | 75 (100.00%) |
| 0dte | C | 0.20 | 2 Mon/Wed/Fri | 245 | 245 (100.00%) |
| 0dte | C | 0.20 | 3 daily | 844 | 844 (100.00%) |
| 0dte | P | 0.20 | 1 Friday-only | 75 | 75 (100.00%) |
| 0dte | P | 0.20 | 2 Mon/Wed/Fri | 245 | 245 (100.00%) |
| 0dte | P | 0.20 | 3 daily | 844 | 844 (100.00%) |
| 0dte | P | 0.33 | 1 Friday-only | 75 | 74 (98.67%) |
| 0dte | P | 0.33 | 2 Mon/Wed/Fri | 245 | 245 (100.00%) |
| 0dte | P | 0.33 | 3 daily | 844 | 844 (100.00%) |
| 1dte | C | 0.20 | 1 Friday-only | 77 | 76 (98.70%) |
| 1dte | C | 0.20 | 2 Mon/Wed/Fri | 244 | 244 (100.00%) |
| 1dte | C | 0.20 | 3 daily | 833 | 833 (100.00%) |
| 1dte | P | 0.20 | 1 Friday-only | 77 | 76 (98.70%) |
| 1dte | P | 0.20 | 2 Mon/Wed/Fri | 244 | 244 (100.00%) |
| 1dte | P | 0.20 | 3 daily | 833 | 833 (100.00%) |
| 1dte | P | 0.33 | 1 Friday-only | 77 | 75 (97.40%) |
| 1dte | P | 0.33 | 2 Mon/Wed/Fri | 244 | 244 (100.00%) |
| 1dte | P | 0.33 | 3 daily | 833 | 833 (100.00%) |

Entries not evaluated (counted, never filled):

| tenor | status | sessions |
|---|---|---|
| 1dte | EXIT_SESSION_EXCLUDED | 1 |
| 1dte | LABEL_CROSSES_BLOCK | 1 |
| 1dte | NO_WINDOW | 10 |

Picked entries whose legs are not stored on the expiry day (all rules pooled; *off-dollar* = a leg on an OCC-adjusted strike, which the Step-0 download did not request):

| tenor | month | off-dollar leg | entries | sessions |
|---|---|---|---|---|
| 1dte | 2022-05 | False | 2 | 1 |
| 1dte | 2022-11 | False | 2 | 1 |
| 1dte | 2022-12 | False | 4 | 1 |
| 1dte | 2023-02 | False | 14 | 1 |
| 1dte | 2025-04 | False | 10 | 1 |

Picked entries with a $1 grid hole within 3 strikes of the pair (the rule skips a pair whose long strike is not listed):

| tenor | era | picked entries | hole near the pair |
|---|---|---|---|
| 0dte | 1 Friday-only | 2,187 | 27 (1.23%) |
| 0dte | 2 Mon/Wed/Fri | 7,315 | 1023 (13.98%) |
| 0dte | 3 daily | 25,263 | 135 (0.53%) |
| 1dte | 1 Friday-only | 4,272 | 114 (2.67%) |
| 1dte | 2 Mon/Wed/Fri | 13,908 | 1799 (12.94%) |
| 1dte | 3 daily | 47,421 | 393 (0.83%) |

## 4. Cleaning: rejection rates (M4 rules, DQ rules v2)

Raw = cleaned + rejected held for every file, holdout included (asserted in `scripts/m19t_build_data.py`). Every rejected record is stored with its reasons in `data/clean/m19t/rejected/`.

| source | year | sessions | raw records | rejected | rate |
|---|---|---|---|---|---|
| ext | 2020 | 112 | 2,927,250 | 50 | 0.00% |
| ext | 2021 | 207 | 7,718,040 | 1,468 | 0.02% |
| ext | 2022 | 251 | 11,185,290 | 1,026 | 0.01% |
| ext | 2023 | 58 | 3,546,180 | 1 | 0.00% |
| 0dte | 2023 | 192 | 6,684,700 | 870 | 0.01% |
| 0dte | 2024 | 252 | 11,141,788 | 1,089 | 0.01% |
| 0dte | 2025 | 250 | 12,349,062 | 1,650 | 0.01% |
| 0dte | 2026 | 63 | 3,532,741 | 1,958 | 0.06% |

| source | rejection reason | records | share of raw |
|---|---|---|---|
| 0dte | BID_GT_ASK | 5,567 | 0.02% |
| ext | BID_GT_ASK | 2,545 | 0.01% |
| ext | NONPOSITIVE_PRICE | 18 | 0.00% |

| source | flag (kept) | records | share of raw |
|---|---|---|---|
| 0dte | MULTIPLIER_UNKNOWN | 33,702,724 | 99.98% |
| 0dte | ZERO_BID | 5,828,648 | 17.29% |
| 0dte | NO_EVENT_TS | 5,143,716 | 15.26% |
| 0dte | NO_BID | 3,288,702 | 9.76% |
| 0dte | OUTSIDE_RTH | 1,259,690 | 3.74% |
| 0dte | ADJUSTED_STRIKE | 524,873 | 1.56% |
| 0dte | ZERO_QUOTE | 36,713 | 0.11% |
| 0dte | EMPTY_BOOK | 34,841 | 0.10% |
| 0dte | NO_ASK | 105 | 0.00% |
| ext | MULTIPLIER_UNKNOWN | 25,374,215 | 99.99% |
| ext | ZERO_BID | 4,063,162 | 16.01% |
| ext | NO_EVENT_TS | 2,447,616 | 9.65% |
| ext | OUTSIDE_RTH | 965,827 | 3.81% |
| ext | ZERO_QUOTE | 813 | 0.00% |

## 5. Strike grid

Only whole-dollar strikes were requested (the M4 band rule), so half-dollar or OCC-adjusted strikes are visible only where they were listed under a requested symbol. *Holes*: whole-dollar strikes missing between the lowest and highest listed strike of an expiry. *Listed / requested*: share of the requested band that resolved to a listed contract (extension only; the band comes from the Nasdaq-venue daily range).

| era | tenor | expiryxside rows | listed strikes (median) | rows with holes | holes (mean) | listed / requested |
|---|---|---|---|---|---|---|
| 1 Friday-only | 0dte | 150 | 35 | 8 | 0.32 | 98.64% |
| 1 Friday-only | 1dte | 154 | 35 | 10 | 0.61 | 96.06% |
| 2 Mon/Wed/Fri | 0dte | 490 | 40 | 186 | 2.63 | 93.49% |
| 2 Mon/Wed/Fri | 1dte | 490 | 40 | 186 | 2.52 | 93.68% |
| 3 daily | 0dte | 1,690 | 53 | 388 | 1.69 | 99.79% |
| 3 daily | 1dte | 176 | 37 | 0 | 0.00 | 100.00% |

Months with holes (expiryxside rows): 2020-01 (4), 2020-03 (4), 2021-04 (6), 2021-05 (34), 2021-06 (14), 2021-07 (54), 2021-08 (48), 2021-09 (56), 2021-10 (34), 2021-11 (36), 2021-12 (32), 2022-01 (30), 2022-02 (4), 2022-03 (14), 2022-04 (8), 2022-05 (4), 2022-06 (2), 2022-11 (8), 2023-06 (6), 2024-01 (12), 2024-02 (4), 2024-04 (2), 2024-05 (2), 2024-06 (16), 2024-07 (14), 2024-08 (12), 2024-09 (10), 2024-10 (30), 2024-11 (14), 2024-12 (16), 2025-01 (14), 2025-02 (2), 2025-04 (2), 2025-05 (10), 2025-06 (20), 2025-07 (24), 2025-08 (32), 2025-09 (34), 2025-10 (26), 2025-11 (14), 2025-12 (26), 2026-01 (34), 2026-02 (6), 2026-03 (4).

## 6. Databento-degraded days

Each day vs 5 sessions either side in the same store. *90% minutes*: RTH minutes in which ≥ 90% of the day's quoted contracts have a non-rejected record. Gaps are RTH stretches with no record for any contract.

| session | role | contracts defined | quoted | minutes with records | 90% minutes | raw | rejected | median spread (bid >= min bid) | gaps (ET) |
|---|---|---|---|---|---|---|---|---|---|
| 2021-06-29 | neighbour | 80 | 80 | 390/390 | 390 | 32,400 | 0 | 0.260 | none |
| 2021-06-30 | neighbour | 78 | 78 | 390/390 | 390 | 31,590 | 0 | 0.310 | none |
| 2021-07-01 | neighbour | 74 | 74 | 390/390 | 390 | 29,970 | 0 | 0.160 | none |
| 2021-07-02 | neighbour | 150 | 150 | 390/390 | 390 | 60,750 | 0 | 0.220 | none |
| 2021-07-06 | neighbour | 152 | 152 | 390/390 | 390 | 61,560 | 0 | 0.140 | none |
| 2021-07-07 | **degraded** | 74 | 74 | 390/390 | 390 | 29,970 | 0 | 0.370 | none |
| 2021-07-08 | neighbour | 74 | 74 | 390/390 | 390 | 29,970 | 0 | 0.200 | none |
| 2021-07-09 | neighbour | 146 | 146 | 390/390 | 390 | 59,130 | 0 | 0.170 | none |
| 2021-07-12 | neighbour | 72 | 72 | 390/390 | 390 | 29,160 | 0 | 0.310 | none |
| 2021-07-13 | neighbour | 66 | 66 | 390/390 | 390 | 26,730 | 0 | 0.140 | none |
| 2021-07-14 | neighbour | 62 | 62 | 390/390 | 390 | 25,110 | 0 | 0.200 | none |
| 2021-07-07 picks | | 0dte C 0.20 OK 10, 0dte P 0.20 OK 10, 0dte P 0.33 OK 10 | | | | | | | |
| | | | | | | | | | |
| 2021-10-19 | neighbour | 74 | 74 | 390/390 | 390 | 29,970 | 0 | 0.170 | none |
| 2021-10-20 | neighbour | 76 | 76 | 390/390 | 390 | 30,780 | 0 | 0.180 | none |
| 2021-10-21 | neighbour | 88 | 88 | 390/390 | 390 | 35,640 | 0 | 0.140 | none |
| 2021-10-22 | neighbour | 176 | 176 | 390/390 | 390 | 71,280 | 0 | 0.180 | none |
| 2021-10-25 | neighbour | 90 | 90 | 390/390 | 390 | 36,450 | 0 | 0.160 | none |
| 2021-10-26 | **degraded** | 86 | 86 | 390/390 | 390 | 34,830 | 0 | 0.170 | none |
| 2021-10-27 | neighbour | 88 | 88 | 390/390 | 390 | 35,640 | 0 | 0.200 | none |
| 2021-10-28 | neighbour | 88 | 88 | 390/390 | 390 | 35,640 | 0 | 0.150 | none |
| 2021-10-29 | neighbour | 172 | 172 | 390/390 | 390 | 69,660 | 0 | 0.180 | none |
| 2021-11-01 | neighbour | 74 | 74 | 390/390 | 390 | 29,970 | 0 | 0.170 | none |
| 2021-11-02 | neighbour | 60 | 60 | 390/390 | 390 | 24,300 | 0 | 0.120 | none |
| 2021-10-26 picks | | 1dte C 0.20 OK 19, 1dte P 0.20 OK 19, 1dte P 0.33 OK 19 | | | | | | | |
| | | | | | | | | | |
| 2022-09-12 | neighbour | 74 | 74 | 390/390 | 390 | 29,970 | 0 | 0.150 | none |
| 2022-09-13 | neighbour | 106 | 106 | 390/390 | 390 | 42,930 | 0 | 0.090 | none |
| 2022-09-14 | neighbour | 72 | 72 | 390/390 | 390 | 29,160 | 0 | 0.120 | none |
| 2022-09-15 | neighbour | 80 | 80 | 390/390 | 390 | 32,400 | 0 | 0.070 | none |
| 2022-09-16 | neighbour | 144 | 144 | 390/390 | 390 | 58,320 | 0 | 0.100 | none |
| 2022-09-19 | **degraded** | 74 | 74 | 390/390 | 390 | 29,970 | 0 | 0.150 | none |
| 2022-09-20 | neighbour | 70 | 70 | 390/390 | 390 | 28,350 | 0 | 0.030 | none |
| 2022-09-21 | neighbour | 86 | 86 | 390/390 | 390 | 34,830 | 0 | 0.080 | none |
| 2022-09-22 | neighbour | 76 | 76 | 390/390 | 390 | 30,780 | 0 | 0.060 | none |
| 2022-09-23 | neighbour | 148 | 148 | 390/390 | 390 | 59,940 | 0 | 0.080 | none |
| 2022-09-26 | neighbour | 72 | 72 | 390/390 | 390 | 29,160 | 0 | 0.100 | none |
| 2022-09-19 picks | | 0dte C 0.20 OK 10, 0dte P 0.20 OK 10, 0dte P 0.33 OK 10 | | | | | | | |
| | | | | | | | | | |

