# Features — feature_version f2 (M5)

**Status: v1.1, approved 2026-10-07 (ADR-0004 + amendment 1: cross-market prices from NBBO mids → f2).** Code: `src/qqq1dte/features/defs.py`
(functions), `inputs.py` (tables), `engine.py` (registry/loop), `writer.py` (PIT gate).
Parameters: `configs/phase1.yaml` → `features:`.

## Conventions that apply to every feature
- **Point in time.** Each feature is computed from an `AsOfReader` with cutoff T (the prediction
  timestamp). Its `available_at` is the latest `available_at` among the rows it used. The writer
  refuses any row with `available_at > T`. `features` cannot import `labels` (import-linter, CI).
- **Price at time t** (`qqq_reference`): close of the last RTH bar of the session that is
  *complete* by t (a bar labelled L is complete at L + 1 min). At the open itself, the session's
  opening price. Before the open: unavailable. P_T = price at T. Pre-market bars are never used
  as a reference.
- **Cross-market price at time t** (`quote_reference`, features 15–20, f2): NBBO mid of the
  latest `bbo-1m` record with `available_at ≤ t` (stamped at interval end). It must be two-sided,
  0 < bid ≤ ask, and no older than `liquidity.max_quote_age_s`, otherwise missing
  (`no_valid_quote`, no fallback to an older quote). Trade bars were stale for thinly traded ETFs (ADR-0004 amendment 1).
- **Missing values** are null with a reason, never filled. `window_before_open`: the lookback
  starts before today's open. `insufficient_history`: fewer prior sessions than required (the
  data starts 2023-03-28, so the first ~15 sessions lack ATR and the first ~10 lack relative
  volume). `no_valid_quote`: no fresh, valid, unrejected quote. `no_data`, `flat_range`.
- **Daily tables** (QQQ daily stats, minute volume profiles) are stamped at the session's last
  RTH bar completion, so a session's own daily row is never visible during it.
- Leakage risk below = what would leak if the rule were broken, and the test that prevents it.
  The generic guards are T-LEAK-03/05 (all features).

## Feature list (28)

