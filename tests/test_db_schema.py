"""Schema v1.0 migrations and constraints (PostgreSQL; skipped without TEST_DATABASE_URL)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from conftest import alembic_cycle, table_names
from qqq1dte.ingestion.catalog import DatasetConflictError, DatasetVersion, record_dataset

EXPECTED_TABLES = {
    "dataset_versions",
    "data_quality_events",
    "model_versions",
    "model_promotions",
    "calibration_results",
    "validation_runs",
    "final_test_access_log",
    "regime_labels",
    "predictions",
    "trade_candidates",
    "simulated_trades",
}
T = datetime(2025, 3, 10, 14, 0, tzinfo=UTC)


def test_upgrade_downgrade_upgrade(test_db_url: str, migrated_engine: Engine) -> None:
    assert table_names(migrated_engine) >= EXPECTED_TABLES
    alembic_cycle(test_db_url, "downgrade")
    assert table_names(migrated_engine) & EXPECTED_TABLES == set()
    alembic_cycle(test_db_url, "upgrade")
    assert table_names(migrated_engine) >= EXPECTED_TABLES


# helpers -----------------------------------------------------------------------------------
def _parents(c: Connection, calibrated: bool = False) -> None:
    c.execute(
        text("""
        INSERT INTO dataset_versions (dataset_id, kind, source, coverage_start, coverage_end,
          row_count, storage_uri, code_commit, config_hash)
        VALUES ('ds1', 'raw_options_data', 'databento', '2025-03-10', '2025-03-14', 10,
          'data/raw', 'abc', 'h')""")
    )
    c.execute(
        text("""
        INSERT INTO validation_runs (run_id, config_hash, config_json, run_kind, data_window_start,
          data_window_end, dataset_id, code_commit, folds, status)
        VALUES ('run1', 'h', '{}', 'backtest', '2025-03-10', '2025-03-14', 'ds1', 'abc', '[]',
          'REGISTERED')""")
    )
    c.execute(
        text("""
        INSERT INTO model_versions (model_version_id, model_family, target_label, train_start,
          train_end, dataset_id, feature_version, label_version, hyperparameters, artifact_uri,
          artifact_sha256, code_commit, config_hash, status)
        VALUES ('m1', 'baseline', 'C_call', '2024-01-01', '2024-12-31', 'ds1', 'f1', 'l1', '{}',
          'x', 'y', 'abc', 'h', 'CANDIDATE')""")
    )
    if calibrated:
        c.execute(
            text("""
            INSERT INTO calibration_results (calibration_version_id, model_version_id, method,
              calib_start, calib_end, eval_start, eval_end, n_calib, n_eval, reliability_bins,
              artifact_uri)
            VALUES ('cal1', 'm1', 'isotonic', '2025-01-01', '2025-01-31', '2025-02-01',
              '2025-02-28', 100, 100, '[]', 'x')""")
        )


def _prediction(
    c: Connection,
    *,
    feature_at: datetime = T,
    decision: str = "NO_TRADE",
    calibration: str | None = None,
) -> uuid.UUID:
    pid = uuid.uuid4()
    c.execute(
        text("""
        INSERT INTO predictions (prediction_id, run_id, prediction_ts, mode, underlying_price,
          feature_snapshot_ref, feature_version, max_feature_available_at, regime,
          model_version_id, calibration_version_id, raw_scores, decision, decision_reasons,
          config_hash, code_commit)
        VALUES (:pid, 'run1', :ts, 'BACKTEST', 483.4, 'snap', 'f1', :fa, '{}', 'm1', :cal,
          '{"C_call": 0.5}', :dec, ARRAY['test'], 'h', 'abc')"""),
        {"pid": pid, "ts": T, "fa": feature_at, "cal": calibration, "dec": decision},
    )
    return pid


# constraints ---------------------------------------------------------------------------------
def test_prediction_with_future_feature_rejected(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as c:
        _parents(c)
        _prediction(c, feature_at=T)  # equal is allowed
    with (
        pytest.raises(IntegrityError, match="features_not_after_prediction"),
        migrated_engine.begin() as c,
    ):
        _prediction(c, feature_at=T + timedelta(microseconds=1))


def test_trade_decision_requires_calibration(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as c:
        _parents(c, calibrated=True)
        _prediction(c, decision="CALL", calibration="cal1")
    with (
        pytest.raises(IntegrityError, match="trade_requires_calibration"),
        migrated_engine.begin() as c,
    ):
        _prediction(c, decision="PUT", calibration=None)


@pytest.mark.parametrize(
    "stmt",
    [
        "UPDATE predictions SET decision = 'NO_TRADE'",
        "DELETE FROM predictions",
        "TRUNCATE predictions CASCADE",
    ],
)
def test_journal_is_append_only(migrated_engine: Engine, stmt: str) -> None:
    with migrated_engine.begin() as c:
        _parents(c)
        _prediction(c)
    with pytest.raises(DBAPIError, match="append-only"), migrated_engine.begin() as c:
        c.execute(text(stmt))


def _candidate(c: Connection, pid: uuid.UUID, quote_ts: datetime, latency_s: int = 5) -> None:
    c.execute(
        text("""
        INSERT INTO trade_candidates (candidate_id, prediction_id, side, occ_symbol, quote_ts,
          latency_s, passed_gates, selection_rule_version, selected)
        VALUES (:cid, :pid, 'CALL', 'QQQ   250311C00483000', :q, :lat, true, '1', true)"""),
        {"cid": uuid.uuid4(), "pid": pid, "q": quote_ts, "lat": latency_s},
    )


def test_candidate_quote_after_entry_time_rejected(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as c:
        _parents(c)
        pid = _prediction(c)
        _candidate(c, pid, T + timedelta(seconds=5))  # exactly T_e is allowed
    with pytest.raises(DBAPIError, match="look-ahead"), migrated_engine.begin() as c:
        _candidate(c, pid, T + timedelta(seconds=5, microseconds=1))


def test_regime_label_available_after_ts_rejected(migrated_engine: Engine) -> None:
    with pytest.raises(IntegrityError), migrated_engine.begin() as c:
        c.execute(
            text("""INSERT INTO regime_labels (ts, axis, value, available_at, regime_version)
                    VALUES (:ts, 'VOL', 'LOW', :av, 'r1')"""),
            {"ts": T, "av": T + timedelta(seconds=1)},
        )


def test_one_production_model_per_target(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as c:
        _parents(c)
        c.execute(
            text("UPDATE model_versions SET status = 'PRODUCTION' WHERE model_version_id='m1'")
        )
    with pytest.raises(IntegrityError, match="one_production"), migrated_engine.begin() as c:
        c.execute(
            text("""
            INSERT INTO model_versions (model_version_id, model_family, target_label, train_start,
              train_end, dataset_id, feature_version, label_version, hyperparameters,
              artifact_uri, artifact_sha256, code_commit, config_hash, status)
            VALUES ('m2', 'logreg', 'C_call', '2024-01-01', '2024-12-31', 'ds1', 'f1', 'l1',
              '{}', 'x', 'y', 'abc', 'h', 'PRODUCTION')""")
        )


def test_calibration_window_must_precede_eval(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as c:
        _parents(c)
    with pytest.raises(IntegrityError), migrated_engine.begin() as c:
        c.execute(
            text("""
            INSERT INTO calibration_results (calibration_version_id, model_version_id, method,
              calib_start, calib_end, eval_start, eval_end, n_calib, n_eval, reliability_bins,
              artifact_uri)
            VALUES ('bad', 'm1', 'platt', '2025-01-01', '2025-02-01', '2025-02-01',
              '2025-02-28', 1, 1, '[]', 'x')""")
        )


# catalog -------------------------------------------------------------------------------------
def _dv(**over: object) -> DatasetVersion:
    base = dict(
        dataset_id="abc123",
        kind="raw_options_data",
        parent_ids=[],
        source="databento",
        coverage_start=date(2025, 3, 10),
        coverage_end=date(2025, 3, 14),
        row_count=5,
        storage_uri="data/raw/parquet/OPRA.PILLAR/cbbo-1m",
        code_commit="deadbeef",
        config_hash="h",
    )
    base.update(over)
    return DatasetVersion(**base)  # type: ignore[arg-type]


def test_record_dataset_is_idempotent(migrated_engine: Engine) -> None:
    assert record_dataset(migrated_engine, _dv()) is True
    assert record_dataset(migrated_engine, _dv(code_commit="later")) is False  # same content
    with migrated_engine.connect() as c:
        n = c.execute(text("SELECT count(*) FROM dataset_versions")).scalar_one()
        row = c.execute(text("SELECT code_commit FROM dataset_versions")).scalar_one()
    assert n == 1
    assert row == "deadbeef"  # first registration kept


def test_record_dataset_same_id_different_content_raises(migrated_engine: Engine) -> None:
    record_dataset(migrated_engine, _dv())
    with pytest.raises(DatasetConflictError):
        record_dataset(migrated_engine, _dv(row_count=6))


def test_json_columns_roundtrip(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as c:
        _parents(c)
        pid = _prediction(c)
        got = c.execute(
            text("SELECT raw_scores FROM predictions WHERE prediction_id = :p"), {"p": pid}
        ).scalar_one()
    assert json.loads(json.dumps(got)) == {"C_call": 0.5}
