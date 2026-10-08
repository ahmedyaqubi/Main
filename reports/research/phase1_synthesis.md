# Phase 1 synthesis: QQQ 0–1DTE options, M1–M19T

Drafted 2026-10-08. Sources: `docs/MILESTONES.md`, ADR-0001 to ADR-0013, and the reports cited
below. **This is a summary of evidence, not a claim about future performance. It is not a trading
recommendation.**

## 1. Bottom line
- **Data window:** about 6 years of 1-minute QQQ and OPRA data (development sessions
  2020-01-02 → 2026-04-02; option models from 2023-03-28).
- **What was tested:** 4 strategy families, under pre-declared rules and
  chronological validation.
- **Result:** none of them shows a validated, calibrated, cost-adjusted edge.
  - Every family failed or was killed on development data.
  - None earned access to the final holdout, which is still unopened.
- **The common pattern:** QQQ 0–1DTE option prices already reflect the size of likely moves.
  - The direction information we could extract is small.
  - Bid–ask spreads and commissions turn any thin edge negative.
  - This is true for buyers of premium (time decay plus costs) and for sellers (tail losses
    plus costs).
- **Trials:** 39 registered configurations on the shared data window. Every one counts towards
  multiple-testing corrections, including failed and abandoned runs.

## 2. What was tested

| family | milestone | idea | trials (cumulative) | decisive evidence | verdict |
|---|---|---|---|---|---|
| Phase 1 models | M7–M19 | Calibrated models (baseline, logistic, LightGBM) predict whether a near-the-money 1DTE call or put hits +30% before −20% within 90 min; trade only above an edge margin | 28 | Gate 6 (beats baseline): C_call BSS +0.0066 [−0.0008, +0.0138], C_put +0.0046 [−0.0020, +0.0116]; gate 12 calibration fails (C_call slope 0.35); 0 trades under the calibrated rule; PBO C_put 0.41 | **FAIL** (gates 6, 12, 15, 16) |
| Research iteration | M19R | Move size versus implied volatility; direction features; tail-score trade rules | 35 | Move-size skill is almost entirely what option prices already imply (Model 2 vs implied-move benchmark ≈ 0). Best direction bucket win rate 0.40–0.42 vs break-even 0.412. Tail rules: mean net +$0.57 [−7.25, +8.43] and +$2.27 [−7.71, +11.99] per trade | **No validated edge** |
| Long-premium trade definitions | M19S (ADR-0012) | Change the trade shape (time exits, underlying stops, deeper strikes, longer holds) so a direction signal could pay | 38 | Model accuracy Â ≤ 0.557 against required accuracy a* ≥ 0.57 in every cell; mean net −$1.47 to −$16.15 per trade | **KILL**, line closed |
| Defined-risk short premium | M19T (ADR-0013) | Sell $1 put spreads and iron condors (0DTE / 1DTE), model-free, held to 15:50 on the expiry day | 39 | All 6 cells KILL: mean net per session −$14 to −$36 (conservative fill); upper bound at the mid fill < 0 in every cell | **KILL**, family closed |

## 3. Why it fails: the common mechanics
- **Prices already carry the information.**
  - M19R D1: a benchmark built only from the option-implied move matches the full model for
    move size.
  - For direction, the information is real but small (M19R D3): about +0.002–0.003 Brier on
    the underlying 90-minute move, and none detectable for C_put.
- **Long premium needs accuracy we don't have** (M19S).
  - Theta and costs set the required win rate at about 0.57–0.65, depending on trade shape.
  - The best accuracy at any horizon and coverage was 0.557.
  - The plain trade won 25–28% of the time against a break-even of about 41%, for a mean net
    of about −$5 per trade.
- **Short premium loses more often than its credit allows** (M19T).
  - Realized loss share is well above the break-even loss share on the same trades. For
    example, S1 loses 0.33 of the time against a break-even of 0.19, and S4 0.29 against 0.14.
  - The credit collected does not pay for the tail.
  - Even at the mid price, every cell is negative after $2.80–$5.60 of round-trip costs; before
    costs S1 is roughly break-even.
- **Friction decides close calls.** Median entry spreads are about $0.02 near the money. Still,
  the gap between conservative fills (ask/bid) and mid fills is $12–$29 per session in the short
  structures: larger than any gross edge we measured.

