# PHASE 1 SPECIFICATION — QQQ 1DTE Research & Validation Engine

**Status: FROZEN v1.1 (2026-10-05; ADR-0001, amended by ADR-0003).** Any change to a definition here
requires a new ADR in `docs/decisions/`, approved by the owner (CLAUDE.md rule 7).

Conventions:
- **ACCEPTED** = a default proposed in M1 where MASTER_PROMPT left a value open, approved by the
  owner on 2026-10-05. The one-line rationale is kept so later ADRs know why it was chosen.
- Items marked "verified in M2" / "checked in M4/M6" are frozen as defaults. If the data
  contradicts them, they change only through an ADR.
- `config:` = the key in `configs/phase1.yaml` that holds the value. Code reads the config and
  never hard-codes the value. The spec says what the key means; the YAML holds the number. If
  the two ever disagree, that is a bug, and a CI test (T-CFG-01) checks for it.
- All times are America/New_York (ET) unless marked UTC. Storage is always UTC.

---

## 1. Instrument

| Item | Definition |
|---|---|
| Underlying | QQQ (Invesco QQQ Trust), US-listed ETF. Reference price = consolidated 1-minute bars (trades), see §1.3. |
| Options | Standard QQQ equity options. **American-style, physically settled.** Root `QQQ`. Strike increments: use what the point-in-time chain lists (do not assume $1). |
| Contract multiplier | 100 (verify per contract from chain metadata; reject the contract if it is not 100, e.g. adjusted series after a corporate action). |

### 1.1 Expiration history (verified 2026-10-05, sources in §13)

| Period | QQQ expirations listed | 1DTE coverage |
|---|---|---|
| before 2021-04-23 | Fridays (weeklies) + end-of-month/quarterly | only Thu→Fri, plus a few month-end cases |
| 2021-04-23 → 2022-11-13 | Mon, Wed, Fri (Mon listed from 2021-04-23, Wed from 2021-04-27) | Fri→Mon, Tue→Wed, Thu→Fri only (3 of 5 weekdays) |
| from 2022-11-14 | Mon–Fri (Tue listed from 2022-11-14, Thu from 2022-11-16) | every trading day |

**Verified in M2 (informational, no definition change):** in the March 2025 sample, Mon–Thu
expirations first appeared 10 sessions before expiry (Fridays earlier), so 1DTE contracts
normally have prior-day open interest. At the 2022 launch, Tue/Thu series were listed one day
ahead. M4 checks the lead time across the full history. See `reports/m2/sample_week.md` (C5).

### 1.2 Definition of 1DTE — ACCEPTED

> At prediction timestamp T in trading session D, the **1DTE expiration** is the QQQ expiration whose
> expiration date equals **the next NYSE trading session after D** (D+1 by the XNYS calendar), *and*
> which is **listed in the point-in-time chain at T**.

- Calendar days to expiry can be 1 (Mon–Thu), 3 (Fri→Mon), or more across holidays. All of these count as 1DTE. Record `calendar_days_to_expiry` as a feature/regime attribute.
- If no such expiration is listed at T (e.g. the D+1 expiration was moved because of a holiday), the timestamp gets `NO_1DTE_EXPIRY` → logged, excluded from option labels, decision = NO_TRADE.
- The definition is never inferred from a calendar alone. It must be confirmed against the chain as of T (rule 9).
- *Rationale:* "next session" is unambiguous and stable across holidays. Calendar-day DTE would mix 1- and 3-day contracts under different names.

### 1.3 Usable history window — ACCEPTED

| Use | Window | Rationale |
|---|---|---|
| Option-outcome labels (C), backtests, Stage 2 | **2023-03-28 → latest available** (~3.5 years, ~885 sessions) — **amended by ADR-0003** (was 2022-11-14) | every session has a 1DTE contract from 2022-11-14; the start is bound by consolidated equity data at the chosen provider (ADR-0002/0003) |
| Underlying-only labels (A, B, D), Stage 1 | same window by default; `config: history.underlying_start` may extend earlier | a longer history helps Stage 1, but structural change (0DTE era) is a risk. Owner decision (§12, OD-1). |
| 2021-04 → 2022-11 partial-coverage period | **excluded** by default | only 3/5 weekdays; including it biases the sample by day of week |

---

## 2. Trading / prediction window

