# M4 data-quality report: full history

## Datasets

| dataset | raw | cleaned | rejected | flagged | sessions | timestamp errors | conservation |
|---|---|---|---|---|---|---|---|
| QQQ ohlcv-1m | 460268 | 460268 | 0 | 117390 | 883 | 0 | conservation OK |
| QQQ bbo-1m | 621899 | 621899 | 0 | 278969 | 884 | 0 | conservation OK |
| QQQ options cbbo-1m | 83470947 | 83460156 | 10791 | 83460156 | 883 | 0 | conservation OK |

### Rejections and flags by check

| dataset | check | kind | rows |
|---|---|---|---|
| QQQ ohlcv-1m | OUTSIDE_RTH | flagged | 117390 |
| QQQ bbo-1m | EMPTY_BOOK | flagged | 3070 |
| QQQ bbo-1m | NON_SESSION | flagged | 1 |
| QQQ bbo-1m | NO_ASK | flagged | 3697 |
| QQQ bbo-1m | NO_BID | flagged | 1478 |
| QQQ bbo-1m | NO_EVENT_TS | flagged | 5760 |
| QQQ bbo-1m | OUTSIDE_RTH | flagged | 278968 |
| QQQ options cbbo-1m | BID_GT_ASK | rejected | 10791 |
| QQQ options cbbo-1m | ADJUSTED_STRIKE | flagged | 1014221 |
| QQQ options cbbo-1m | EMPTY_BOOK | flagged | 75141 |
| QQQ options cbbo-1m | MULTIPLIER_UNKNOWN | flagged | 83460156 |
| QQQ options cbbo-1m | NO_ASK | flagged | 165 |
| QQQ options cbbo-1m | NO_BID | flagged | 1492260 |
| QQQ options cbbo-1m | NO_EVENT_TS | flagged | 14658577 |
| QQQ options cbbo-1m | OUTSIDE_RTH | flagged | 3170307 |
| QQQ options cbbo-1m | ZERO_BID | flagged | 1345807 |
| QQQ options cbbo-1m | ZERO_QUOTE | flagged | 73360 |

## Underlying bars (QQQ, RTH)

Sessions 883; bars expected 342,930, received 342,878; missing 52 (0.0152%). Sessions below threshold: 0.

## Options chain coverage (frozen-rule call and put at prediction timestamps)

Sessions 883; timestamps 56,224; valid 56,130; no spot 0; call invalid 36; put invalid 76.

## Gates

| gate | name | result | numbers | rule |
|---|---|---|---|---|
| 1 | Data coverage | PASS | sessions=882; sessions_below_bar_coverage=0; min_bar_coverage_seen=0.9923; sessions_with_valid_chain=879; valid_chain_session_share=0.9966 | all sessions >= 98% RTH bars; >= 95% of sessions with a valid chain at >= 95% of prediction timestamps |
| 2 | Data quality | PASS | open_critical_events=0; invalid_quote_rate=0.0002544 | 0 open CRITICAL events; invalid-quote rate <= 2% (D+1, ATM +- 5, RTH) |

Generated 2026-10-06 20:02 UTC, code 08fc18944166, config 6fa66b5edf89. Window 2023-03-28 → 2026-10-02 (883 sessions).

## Coverage by month

