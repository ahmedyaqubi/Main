# Data Requirements — Milestone 2

**Status: v1.0 (M2, 2026-10-05). Primary provider: Databento (ADR-0002).** Provider facts were checked on vendor pages on 2026-10-05
(sources in §6). Anything marked **VERIFY** must be confirmed against real data in the
one-week sample pull (§5) before M3.

Required window (spec §1.3, ADR-0003): **2023-03-28 → present**. Every source must cover it.

## 1. Requirements matrix

PIT = point-in-time. `available_at` rules are from spec §7.

### 1.1 QQQ options (the critical dataset)
| Field | Granularity needed | Why | PIT notes |
|---|---|---|---|
| timestamp | ms or better | quote age, latency | vendor timestamp semantics must be documented: bucketed "1m" quotes must be the last quote **at or before** the bucket time, not within the following minute. **Verified (C3):** `cbbo-1m` `ts_recv` = interval end; 42,900/42,900 RTH contract-minutes over 5 sessions (2025-03-10→14, D+1 ATM ± 5) equal the last tick at or before `ts_recv`; 0 leaked the following minute |
| expiration, strike, right, root, multiplier | per contract | 1DTE resolution, invalid-contract checks | listing date per contract is needed to prove the contract existed at T. **Finding:** Databento `definition.activation` is empty for OPRA; use first appearance in the daily definition files (C5) |
| bid, ask, bid_size, ask_size | **NBBO**, ≤ 1-min snapshots (tick preferred) | fills, liquidity gates, labels | NBBO required. Per-exchange BBO is acceptable only if we can build the NBBO ourselves. Trades/last are **not** acceptable for fills |
| quote condition | per quote | DQ (e.g. non-firm quotes) | — |
| last, volume | per minute | feature only | cumulative-day vs interval volume must be known |
| open interest | daily | feature only (not a gate, OD-7) | OPRA publishes ~06:30 ET for the prior day's close (§6). Spec uses 09:30 availability, which is conservative and needs no change |
| IV / Greeks | — | **computed in-house** from NBBO mid (OD-7); vendor values stored but unused | — |
| underlying price | at each quote time | IV calc, selection reference | take from the QQQ NBBO / bars dataset, not the vendor's options feed |

Volume estimate: 1DTE QQQ chain within ±5% of spot ≈ 60 strikes × 2 rights × 390 minutes ≈ 47k
rows/session at 1-min; ~46M rows for ~980 sessions. Tick NBBO is orders of magnitude more,
so it is pulled only for the ATM ± 5 strikes used by selection and fills.

### 1.2 Underlying and cross-market instruments
| Instrument | Need | Granularity | Proposed source | History OK for 2022-11? | PIT / caveats |
|---|---|---|---|---|---|
| QQQ | OHLCV (+ NBBO mid preferred) | 1-min (RTH + pre/post for overnight features) | Databento `EQUS.MINI` (consolidated, from 2023-03-28) | yes | bar timestamp convention **verified (C2): labelled at bar start** (mean \|close − quote mid at label+1m\| ≈ $0.04 vs ≈ $0.29 at label), so `available_at = ts_event + 1 min`; 390 RTH bars/session; consolidated required |
| SPY | OHLCV | 1-min | Databento `EQUS.MINI` | yes | NYSE Arca listing → CTA tape |
| SOXX, NVDA, AMD, AVGO | OHLCV | 1-min | Databento `EQUS.MINI` | yes | corporate actions: NVDA 10:1 split 2024-06-10, AVGO 10:1 split 2024-07-15. Use **unadjusted** prices plus our own documented adjustment for returns |
| TSM | OHLCV | 1-min | Databento `EQUS.MINI` | yes | ADR, NYSE |
| NQ, ES | OHLCV | 1-min, ~23h | Databento `GLBX.MDP3` (history from 2010-06-06) | yes | the roll rule must be fixed and PIT: proposed **volume-based roll known at the prior session close**, never Databento's continuous series if its roll date uses same-day volume (**VERIFY** the `c.0` rule) |
| VIX | prior-session close (regime); intraday level (feature) | daily; 1-min | daily close: Cboe's free VIX history file; intraday: **front-month VX futures**, Databento `XCBF.PITCH` (from 2018-11-04) | yes | the VIX index itself is not on Databento; the futures proxy needs ADR-0004 |
| DXY | level | 1-min | **DX futures** via Databento `IFUS.IMPACT` (history from 2018-12-23) | yes | the ICE spot index (DXY) is a separately licensed index, so DX futures are the proxy. Needs an ADR to rename the feature |
| US 2Y / 10Y yield | change | 1-min | **ZT / ZN futures** via Databento `GLBX.MDP3` | yes | FRED DGS2/DGS10 are daily, published the next day, so they can't be used intraday. Use futures price changes as yield-change proxies. Needs an ADR |
| Macro calendar (CPI, FOMC, NFP) | scheduled times | event | BLS release schedules + Federal Reserve FOMC calendars (public, archived) | yes | the schedule date is known in advance; only use calendar versions published before T |
| Breadth | — | — | **dropped for Phase 1** (no reliable PIT intraday source found) | — | already parked under "Later" |

