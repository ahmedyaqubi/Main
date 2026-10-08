# ADR-0013 — Phase 1c: defined-risk short premium (model-free screen first)

- Status: **PROPOSED**. Drafted 2026-10-08 from the owner's 10-point review. Acceptance waits for
  the Step-0 data quote and the owner's purchase decision.
- Date: 2026-10-08
- Milestone: M19T (placeholder name)
- Amends, **for this strategy family only**: PHASE_1_SPEC §3 (C labels), §4.7–4.8 (exits, costs
  per leg) and §5 (selection). The Phase 1 definitions and the closed long-premium family
  (ADR-0012) are unchanged.
- Disclosure: drafted after the long-premium family closed (M19, M19R, M19S). It is motivated
  by M19R D1 (option prices already price move size; any volatility-risk-premium edge sits with
  the seller). No short-premium outcome has been looked at.
- Registry at drafting: **n_trials = 38**.

## Context
- Every long-premium definition failed: theta plus costs exceed the direction signal (M19S:
  Â ≤ 0.557 vs a* ≥ 0.57).
- Defined-risk credit spreads cap the loss per trade at width − credit (≤ $100 for a $1 width).
  That is a capital scale similar to T0, with no capital needed for the underlying.
- Data on disk covers, per session D, only contracts expiring at D+1 and D+2
  (`scripts/m4_fetch_history.py`). **Expiry-day quotes are not on disk**, so neither 0DTE
  trades nor 1DTE holds to expiry can be tested without new data.

## Decision

### D0. Data roles and order of work
- **Step 0 (no trial):** specify the data gap, get a cost quote, purchase only with the owner's
  approval, then build and verify the data.
- **Step 1 (1 registered screen):** a model-free screen (D3).
- Filters and models enter only in a later step, under their own ADR.
- **Development data:** sessions 2020-01-02 → 2026-04-02 (D2). Confirmation data: the holdout
  (D7) and forward data (D8). No development result is reported as out-of-sample.

### D1. Trade definition (common to all cells)
a. **Structure:** QQQ, $1 width.
   - Short strike = the furthest out-of-the-money strike whose **conservative** credit (short
     bid − long ask) is ≥ X × width.
   - Long strike = short − $1 (puts) or short + $1 (calls).
   - No strike meets X → NO_TRADE (logged reason).
   - Model-free and point-in-time: it uses only quotes in force at T_e = T + latency. It needs
     no spot price.
b. **Entry:** every 5-minute timestamp in the cell's window. Per-leg §4.9 gates; conservative
   fills (sell at the bid, buy at the ask); §4.8 costs per leg; 1 unit. Entries are
   **averaged within the session**: the unit of analysis is the session.
c. **Exit:** no stop and no target. Every leg is closed at **15:50 ET on the expiry session**
   (close − 10 min on early-close days) at the conservative fill: short legs bought at the ask,
   long legs sold at the bid.
   - A missing bid counts as 0.
   - A missing ask, or a quote gap longer than `max_path_gap_minutes`, gives UNRESOLVED_DATA
     (logged, never filled).
   - No settlement, exercise or pin-risk modelling.
   - Legs that would have expired worthless are bought back (conservative).
d. **Ex-dividend:** any structure with a **short call leg** whose hold spans the close before a
   QQQ ex-dividend date is excluded (`EX_DIV_SPAN`).
   - The dates come from the issuer's declarations (known in advance, so point-in-time). They
     are stored in config with their source.
   - Early exercise of short puts is noted, not modelled: the long put caps the loss, and the
     15:50 mark prices intrinsic value.
e. **Label span and purge:**
   - A label is used only if its exit lies in the same block as its entry: development, train,
     calibration, test, or confirmation. Otherwise it is dropped (`LABEL_CROSSES_BLOCK`) and
     counted.
   - No development label may end in the holdout. The holdout guard checks exit sessions as well
     as entry sessions.
   - Later model steps use this purge in addition to the 1-session embargo. The current splitter
     has no embargo between calibration and test.

### D2. Development data extension
OPRA cbbo-1m and definitions for QQQ, 2020-01-02 → 2023-03-27.
- This span covers the 2020 crash and the 2022 bear market (repeated realized > implied).
- It is used **only for model-free screens of this family**. It never enters walk-forward folds
  or model training without a new ADR. It has touched no decision.
- The underlying is not needed for pricing (D1.a, D1.c). Nasdaq-venue QQQ daily bars are used
  only to choose which strikes to download, never in a label.

