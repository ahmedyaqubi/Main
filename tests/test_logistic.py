"""Model 1 (M8): L2 logistic regression. Known-coefficient recovery, numpy scoring equals
scikit-learn, C chosen on the calibration block only, JSON save/load round trip (T-REP-01)."""

from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression

from qqq1dte.core.config import Logistic
from qqq1dte.models.design import DesignSpec
from qqq1dte.models.logistic import LogisticModel, fit_logistic, load, save, select_c
from qqq1dte.models.metrics import log_loss

CFG = Logistic(
    c_grid=[0.001, 0.01, 0.1, 1.0, 10.0], z_clip=5.0, solver="lbfgs", max_iter=2000, tol=1e-8
)


def _synthetic(n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 2))
    logit = 0.5 + 1.0 * x[:, 0] - 2.0 * x[:, 1]
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(np.float64)
    return x, y


def test_recovers_known_coefficients() -> None:
    x, y = _synthetic(200_000, 0)
    coef, b = fit_logistic(x, y, 10.0, CFG)
    assert b == pytest.approx(0.5, abs=0.03)
    np.testing.assert_allclose(coef, [1.0, -2.0], atol=0.03)


def test_strong_regularisation_shrinks_towards_zero() -> None:
    x, y = _synthetic(5_000, 1)
    weak, _ = fit_logistic(x, y, 10.0, CFG)
    strong, _ = fit_logistic(x, y, 0.001, CFG)
    assert np.all(np.abs(strong) < np.abs(weak))


def _model(coef: list[float], b: float) -> LogisticModel:
    spec = DesignSpec(
        columns=("u", "v"), mean=(0.0, 0.0), std=(1.0, 1.0), indicator_for=(), z_clip=5.0
    )
    return LogisticModel(design=spec, coef=tuple(coef), intercept=b, c=1.0)


def test_numpy_scores_equal_sklearn() -> None:
    x, y = _synthetic(3_000, 2)
    sk = LogisticRegression(C=1.0, solver="lbfgs", max_iter=2000, tol=1e-8).fit(x, y)
    coef, _b = fit_logistic(x, y, 1.0, CFG)
    np.testing.assert_allclose(coef, sk.coef_[0], atol=1e-6)
    m = _model(list(sk.coef_[0]), float(sk.intercept_[0]))
    np.testing.assert_allclose(m.score_matrix(x), sk.predict_proba(x)[:, 1], rtol=0, atol=1e-12)


def test_select_c_minimises_calibration_log_loss_and_sees_no_test_rows() -> None:
    xt, yt = _synthetic(2_000, 3)
    xc, yc = _synthetic(1_000, 4)
    c, losses = select_c(xt, yt, xc, yc, CFG)
    expected = {}
    for cc in CFG.c_grid:
        coef, b = fit_logistic(xt, yt, cc, CFG)
        expected[cc] = log_loss(yc, _model(list(coef), b).score_matrix(xc))
    assert losses == pytest.approx(expected)
    assert c == min(expected, key=lambda k: expected[k])
    assert list(inspect.signature(select_c).parameters) == [
        "x_train",
        "y_train",
        "x_calib",
        "y_calib",
        "cfg",
    ]


def test_t_rep_01_save_load_roundtrip(tmp_path: Path) -> None:
    x, _ = _synthetic(500, 5)
    m = _model([0.123456789012345, -1.5], 0.25)
    sha = save(m, tmp_path / "m.json")
    m2, sha2 = load(tmp_path / "m.json")
    assert m2 == m and sha2 == sha
    assert np.array_equal(m.score_matrix(x), m2.score_matrix(x))  # bit-identical


def test_load_rejects_tampered_artifact(tmp_path: Path) -> None:
    m = _model([1.0, 2.0], 0.0)
    sha = save(m, tmp_path / "m.json")
    p = tmp_path / "m.json"
    p.write_text(p.read_text(encoding="utf-8").replace("2.0", "3.0"), encoding="utf-8")
    with pytest.raises(ValueError, match="sha256"):
        load(p, expected_sha256=sha)