| Item | Value | Config key | Status |
|---|---|---|---|
| Regular market hours | 09:30–16:00 ET. Early-close sessions per XNYS calendar (13:00 close). | `session.calendar = XNYS` | fixed |
| Option trading after 16:00 | QQQ options may trade to 16:15 on non-expiry days. **Ignored**: no entries, exits, or labels use quotes after the equity close. | `session.ignore_post_close_options = true` | ACCEPTED (avoids a regime where the underlying is not trading; *uncertain mechanics flagged*) |
| Prediction timestamps | Every 5 minutes, at bar boundaries, from **09:45 to 15:00 inclusive** → 64 timestamps on a full day | `schedule.cadence_minutes = 5`, `schedule.first = "09:45"`, `schedule.last_new_entry = "15:00"` | ACCEPTED (skips the open, where spreads are wide and the opening range is still forming) |
| Early-close days | first = 09:45, last new entry = close − 60 min | `schedule.early_close_last_entry_offset_min = 60` | ACCEPTED |
| Information set at T | Only records with `available_at <= T`. A 1-min bar covering [t, t+1m) has `available_at = t + 1m` (bar **end**), plus any vendor publication lag. | — | fixed (hard rule 2) |
| Entry allowed | Only at prediction timestamps, only when there is no open position (§4.7), and only if every gate in §4.9 passes | — | ACCEPTED |
| Forced flat time | **15:50** (early close: close − 10 min) | `trade.forced_exit_time = "15:50"` | ACCEPTED (avoids the closing auction and 16:00 quote discontinuities) |
| Max holding period | **min(entry + 90 min, forced flat time)** | `trade.max_holding_minutes = 90` | ACCEPTED (limits label overlap to 18 timestamps and keeps every trade intraday) |
| Overnight holds | **Not allowed** (intraday-only) | `trade.allow_overnight = false` | ACCEPTED, see OD-2 |

---

## 3. Prediction targets (labels)

Notation: `P_T` = QQQ reference price at T = close of the last 1-min bar ending at or before T.
`H` = label horizon. Window `W = (T, T_end]`, where `T_end = min(T + H, forced_flat_time)`.
Bars are 1-minute bars; a label uses bars whose interval lies **entirely inside** W.
`config: labels.horizon_minutes = 90` (ACCEPTED, same as max holding, so labels and trades describe the same window).

Every label is produced for both sides (UP/CALL and DOWN/PUT) separately. They are **not**
complements of each other. Both can be 0 (that region is where NO_TRADE should come from).

| ID | Question | Definition | Defaults (config) |
|---|---|---|---|
| **A_up / A_dn** Direction | Will QQQ be higher (lower) than `P_T·(1±d)` at `T_end`? | `A_up = 1 if close(T_end) > P_T·(1+d)` ; `A_dn = 1 if close(T_end) < P_T·(1−d)` | `labels.direction.deadband = 0.0005` (5 bp) ACCEPTED: a tiny drift shouldn't count as a direction call |
| **B_up / B_dn** Magnitude | Will QQQ touch +m% (−m%) at any time in W? | `B_up = 1 if max(high in W) >= P_T·(1+m)` | `labels.magnitude.thresholds = [0.0025, 0.0050]`. **Primary 0.25%** ACCEPTED: 0.50% in ≤90 min is rare and would give few positives. The 0.50% variant is kept but counts toward multiple testing. |
| **C_call / C_put** Option outcome | Will the contract chosen by §5 reach +30% before −20%? | Simulated with the **conservative** fill (§6): entry at ask, path checked against **bid**. WIN if `bid >= 1.30·entry_fill` first; LOSS if `bid <= 0.80·entry_fill` first; otherwise TIME_EXIT at `T_end` | `labels.option.target_pct = 0.30`, `labels.option.stop_pct = 0.20` (from MASTER_PROMPT) |
| **D_call / D_put** Risk (underlying) | Will the underlying stop be touched before the underlying target? | CALL side: `D_call = 1` if low ≤ `P_T·(1−s)` before high ≥ `P_T·(1+m)`. Neither touched → `UNRESOLVED` (kept as a separate class, never coerced) | `labels.risk.stop = 0.0015`, target = primary m. ACCEPTED: roughly matches the −20%/+30% option bracket for an ATM 1DTE contract (to be checked empirically in M6) |

Rules shared by all labels:
- **Same-bar ambiguity:** if one bar (or one quote interval) breaches both stop and target, **stop is assumed first** (conservative). These rows get flagged `AMBIGUOUS_BAR` and counted.
- Missing bars inside W → label = `INVALID` with reason. Never interpolated (rule 8).
- Labels are computed only by `labels/` and are never readable by `features/` (enforced, see ARCHITECTURE §4).

