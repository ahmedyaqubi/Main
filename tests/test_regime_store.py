"""regime_labels writer (M14). PostgreSQL; skipped without TEST_DATABASE_URL (required in CI)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from qqq1dte.backtesting.registry import register_run
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.regimes.store import RegimeLabel, write_regime_labels

T = datetime(2024, 6, 3, 14, 0, tzinfo=UTC)


def _run(engine: Engine) -> str:
    record_dataset(
        engine,
        DatasetVersion(
            "feat", "features", "q", date(2023, 1, 1), date(2026, 1, 1), 1, "f", "c", "h"
        ),
    )
    return register_run(
        engine,
        run_kind="regime",
        config={"v": "R1"},
        data_window=(date(2023, 3, 28), date(2026, 2, 27)),
        dataset_id="feat",
        code_commit="c",
        folds=[],
    )


def test_write_and_read_back(migrated_engine: Engine) -> None:
    run = _run(migrated_engine)
    rows = [
        RegimeLabel(T, "volatility", "LOW", T - timedelta(hours=20)),
        RegimeLabel(T, "trend", "CHOP", T - timedelta(hours=22)),
        RegimeLabel(T, "event", "NORMAL", T),
    ]
    assert write_regime_labels(migrated_engine, rows, run, "R1") == 3
    with migrated_engine.connect() as c:
        got = c.execute(
            text(
                "SELECT axis, value, thresholds_fit_run, regime_version "
                "FROM regime_labels ORDER BY axis"
            )
        ).all()
    assert [tuple(r) for r in got] == [
        ("event", "NORMAL", run, "R1"),
        ("trend", "CHOP", run, "R1"),
        ("volatility", "LOW", run, "R1"),
    ]


def test_label_known_after_its_timestamp_is_rejected(migrated_engine: Engine) -> None:
    run = _run(migrated_engine)
    with pytest.raises(DBAPIError):
        write_regime_labels(
            migrated_engine, [RegimeLabel(T, "event", "MACRO", T + timedelta(minutes=1))], run, "R1"
        )


def test_rewrite_is_idempotent_and_conflicts_are_errors(migrated_engine: Engine) -> None:
    run = _run(migrated_engine)
    rows = [RegimeLabel(T, "volatility", "LOW", T - timedelta(hours=20))]
    assert write_regime_labels(migrated_engine, rows, run, "R1") == 1
    run2 = _run(migrated_engine)
    assert write_regime_labels(migrated_engine, rows, run2, "R1") == 0  # identical: kept as is
    with pytest.raises(ValueError, match="different"):
        write_regime_labels(migrated_engine, [RegimeLabel(T, "volatility", "HIGH", T)], run2, "R1")
