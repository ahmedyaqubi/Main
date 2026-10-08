# M16 prediction / trade journal (spec Phase 1O)

Generated 2026-10-08 02:31 UTC, code 1348fb86b8ba, run `journal-4a7a186908c7` (decision configuration hash 1eb97f258280, same as the M15 decision run). Test blocks 2024-05-28 → 2026-02-27, 440 sessions; final holdout not opened.

## Rows journaled

| table | rows |
|---|---|
| predictions | 27,944 |
| prediction_scores | 55,888 |
| trade_candidates | 55,888 |
| simulated_trades | 0 |

| decision | predictions |
|---|---|
| NO_TRADE | 27,944 |

Underlying price older than 60 s at T: 0 predictions (the quote time is used as is and is reproducible from the cleaned NBBO).

## Replay (T-REP-02)

Seeded sample of 200 predictions (seed 20261009); each re-derives raw scores and calibrated probabilities (|diff| ≤ 1e-9), ADR-0010 support, entry fills, EV and margins (≤ 1e-6), the rule decision and its reasons from the stored references only (config hash, feature snapshot, model / calibrator artifacts by sha256, cleaned market data).

- Checks run: 3,400
- Predictions reproduced: **200 / 200**

## Phase 1O field coverage

| Phase 1O field | journaled as |
|---|---|
| prediction_id | predictions.prediction_id |
| timestamp | predictions.prediction_ts |
| underlying price | predictions.underlying_price |
| option chain snapshot/reference | predictions.chain_snapshot_ref |
| feature values | predictions.feature_snapshot_ref (immutable f2 snapshot row) |
| feature version | predictions.feature_version |
| regime | predictions.regime (R1 axes + cell) |
| model version | prediction_scores.model_version_id (per target) |
| raw probability | prediction_scores.raw_score (uncalibrated score) |
| calibrated probability | prediction_scores.calibrated_prob |
| calibration version | prediction_scores.calibration_version_id |
| candidate contracts | trade_candidates (chosen contract per side, gates) |
| selected contract | trade_candidates.selected / occ_symbol |
| bid/ask | trade_candidates.bid / ask |
| assumed entry | prediction_scores.entry_price; simulated_trades.entry_price |
| target | simulated_trades.target_price (entered trades) |
| stop | simulated_trades.stop_price (entered trades) |
| expected value | prediction_scores.expected_value; predictions.expected_value |
| actual MFE | simulated_trades.mfe |
| actual MAE | simulated_trades.mae |
| outcome | simulated_trades.outcome |
| P&L | simulated_trades.gross_pnl / net_pnl |
| costs | simulated_trades.commissions / fees / spread_cost |
| reason for decision | predictions.decision_reasons; prediction_scores.side_reason |
| CALL/PUT/NO TRADE | predictions.decision |

Journal tables are append-only (triggers) and the `qqq1dte_journal_writer` role holds INSERT / SELECT only (migration 0002; `tests/test_journal_schema.py`).
