"""Run registry (spec §8 / SCHEMA `validation_runs`): every evaluation is registered BEFORE it
runs, so failed and abandoned runs still count towards n_trials (the multiple-testing count)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from sqlalchemy import Engine, text

from qqq1dte.core.config import config_hash


def register_run(
    engine: Engine,
    *,
    run_kind: str,
    config: Mapping[str, Any],
    data_window: tuple[date, date],
    dataset_id: str,
    code_commit: str,
    folds: Sequence[Mapping[str, Any]],
    touches_final_holdout: bool = False,
) -> str:
    """Insert a REGISTERED run and return its run_id."""
    run_id = f"{run_kind}-{uuid.uuid4().hex[:12]}"
    with engine.begin() as c:
        c.execute(
            text("""
                INSERT INTO validation_runs (run_id, config_hash, config_json, run_kind,
                  data_window_start, data_window_end, touches_final_holdout, dataset_id,
                  code_commit, folds, status)
                VALUES (:run_id, :h, CAST(:cfg AS JSONB), :kind, :ws, :we, :hold, :ds,
                  :commit, CAST(:folds AS JSONB), 'REGISTERED')"""),
            {
                "run_id": run_id,
                "h": config_hash(config),
                "cfg": json.dumps(config, sort_keys=True, default=str),
                "kind": run_kind,
                "ws": data_window[0],
                "we": data_window[1],
                "hold": touches_final_holdout,
                "ds": dataset_id,
                "commit": code_commit,
                "folds": json.dumps(list(folds), default=str),
            },
        )
    return run_id


def _finish(engine: Engine, run_id: str, status: str, metrics: Mapping[str, Any]) -> None:
    with engine.begin() as c:
        n = c.execute(
            text("""
                UPDATE validation_runs SET status = :s, metrics = CAST(:m AS JSONB),
                  finished_at = now()
                WHERE run_id = :r AND status = 'REGISTERED'"""),
            {"s": status, "m": json.dumps(metrics, default=str), "r": run_id},
        ).rowcount
    if n != 1:
        raise RuntimeError(f"run {run_id} is not a REGISTERED run; cannot mark it {status}")


def complete_run(engine: Engine, run_id: str, metrics: Mapping[str, Any]) -> None:
    _finish(engine, run_id, "COMPLETED", metrics)


def fail_run(engine: Engine, run_id: str, reason: str) -> None:
    _finish(engine, run_id, "FAILED", {"failure_reason": reason})


def n_trials(engine: Engine, window_start: date, window_end: date) -> int:
    """Distinct configurations evaluated on data overlapping [window_start, window_end],
    whatever their status."""
    with engine.connect() as c:
        return int(
            c.execute(
                text("""
                    SELECT count(DISTINCT config_hash) FROM validation_runs
                    WHERE data_window_start <= :we AND data_window_end >= :ws"""),
                {"ws": window_start, "we": window_end},
            ).scalar_one()
        )
