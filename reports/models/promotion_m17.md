# M17 promotion review (spec Phase 1P)

Generated 2026-10-08 02:58 UTC, code cc297f8b81df, run `promotion_review-d7ae9c089efa`, reviewer **Ahmed**. Candidates: `gbm_m2` fold 7 models of `walk_forward-8adbdf4112a5`. Evidence runs: model_run `walk_forward-8adbdf4112a5`, canary_run `canary-a633f3966f65`, calibration_run `calibration-e19b6c392dd0`, decision_run `decision-7cd0dc2805d1`.

Gates: Phase 1P mapped to spec §11 numbers (M17 Q1). NOT_EVALUABLE counts as not passed. Promotion is never automatic: an eligible candidate needs a separate human action (`uv run python -m qqq1dte.models.promotion --review-run <run> --target <t> --approved-by <name>`), and the database refuses PRODUCTION without a PROMOTED record (migration 0003).

## C_call

Candidate `m2-walk_forward-8adbdf4112a5-f7-C_call`; current production model: none. Decision recorded: **KEEP_CURRENT**.

| gate | status | detail |
|---|---|---|
| oos_performance | FAIL | BSS vs Model 0 CI (-0.0007934811029221099, 0.013767426198146507) not above 0 |
| no_degradation | PASS | no current production model |
| calibration | FAIL | gate 12: fail |
| regimes | NOT_EVALUABLE | gate 13: no evidence |
| after_costs | NOT_EVALUABLE | no traded expectancy |
| sample_size | FAIL | 0 trades, 0 sessions |
| leakage | PASS | gate 4 canary: pass |
| walk_forward_stability | NOT_EVALUABLE | fold shares missing |

Evidence: bss_vs_m0 = 0.0066291967947404995, bss_vs_m0_ci = [-0.0007934811029221099, 0.013767426198146507], folds_better = 5/7, gate12_pass = False, ece = 0.02157294128088927, slope = 0.3482791778802287, canary_statistic = 0.49965552310270855, n_trades = 0.

## C_put

Candidate `m2-walk_forward-8adbdf4112a5-f7-C_put`; current production model: none. Decision recorded: **KEEP_CURRENT**.

| gate | status | detail |
|---|---|---|
| oos_performance | FAIL | BSS vs Model 0 CI (-0.0020268878697379694, 0.011612154445751737) not above 0 |
| no_degradation | PASS | no current production model |
| calibration | FAIL | gate 12: fail |
| regimes | NOT_EVALUABLE | gate 13: no evidence |
| after_costs | NOT_EVALUABLE | no traded expectancy |
| sample_size | FAIL | 0 trades, 0 sessions |
| leakage | PASS | gate 4 canary: pass |
| walk_forward_stability | NOT_EVALUABLE | fold shares missing |

Evidence: bss_vs_m0 = 0.004591930642202535, bss_vs_m0_ci = [-0.0020268878697379694, 0.011612154445751737], folds_better = 5/7, gate12_pass = False, ece = 0.015478560638036671, slope = 0.8568873144074894, canary_statistic = 0.49840706166386506, n_trades = 0.