| month | sessions | min bar coverage | mean chain share | min chain share | ATM records | ATM rejected |
|---|---|---|---|---|---|---|
| 2023-03 | 4 | 1.0000 | 1.0000 | 1.0000 | 34,320 | 0 |
| 2023-04 | 19 | 1.0000 | 1.0000 | 1.0000 | 163,020 | 0 |
| 2023-05 | 22 | 1.0000 | 1.0000 | 1.0000 | 188,760 | 0 |
| 2023-06 | 21 | 1.0000 | 0.9985 | 0.9688 | 180,180 | 133 |
| 2023-07 | 20 | 1.0000 | 1.0000 | 1.0000 | 167,640 | 104 |
| 2023-08 | 23 | 1.0000 | 1.0000 | 1.0000 | 197,340 | 0 |
| 2023-09 | 20 | 1.0000 | 1.0000 | 1.0000 | 171,600 | 0 |
| 2023-10 | 22 | 1.0000 | 0.9964 | 0.9531 | 188,760 | 192 |
| 2023-11 | 21 | 1.0000 | 1.0000 | 1.0000 | 176,220 | 0 |
| 2023-12 | 20 | 1.0000 | 0.9500 | 0.0000 | 171,600 | 2 |
| 2024-01 | 21 | 1.0000 | 1.0000 | 1.0000 | 180,180 | 0 |
| 2024-02 | 20 | 1.0000 | 0.9938 | 0.8750 | 171,600 | 327 |
| 2024-03 | 20 | 1.0000 | 1.0000 | 1.0000 | 171,600 | 0 |
| 2024-04 | 22 | 1.0000 | 1.0000 | 1.0000 | 188,760 | 0 |
| 2024-05 | 22 | 0.9949 | 1.0000 | 1.0000 | 188,760 | 0 |
| 2024-06 | 19 | 0.9974 | 1.0000 | 1.0000 | 163,020 | 0 |
| 2024-07 | 22 | 0.9974 | 1.0000 | 1.0000 | 184,800 | 0 |
| 2024-08 | 22 | 0.9974 | 1.0000 | 1.0000 | 188,760 | 0 |
| 2024-09 | 20 | 0.9974 | 1.0000 | 1.0000 | 171,600 | 0 |
| 2024-10 | 23 | 0.9949 | 1.0000 | 1.0000 | 197,340 | 0 |
| 2024-11 | 20 | 0.9949 | 1.0000 | 1.0000 | 167,640 | 0 |
| 2024-12 | 21 | 0.9949 | 1.0000 | 1.0000 | 176,220 | 0 |
| 2025-01 | 20 | 1.0000 | 1.0000 | 1.0000 | 171,600 | 0 |
| 2025-02 | 19 | 0.9974 | 1.0000 | 1.0000 | 163,020 | 0 |
| 2025-03 | 21 | 1.0000 | 1.0000 | 1.0000 | 180,180 | 0 |
| 2025-04 | 21 | 1.0000 | 0.9985 | 0.9688 | 180,180 | 193 |
| 2025-05 | 21 | 0.9974 | 1.0000 | 1.0000 | 180,180 | 0 |
| 2025-06 | 20 | 1.0000 | 1.0000 | 1.0000 | 171,600 | 0 |
| 2025-07 | 22 | 0.9974 | 0.9986 | 0.9688 | 184,734 | 246 |
| 2025-08 | 21 | 0.9974 | 1.0000 | 1.0000 | 180,180 | 0 |
| 2025-09 | 21 | 1.0000 | 1.0000 | 1.0000 | 180,180 | 2 |
| 2025-10 | 23 | 1.0000 | 0.9973 | 0.9375 | 197,172 | 76 |
| 2025-11 | 19 | 1.0000 | 1.0000 | 1.0000 | 159,053 | 17 |
| 2025-12 | 22 | 1.0000 | 1.0000 | 1.0000 | 184,799 | 0 |
| 2026-01 | 20 | 0.9974 | 1.0000 | 1.0000 | 171,582 | 0 |
| 2026-02 | 19 | 1.0000 | 1.0000 | 1.0000 | 162,952 | 0 |
| 2026-03 | 22 | 1.0000 | 0.9957 | 0.9062 | 188,756 | 587 |
| 2026-04 | 21 | 1.0000 | 1.0000 | 1.0000 | 180,179 | 3 |
| 2026-05 | 20 | 0.9974 | 0.9992 | 0.9844 | 171,600 | 23 |
| 2026-06 | 21 | 1.0000 | 1.0000 | 1.0000 | 180,174 | 1 |
| 2026-07 | 22 | 0.9974 | 1.0000 | 1.0000 | 188,633 | 1 |
| 2026-08 | 21 | 0.9949 | 1.0000 | 1.0000 | 180,180 | 0 |
| 2026-09 | 21 | 0.9923 | 1.0000 | 1.0000 | 180,180 | 12 |
| 2026-10 | 2 | 0.9974 | 1.0000 | 1.0000 | 17,160 | 0 |

## CRITICAL events (4; open: 0)

| check | session | reason | closed by |
|---|---|---|---|
| CHAIN_COVERAGE_LOW | 2023-12-27 | 0/64 prediction timestamps with a valid call and put (0.00%) | ADR-0006 |
| CHAIN_COVERAGE_LOW | 2024-02-06 | 56/64 prediction timestamps with a valid call and put (87.50%) | ADR-0006 |
| CHAIN_COVERAGE_LOW | 2025-10-22 | 60/64 prediction timestamps with a valid call and put (93.75%) | ADR-0006 |
| CHAIN_COVERAGE_LOW | 2026-03-10 | 58/64 prediction timestamps with a valid call and put (90.62%) | ADR-0006 |

## Excluded sessions (history.excluded_sessions)

- 2023-12-27: ADR-0006: OCC #53847 ex-date: vendor lists superseded pre-adjustment series quoted 0/0 all day

## Catalogue

Registered raw + cleaned datasets in `dataset_versions`; wrote 9490 aggregated `data_quality_events` (0 = already written for this dataset).
