"""Model 2 (M9): LightGBM. Learns a planted signal, ~0.5 AUC on noise, selection sees train and
calibration only, deterministic refits, save/load round trip (T-REP-01), label-permutation
canary helper (T-LEAK-13)."""

from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pytest

from qqq1dte.core.config import load_config
from qqq1dte.models.gbm import (
    canary_permutation,
    fit_gbm,
    gain_importance,
    grid_points,
    load,
    save,
    select_params,
)
from qqq1dte.models.metrics import auc

CFG = load_config().models.gbm
NAMES = ["x0", "x1", "x2"]


def _data(n: int, seed: int, signal: float) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 3))
    x[rng.random(n) < 0.05, 1] = np.nan  # native missing handling
    p = 1 / (1 + np.exp(-signal * x[:, 0]))
    return x, (rng.random(n) < p).astype(np.float64)


def test_grid_points_are_the_declared_product() -> None:
    pts = grid_points(CFG)
    assert len(pts) == len(CFG.grid.num_leaves) * len(CFG.grid.min_data_in_leaf)
    assert {(p["num_leaves"], p["min_data_in_leaf"]) for p in pts} == {
        (a, b) for a in CFG.grid.num_leaves for b in CFG.grid.min_data_in_leaf
    }


def test_learns_planted_signal_and_ranks_it_first() -> None:
    xt, yt = _data(20_000, 0, 2.0)
    xc, yc = _data(5_000, 1, 2.0)
    xs, ys = _data(10_000, 2, 2.0)
    fit = fit_gbm(xt, yt, xc, yc, grid_points(CFG)[0], CFG, NAMES)
    assert auc(ys, fit.predict(xs)) > 0.75
    imp = gain_importance(fit.booster)
    assert max(imp, key=lambda k: imp[k]) == "x0"
    assert sum(imp.values()) == pytest.approx(1.0)
    assert 1 <= fit.best_iteration <= CFG.max_rounds


def test_noise_gives_auc_near_half() -> None:
    xt, yt = _data(20_000, 3, 0.0)
    xc, yc = _data(5_000, 4, 0.0)
    xs, ys = _data(20_000, 5, 0.0)
    fit = fit_gbm(xt, yt, xc, yc, grid_points(CFG)[0], CFG, NAMES)
    assert abs(auc(ys, fit.predict(xs)) - 0.5) < 0.02


def test_select_params_uses_calibration_log_loss_only() -> None:
    xt, yt = _data(8_000, 6, 1.0)
    xc, yc = _data(3_000, 7, 1.0)
    best, results = select_params(xt, yt, xc, yc, CFG, NAMES)
    assert len(results) == len(grid_points(CFG))
    assert best.calib_log_loss == min(r.calib_log_loss for r in results)
    assert list(inspect.signature(select_params).parameters) == [
        "x_train",
        "y_train",
        "x_calib",
        "y_calib",
        "cfg",
        "feature_names",
    ]


def test_refit_is_deterministic() -> None:
    xt, yt = _data(6_000, 8, 1.0)
    xc, yc = _data(2_000, 9, 1.0)
    a = fit_gbm(xt, yt, xc, yc, grid_points(CFG)[1], CFG, NAMES)
    b = fit_gbm(xt, yt, xc, yc, grid_points(CFG)[1], CFG, NAMES)
    assert np.array_equal(a.predict(xc), b.predict(xc))


def test_t_rep_01_save_load_roundtrip(tmp_path: Path) -> None:
    xt, yt = _data(6_000, 10, 1.0)
    xc, yc = _data(2_000, 11, 1.0)
    fit = fit_gbm(xt, yt, xc, yc, grid_points(CFG)[0], CFG, NAMES)
    sha = save(fit, tmp_path / "m.txt")
    booster, sha2 = load(tmp_path / "m.txt", expected_sha256=sha)
    assert sha2 == sha
    assert np.array_equal(fit.predict(xc), booster.predict(xc))  # bit-identical
    p = tmp_path / "m.txt"
    p.write_bytes(p.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="sha256"):
        load(p, expected_sha256=sha)


def test_canary_permutation_keeps_counts_and_breaks_alignment() -> None:
    y = np.array([0.0] * 700 + [1.0] * 300)
    s = canary_permutation(y, 123)
    assert sorted(s) == sorted(y) and not np.array_equal(s, y)
    assert np.array_equal(s, canary_permutation(y, 123))  # seeded, reproducible


def test_canary_statistic_averages_fold_aucs_over_permutations() -> None:
    """ADR-0008: mean over permutations of the mean per-fold AUC; spread reported."""
    from qqq1dte.models.gbm import canary_statistic  # noqa: PLC0415

    aucs = np.array([[0.40, 0.60, 0.50], [0.52, 0.50, 0.51], [0.47, 0.49, 0.48]])
    s = canary_statistic(aucs, tolerance=0.02)
    per_perm = [0.5, 0.51, 0.48]
    assert s["statistic"] == pytest.approx(np.mean(per_perm))
    assert s["perm_sd"] == pytest.approx(np.std(per_perm, ddof=1))
    assert (s["perm_min"], s["perm_max"]) == pytest.approx((0.48, 0.51))
    assert s["fold_mean"] == pytest.approx([0.463333, 0.53, 0.496667], abs=1e-6)
    assert s["pass"] is True
    assert canary_statistic(aucs + 0.05, tolerance=0.02)["pass"] is False
