"""Journal writer for backtest candidates and simulated trades (M11). PostgreSQL; skipped without
TEST_DATABASE_URL (required in CI). A CALL prediction needs a calibration version (schema), so
the fixture builds a synthetic model + calibration row; nothing here is a real decision."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from qqq1dte.backtesting.registry import ModelVersion, record_model_version, register_run
from qqq1dte.execution_sim.engine import Candidate, Trade
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.journal.writer import write_backtest

T = datetime(2025, 3, 11, 15, 0, tzinfo=UTC)
TE = T + timedelta(seconds=5)


def _prediction(engine: Engine) -> uuid.UUID:
    record_dataset(
        engine,
        DatasetVersion(
            "feat", "features", "q", date(2025, 1, 1), date(2025, 12, 31), 1, "f", "c", "h"
        ),
    )
    run = register_run(
        engine,
        run_kind="backtest",
        config={"x": 1},
        data_window=(date(2025, 1, 1), date(2025, 12, 31)),
        dataset_id="feat",
        code_commit="c",
        folds=[],
    )
    record_model_version(
        engine,
        ModelVersion(
            "mv",
            "synthetic",
            "C_call",
            date(2025, 1, 1),
            date(2025, 2, 1),
            "feat",
            "f2",
            "L2",
            {},
            "u",
            "ab" * 32,
            "c",
            "h",
        ),
    )
    pid = uuid.uuid4()
    with engine.begin() as c:
        c.execute(
            text("""
            INSERT INTO calibration_results (calibration_version_id, model_version_id, method,
              calib_start, calib_end, eval_start, eval_end, n_calib, n_eval, reliability_bins,
              artifact_uri)
            VALUES ('cal', 'mv', 'none', '2025-02-02', '2025-02-28', '2025-03-01', '2025-03-31',
              1, 1, '[]', 'u')""")
        )
        c.execute(
            text("""
            INSERT INTO predictions (prediction_id, run_id, prediction_ts, mode, underlying_price,
              feature_snapshot_ref, feature_version, max_feature_available_at, regime,
              model_version_id, calibration_version_id, raw_scores, decision, decision_reasons,
              config_hash, code_commit)
            VALUES (:p, :r, :t, 'BACKTEST', 500.4, 'f', 'f2', :t, '{}', 'mv', 'cal', '{}',
              'CALL', '{}', 'h', 'c')"""),
            {"p": pid, "r": run, "t": T},
        )
    return pid


def _candidate(quote_ts: datetime = T) -> Candidate:
    return Candidate(
        T,
        "C",
        "QQQ   250312C00501000",
        501.0,
        date(2025, 3, 12),
        quote_ts,
        1.00,
        1.02,
        10,
        10,
        5,
        True,
        (),
        True,
    )


def _trade(fill_model: str = "CONSERVATIVE") -> Trade:
    return Trade(
        T,
        "C",
        "QQQ   250312C00501000",
        501.0,
        fill_model,
        "WIN",
        "TARGET",
        TE,
        1.02,
        1.00,
        1.02,
        T + timedelta(minutes=50),
        1.326,
        0.816,
        T + timedelta(minutes=20),
        1.33,
        1.33,
        1.35,
        0.3039,
        -0.0196,
        31.0,
        1.3,
        0.1,
        2.0,
        29.6,
        29.6 / 21.8,
        1195,
    )


def test_writes_candidate_and_trade(migrated_engine: Engine) -> None:
    pid = _prediction(migrated_engine)
    cid = write_backtest(migrated_engine, pid, _candidate(), [_trade()])
    with migrated_engine.connect() as c:
        cand = c.execute(
            text(
                "SELECT side, strike, passed_gates, selected, selection_rule_version"
                " FROM trade_candidates WHERE candidate_id = :c"
            ),
            {"c": cid},
        ).one()
        tr = c.execute(
            text(
                "SELECT fill_model, outcome, exit_reason, entry_price, exit_price, "
                "net_pnl, holding_seconds FROM simulated_trades"
            )
        ).one()
    assert tuple(cand) == ("CALL", 501.0, True, True, "S1")
    assert tuple(tr) == ("CONSERVATIVE", "WIN", "TARGET", 1.02, 1.33, 29.6, 1195)


def test_pit_trigger_rejects_a_candidate_quote_after_t_e(migrated_engine: Engine) -> None:
    pid = _prediction(migrated_engine)
    with pytest.raises(DBAPIError, match="look-ahead"):
        write_backtest(migrated_engine, pid, _candidate(T + timedelta(seconds=6)), [])


def test_one_trade_per_candidate_and_fill_model_and_append_only(migrated_engine: Engine) -> None:
    pid = _prediction(migrated_engine)
    with pytest.raises(DBAPIError):
        write_backtest(migrated_engine, pid, _candidate(), [_trade(), _trade()])
    with migrated_engine.connect() as c:  # the failed write left nothing behind (one transaction)
        assert c.execute(text("SELECT count(*) FROM trade_candidates")).scalar_one() == 0
    write_backtest(migrated_engine, pid, _candidate(), [_trade()])
    with pytest.raises(DBAPIError, match="append-only"), migrated_engine.begin() as c:
        c.execute(text("UPDATE simulated_trades SET net_pnl = 0"))