---

## 4. Trade definitions

### 4.1 Entry condition
At T, decision engine output ∈ {CALL, PUT, NO_TRADE}. CALL requires all of the following:
`calibrated_p(C_call) − p_breakeven > edge_margin`, EV after costs (moderate fill) > 0, every gate in §4.9 passes, and the CALL side wins over the PUT side by EV. PUT is symmetric. Both sides failing → NO_TRADE with a reason code.
`config: decision.edge_margin = 0.03` ACCEPTED: a 3 pp buffer over break-even absorbs calibration error of about the ECE gate size.
Until calibration exists (before M13), the engine may emit predictions but **must emit NO_TRADE for every timestamp** (rule 6).

### 4.2 Candidate option selection → §5 (frozen rule)

### 4.3 Target / 4.4 Stop
Target: +30% of entry fill price (`labels.option.target_pct`). Stop: −20% (`labels.option.stop_pct`).
Both are checked on the **executable exit side** (bid for long options), never on mid or last.

### 4.5 Max holding period → §2.

### 4.6 Outcome classes
| Class | Definition |
|---|---|
| WIN | target touched first (exit side) |
| LOSS | stop touched first (or ambiguous bar, see §3) |
| TIME_EXIT_PROFIT / TIME_EXIT_LOSS | neither touched; exited at `T_end`, classified by the sign of net P&L |
| BREAKEVEN | TIME_EXIT with `|net P&L| <= 2%` of entry premium (`trade.breakeven_band = 0.02`, ACCEPTED: below typical round-trip cost noise) |
| EXPIRED | only possible if overnight holds are enabled (OD-2). With intraday-only it should never occur, and an assertion enforces that. |
| UNFILLED | the decision was CALL/PUT but the quote in force at `T_e` fails the §4.9 hard/age checks (the selected-contract liquidity failure *at selection* is NO_TRADE instead; UNFILLED covers checks that happen at fill time) |
| UNRESOLVED_DATA | path quotes missing, so the outcome can't be determined (logged, excluded, counted) |

### 4.7 Position sizing & concurrency (research)
- Size: **1 contract** fixed (`trade.contracts = 1`). Results are reported per contract, in % of premium, and in R.
- **1R** = `stop_pct × entry_fill × 100 + round-trip costs` (the maximum planned loss).
- Max simultaneous positions: **1** (`trade.max_open_positions = 1`).
- Max new entries per session: **3** (`trade.max_entries_per_day = 3`). ACCEPTED: caps clustering and serial dependence within one day.
- While a position is open, predictions are still computed and logged at every timestamp, with decision `BLOCKED_POSITION_OPEN`. This is a distinct code from model NO_TRADE, so NO_TRADE statistics stay clean.

### 4.8 Costs
| Item | Default | Config | Status |
|---|---|---|---|
| Commission | $0.65 per contract per side | `costs.commission_per_contract = 0.65` | ACCEPTED (typical retail broker tier) |
| Exchange/regulatory fees | $0.05 per contract per side, all-in | `costs.fees_per_contract = 0.05` | ACCEPTED (conservative lump; refine in M12) |
| Slippage | built into the fill model (§6) plus latency | — | — |

### 4.9 Liquidity / quote-validity gates (at entry time, on the selected contract)
| Gate | Default | Config |
|---|---|---|
| bid > 0, ask > 0, ask ≥ bid | hard | — |
| Quote age at decision | ≤ 60 s | `liquidity.max_quote_age_s = 60` |
| Max spread | ≤ max($0.05, 5% of mid) | `liquidity.max_spread_abs = 0.05`, `liquidity.max_spread_pct = 0.05` |
| Min bid | ≥ $0.20 | `liquidity.min_bid = 0.20` |
| Displayed size | ≥ contracts (if the vendor supplies sizes; otherwise flag `NO_SIZE_DATA`) | `liquidity.require_size = true` |
| Open interest | **not** used as a gate (see OD-7: a newly listed 1DTE series has no prior-day OI) | — |

All ACCEPTED. Rationale: ATM QQQ 1DTE spreads are normally a few cents, so these gates reject only abnormal quotes, not normal markets. They get rechecked against real data in M4.

---

## 5. Frozen option-selection rule — ACCEPTED (OD-3)

