"""Run registry (every run registered before evaluation; n_trials) and the final-holdout lock
(T-WF-03). PostgreSQL; skipped without TEST_DATABASE_URL (required in CI)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import Engine, text

from qqq1dte.backtesting.holdout import HoldoutGuard, HoldoutLockedError
from qqq1dte.backtesting.registry import complete_run, fail_run, n_trials, register_run
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset

HOLD = date(2026, 4, 2)


def _dataset(engine: Engine) -> str:
    record_dataset(
        engine,
        DatasetVersion(
            dataset_id="feat",
            kind="features",
            source="qqq1dte",
            coverage_start=date(2023, 3, 28),
            coverage_end=date(2026, 10, 2),
            row_count=1,
            storage_uri="data/features/f2",
            code_commit="c",
            config_hash="h",
        ),
    )
    return "feat"


def _register(
    engine: Engine,
    cfg: dict[str, object],
    holdout: bool = False,
    window: tuple[date, date] = (date(2023, 3, 28), date(2026, 2, 27)),
) -> str:
    return register_run(
        engine,
        run_kind="walk_forward",
        config=cfg,
        data_window=window,
        dataset_id=_dataset(engine),
        code_commit="c",
        folds=[{"k": 1}],
        touches_final_holdout=holdout,
    )


def test_run_is_registered_before_evaluation_then_completed(migrated_engine: Engine) -> None:
    rid = _register(migrated_engine, {"model": "baseline"})
    with migrated_engine.connect() as c:
        status = c.execute(
            text("SELECT status FROM validation_runs WHERE run_id = :r"), {"r": rid}
        ).scalar_one()
    assert status == "REGISTERED"
    complete_run(migrated_engine, rid, {"brier": 0.24})
    with migrated_engine.connect() as c:
        row = c.execute(
            text("SELECT status, metrics, finished_at FROM validation_runs WHERE run_id = :r"),
            {"r": rid},
        ).one()
    assert row[0] == "COMPLETED" and row[1] == {"brier": 0.24} and row[2] is not None


def test_failed_run_still_counts_as_a_trial(migrated_engine: Engine) -> None:
    a = _register(migrated_engine, {"model": "baseline", "x": 1})
    fail_run(migrated_engine, a, "boom")
    _register(migrated_engine, {"model": "baseline", "x": 2})
    _register(migrated_engine, {"x": 2, "model": "baseline"})  # same config, other key order
    assert n_trials(migrated_engine, date(2023, 3, 28), date(2026, 2, 27)) == 2
    assert n_trials(migrated_engine, date(2026, 5, 1), date(2026, 6, 1)) == 0  # no overlap


def test_wf_03_holdout_access_requires_a_registered_holdout_run(migrated_engine: Engine) -> None:
    guard = HoldoutGuard(HOLD, migrated_engine)
    guard.check([date(2026, 3, 31), date(2026, 4, 2)])  # pre-holdout: no run needed
    with pytest.raises(HoldoutLockedError):
        guard.check([date(2026, 4, 6)])  # no run
    normal = _register(migrated_engine, {"m": 1})
    with pytest.raises(HoldoutLockedError):
        guard.check([date(2026, 4, 6)], run_id=normal, justification="x")  # not a holdout run


def test_wf_03_access_is_logged_and_a_second_access_needs_an_adr(migrated_engine: Engine) -> None:
    guard = HoldoutGuard(HOLD, migrated_engine)
    run = _register(migrated_engine, {"final": True}, holdout=True)
    guard.check([date(2026, 4, 6)], run_id=run, justification="M19 final evaluation")
    with pytest.raises(HoldoutLockedError, match="ADR"):
        guard.check([date(2026, 4, 7)], run_id=run, justification="again")
    guard.check([date(2026, 4, 7)], run_id=run, justification="again", adr_ref="ADR-0099")
    with migrated_engine.connect() as c:
        n = c.execute(text("SELECT count(*) FROM final_test_access_log")).scalar_one()
    assert n == 2


def test_guard_without_database_refuses_any_holdout_access() -> None:
    guard = HoldoutGuard(HOLD, None)
    guard.check([date(2026, 4, 2)])
    with pytest.raises(HoldoutLockedError):
        guard.check([date(2026, 4, 6)], run_id="r", justification="j")