| # | Feature | Definition / formula | Source | Available at | Missing when | Why it might matter | Leakage risk / guard |
|---|---|---|---|---|---|---|---|
| 1 | `vwap_dist` | (P_T − VWAP)/VWAP; VWAP = Σ((H+L+C)/3·V)/ΣV over today's RTH bars complete by T | QQQ bars | latest bar used | no RTH bar yet | mean reversion / trend vs. volume-weighted fair price | using the unfinished bar (T-LEAK-06) |
| 2 | `ret_since_prev_close` | P_T / prev RTH close − 1 | QQQ bars + daily | max(bar, prev daily row) | no prior session | day's move so far | today's close (T-LEAK-08) |
| 3 | `dist_prev_high` | P_T / prev RTH high − 1 | QQQ daily | same | no prior session | proximity to resistance | T-LEAK-08 |
| 4 | `dist_prev_low` | P_T / prev RTH low − 1 | QQQ daily | same | no prior session | proximity to support | T-LEAK-08 |
| 5 | `or_position` | (P_T − ORL)/(ORH − ORL); OR = first 15 RTH bars | QQQ bars | 09:45 onward | before 09:45; flat range | breakout / range position | OR bars after T |
| 6 | `overnight_gap` | today's RTH open / prev RTH close − 1 | QQQ bars + daily | 09:31 | no prior session | gap fill vs. continuation | T-LEAK-08 |
| 7 | `range_atr` | (today's RTH high − low so far) / ATR14; TR = max(H−L, \|H−C₋₁\|, \|L−C₋₁\|) over the last 14 prior sessions | QQQ daily | max(bar, daily) | < 15 prior sessions | how much of the "normal" day's range is used | today's daily row (T-LEAK-08) |
| 8–11 | `ret_5m`, `ret_15m`, `ret_30m`, `ret_60m` | ln(P_T / price at T − k) | QQQ bars | latest bar used | T − k before the open | short-horizon momentum | future bars (T-LEAK-04/05) |
| 12 | `mom_accel` | ret over (T−15, T] − ret over (T−30, T−15] | QQQ bars | latest bar | before 10:00 | momentum acceleration | same |
| 13 | `rv_30m` | stdev of the last 30 one-minute log returns (31 complete RTH bars) × √(252·390) | QQQ bars | latest bar | fewer than 31 bars (before ~10:01) | realized volatility | same |
| 14 | `rel_volume` | today's cumulative RTH volume after m bars / median of the same over the prior 20 sessions (≥ 10 required) | QQQ bars + profiles | max(bar, profile) | < 10 prior sessions | participation / news flow | today's full-day profile (T-LEAK-08) |
| 15 | `spy_qqq_rel_15m` | 15-min log return of SPY − QQQ | SPY NBBO, QQQ bars | latest quote/bar used | window before open; no valid quote | tech vs. broad market leadership | future quotes (T-LEAK-05) |
| 16 | `soxx_ret_15m` | 15-min log return of SOXX | SOXX NBBO | latest bar | window before open | semiconductor lead | same |
| 17 | `megacap_ret_15m` | mean 15-min log return of NVDA, AMD, AVGO, TSM (≥ 3 required) | stock NBBO | latest bar used | < 3 available | heavyweight / semis momentum | same |
| 18 | `uup_ret_60m` | 60-min log return of UUP (DX proxy, ADR-0004) | UUP NBBO | latest bar | window before open | dollar strength | same |
| 19 | `ief_ret_60m` | 60-min log return of IEF (10Y proxy; ≈ −duration·Δyield) | IEF NBBO | latest bar | window before open | rate moves vs. growth stocks | same |
| 20 | `shy_ret_60m` | 60-min log return of SHY (2Y proxy) | SHY NBBO | latest bar | window before open | front-end rates / Fed expectations | same |
| 21 | `vix_prev_close` | VIX close of the most recent prior date | Cboe VIX file | that date 18:00 ET (conservative) | no prior date | volatility regime | today's close (T-LEAK-08 analogue; fixture hides D's value) |
| 22 | `straddle_move` | (call mid + put mid) / spot for the spec §5 contracts | QQQ NBBO, options, chain | max(spot, quotes, definitions) | no fresh valid quote | market-implied move to the D+1 expiry | later quotes; rejected-quote fallback |
| 23 | `atm_spread_pct` | mean of (ask − bid)/mid over the two §5 contracts | same | same | same | liquidity / cost | same |
| 24 | `put_call_imbalance` | (put mid − call mid)/(put mid + call mid) | same | same | same | skew / directional demand | same |
| 25 | `minutes_since_open` | (T − open)/60 s | calendar | T | never | intraday seasonality | — |
| 26 | `day_of_week` | Mon = 0 … Fri = 4 | calendar | T | never | weekly effects (Fri→Mon expiry) | — |
| 27 | `cal_days_to_expiry` | days from D to the next session (1, or 3+ over weekends/holidays) | calendar | T | never | theta / weekend risk | — |
| 28 | `macro_event_today` | 1 if a CPI/NFP release (08:30 ET, actual dates) or a scheduled FOMC statement (14:00 ET) falls on D | `configs/reference/macro_calendar.csv` | release time / prior-year schedule | never (0 if none) | event-driven volatility | actual release *values* are never stored (T-LEAK-09) |

## Notes
- **Spec §5 contracts** for features 22–24: spot = latest valid QQQ NBBO mid with age ≤
  `liquidity.max_quote_age_s`; call = lowest standard D+1 strike ≥ spot; put = highest standard
  D+1 strike ≤ spot (ADR-0005 standard contracts, adjusted strikes included). Each quote = the
  latest record for the contract. If that record was rejected or is stale, the feature is missing.
  It never falls back to an older quote (M4 open issue 1).
- **Holiday releases:** BLS published the March 2023 and March 2026 jobs reports on Good Friday
  (NYSE closed). They never set `macro_event_today`; their information reaches the next
  session through prices (e.g. `overnight_gap`).
- **Not in f1 (ADR-0004):** NQ/ES, DX/ZN/ZT/VX futures, open interest (rule tested by T-LEAK-07),
  in-house IV/Greeks, breadth.