Run at entry time `T_e = T + latency` using **only** the chain snapshot with `available_at <= T_e`:
1. Expiration = the 1DTE expiration per §1.2.
2. Reference spot `S` = QQQ NBBO mid (or the last 1-min close if NBBO is unavailable; source recorded) at or before `T_e`.
3. CALL: the **lowest listed strike K ≥ S**. PUT: the **highest listed strike K ≤ S**. (ATM / first OTM.)
4. If that contract fails §4.9 → **NO_TRADE (`SELECTED_CONTRACT_ILLIQUID`)**. There is **no fallback** to another strike.
5. Selection is a pure function `(chain_snapshot, S, side, config) → contract | NoTrade`. Same inputs, same output, every time (T-SEL-*).

*Rationale:* the rule is strike-based and needs no model, vendor Greeks, or IV, so it can't be biased by data that was unavailable at T. Having no fallback leaves exactly one selection path, which removes any search over contracts.

---

## 6. Fill models

The entry fill uses the **quote in force at `T_e = T + latency`**: the latest NBBO with `available_at <= T_e` (`fills.latency_s = 5`, ACCEPTED). This is the same quote the selection rule (§5) sees. If its age exceeds `liquidity.max_quote_age_s`, the trade is UNFILLED. Exits use the quote in force at each simulated clock step after entry. *Data dependence:* with 1-min snapshots, latency below 60 s has no effect. M2 has to establish the quote granularity.
All fills round **against** the trader to the $0.01 tick.

| Model | Buy (open long) | Sell (close long) | Status |
|---|---|---|---|
| Conservative | ask | bid | fixed (MASTER_PROMPT) |
| **Moderate** | `mid + α·(ask − mid)` | `mid − α·(mid − bid)` | **ACCEPTED** (`fills.moderate_alpha = 0.5`), i.e. pay ¾ of the spread round trip. See OD-6. |
| Optimistic | mid | mid | fixed (MASTER_PROMPT) |

- Stop/target **triggers** always use the conservative side (bid), in every model. Only the fill price differs. This stops the optimistic model from triggering on prices nobody could trade at.
- Fill probability is assumed 1 when the gates pass. That is a known limitation, reported in the M12 sensitivity analysis.
- Results are always reported under all three models side by side (Phase 1I).

---

## 7. Point-in-time rules

| Data | `available_at` rule |
|---|---|
| 1-min bar [t, t+1m) | t + 1m + `pit.bar_publication_lag_s` (default 0; vendor-specific, set in M2) |
| NBBO quote/snapshot | its exchange/vendor timestamp |
| Daily bar for session D | D close + publication lag; **never** visible during D |
| Open interest "as of D−1" | **09:30 on D** at the earliest (`pit.oi_available_time = "09:30"`). OI dated D is never used during D. ACCEPTED (OCC publishes overnight; exact vendor timing is verified in M2). |
| Vendor IV / Greeks | vendor timestamp, *and* only if the vendor computes them from quotes at or before that timestamp. Default: **not used as features**. We compute our own IV/Greeks from NBBO mid at T (OD-7). |
| Macro calendar | the event's *scheduled time* is available from its announcement date. The *actual value* is available only at release time + lag. |
| Regime labels | computed from information ≤ T only. Thresholds (e.g. VIX terciles) are fit on the training fold only. |

---

## 8. Validation protocol

- Chronological walk-forward only. **Expanding window**: first train = 12 months; then **calibration block = 2 months** and **test block = 3 months**, rolling forward 3 months. (`validation.*`, ACCEPTED: gives ~8–10 OOS folds on ~3.9 years while keeping calibration separate from training.)
- **Final holdout:** the last 6 calendar months of available data (`validation.final_holdout_months = 6`) are locked until M19. Every read of them is logged to `final_test_access_log`. A second access requires an ADR (rule 5).
- **Purge/embargo:** labels never cross a session (intraday-only), so block boundaries are placed at session boundaries, with an **embargo of 1 full session** after each training block (`validation.embargo_sessions = 1`). If overnight holds are enabled, the embargo must be ≥ max holding + 1 session.
- **Uncertainty:** every CI uses a **session-block bootstrap** (resample whole days, 2,000 reps), because predictions within a day are strongly dependent.
- **Sample-size reporting:** every metric reports `n_predictions`, `n_sessions`, and `n_effective = n_sessions × floor(minutes_in_window / H)` (non-overlapping windows), plus `n_trades` for trading metrics.

---

## 9. Regimes (initial coarse set) — ACCEPTED (OD-9)