**Era reporting:**
- Results are reported per era. Expirations were verified from the listings downloaded in Step 0:
  - **Friday-only**, 2020-01 to about 2021-04;
  - **Mon/Wed/Fri**, about 2021-05 to 2022-11-13;
  - **daily**, from 2022-11-14.

  They are also reported per weekday.
- The decision uses pooled development data. A cell whose pooled result is driven by one era is
  flagged.

### D3. Screen outcomes
Statistic: mean net P&L per session (D1.b), with a session-block bootstrap (2,000 reps).
- **ADVANCE:** one-sided 95% lower bound at the **conservative** fill > 0, and the D4 guards are
  met.
- **KILL:** two-sided 95% upper bound at the **mid** fill < 0 (it loses even at generous fills).
- **AMBIGUOUS:** neither.

Family outcome:
- **ADVANCE** if any cell advances: at most 2 cells, chosen by the largest conservative lower
  bound, with ties broken by more sessions from 2023 on. → A Step-2 ADR.
- **KILL** if every cell is KILL. → The family is closed.
- **AMBIGUOUS** otherwise. → **More development data only.**
  - No filters, no models, no new cells, no holdout.
  - The same frozen cells are re-screened **once** after the development data grows by ≥ 250
    sessions. That re-screen is pre-registered, uses the same config hashes, and is disclosed as
    a second look.
  - Still AMBIGUOUS → the family is **PARKED**.

### D4. Report columns and guards
**Columns, per cell and per era / weekday row:**
- sessions and trades;
- mean net per session with CI, at the conservative, moderate (α = 0.5) and mid fills;
- median net per session; loss share; worst-5% mean; maximum consecutive losing sessions;
- maximum drawdown in $ and in units of maximum risk;
- realized loss frequency vs breakeven loss frequency (from the cell's own win and loss sizes on
  the same rows) vs X;
- mean net per $ of maximum risk;
- NO_TRADE share and §4.9 rejection rates.

**Descriptive rows only, never cells:** Friday→Monday and pre-holiday entries.

**Guards (a cell cannot ADVANCE if any applies):**
- fewer than 300 trades;
- fewer than 150 sessions from 2023 on, or fewer than 300 sessions in total.

### D5. Candidate cells (frozen; nothing added after any result)
| cell | tenor | structure | X | entry window (ET) | hold |
|---|---|---|---|---|---|
| S1 | 0DTE | put credit spread | 0.20 | 09:45–10:30 | intraday, flat 15:50 |
| S2 | 0DTE | put credit spread | 0.33 | 09:45–10:30 | intraday, flat 15:50 |
| S3 | 0DTE | iron condor | 0.20 per side | 09:45–10:30 | intraday, flat 15:50 |
| S4 | 1DTE | put credit spread | 0.20 | 13:00–14:30 | overnight, flat 15:50 on expiry day |
| S5 | 1DTE | put credit spread | 0.33 | 13:00–14:30 | overnight, flat 15:50 on expiry day |
| S6 | 1DTE | iron condor | 0.20 per side | 13:00–14:30 | overnight, flat 15:50 on expiry day |

**Rationale:**
- Tenor is the structural fork: steepest intraday theta vs the overnight gap premium.
- Puts are primary because downside skew makes them richer. The condor tests whether the thinner
  call side adds return per $ of maximum risk.
- X = 0.20 and 0.33 bracket the moneyness range, from "rare loss" to "more premium". For a
  narrow spread, credit ÷ width ≈ the implied probability of finishing in the money, so the
  screen tests whether the realized loss frequency stays below X.
- The last hour is excluded: penny premium and a fat tail leave no power to estimate the mean.

**Fallback, if the owner declines the D2 / expiry-day purchase:**
- S4–S6 become **2DTE entered on D, flat at 15:50 on D+1**, using data on disk.
- S1–S3 cannot be tested.
- This must be decided before the screen.

### D6. Budget
- Step 1: 1 screen + at most 1 pre-registered re-screen (D3).
- Step 2: declared in its own ADR.
- A per-family ledger (spent vs remaining) is kept in MILESTONES.
- One active family at a time.
- n_trials is shared across families on the same data window, so every trial raises the bar for
  all of them.

### D7. Holdout sequencing
The single holdout access (ADR-0011) is shared across strategy families. This family may request
it only if:
1. its screen is ADVANCE;
2. its frozen Step-2 configuration passes every development gate;
3. the request is recorded in an owner-approved ADR.

