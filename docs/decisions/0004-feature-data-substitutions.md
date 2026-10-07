# ADR-0004 — Feature data sources and substitutions (M5)

- Status: **ACCEPTED** (owner, 2026-10-06: D1(A), D2, D3, D4, D5 and the 28-feature list)
- Date: 2026-10-06
- Milestone: M5
- Amends: MASTER_PROMPT Phase 1B/1F instrument list as implemented; spec OD-7 (IV/Greeks timing)

## Context
MASTER_PROMPT lists NQ, ES, VIX, DXY and the US 2Y/10Y yields among the cross-market inputs.
Priced on 2026-10-06 (Databento, 2023-03-28 → 2026-10-02, front contract only): NQ/ES/ZN/ZT
1-min $17.12, DX $24.86, VX $159.47. Full-chain QQQ open interest $371. ETF/stock 1-min bars
cost cents per symbol. Futures trade ~23 h/day at higher per-GB rates.

## Decision
| Need | Source used | Rationale |
|---|---|---|
| QQQ, SPY, SOXX, NVDA, AMD, AVGO, TSM | `EQUS.MINI` 1-min bars | as listed |
| NQ, ES | **dropped**; SPY + QQQ's own pre-market bars | in RTH, NQ ≈ QQQ and ES ≈ SPY; their unique value (overnight) is in QQQ pre-market bars |
| DXY | **UUP** ETF 1-min bars | UUP tracks DX futures; consolidated tape; cents |
| US 10Y / 2Y | **IEF / SHY** ETF 1-min bars (returns ≈ −duration × Δyield) | sign and timing of rate moves, consistent data type |
| VIX | Cboe official daily `VIX_History.csv` (downloaded 2026-10-06, 9,288 lines, 1990 → 2026-10-05); used as **prior-session close** | the spec's regime uses the index close; intraday VX futures cost $159 |
| Open interest | **deferred** (no OI feature in feature_version f1) | feature only (OD-7); not needed by f1 |
| IV / Greeks (OD-7) | **deferred**; replaced in f1 by model-free ATM straddle expected move, ATM spread %, put/call mid imbalance | in-house IV needs a point-in-time rate and dividend inputs; revisit when needed |
| Breadth | dropped (already "Later") | no point-in-time intraday source |
| Macro calendar | `configs/reference/macro_calendar.csv` (BLS + Fed, 119 events) | CPI/NFP use **actual** release dates, which are public at 08:30 ET (before every prediction timestamp), so the 2025 shutdown postponements and cancellations are handled without needing announcement dates. FOMC uses the Fed's scheduled statement days, known since the prior year (conservatively 31 Dec of the prior year). The 2025-08-22 notation vote is excluded (not a scheduled meeting). |

Futures (NQ/ES/ZN/ZT/DX/VX, RTH-windowed ≈ $70) stay a "Later" option if models show the
proxies are inadequate. Adding them later counts as a new feature version and as a tested
configuration.

## Consequences
- feature_version `f1` = the 28 features in `docs/FEATURES.md`.
- Cross-market data gets the M4 data-quality checks (reported in `reports/features/summary.md`).
- Spend: cross-market bars $1.84; VIX file free.

## Amendment 1 (owner, 2026-10-07): cross-market prices from NBBO mids → feature_version f2
The first full build (f1) showed that 1-minute **trade** bars exist only in minutes with a
trade. UUP, SHY and IEF were below 98% of RTH minutes in 882, 882 and 876 of 882 sessions (worst
3%, 9%, 45%), SOXX in 621 and AVGO in 177. Their f1 returns were stale (median 60-min return 0
for UUP/IEF/SHY). Decision: all 9 cross-market features read the **NBBO mid** from `EQUS.MINI`
`bbo-1m` (stamped at interval end, so `available_at = ts_recv`), cleaned with the M4 quote checks.
The latest record must be two-sided, valid and no older than `liquidity.max_quote_age_s`, with
no fallback to an older quote. QQQ's own price features stay on bars (spec §3 P_T). Cost $1.32.
`features.version` = **f2**. f1 snapshots stay registered in the catalogue as superseded.