| Axis | Buckets | Definition (known at T) |
|---|---|---|
| Volatility | LOW / NORMAL / HIGH | prior-session VIX close, tercile cut points fit **on the training fold only**. "EXTREME" stays merged into HIGH until it has ≥ 30 sessions in a training fold. |
| Trend | TREND / CHOP | 20-session QQQ efficiency ratio (|net move| / sum |daily moves|) at prior close, median split fit on the training fold |
| Event | NORMAL / MACRO | session D (or D+1 for an overnight hold) has a scheduled CPI, FOMC decision, or NFP release |

3 × 2 × 2 = 12 cells. With ~980 sessions that averages ~80 sessions per cell, and some cells will be far smaller. A cell with < 30 sessions or < 100 trades in a fold is **reported but flagged LOW_SUPPORT and never used to gate decisions**. The MARKET STRUCTURE axis (bull/bear/reversal/chop) and the earnings-event axis are recorded as attributes but not stratified in Phase 1.

---

## 10. Multiple-testing accounting

- Every run of a model, label variant, threshold, feature set, or fill model on validation or test data writes a `validation_runs` row with the full config hash, **whether or not the result is kept**. A run that skips the registry is a bug (the backtest entry point refuses to run without a registered `run_id`).
- `n_trials` = count of distinct config hashes evaluated on the same data window. It feeds the **Deflated Sharpe Ratio** and the **Probability of Backtest Overfitting (CSCV)** in gate 16.

---

## 11. Phase 1V gates — numeric thresholds (all ACCEPTED, OD-5)

| # | Gate | Pass threshold |
|---|---|---|
| 1 | Data coverage | ≥ 98% of expected 1-min bars per required instrument-session; ≥ 95% of sessions in the window have a valid 1DTE chain at ≥ 95% of prediction timestamps |
| 2 | Data quality | 0 open CRITICAL `data_quality_events`; invalid-quote rate ≤ 2% in ATM ± 5 strikes |
| 3 | PIT integrity | 100% of feature rows satisfy `available_at <= T` (checked on the full dataset, not a sample); replaying 20 random historical timestamps reproduces the stored features exactly |
| 4 | Leakage tests | full T-LEAK suite passes; planted-future-feature canary detected; model on time-shuffled labels gives OOS AUC within 0.50 ± 0.02 |
| 5 | Baseline | Model 0 OOS Brier, log loss, and calibration reported for every fold |
| 6 | Beats baseline | Brier skill score vs Model 0 > 0 with session-bootstrap 95% CI lower bound > 0, pooled OOS; and better in ≥ 70% of folds |
| 7 | PIT option selection | T-SEL suite passes; 100% of journal selections reproduce from the stored snapshot |
| 8 | Bid/ask execution | T-FILL and T-BT accounting suites pass |
| 9 | Costs | every reported P&L is net of §4.8 costs (enforced by the report type) |
| 10 | Walk-forward positive | pooled OOS expectancy (moderate fills, net) > 0 with 95% CI lower bound > 0; positive in ≥ 60% of folds |
| 11 | Execution robustness | point-estimate expectancy > 0 under **conservative** fills; result sign does not depend on α ∈ [0.25, 0.75] |
| 12 | Calibration | held-out ECE ≤ 0.03 (10 equal-count bins); calibration slope in [0.8, 1.2]; every bin with n ≥ 200 has its observed rate inside the 95% Wilson CI of its mean predicted value |
| 13 | Regime behaviour | every traded regime cell with ≥ 100 trades has expectancy CI upper bound > 0; cells failing this are set to NO_TRADE by rule, not by tuning on test |
| 14 | NO_TRADE validated | counterfactual expectancy of NO_TRADE timestamps (trade simulated anyway) < expectancy of traded timestamps, with session-bootstrap CI on the difference excluding 0 |
| 15 | Sample size | ≥ 300 OOS trades **and** ≥ 150 distinct OOS sessions with a trade; buckets with n < 100 are labelled LOW_SUPPORT in every report |
| 16 | No overfitting | PBO ≤ 0.20; Deflated Sharpe probability ≥ 0.95 using the logged `n_trials` |
| 17 | Reproducibility | re-running a logged validation run from its stored versions reproduces predictions to within 1e-9 and identical trades |
| 18 | Drift monitoring | synthetic drift injection (shifted feature distribution; degraded calibration) raises the right alert within 10 sessions in a replay test |
| 19 | Paper ≈ research | over the paper period: ECE ≤ 0.05; mean realized-vs-moderate-model slippage within ±50%; prediction-distribution PSI ≤ 0.2 vs research OOS |
| 20 | Stable live paper period | ≥ 60 trading sessions **and** ≥ 100 paper trades (whichever ends later); paper expectancy not significantly below research (one-sided test, p > 0.05) |

