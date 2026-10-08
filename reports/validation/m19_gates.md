# M19 full historical validation: gates 1-18 (spec §11)

Generated 2026-10-08 04:17 UTC, code 287846e89027, run `final_validation-b060967f6104`. Walk-forward evidence (7 folds, test blocks 2024-05-28 → 2026-02-27). **Final holdout not opened** (ADR-0011; final_test_access_log rows: 0). n_trials on the test window: **28** distinct registered configurations.

## Verdict: **FAIL** — 10 PASS, 4 FAIL, 4 NOT_EVALUABLE (counts as not passed).

Progression to M20 (paper mode) is blocked unless the owner records an ADR accepting the limitation (M19 criterion 3). This report states evidence and uncertainty only; it makes no claim of profitability (rule 12).

| # | gate | status | rule | key numbers |
|---|---|---|---|---|
| 1 | Data coverage | **PASS** | ≥ 98% of 1-min bars per session; ≥ 95% of sessions with a valid chain at ≥ 95% of timestamps | sessions=882; sessions_below_bar_coverage=0; min_bar_coverage_seen=0.9923; sessions_with_valid_chain=879; valid_chain_session_share=0.9966 |
| 2 | Data quality | **PASS** | 0 open CRITICAL DQ events; invalid-quote rate ≤ 2% (ATM ± 5) | open_critical_events=0; invalid_quote_rate=0.0002544; open CRITICAL now 0 |
| 3 | PIT integrity | **PASS** | 100% of feature rows available_at ≤ T; 20 random timestamps replay exactly | 1,346,688 pre-holdout rows, 0 violations; 20/20 replays identical |
| 4 | Leakage tests | **PASS** | T-LEAK suite passes; planted-future canary; shuffled-label AUC 0.50 ± 0.02 (ADR-0008) | canary statistic 0.4957-0.5059 (10 targets); import contract kept |
| 5 | Baseline | **PASS** | Model 0 OOS Brier, log loss, calibration per fold | 70 fold x target rows, 10 pooled targets |
| 6 | Beats baseline | **FAIL** | BSS vs Model 0 CI lower bound > 0, pooled OOS; better in >= 70% of folds | C_call BSS +0.0066 [-0.0008, +0.0138], 5/7 folds; C_put BSS +0.0046 [-0.0020, +0.0116], 5/7 folds |
| 7 | PIT option selection | **PASS** | T-SEL suite passes; 100% of journal selections reproduce | 55,888/55,888 journal candidates reproduced |
| 8 | Bid/ask execution | **PASS** | T-FILL and T-BT suites pass | test_fills_accounting.py 14, test_backtest_engine.py 17, test_cursor.py 4 |
| 9 | Costs | **PASS** | every reported P&L net of §4.8 costs (type) | NetPnl type; report helpers accept only NetPnl |
| 10 | Walk-forward positive | **NOT_EVALUABLE** | pooled OOS expectancy (moderate, net) CI lower bound > 0; positive in >= 60% of folds | 0 trades under the decision configuration (ADR-0010) |
| 11 | Execution robustness | **NOT_EVALUABLE** | conservative expectancy > 0; sign independent of alpha in [0.25, 0.75] | no trades: conservative expectancy and alpha sign not defined |
| 12 | Calibration | **FAIL** | ECE ≤ 0.03; slope in [0.8, 1.2]; bin rule (ADR-0009) | C_call ECE 0.0216, slope 0.348, bins failed 4/10; C_put ECE 0.0155, slope 0.857, bins failed 1/10 |
| 13 | Regime behaviour | **NOT_EVALUABLE** | every traded cell with >= 100 trades has expectancy CI upper bound > 0 | no traded regime cells |
| 14 | NO_TRADE validated | **NOT_EVALUABLE** | counterfactual NO_TRADE expectancy < traded expectancy, CI on the difference excluding 0 | 0 traded timestamps; NO_TRADE counterfactual 27,827 trades (M15) |
| 15 | Sample size | **FAIL** | >= 300 OOS trades and >= 150 sessions with a trade | 0 trades, 0 sessions |
| 16 | No overfitting | **FAIL** | PBO <= 0.20; deflated Sharpe probability >= 0.95 with the logged n_trials | PBO C_call 0.062, C_put 0.410; DSR not evaluable (no trade returns); n_trials 28 |
| 17 | Reproducibility | **PASS** | re-running a logged run reproduces predictions to 1e-9 and identical trades | 200/200 predictions replayed (fresh seed), 3,400 checks; 0 trades to compare |
| 18 | Drift monitoring | **PASS** | synthetic drift raises the right alert within 10 sessions (replay) | calibration: 20/20 detected, max delay 10, 0 false-alarm replays; feature_shift: 20/20 detected, max delay 10, 1 false-alarm replays |

## Details

### Gate 1: Data coverage — PASS

- M4 evaluation: pass
- From M4 (`reports/dq/gates.md`, full downloaded history).

### Gate 2: Data quality — PASS

- M4 evaluation: pass
- open CRITICAL events now = 0 (current dataset versions): pass

### Gate 3: PIT integrity — PASS

- no violations: pass
- replays identical: pass

### Gate 4: Leakage tests — PASS

- T-LEAK test files pass: pass
- import contract (lint-imports): pass
- shuffled-label canary: pass

### Gate 5: Baseline — PASS

- all folds reported: pass
- all targets pooled: pass

### Gate 6: Beats baseline — FAIL

- C_call CI lower > 0: fail
- C_call folds better >= 70%: pass
- C_put CI lower > 0: fail
- C_put folds better >= 70%: pass
- Model family `gbm_m2` (decision.model_family), decision targets C_call / C_put, reference = conditional Model 0.

### Gate 7: PIT option selection — PASS

- T-SEL tests pass: pass
- all journal candidates reproduce: pass

### Gate 8: Bid/ask execution — PASS

- T-FILL / T-BT tests pass: pass

### Gate 9: Costs — PASS

- gate-9 tests pass (incl. mypy check): pass

### Gate 10: Walk-forward positive — NOT_EVALUABLE

- pooled CI lower > 0: not evaluable
- positive in >= 60% of folds: not evaluable

### Gate 11: Execution robustness — NOT_EVALUABLE

- conservative point estimate > 0: not evaluable
- sign stable for alpha in [0.25, 0.75]: not evaluable

### Gate 12: Calibration — FAIL

- C_call gate 12: fail
- C_put gate 12: fail

### Gate 13: Regime behaviour — NOT_EVALUABLE

- traded regime cells: not evaluable

### Gate 14: NO_TRADE validated — NOT_EVALUABLE

- traded - counterfactual CI lower > 0: not evaluable

### Gate 15: Sample size — FAIL

- >= 300 OOS trades: fail
- >= 150 OOS sessions with a trade: fail

### Gate 16: No overfitting — FAIL

- PBO <= 0.2: fail
- DSR probability >= 0.95: not evaluable
- C_call: PBO 0.062 over 9 configurations x 440 test sessions (log-loss improvement vs Model 0)
- C_put: PBO 0.410 over 9 configurations x 440 test sessions (log-loss improvement vs Model 0)
- DSR needs strategy returns; there are none under the decision configuration, so the DSR check is NOT_EVALUABLE.

### Gate 17: Reproducibility — PASS

- journal replay sample reproduced: pass
- all journal selections reproduce: pass
- serialization / replay tests pass: pass

### Gate 18: Drift monitoring — PASS

- calibration: pass
- feature_shift: pass