If two families qualify, the owner chooses one in an ADR before either sees the holdout; the
other confirms on forward data. An AMBIGUOUS or PARKED family never uses the holdout.

### D8. Forward data
- Collected data-only (no broker or order API) after the owner approves a monthly cost estimate.
- Reserved as confirmation data for any family. It is never development data.
- Walk-forward folds are unchanged: same pre-holdout sessions, with forward data and the holdout
  outside every fold.

## Step-0 results (2026-10-08; data only, no trial)
Source: `reports/research/m19t_data_coverage.md` (development sessions only; the holdout is
stored and cleaned, not read). No P&L or outcome has been computed. n_trials is still 38.

**Verified:**
- **Data spend:** $10.18, within the $20 cap.
- **Cleaning:** M4 rules unchanged. Development rejection rate is ≤ 0.06% a year. Conservation
  holds for every file.
- **Session counts:**
  - 0DTE: 1,163 sessions, 813 of them from 2023.
  - 1DTE: 1,166 sessions, 814 of them from 2023.
  - Every cell clears the D4 session guards.
- **D2 eras, from the listings:**
  - Friday-only: up to 2021-05-04;
  - Mon/Wed/Fri: 2021-05-05 to 2022-11-16;
  - daily (Tue/Thu continuous): from 2022-11-17.
- **D1.a:** the rule works with no spot price.
  - The download band never binds (AT_BAND_EDGE 0%; ≥ 9 stored strikes beyond the long leg at
    p5).
  - NO_QUALIFYING rate: 0.03–3.6%.
- **D1.c exit coverage:**
  - Usable 15:50 ask on both legs: 100% (0DTE), 99.2–99.7% (1DTE).
  - Quote gaps > 5 min (→ UNRESOLVED_DATA): 0–2.4% of picks.
- **D1.e purge:** 1 entry crosses into the holdout (2026-04-02 → 2026-04-06,
  `LABEL_CROSSES_BLOCK`). 1 exits on the ADR-0006 excluded session.

**Open questions for acceptance (owner decides; no definition has been changed):**
- **Q1, §4.9 gates per leg (D1.b).** Both legs pass in 74.6–98.1% of 0DTE picks and in 88.5–99.9%
  of 1DTE picks. The main failures:
  - the long call leg's `BID_BELOW_MIN` (6.6% of 0DTE call picks);
  - `SPREAD_TOO_WIDE` on either leg (≤ 3.7%).

  The ADR does not say whether the gates act **before** selection or **after** it:
  - **before:** the furthest pair whose legs pass is chosen;
  - **after:** the rule picks a pair, then a failed gate gives NO_TRADE with no fallback, like
    spec §5.

  It also does not say whether the $0.20 min-bid gate should apply to a leg that is bought.
- **Q2, missing long strike.** A pair whose long strike is not listed is treated as ineligible,
  and the rule moves on to other pairs. That is how the coverage check implemented it.
  - $1 grid holes lie within 3 strikes of the pair in 13–14% of Mon/Wed/Fri-era picks
    (0.5–2.7% in the other eras).
  - Confirm, or make it NO_TRADE.
  - Also confirm that OCC-adjusted strikes count like standard ones (M6 Q1).
- **Q3, OCC #53847 gap.** The Step-0 download requested whole-dollar symbols only, so:
  - **2023-12-28 has no 0DTE data;**
  - adjusted 1DTE exit legs are missing for 324 picked entries in 11 sessions (2023-12 to
    2024-02).

  Options: (a) a small supplemental download (to be priced first), or (b) log these as
  `UNRESOLVED_DATA` / NO_DATA and exclude them.
- **Q4, degraded days** (2021-07-07, 2021-10-26, 2022-09-19).
  - **Same as their neighbours:** full minute coverage, no gaps, no rejections, the same
    contract counts.
  - **Different:** 07-07 and 09-19 have the widest median spread in their 11-session windows.

  Options: keep them, keep them flagged with a with/without sensitivity row (descriptive), or
  exclude them by ADR.
- **Q5, ex-dividend dates (D1.d).** Not yet sourced or stored. They are needed before the Step-1
  code.

## Consequences
- New code: multi-leg positions, per-leg fills and gates, labels spanning two sessions, the
  purge rule, and the ex-dividend list. The engine is otherwise reused unchanged.
- The long-premium family stays closed (ADR-0012). Its code and tests remain.
- Any change to cells, rules, thresholds or budget needs a new ADR.
