# ADR-0010 — Trade only where the calibration block supports the score

- Status: **PROPOSED** (drafted 2026-10-07 at the owner's request; not in force until the owner accepts it)
- Date: 2026-10-07
- Milestone: M15 (decision engine); affects every later evaluation that uses `decide`
- Amends: PHASE_1_SPEC §4.1 (adds one per-side condition); no other definition changes

## Context
M15 (run `decision-8a196b570c04`, model family `gbm_m2`, M13 calibrators) produced 175 CALL and 2 PUT
rule decisions out of 27,944 test-block timestamps (46 trades after position limits). In the M15 summary
I said that most CALL decisions came from isotonic step values. **That was wrong.** Traced per decision:

| fold | C_call calibration method | CALL decisions | trades |
|---|---|---|---|
| 1 | isotonic | 47 | 12 |
| 5 | temperature | 40 | 12 |
| 6 | none (raw score) | 88 | 22 |

The common factor is support, not the method. For every one of the 175 CALL decisions, the raw model
score lies in the extreme upper tail of that fold's calibration block:

| fold | calibration rows | calibration rows with raw score ≥ the decision's raw score: min / median / max |
|---|---|---|
| 1 | 2,560 | 0 / 5 / 18 |
| 5 | 2,560 | 12 / 50 / 79 |
| 6 | 2,588 | 0 / 11 / 26 |

So the calibrated probability that cleared the breakeven margin is estimated from at most 79, and typically
5–50, binary outcomes, or is extrapolated beyond any calibration data (0 rows). Isotonic produces visible steps
(P = 0.9999 at 20 timestamps), but temperature scaling and the raw score extrapolate the same thin tail more
smoothly. Gate 12 can only check bins with n ≥ 200, so these probabilities are outside anything the
calibration evidence covers.

## Options
- **A (recommended): minimum calibration support per side.** A side qualifies only if its fold's
  calibration block contains at least `decision.min_calibration_support` rows whose raw score is ≥ the
  current raw score (one-sided tail support). Otherwise NO_TRADE with reason `INSUFFICIENT_CALIBRATION_SUPPORT`.
  Proposed value **200**, the same n at which gate 12 checks a bin. The support count is stored with each
  decision (the journal's `support_n` field, M16). It applies to every calibration method.
- **B: drop isotonic from the calibration candidates.** It removes the step artifacts but addresses only
  47 of the 175 decisions; folds 5 and 6 extrapolate the same thin tail.
- **C: no change.** Keep the M15 rule and record the limitation for M19.

## Disclosure
This ADR is drafted **after** the M15 results were seen. Under option A with 200 (or 100), all 175 CALL
and 2 PUT decisions become NO_TRADE: **0 trades**. With a threshold of 50, 23 CALL decisions would remain.
The threshold is not tuned to a desired trade count. It is set at the gate-12 bin size so that the engine
only acts on probabilities whose calibration could in principle be checked. The 46 M15 trades
(mean net +$12.0, median −$5.9, CI including 0) stay recorded in run `decision-8a196b570c04`.

## Decision (proposed)
Option A with `decision.min_calibration_support = 200`.

## Consequences (if accepted)
- `SideInput` carries the raw score's calibration support. `decide` adds the support check after the
  selection checks and before the margin check. Tests cover the boundary (199 vs 200) and the reason code.
- M15 is rerun as a new configuration. Expected: 100% NO_TRADE on the test blocks, so gates 13–15 are not
  evaluable. The gate-14 counterfactual at NO_TRADE timestamps is still reported.
- The binding constraint on Phase 1 is now explicit: the models do not produce well-supported
  probabilities above breakeven. Better models or features would be needed, not looser rules.
- Changing the threshold again needs a new ADR, and each value tried counts as a trial (spec §10).
