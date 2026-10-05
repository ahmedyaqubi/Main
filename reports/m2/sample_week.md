# M2 sample-week report (Databento)

Generated 2026-10-05 16:42 EDT by `scripts/m2_sample_check.py`. Week 2025-03-10 → 2025-03-14.

## C1 timestamps/timezone · C2 QQQ 1-min bars

| session | tz | first RTH bar label (UTC) | RTH bars (start-labelled 09:30-15:59) | align err start | align err end | n |
|---|---|---|---|---|---|---|
| 2025-03-10 | UTC | 13:30 | 390 | 0.0371 | 0.2885 | 390 |
| 2025-03-11 | UTC | 13:30 | 390 | 0.0412 | 0.3987 | 390 |
| 2025-03-12 | UTC | 13:30 | 390 | 0.0372 | 0.2847 | 390 |
| 2025-03-13 | UTC | 13:30 | 390 | 0.0419 | 0.2738 | 390 |
| 2025-03-14 | UTC | 13:30 | 390 | 0.0323 | 0.2065 | 390 |

Reading: the hypothesis with the far smaller mean |close - quote mid| is the vendor's bar-label convention. `cbbo-1m`/`bbo-1m` `ts_recv` minute stamps are used as the quote time.

`cbbo-1m` records stamped exactly on a minute boundary (whole week): 100.00% of 844,452.

## C4 1DTE expiration present every session

Sessions checked: 5. Missing next-session expiry: none.

## C5 listing lead time (first appearance in daily definitions)

| expiration | weekday | first seen | lead (sessions) |
|---|---|---|---|
| 2025-03-11 | Tue | 2025-02-25 | 10 |
| 2025-03-12 | Wed | 2025-02-26 | 10 |
| 2025-03-13 | Thu | 2025-02-27 | 10 |
| 2025-03-14 | Fri | 2025-02-24 | ≥ 14 |
| 2025-03-17 | Mon | 2025-03-03 | 10 |
| 2025-03-18 | Tue | 2025-03-04 | 10 |

Lookback starts 2025-02-24; '≥' = already listed on the first lookback day (lead is censored). Databento OPRA definitions leave `activation` empty, so first appearance is the only listing evidence here.

## C6 quote validity, D+1 ATM ± 5 strikes, RTH (`cbbo-1m`)

| session | spot (09:30 open) | quotes | missing side | non-positive | crossed | valid | spread p50 | p90 | p99 | pass §4.9 gates |
|---|---|---|---|---|---|---|---|---|---|---|
| 2025-03-10 | 483.43 | 8580 | 0 | 0 | 0 | 8580 | 0.030 | 0.150 | 0.990 | 98.4% |
| 2025-03-11 | 472.31 | 8580 | 0 | 0 | 0 | 8580 | 0.030 | 0.070 | 0.180 | 99.8% |
| 2025-03-12 | 479.25 | 8580 | 0 | 0 | 0 | 8580 | 0.020 | 0.070 | 0.150 | 99.8% |
| 2025-03-13 | 476.27 | 8580 | 0 | 0 | 0 | 8580 | 0.030 | 0.150 | 0.530 | 99.2% |
| 2025-03-14 | 473.75 | 8580 | 0 | 0 | 0 | 8580 | 0.020 | 0.090 | 0.310 | 99.6% |

Spec §4.9: spread ≤ max($0.05, 5% of mid) and bid ≥ $0.20.

## C7 open interest timing (`statistics`, stat_type 9)

| session | OI records | first arrival (ET) | last arrival (ET) | arrivals after 09:30 ET | instruments with >1 distinct OI value |
|---|---|---|---|---|---|
| 2025-03-10 | 7632 | 06:30:00 | 06:30:02 | 0 | 0 |
| 2025-03-11 | 7632 | 06:30:00 | 06:30:02 | 0 | 0 |
| 2025-03-12 | 7632 | 06:30:00 | 06:30:02 | 0 | 0 |
| 2025-03-13 | 7632 | 06:30:00 | 06:30:02 | 0 | 0 |
| 2025-03-14 | 7344 | 06:30:00 | 06:30:02 | 0 | 0 |

## C3 `cbbo-1m` timestamp semantics vs `cmbp-1` ticks

Contracts per day: D+1 expiry, ATM ± 5 strikes around the 09:30 open, calls and puts. Buckets = RTH `cbbo-1m` records for those contracts.

| session | D+1 | spot | contracts | tick records scanned | kept | buckets | at_or_before | within_next_bucket | ambiguous | neither | empty side |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2025-03-10 | 2025-03-11 | 483.43 | 22 | 245,574,220 | 34,926,923 | 8,580 | 8,431 | 0 | 149 | 0 | 0 |
| 2025-03-11 | 2025-03-12 | 472.31 | 22 | 48,610,273 | 48,610,273 | 8,580 | 8,544 | 0 | 36 | 0 | 0 |
| 2025-03-12 | 2025-03-13 | 479.25 | 22 | 47,225,256 | 47,225,256 | 8,580 | 8,445 | 0 | 135 | 0 | 0 |
| 2025-03-13 | 2025-03-14 | 476.27 | 22 | 43,106,319 | 43,106,319 | 8,580 | 8,435 | 0 | 145 | 0 | 0 |
| 2025-03-14 | 2025-03-17 | 473.75 | 22 | 39,298,412 | 39,298,412 | 8,580 | 8,412 | 0 | 168 | 0 | 0 |

| all tick days | buckets | share |
|---|---|---|
| at_or_before | 42,267 | 98.52% |
| within_next_bucket | 0 | 0.00% |
| ambiguous | 633 | 1.48% |
| neither | 0 | 0.00% |

`at_or_before` = equals the last tick with ts_recv ≤ the record's ts_recv (point-in-time safe). `within_next_bucket` = equals the last tick before ts_recv + 1 min (would mean the record leaks up to one minute of future quotes). `ambiguous` = quote unchanged, both agree.

## C8 NBBO consistency (internal: `cbbo-1m` vs minute-end state from `cmbp-1`)

Identical bid/ask at the record time: 100.00% of 42,900 contract-minutes over 5 sessions. An independent second-vendor comparison is deferred to M20 (ADR-0002).
