"""Model 2 (spec Phase 1G, M9): LightGBM gradient-boosted trees on the wide feature matrix.

- inputs: raw features (no standardisation), missing values handled natively by LightGBM;
- each pre-declared grid point is fit on train with early stopping on calibration-block log
  loss; the grid point with the lowest calibration log loss is kept (`select_params` cannot
  receive test rows);
- deterministic settings (config) make refits and saved models reproduce scores exactly;
- saved in LightGBM's text format with a sha256 (T-REP-01).

Outputs are UNCALIBRATED scores, not probabilities (rule 6) until M13.
"""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import numpy.typing as npt

from qqq1dte.core.config import Gbm
from qqq1dte.models.metrics import log_loss

Arr = npt.NDArray[np.float64]


def grid_points(cfg: Gbm) -> list[dict[str, Any]]:
    return [
        {"num_leaves": a, "min_data_in_leaf": b}
        for a, b in itertools.product(cfg.grid.num_leaves, cfg.grid.min_data_in_leaf)
    ]


@dataclass(frozen=True)
class GbmFit:
    booster: lgb.Booster
    params: dict[str, Any]
    best_iteration: int
    calib_log_loss: float

    def predict(self, x: Arr) -> Arr:
        return np.asarray(self.booster.predict(x, num_iteration=self.best_iteration))


def fit_gbm(
    x_train: Arr,
    y_train: Arr,
    x_calib: Arr,
    y_calib: Arr,
    point: dict[str, Any],
    cfg: Gbm,
    feature_names: Sequence[str],
) -> GbmFit:
    params = {**cfg.fixed, **point, "metric": "binary_logloss"}
    names = list(feature_names)
    dtrain = lgb.Dataset(x_train, y_train, feature_name=names, free_raw_data=False)
    dcal = lgb.Dataset(x_calib, y_calib, feature_name=names, reference=dtrain)
    booster = lgb.train(
        params,
        dtrain,
        num_boost_round=cfg.max_rounds,
        valid_sets=[dcal],
        callbacks=[lgb.early_stopping(cfg.early_stopping_rounds, verbose=False)],
    )
    best = int(booster.best_iteration) or cfg.max_rounds
    fit = GbmFit(booster, {**point}, best, 0.0)
    return GbmFit(booster, {**point}, best, log_loss(y_calib, fit.predict(x_calib)))


def select_params(
    x_train: Arr,
    y_train: Arr,
    x_calib: Arr,
    y_calib: Arr,
    cfg: Gbm,
    feature_names: Sequence[str],
) -> tuple[GbmFit, list[GbmFit]]:
    """Fit every grid point; keep the lowest calibration log loss (ties -> first declared)."""
    fits = [
        fit_gbm(x_train, y_train, x_calib, y_calib, pt, cfg, feature_names)
        for pt in grid_points(cfg)
    ]
    best = min(fits, key=lambda f: f.calib_log_loss)
    return best, fits


def gain_importance(booster: lgb.Booster) -> dict[str, float]:
    """Share of total split gain per feature (sums to 1)."""
    gain = np.asarray(booster.feature_importance(importance_type="gain"), dtype=np.float64)
    total = gain.sum()
    shares = gain / total if total > 0 else gain
    return dict(zip(booster.feature_name(), (float(v) for v in shares), strict=True))


def canary_permutation(y: Arr, seed: int) -> Arr:
    """T-LEAK-13: training labels permuted across rows, detached from their features."""
    return np.asarray(np.random.default_rng(seed).permutation(y), dtype=np.float64)


def save(fit: GbmFit, path: Path) -> str:
    """Write the model truncated at best_iteration; return the file's sha256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fit.booster.save_model(str(path), num_iteration=fit.best_iteration)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, expected_sha256: str | None = None) -> tuple[lgb.Booster, str]:
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and sha != expected_sha256:
        raise ValueError(f"{path}: sha256 {sha} != expected {expected_sha256}")
    return lgb.Booster(model_str=data.decode("utf-8")), sha


def canary_statistic(fold_aucs: Arr, tolerance: float) -> dict[str, Any]:
    """ADR-0008 gate-4 statistic from an (n_permutations, n_folds) array of per-fold OOS AUCs:
    mean over permutations of the mean per-fold AUC; pass if within 0.5 +/- tolerance."""
    a = np.asarray(fold_aucs, dtype=np.float64)
    per_perm = a.mean(axis=1)
    stat = float(per_perm.mean())
    return {
        "statistic": stat,
        "perm_sd": float(per_perm.std(ddof=1)) if len(per_perm) > 1 else 0.0,
        "perm_min": float(per_perm.min()),
        "perm_max": float(per_perm.max()),
        "fold_mean": [float(v) for v in a.mean(axis=0)],
        "n_permutations": int(a.shape[0]),
        "pass": bool(abs(stat - 0.5) <= tolerance),
    }
