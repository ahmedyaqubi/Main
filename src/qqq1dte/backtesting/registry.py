"""Run registry (spec §8 / SCHEMA `validation_runs`): every evaluation is registered BEFORE it
runs, so failed and abandoned runs still count towards n_trials (the multiple-testing count)."""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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


def _finite(x: Any) -> Any:
    """JSONB has no NaN/inf: non-finite floats are stored as null."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, Mapping):
        return {k: _finite(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_finite(v) for v in x]
    return x


def _finish(engine: Engine, run_id: str, status: str, metrics: Mapping[str, Any]) -> None:
    with engine.begin() as c:
        n = c.execute(
            text("""
                UPDATE validation_runs SET status = :s, metrics = CAST(:m AS JSONB),
                  finished_at = now()
                WHERE run_id = :r AND status = 'REGISTERED'"""),
            {"s": status, "m": json.dumps(_finite(metrics), default=str), "r": run_id},
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


@dataclass(frozen=True)
class ModelVersion:
    model_version_id: str
    model_family: str
    target_label: str
    train_start: date
    train_end: date
    dataset_id: str
    feature_version: str
    label_version: str
    hyperparameters: Mapping[str, Any]
    artifact_uri: str
    artifact_sha256: str
    code_commit: str
    config_hash: str


def record_model_version(engine: Engine, mv: ModelVersion) -> bool:
    """Insert a CANDIDATE model version; False if the identical artifact is already recorded,
    ValueError if the id exists with a different artifact."""
    with engine.begin() as c:
        inserted = c.execute(
            text("""
                INSERT INTO model_versions (model_version_id, model_family, target_label,
                  train_start, train_end, dataset_id, feature_version, label_version,
                  hyperparameters, artifact_uri, artifact_sha256, code_commit, config_hash, status)
                VALUES (:model_version_id, :model_family, :target_label, :train_start,
                  :train_end, :dataset_id, :feature_version, :label_version,
                  CAST(:hp AS JSONB), :artifact_uri, :artifact_sha256, :code_commit,
                  :config_hash, 'CANDIDATE')
                ON CONFLICT (model_version_id) DO NOTHING
                RETURNING model_version_id"""),
            {**mv.__dict__, "hp": json.dumps(mv.hyperparameters, sort_keys=True)},
        ).first()
        if inserted is not None:
            return True
        sha = c.execute(
            text("SELECT artifact_sha256 FROM model_versions WHERE model_version_id = :m"),
            {"m": mv.model_version_id},
        ).scalar_one()
    if sha != mv.artifact_sha256:
        raise ValueError(f"model {mv.model_version_id} already recorded with a different artifact")
    return False
