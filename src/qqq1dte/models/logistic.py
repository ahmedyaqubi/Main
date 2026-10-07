"""Model 1 (spec Phase 1G, M8): L2-regularised logistic regression on the design matrix.

Fitting uses scikit-learn; the fitted model is stored as JSON (design statistics, coefficients,
intercept, C) and scored with numpy, so a saved model reproduces its scores bit for bit
(T-REP-01). Outputs are UNCALIBRATED scores, not probabilities (rule 6) until M13.

C is chosen on the calibration block only (`select_c` cannot receive test rows), never on test.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl
from sklearn.linear_model import LogisticRegression

from qqq1dte.core.config import Logistic
from qqq1dte.models.design import DesignSpec, transform
from qqq1dte.models.metrics import log_loss

Arr = npt.NDArray[np.float64]


@dataclass(frozen=True)
class LogisticModel:
    design: DesignSpec
    coef: tuple[float, ...]
    intercept: float
    c: float

    def score_matrix(self, x: Arr) -> Arr:
        z = x @ np.asarray(self.coef) + self.intercept
        return np.asarray(1.0 / (1.0 + np.exp(-z)), dtype=np.float64)

    def score(self, wide: pl.DataFrame) -> Arr:
        x, _ = transform(self.design, wide)
        return self.score_matrix(x)


def fit_logistic(x: Arr, y: Arr, c: float, cfg: Logistic) -> tuple[Arr, float]:
    m = LogisticRegression(C=c, solver=cfg.solver, max_iter=cfg.max_iter, tol=cfg.tol)
    m.fit(x, y)
    return np.asarray(m.coef_[0], dtype=np.float64), float(m.intercept_[0])


def select_c(
    x_train: Arr, y_train: Arr, x_calib: Arr, y_calib: Arr, cfg: Logistic
) -> tuple[float, dict[float, float]]:
    """C from cfg.c_grid with the lowest calibration-block log loss (ties -> smaller C)."""
    losses: dict[float, float] = {}
    for c in cfg.c_grid:
        coef, b = fit_logistic(x_train, y_train, c, cfg)
        p = 1.0 / (1.0 + np.exp(-(x_calib @ coef + b)))
        losses[c] = log_loss(y_calib, p)
    best = min(sorted(losses), key=lambda k: losses[k])
    return best, losses


def _to_json(m: LogisticModel) -> str:
    d = asdict(m)
    d["format"] = "qqq1dte.logistic.v1"
    return json.dumps(d, indent=1, sort_keys=True)


def save(m: LogisticModel, path: Path) -> str:
    """Write the model as JSON; return the file's sha256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _to_json(m).encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def load(path: Path, expected_sha256: str | None = None) -> tuple[LogisticModel, str]:
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and sha != expected_sha256:
        raise ValueError(f"{path}: sha256 {sha} != expected {expected_sha256}")
    d = json.loads(data)
    if d.pop("format") != "qqq1dte.logistic.v1":
        raise ValueError(f"{path}: unknown model format")
    ds = d["design"]
    design = DesignSpec(
        columns=tuple(ds["columns"]),
        mean=tuple(ds["mean"]),
        std=tuple(ds["std"]),
        indicator_for=tuple(ds["indicator_for"]),
        z_clip=ds["z_clip"],
    )
    return LogisticModel(design, tuple(d["coef"]), d["intercept"], d["c"]), sha
