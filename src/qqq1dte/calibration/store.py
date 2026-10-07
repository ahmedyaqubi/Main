"""calibration_results writer (SCHEMA; M13). The database enforces calib_end < eval_start and a
model_versions reference. The table has no sha column, so the artifact sha256 is appended to
artifact_uri as `#sha256=<hex>`; re-recording an id with a different method or artifact is an
error."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Engine, text


@dataclass(frozen=True)
class CalibrationRecord:
    calibration_version_id: str
    model_version_id: str
    method: str
    calib_start: date
    calib_end: date
    eval_start: date
    eval_end: date
    n_calib: int
    n_eval: int
    brier: float
    log_loss: float
    ece: float
    slope: float
    intercept: float
    reliability_bins: list[dict[str, Any]]
    artifact_uri: str
    artifact_sha256: str


def record_calibration(engine: Engine, r: CalibrationRecord) -> bool:
    """Insert; False if the identical calibration version already exists."""
    uri = f"{r.artifact_uri}#sha256={r.artifact_sha256}"
    with engine.begin() as c:
        inserted = c.execute(
            text("""
                INSERT INTO calibration_results (calibration_version_id, model_version_id, method,
                  calib_start, calib_end, eval_start, eval_end, n_calib, n_eval, brier, log_loss,
                  ece, slope, intercept, reliability_bins, artifact_uri)
                VALUES (:id, :mv, :method, :cs, :ce, :es, :ee, :nc, :ne, :brier, :ll, :ece,
                  :slope, :intercept, CAST(:bins AS JSONB), :uri)
                ON CONFLICT (calibration_version_id) DO NOTHING
                RETURNING calibration_version_id"""),
            {
                "id": r.calibration_version_id,
                "mv": r.model_version_id,
                "method": r.method,
                "cs": r.calib_start,
                "ce": r.calib_end,
                "es": r.eval_start,
                "ee": r.eval_end,
                "nc": r.n_calib,
                "ne": r.n_eval,
                "brier": r.brier,
                "ll": r.log_loss,
                "ece": r.ece,
                "slope": r.slope,
                "intercept": r.intercept,
                "bins": json.dumps(r.reliability_bins),
                "uri": uri,
            },
        ).first()
        if inserted is not None:
            return True
        row = c.execute(
            text(
                "SELECT method, artifact_uri FROM calibration_results "
                "WHERE calibration_version_id = :id"
            ),
            {"id": r.calibration_version_id},
        ).one()
    if tuple(row) != (r.method, uri):
        raise ValueError(f"calibration {r.calibration_version_id} recorded with different content")
    return False
