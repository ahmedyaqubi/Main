# Data-Quality Checks (M4)

**Status: v1.1 (M4, owner decisions 2026-10-06; ADR-0005).** Implements MASTER_PROMPT Phase 1D for the
M4 scope: QQQ underlying (`EQUS.MINI` `ohlcv-1m`, `bbo-1m`) and QQQ options (`OPRA.PILLAR`
`cbbo-1m`, `definition`). Cross-market instruments get the same checks in M5, after ADR-0004.
Thresholds live in `configs/phase1.yaml` under `dq:`. Gate numbers stay in spec §11.

## Principles (CLAUDE.md rule 8)
- **Nothing is filled, adjusted, or dropped silently.** Every raw row ends up either in the
  cleaned dataset (`dq_status` `OK` or `FLAGGED`, with `dq_flags`) or in the rejected dataset
  with its `dq_reasons`. Conservation: `raw = cleaned + rejected`, checked for every dataset.
- **REJECTED** = structurally invalid (cannot be a real market state).
  **FLAGGED** = a real but notable state, kept so the point-in-time reader sees the market as it
  was. One-sided books are flagged, not rejected: rejecting them would let an older two-sided
  quote stand in for "no bid" (owner decision 2, M4).
- Per-row reasons live in Parquet. `data_quality_events` (Postgres) gets one **aggregated** row
  per (check, instrument/contract, session) with a count and up to 5 sample timestamps.
- **CRITICAL** events are session-level and block gate 2. They can only be closed by an ADR
  (`resolved_by_adr`). **WARN** = record-level issues. **INFO** = flags worth counting.

## Cleaned-layer conventions (from M2 findings)
| Schema | `ts` | `available_at` |
|---|---|---|
| `ohlcv-1m` | bar label (`ts_event`, bar **start**) | `ts_event + 60 s + pit.bar_publication_lag_s` |
| `bbo-1m`, `cbbo-1m` | `ts_recv` (interval **end**) | `ts_recv` |
| `definition` | `ts_recv` | `ts_recv` |

Fixed-point prices become floats (×1e-9). The vendor's undefined sentinel becomes null **plus a
flag**. `session_date` is the ET date of `ts`.

## Record-level checks
| Check | Applies to | Action | Severity | Rule |
|---|---|---|---|---|
| `TS_AFTER_INGEST` | all | REJECT | WARN | record timestamp later than its `ingested_at` (future information) |
| `TS_EVENT_AFTER_RECV` | quotes | REJECT | WARN | `ts_event > ts_recv` beyond `dq.max_event_recv_skew_s` |
| `DUP_EXACT` | all | REJECT (extra copies) | WARN | identical row repeated; the first copy is kept, the copies are rejected and counted |
| `DUP_CONFLICT` | all | REJECT (all copies) | WARN | same key (`instrument_id`, `ts`), different values: no basis to choose one |
| `PRICE_NONPOSITIVE` | bars | REJECT | WARN | any of O/H/L/C undefined or ≤ 0 |
| `OHLC_INCONSISTENT` | bars | REJECT | WARN | `low > high`, or `high < max(open, close)`, or `low > min(open, close)` |
| `BID_GT_ASK` | quotes | REJECT | WARN | both sides defined and `bid > ask` |
| `NONPOSITIVE_PRICE` | quotes | REJECT | WARN | defined `bid < 0`, or defined `ask ≤ 0` unless the quote is 0/0 |
| `CONTRACT_UNKNOWN` | options | REJECT | WARN | no same-session definition for the `instrument_id`, and the contract never appears in definitions |
| `NOT_YET_LISTED` | options | REJECT | WARN | no same-session definition, and the contract's first appearance in definitions is later than the quote's session |
| `SYMBOL_MISMATCH` | options | REJECT | WARN | the session's definition for the `instrument_id` names a different contract than the quote's symbol mapping |
| `INVALID_MULTIPLIER` | options | REJECT | WARN | a **defined** multiplier ≠ 100 (ADR-0005) |
| `NONSTANDARD_ROOT` | options | REJECT | WARN | OCC root ≠ `dq.option_root` (adjusted-deliverable series get new roots) |
| `NONSTANDARD_STRIKE` | options | REJECT | WARN | strike neither on the `dq.strike_increment` grid nor explained by a documented OCC adjustment in `dq.strike_adjustments` on/after its ex-date |
| `EXPIRATION_MISMATCH` | options | REJECT | WARN | definition expiration ≠ date encoded in the OCC symbol |
| `EXPIRATION_NOT_SESSION` | options | REJECT | WARN | expiration is not an XNYS session |
| `NO_BID` / `NO_ASK` / `EMPTY_BOOK` | quotes | FLAG | INFO | side(s) undefined: one-sided or empty book |
| `ZERO_BID` | quotes | FLAG | INFO | defined bid = 0 with a non-zero ask |
| `ZERO_QUOTE` | quotes | FLAG | INFO | bid = 0 and ask = 0: the venue's "no market" (found in real data, M4: 73,360 rows) |
| `MULTIPLIER_UNKNOWN` | options | FLAG | INFO | vendor leaves the multiplier undefined (all Databento OPRA definitions, ADR-0005) |
| `ADJUSTED_STRIKE` | options | FLAG | INFO | strike matches a documented OCC strike adjustment (e.g. memo #53847, 2023-12-27) |
| `NO_EVENT_TS` | quotes | FLAG | INFO | `ts_event` is the vendor's undefined timestamp: no update during the interval (book carried forward). Found in real QQQ `bbo-1m` data, M4 |
| `OUTSIDE_RTH` | all | FLAG | INFO | outside the session's regular hours (early closes respected) |
| `NON_SESSION` | all | FLAG | INFO | ET date is not an XNYS session |

## Session-level checks
| Check | Severity | Rule |
|---|---|---|
| `MISSING_BAR` | WARN | expected RTH bar labels absent (lists them) |
| `BAR_COVERAGE_LOW` | CRITICAL | received/expected RTH bars < `dq.min_bar_coverage` (gate 1) |
| `NO_1DTE_EXPIRY` | CRITICAL | next-session expiration absent from the session's definitions |
| `CHAIN_COVERAGE_LOW` | CRITICAL | share of prediction timestamps with a valid frozen-rule call **and** put quote < `dq.min_chain_timestamp_share` (gate 1) |
| `INVALID_QUOTE_RATE_HIGH` | WARN | rejected share in D+1 ATM ± 5 during RTH > `dq.max_invalid_quote_rate` (gate 2) |

A **valid frozen-rule quote at T**: spec §5 contract (spot = underlying NBBO mid in force at T;
call = lowest strike ≥ spot, put = highest strike ≤ spot, D+1 expiry), latest cleaned quote with
`available_at ≤ T`, age ≤ `liquidity.max_quote_age_s`, both sides defined, `0 < bid ≤ ask`.
This is a data-coverage test: the §4.9 spread and min-bid gates are trading rules, studied
separately in `reports/dq/liquidity_spreads.md`.

## Not covered in M4 (documented, not silently skipped)
- Suspicious OI changes: OI (`statistics`) is deferred to M5 (owner decision, M4).
- "Required features available": M5.
- Corporate actions beyond multiplier/strike checks: QQQ had no split in the window. Equity
  corporate actions for cross-market names are handled in M5.
