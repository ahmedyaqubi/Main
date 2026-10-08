# M19R closing report: no validated edge for the Phase 1 trade definition

Status: **closed 2026-10-08, no validated edge found.** M19's verdict stays FAIL; M20 stays blocked.
The final holdout (sessions after 2026-04-02) was never read and stays locked (ADR-0011).

This report covers what was tested and what the evidence supports. It does not claim profitability
or the lack of it in general. It says that *this* trade definition, with *these* features and data,
at *these* costs, shows no edge that survives the Phase 1 gates.

## 1. What was tested

- **Trade definition (PHASE_1_SPEC §3, §5, §6):**
  - Buy the frozen-rule near-the-money D+1 QQQ call or put at T + 5 s, entering at the ask.
  - Exit at +30% (WIN) or −20% (LOSS), triggered on the bid, or at T + 90 min (TIME_EXIT).
  - Round-trip commissions and fees are $1.40 per contract.
  - 64 prediction timestamps per session, 09:45–15:00 ET.
- **Validation:**
  - walk-forward, 7 folds;
  - test blocks 2024-05-28 → 2026-02-27, calibration on separate 2-month blocks, 1-session embargo;
  - session-block bootstrap CIs with 2,000 reps;
  - every run registered (n_trials counts distinct configurations: more than 35 at closing).
- **Models:**
  - Model 0 (conditional base rates);
  - Model 1 (L2 logistic);
  - Model 2 (LightGBM);
  - M13 calibration;
  - §4.1 decision rule with ADR-0010 calibration support.

## 2. Evidence chain

| step | run / report | finding |
|---|---|---|
| M19 gates | `reports/validation/m19_gates.md` | FAIL: gates 6, 12, 15 and 16 fail; 10, 11, 13 and 14 are not evaluable (no trades from the §4.1 rule) |
| D1 move size (B) | `diagnostic-28e2588a772d`, `m19r_diagnostics.md` | B skill is almost entirely what option prices already imply. Model 2 beats an implied-move-only benchmark only for B_up 0.25% (+0.0195 [+0.0015, +0.0352], 4/7 folds) |
| D2 direction lift | same | C_call top 1% win rate 0.288; C_put top 1% 0.374 [0.319, 0.432]; breakeven ≈ 0.412 |
| D3 ablation | same | small, real direction information (price path, momentum, cross-asset) for the A targets; none of the C_put feature groups clears 0 |
| E1–E4 | `experiment-d878fa4dade5`, `-204b18b73d79`, `-77f47aa007f9`, `-e4ace04b0c76`; `m19r_experiments.md` | E1 C_call passes gate 6 (BSS +0.0091 [+0.0032, +0.0154], 5/7) but fails gate 12; the top buckets reach ≈ 0.30 vs 0.412. No configuration passes gates 6 and 12 together. E4 repeats E2's C_put model (disclosed) |
| E5–E6 | `experiment-a4a5672324a1`, `-64105fcb6609`; `m19r_tail_rule.md` | C_put score tail. q 0.98: 1,201 trades, win rate 0.381 [0.354, 0.409], mean net +$0.57 [−7.25, +8.43]. q 0.99: 828 trades, 0.396 [0.363, 0.430], +$2.27 [−7.71, +11.99]. Median −$35.40. No edge |

## 3. Why the trade definition is hard to beat (descriptive, pre-holdout)

Source: `scripts/m19r_label_stats.py`. This is a descriptive pass over the stored L2 option labels: 95,674 labelled trades over 756 pre-holdout sessions. No model is involved.

| side | WIN | LOSS | TIME_EXIT profit / loss | BREAKEVEN | mean net $ / trade | median entry $ |
|---|---|---|---|---|---|---|
| call | 25.3% (+$73) | 47.9% (−$52) | 12.9% (+$26) / 10.6% (−$21) | 3.3% | −5.27 | 2.01 |
| put | 27.9% (+$77) | 51.6% (−$50) | 7.2% (+$25) / 10.9% (−$21) | 2.4% | −5.05 | 1.96 |

- **Friction is small but not negligible.** The median entry spread is $0.02, which is 0.82% of a premium of about $1.95. So the round trip (pay half the spread on each side, plus commissions and fees) is about $3.40 per trade. That is roughly two thirds of the −$5 unconditional mean, and it moves the breakeven win rate by about 2 points.
- **The main obstacle is the bracket's geometry.** Within 90 minutes, a near-the-money 1DTE option loses 20% (about 1.3× the time it gains 30%). The −20% stop is closer, measured in underlying-move terms, and time decay pushes toward it. The unconditional win rate is 25–28% against a breakeven of about 41%. A model must therefore lift the win rate by about 13–16 points in the tail it trades. The best observed lift was about 10–12 points (C_put top 1%, with a CI reaching breakeven).
- **Option prices already carry the move-size information (D1).** That limits what any feature set built on the same quotes can add.

## 4. Limitations

- **Data:** features are built from 1-minute NBBO snapshots only. Historical OPRA open interest is on disk for 5 sessions, so no OI or flow features were possible. Trade prints and volume by contract were not used.
- **Overlapping labels:**
  - each label spans 90 minutes, so timestamps 5 minutes apart overlap heavily;
  - the session-block bootstrap handles this for mean-based statistics;
  - the Wilson CIs on tail win rates treat trades as independent and are too narrow.
- **Single trade definition:** one strike rule, one bracket and one horizon. The result says nothing about other payoffs (see §5).
- **Multiple testing:** more than 35 registered configurations. Any future marginal positive must survive the deflated Sharpe ratio (DSR) and probability of backtest overfitting (PBO) adjustments for the full count.

## 5. What remains open (not started; each needs owner approval)

1. **New information (data):**
   - historical OI, volume and trade prints;
   - verify vendor coverage and cost first (hard rule 9);
   - a new, pre-declared trial budget.
2. **Different trade definition (spec change):**
   - only via a new ADR that declares a small set of definitions and a trial budget before any run;
   - the same gates;
   - the holdout still locked until a single configuration is frozen.
3. **Different strategy class** (for example, selling premium to capture the volatility risk premium suggested by D1): a separate project with its own spec and tail-risk controls.

None of these were run in M19R.