## 4. How much to trust these results
**Safeguards that held throughout:**
- Point-in-time features, enforced in code (`available_at <= T`; 0 violations in 1.35M rows).
- Chronological walk-forward only, with an embargo.
- Every evaluation registered before it ran.
- Reruns from committed code reproduced the results exactly.
- Leakage reviews, with findings fixed before registered runs.
- Independent hand recomputation of sampled trades: M19T 18/18 match.
- **The final holdout (2026-04-03 → 2026-10-02) has never been read** (ADR-0011).

**Limits (each could matter):**
- **1-minute consolidated quotes.** Intra-minute moves and fills are not seen. Real fills
  between mid and the conservative price could be better than the conservative case, but M19T
  is negative even at the mid.
- **Fill and cost model.** It assumes $0.65 commission plus $0.05 fees per contract per side
  and a 5-second latency. A cheaper broker narrows the costs but does not flip any M19T cell:
  each is negative at the mid even before fills are worsened.
- **Data scope.**
  - No historical open interest or trade prints; OI was on disk for only 5 sessions.
  - No tick data beyond one sample week.
  - QQQ only; 0–2 day expiries only.
- **Period.** 2020–2026 covers the 2020 crash, the 2022 bear market and the 2023–2025 rally.
  Different regimes could behave differently. Per-era rows were all negative in M19T.
- **Multiple testing.** With 39 trials, any future marginal positive on this window would need
  deflation (deflated Sharpe, PBO) before it means anything.

**What was not tested:**
- longer tenors (weekly to 30-day), where the variance premium is usually reported to be
  larger relative to costs (literature, not verified here);
- other underlyings (SPX/XSP, single stocks);
- execution alpha (working orders inside the spread);
- signals that need data we don't hold (order flow, open interest history).

## 5. Where things stand
- **Code:**
  - **Ingestion and data quality:** pipeline M3–M4 plus the M19T stores.
  - **Point-in-time features and labels:** f2/f3; L2; study1b; study1c.
  - **Walk-forward and registry:** the walk-forward, the run registry and the holdout guard.
  - **Models, calibration and decisions:** baseline, logistic and LightGBM models; calibration;
    regimes; NO_TRADE logic.
  - **Journal and monitoring:** journal, drift monitoring, and the credit-spread engine.
  - **Status:** all tested (449 tests), CI green.
- **Data spend recorded:** about $26.70 (M2/M4 $13.27, M5 $3.17, M19T $10.26). All pay-per-use;
  nothing recurring (`docs/reminders/data-costs-and-cancellation.md`).
- **Not started, on purpose:**
  - forward data collection (ADR-0013 D8);
  - M20–M22 (paper trading, dashboard), blocked by the M19 FAIL;
  - no broker or order code exists anywhere (hard rule 1).
- **Still available:** the locked holdout, for a future configuration that passes every
  development gate.

## 6. Recommendation
1. **Close Phase 1 here.** No new strategy family on this data window: the evidence is
   consistent, and each extra idea tested on it raises the false-positive risk.
2. **If research continues, make it a new project with its own ADR:**
   - longer-dated options (weekly to 30-day), possibly on SPX/XSP (cash-settled, European:
     no early exercise or ex-dividend handling);
   - a fixed trial budget declared before any run;
   - a data-cost quote and a Step-0 coverage check before purchase;
   - the same model-free screen first, then filters and models only after an ADVANCE;
   - fresh or forward data where possible.
3. **Don't start forward collection or paid live data** until a family advances.

## References
- **Validation:** `reports/validation/m19_gates.md` (M19, run `final_validation-b060967f6104`).
- **Research iteration (M19R):** `reports/research/m19r_diagnostics.md`, `m19r_experiments.md`,
  `m19r_tail_rule.md`, `m19r_closing.md`.
- **Trade-definition study (M19S):** `reports/research/m19s_step1.md` (run `screen-667eb0490979`).
- **Short premium (M19T):** `reports/research/m19t_price_quote.md`, `m19t_data_coverage.md`,
  `m19t_step1_screen.md` (run `screen_1c-9c607f3c96e7`).
- **Spec and decisions:**
  - spec: `docs/PHASE_1_SPEC.md`;
  - holdout: ADR-0011;
  - studies: ADR-0012 and ADR-0013.