## 2. QQQ expiration history (criterion 2)
| Date | Event | Source |
|---|---|---|
| before 2021-04-23 | QQQ weeklies expire Fridays only (+ end-of-month/quarter) | — |
| 2021-04-23 | Monday expirations first listed | Nasdaq OTA2021-23, Cboe notice |
| 2021-04-27 | Wednesday expirations first listed | same |
| 2022-11-14 | Tuesday expirations first listed (first expiry 2022-11-15) | Nasdaq OTA2022-40, Cboe notice |
| 2022-11-16 | Thursday expirations first listed (first expiry 2022-11-17) | same |

**Verified in the M2 sample (C5, `reports/m2/sample_week.md`):** in March 2025, every
Mon–Thu expiration (including Tue/Thu) first appeared in Databento's definitions **10 sessions
(two weeks) before expiry**, not one. Fridays were already listed when the lookback began
(≥ 14 sessions). So a 1DTE contract is normally **not** brand new and does have prior-day OI.
OI stays a feature rather than a gate (OD-7). That decision still holds; only its stated
rationale was too pessimistic. This was one sample period; M4 checks the lead time across the full history.

## 3. IBKR vs historical provider (criterion 3)
| Need | IBKR | Comment |
|---|---|---|
| Historical **expired** QQQ options quotes | **Not available.** IBKR's documented historical limitations exclude "data for securities which are no longer trading", and EOD data for options | so every backtest option needs a third-party historical provider |
| Historical 1-min underlying bars | available, but subject to pacing limits; bars ≤ 30 s unavailable beyond 6 months | usable as a cross-check, not as the primary research source |
| Expired futures | not available older than 2 years past expiry | NQ/ES/ZN/ZT history comes from Databento |
| Live quotes for paper mode (M20) | yes (market-data subscriptions) | **market data only.** Order APIs are never connected (hard rule 1) |
| Live OI, IV, Greeks | yes (snapshot) | stored but treated as in OD-7 |

Implication: research data comes from a historical vendor. IBKR's role is limited to live paper
data in M20, and the M20/M21 live-vs-replay check will reveal any feed differences between
IBKR and the research vendor.

## 4. Candidate options-data providers (criterion 3, detail in ADR-0002)
See `docs/decisions/0002-options-data-provider.md`.

## 5. One-week sample validation (criterion 4) — pending provider choice and access
`scripts/m2_sample_check.py` will run these checks on one full week (proposed: **2025-03-10 →
2025-03-14**, a normal week with a CPI release on Wed 03-12) and write `reports/m2/sample_week.md`:

| ID | Check |
|---|---|
| C1 | timestamps parse; timezone determined (vendor ET vs UTC); DST is handled (that week is just after the 2025-03-09 DST change) |
| C2 | QQQ 1-min bars: 390/session; start- vs end-labelled convention determined by comparing with a second source |
| C3 | interval quote semantics: the 1-min bucket quote equals the last tick quote **at or before** the bucket time (needs tick data for at least one contract-hour) |
| C4 | a 1DTE expiration is present at every prediction timestamp of every session |
| C5 | first-quote date of each 1DTE series → listing lead time |
| C6 | quote validity: crossed/zero/negative quote counts; spread distribution for ATM ± 5 strikes vs spec §4.9 gates |
| C7 | OI timestamps: OI for D−1 first appears on D at about what time |
| C8 | NBBO consistency: `cbbo-1m` vs the minute-end state rebuilt from `cmbp-1` ticks (both Databento; an independent second vendor is deferred to the M20 IBKR live-vs-replay check) — share of contract-minutes with identical bid/ask |

## 6. Sources (checked 2026-10-05)
- ThetaData pricing: https://www.thetadata.net/pricing ; options data overview: https://www.thetadata.net/options-data ; quote endpoint: https://thetadata.net/docs/operations/option_history_quote.html ; OI endpoint (06:30 ET, prior-day close; Pro tier): https://thetadata.net/docs/operations/option_history_open_interest.html ; stocks (UTP since 2012-06, CTA since 2017-01): https://www.thetadata.net/stocks-data ; indices (VIX listed): https://www.thetadata.net/indices-data
- Databento OPRA history extension (cbbo-1m, trades, statistics, definitions from 2013-04-01; cbbo-1s and tcbbo from 2023-03-28): https://databento.com/blog/opra-improvements-coming-soon ; OPRA plans: https://databento.com/blog/introducing-new-opra-pricing-plans ; pricing: https://databento.com/pricing ; CME history from 2010-06-06: https://databento.com/blog/CME-history-extended-to-2010 ; ICE Futures US from 2018-12-23: https://databento.com/blog/introducing-ice-futures-us
- Massive (formerly Polygon) options quotes (history from 2022-03-07; Options Advanced plan): https://massive.com/docs/rest/options/trades-quotes/quotes ; plans: https://massive.com/options
- Cboe DataShop Option Quotes Intervals (1-min, optional IV/Greeks/OI, from 2012-01): https://datashop.cboe.com/options-intervals-subscription
- IBKR historical data limitations: https://interactivebrokers.github.io/tws-api/historical_limitations.html
- Expiration history: see PHASE_1_SPEC §13.
