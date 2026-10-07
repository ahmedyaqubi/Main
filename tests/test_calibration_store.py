"""calibration_results writer (M13). PostgreSQL; skipped without TEST_DATABASE_URL (CI)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from qqq1dte.backtesting.registry import ModelVersion, record_model_version
from qqq1dte.calibration.store import CalibrationRecord, record_calibration
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset


def _model(engine: Engine) -> None:
    record_dataset(
        engine,
        DatasetVersion(
            "feat", "features", "q", date(2023, 1, 1), date(2026, 1, 1), 1, "f", "c", "h"
        ),
    )
    record_model_version(
        engine,
        ModelVersion(
            "mv",
            "logistic_l2",
            "C_call",
            date(2023, 3, 28),
            date(2024, 3, 27),
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


def _rec(**kw: object) -> CalibrationRecord:
    base = dict(
        calibration_version_id="cal-1",
        model_version_id="mv",
        method="platt",
        calib_start=date(2024, 4, 1),
        calib_end=date(2024, 5, 24),
        eval_start=date(2024, 5, 28),
        eval_end=date(2024, 8, 27),
        n_calib=2500,
        n_eval=4000,
        brier=0.2,
        log_loss=0.6,
        ece=0.02,
        slope=0.95,
        intercept=0.01,
        reliability_bins=[{"bin": 0, "n": 400}],
        artifact_uri="data/calibration/x.json",
        artifact_sha256="cd" * 32,
    )
    base.update(kw)
    return CalibrationRecord(**base)  # type: ignore[arg-type]


def test_record_and_read_back(migrated_engine: Engine) -> None:
    _model(migrated_engine)
    assert record_calibration(migrated_engine, _rec())
    assert not record_calibration(migrated_engine, _rec())  # identical: no-op
    with migrated_engine.connect() as c:
        row = c.execute(
            text("SELECT method, n_eval, reliability_bins, artifact_uri FROM calibration_results")
        ).one()
    uri = "data/calibration/x.json#sha256=" + "cd" * 32  # no sha column: hash kept in the URI
    assert tuple(row) == ("platt", 4000, [{"bin": 0, "n": 400}], uri)
    with pytest.raises(ValueError, match="different"):
        record_calibration(migrated_engine, _rec(method="isotonic"))


def test_database_rejects_calibration_window_not_before_evaluation(migrated_engine: Engine) -> None:
    _model(migrated_engine)
    with pytest.raises(DBAPIError):
        record_calibration(migrated_engine, _rec(calib_end=date(2024, 6, 1)))
