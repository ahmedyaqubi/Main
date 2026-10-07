"""Load saved model and calibrator artifacts by run (sha256-checked) for out-of-sample scoring
(M13 calibration, M14 regime analysis). Nothing is refit here."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from sqlalchemy import Engine, text

from qqq1dte.calibration.methods import Calibrator
from qqq1dte.calibration.methods import load as load_calibrator
from qqq1dte.models import gbm, logistic
from qqq1dte.models.design import KEYS

Scorer = Callable[[pl.DataFrame], np.ndarray]
PREFIX = {"logistic_m1": "m1", "gbm_m2": "m2"}


def model_scorers(
    engine: Engine, root: Path, family: str, run_id: str, expected: int = 70
) -> dict[tuple[int, str], tuple[str, Scorer]]:
    """(fold, target) -> (model_version_id, scorer on wide feature rows) for a model run."""
    p = f"{PREFIX[family]}-{run_id}-f"
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT model_version_id, target_label, artifact_uri, artifact_sha256 "
                "FROM model_versions WHERE model_version_id LIKE :p"
            ),
            {"p": p + "%"},
        ).all()
    out: dict[tuple[int, str], tuple[str, Scorer]] = {}
    for mid, tgt, uri, sha in rows:
        fold = int(mid.removeprefix(p).split("-")[0])
        if family == "logistic_m1":
            m, _ = logistic.load(root / uri, expected_sha256=sha)
            out[(fold, tgt)] = (mid, m.score)
        else:
            b, _ = gbm.load(root / uri, expected_sha256=sha)

            def _score(df: pl.DataFrame, b: Any = b) -> np.ndarray:
                feats = [c for c in df.columns if c not in (*KEYS, "y")]
                return np.asarray(b.predict(df.select(feats).to_numpy().astype(np.float64)))

            out[(fold, tgt)] = (mid, _score)
    if len(out) != expected:
        raise RuntimeError(f"expected {expected} {family} artifacts for {run_id}, found {len(out)}")
    return out


def calibrators(
    engine: Engine, root: Path, calibration_run_id: str
) -> dict[str, tuple[str, Calibrator]]:
    """model_version_id -> (calibration_version_id, calibrator) for a calibration run."""
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT calibration_version_id, model_version_id, artifact_uri "
                "FROM calibration_results WHERE calibration_version_id LIKE :p"
            ),
            {"p": f"cal-{calibration_run_id}-f%"},
        ).all()
    out = {}
    for cid, mid, uri in rows:
        path, _, sha = uri.partition("#sha256=")
        cal, _ = load_calibrator(root / path, expected_sha256=sha)
        out[mid] = (cid, cal)
    if not out:
        raise RuntimeError(f"no calibrators recorded for {calibration_run_id}")
    return out
