# ADR-0002 — Historical data providers

- Status: **ACCEPTED** (owner, 2026-10-05): **Databento** is the primary provider
- Date: 2026-10-05
- Milestone: M2

## Context
Spec §1.3 needs QQQ option **NBBO** quotes at ≤ 1-min granularity from 2022-11-14 to present,
for expired contracts. IBKR doesn't serve expired options (DATA_REQUIREMENTS §3). Prices and
coverage below were read from vendor pages on 2026-10-05. Prices are retail/individual unless
stated. Commercial use is priced separately.

## Options-data candidates
| Provider | QQQ option data | NBBO? | Granularity | History start | Cost (2026-10-05) | Notes / risks |
|---|---|---|---|---|---|---|
| **ThetaData** | full OPRA | **yes** ("every NBBO quote reported by OPRA") | tick, or buckets 10ms…1h | 2012-06 (plan limits: Value 6 y, Standard 10 y, Pro 14 y) | Value **$40/mo** (1-min intervals), Standard **$80/mo** (tick NBBO), Pro **$160/mo** (adds e.g. historical OI) | cheapest fit; bucket semantics need checking (C3); multi-day requests ≤ 1 month and need an expiration (fine for 1DTE); personal-use licence |
| Databento `OPRA.PILLAR` | full OPRA | yes (consolidated BBO) | `cbbo-1m` from 2013-04-01; `cbbo-1s`/`tcbbo` from 2023-03-28 | 2013-04-01 for 1-min | Standard **$199/mo** includes 12 months of L1 history. Older L1 is **usage-based per GB** (rate not shown on the public page) | very clean timestamps and documentation; cost for 4 years of QQQ cbbo-1m is unknown until quoted. Good as an independent cross-check (C8) |
| Massive (ex-Polygon) | options quotes | **unclear**: the docs describe per-exchange bid/ask exchange IDs, so the NBBO may have to be reconstructed | tick | **2022-03-07** (quotes) | Options Advanced **$199/mo** | history only just covers our window; NBBO semantics need confirmation |
| Cboe DataShop (Option Quotes Intervals) | 1-min intervals incl. bid/ask, sizes, underlying bid/ask; optional IV/Greeks/OI | yes | 1-min (or N-min) | 2012-01 | quote-based (not listed); historically far above retail feeds | the institutional reference; best for one-off validation, too costly as primary |
| IBKR | live only | — | — | **no expired options** | — | live paper data (M20) only |

Not shortlisted: ORATS (snapshot/derived focus), AlgoSeek, OptionMetrics (EOD only, academic),
EOD-chain vendors (EOD only, so they can't support intraday fills).

## Other datasets
| Data | Proposed source | Cost |
|---|---|---|
| QQQ, SPY, SOXX, NVDA, AMD, AVGO, TSM 1-min | ThetaData stocks (UTP since 2012-06, CTA since 2017-01) | stock plan price not shown on the public page — **check at signup** |
| VIX intraday | ThetaData indices (VIX listed) | price/history **check at signup** |
| NQ, ES, ZT, ZN 1-min | Databento `GLBX.MDP3`, usage-based `ohlcv-1m` | small (1-min OHLCV for 4 futures × 4 years is a few GB at most) |
| DX (DXY proxy) 1-min | Databento `IFUS.IMPACT`, usage-based `ohlcv-1m` | small |

## Recommendation
1. **ThetaData Options Standard ($80/mo)** as the primary options source. Tick-level NBBO
   lets us measure real quote age and latency and check the bucketing semantics. Value ($40)
   would also meet the ≤ 1-min requirement, but it can't verify C3 because it has no tick data.
   Pro ($160) is only needed for historical OI, which is a feature rather than a gate, so it can
   wait.
2. **ThetaData stocks + indices** for the equities and VIX, if their combined price is
   reasonable at signup. Otherwise, Databento for equities.
3. **Databento usage-based** for the CME and ICE futures, plus a **one-week OPRA cbbo-1m pull**
   as the independent cross-check C8.
4. Re-evaluate after the sample week. If ThetaData fails C3 or C8, the fallback is Databento
   OPRA, with its multi-year cost quoted first.

Estimated monthly cost while pulling history: about $80 + the ThetaData stock/index plan +
low tens of dollars of Databento usage. This is research cost only.

## Consequences
- Personal-use licences: research results may be used internally. Redistributing raw data
  is not allowed.
- DXY → DX futures and 2Y/10Y yields → ZT/ZN futures substitutions need ADR-0004 (feature
  definitions) before M5.
- The sample-week report (DATA_REQUIREMENTS §5) is the evidence that turns this ADR into ACCEPTED.

## Owner decision (2026-10-05)
After pricing with Databento's free `metadata.get_cost` (no data bought), the owner chose
**Databento for everything**, usage-based, and **no ThetaData**:

| Item | Dataset / schema | Estimated cost |
|---|---|---|
| QQQ options 1-min NBBO, D+1/D+2 expiries, strikes in [0.95·month low, 1.05·month high], 2022-11-01→2026-10-02 (upper bound; the window is now 2023-03-28→, ADR-0003) | `OPRA.PILLAR` `cbbo-1m` | $19.07 |
| QQQ 1-min bars, consolidated | `EQUS.MINI` `ohlcv-1m` (from 2023-03-28) | $0.29 |
| One week tick NBBO for C3/C8 (2025-03-10→14) | `OPRA.PILLAR` `cmbp-1` | $14.13 |
| **Total** | | **≈ $34** (vs ≈ $280 for a 2-month ThetaData sprint) |

Consequences of choosing Databento:
- Consolidated equity data starts 2023-03-28, so the window moves (ADR-0003).
- The VIX index is not available. Regime uses the prior-session VIX close (free daily file from
  Cboe); intraday VIX features use front-month VX futures from `XCBF.PITCH` (from 2018-11-04).
  This goes into ADR-0004 (feature substitutions).
- C8 (cross-source NBBO) becomes an internal-consistency check: `cbbo-1m` vs the minute state
  rebuilt from `cmbp-1`, both Databento. An independent second-vendor check is deferred to the
  M20 live-vs-replay comparison with IBKR.
- Timestamps: `cbbo-1m`/`bbo-1m` `ts_recv` = **end** of interval (dbn field docs); `ohlcv-*`
  stamped at interval **open**, so `available_at = ts_event + interval`.
- Licence terms for stored historical data must be read before M3 (not yet reviewed).