Passing every gate is evidence of a validated edge under these assumptions. It is **not** a claim of profitability (rule 12).

---

## 12. Decisions (all resolved 2026-10-05: owner accepted every recommendation, ADR-0001)

| ID | Decision | Options | Claude's recommendation |
|---|---|---|---|
| **OD-1** | 1DTE definition and history window | (a) §1.2 + 2022-11-14 onward for everything; (b) same, but Stage 1 underlying labels also use earlier years | **(a)** at first; (b) as a later experiment that counts toward `n_trials` |
| **OD-2** | Intraday-only vs overnight holds | (a) intraday-only, flat by 15:50; (b) allow holding into D+1 (the thing that makes 1DTE different from 0DTE) | **(a)** for Phase 1: overnight gaps, weekend theta, and pin/assignment risk would each need their own labels and much more data. Note: under (a), 1DTE is chosen for its lower gamma/theta noise compared with 0DTE, not for overnight exposure. Please confirm that is the thesis you want to test. |
| **OD-3** | Frozen selection rule | (a) ATM/first-OTM strike, no fallback (§5); (b) target delta 0.40 using our own computed delta; (c) (a) with one-strike fallback | **(a)**: no model dependency, and a single path |
| **OD-4** | Cadence vs effective sample | 5-min cadence gives ~62k predictions but only ~980 sessions and ~3.5k non-overlapping 90-min windows; 1 position at a time + ≤ 3 entries/day | keep the 5-min cadence for *prediction* quality; judge *trading* on trades and sessions; all CIs session-block bootstrap (§8) |
| **OD-5** | Gate thresholds | §11 table | as proposed; the ones I'm least sure of are ECE ≤ 0.03 and ≥ 300 trades, both of which could be too strict for ~3 years of OOS data |
| **OD-6** | "Moderate" fill | α = 0.5 (¾ spread round trip) vs α = 0.25 vs a size/spread-dependent model fit on paper fills later | **α = 0.5** until paper fills give an empirical estimate (gate 19) |
| **OD-7** | OI and vendor IV/Greeks | OI: prior-day only, available 09:30 D, feature only (not a gate); IV/Greeks: compute ourselves from NBBO mid, vendor values stored but not used | as stated. Open question: American-exercise/dividend handling for our IV (QQQ pays quarterly; it matters near ex-div for calls). Proposed: European BSM with a discrete-dividend adjustment, flagged on ex-div −1 sessions. |
| **OD-8** | Logging every configuration tested | registry as in §10, DSR + PBO in gate 16 | as stated |
| **OD-9** | Coarse regime set | 12 cells (§9) vs a smaller 6 (vol × event only) | start with **12**, flag LOW_SUPPORT, and collapse the trend axis if it doesn't separate outcomes in M14 |
| **OD-10** | Primary magnitude threshold | 0.25% vs 0.50% (MASTER_PROMPT example) | 0.25% primary; 0.50% secondary |
| **OD-11** | Package layout | CLAUDE.md layout + a small `core/` package (calendar, clock, PIT reader, config) shared by all modules | add `core/`. It's a layout change, so it needs your OK. |
| **OD-12** | Early-close sessions and the 16:00–16:15 option session | include early-close days with shifted times; ignore post-16:00 options quotes | as proposed; the mechanics get verified against vendor data in M2 |

---

## 13. Sources for verified facts
- Nasdaq Options Trader Alert OTA2021-23 / Cboe notice: QQQ Monday & Wednesday weeklies first listed 2021-04-23 / 2021-04-27 — https://www.nasdaqtrader.com/MicroNews.aspx?id=23 , https://cdn.cboe.com/resources/product_update/2021/Cboe-Exchanges-to-List-Monday-and-Wednesday-Expiring-Weekly-Options-on-QQQ.pdf
- Nasdaq OTA2022-40 / Cboe notice: QQQ Tuesday expirations listed from 2022-11-14, Thursday from 2022-11-16 — https://www.nasdaqtrader.com/MicroNews.aspx?id=OTA2022-40 , https://cdn.cboe.com/resources/product_update/2022/Cboe-Options-to-List-SPY-and-QQQ-Tuesday-and-Thursday-Expiring-Weekly-Options.pdf
