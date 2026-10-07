"""Probability calibration (M13; spec Phase 1L, gate 12): methods, metrics (T-CAL-01/02), fitting
on calibration rows only (T-CAL-03) and the uncalibrated guard (T-CAL-04)."""

from __future__ import annotations

import math
import textwrap
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
from mypy import api

from qqq1dte.calibration.fit import fit_calibration
from qqq1dte.calibration.methods import Calibrator, fit_method, load, logit, save
from qqq1dte.calibration.metrics import calibration_slope, gate12, reliability, wilson_ci
from qqq1dte.core.config import load_config
from qqq1dte.execution_sim.decision import CalibratedProbability, decide
from qqq1dte.models.metrics import ece

CFG = load_config()
ROOT = Path(__file__).resolve().parents[1]


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-z))


def _miscalibrated(n: int, seed: int, a: float, b: float) -> tuple[np.ndarray, np.ndarray]:
    """Raw scores p; true probability sigmoid(a logit(p) + b)."""
    rng = np.random.default_rng(seed)
    p = rng.uniform(0.05, 0.95, n)
    y = (rng.random(n) < _sigmoid(a * logit(p) + b)).astype(np.float64)
    return p, y


# -- methods ----------------------------------------------------------------------------------
def test_platt_recovers_known_parameters() -> None:
    p, y = _miscalibrated(200_000, 0, 0.6, 0.3)
    c = fit_method("platt", p, y, CFG)
    assert c.params["a"] == pytest.approx(0.6, abs=0.02)
    assert c.params["b"] == pytest.approx(0.3, abs=0.02)


def test_temperature_recovers_known_scale() -> None:
    p, y = _miscalibrated(200_000, 1, 0.5, 0.0)  # logit / T with T = 2
    c = fit_method("temperature", p, y, CFG)
    assert c.params["T"] == pytest.approx(2.0, rel=0.03)


def test_isotonic_is_monotone_and_identity_is_identity() -> None:
    p, y = _miscalibrated(5_000, 2, 1.5, -0.2)
    iso = fit_method("isotonic", p, y, CFG)
    grid = np.linspace(0.0, 1.0, 101)
    assert np.all(np.diff(iso.apply(grid)) >= 0)
    ident = fit_method("none", p, y, CFG)
    np.testing.assert_allclose(ident.apply(np.array([0.2, 0.7])), [0.2, 0.7])


def test_outputs_are_clipped() -> None:
    p, y = _miscalibrated(2_000, 3, 1.0, 0.0)
    c = fit_method("isotonic", p, y, CFG)
    out = c.apply(np.array([0.0, 1.0]))
    assert out.min() >= CFG.calibration.prob_clip and out.max() <= 1 - CFG.calibration.prob_clip


@pytest.mark.parametrize("method", ["none", "temperature", "platt", "isotonic"])
def test_save_load_roundtrip(method: str, tmp_path: Path) -> None:
    p, y = _miscalibrated(3_000, 4, 0.8, 0.1)
    c = fit_method(method, p, y, CFG)
    sha = save(c, tmp_path / "c.json")
    c2, sha2 = load(tmp_path / "c.json", expected_sha256=sha)
    assert sha2 == sha and c2.method == method
    assert np.array_equal(c.apply(p), c2.apply(p))


# -- metrics ----------------------------------------------------------------------------------
def test_cal_01_ece_known() -> None:
    y, p = np.array([0, 1, 1, 1]), np.array([0.2, 0.2, 0.8, 0.8])
    assert ece(y, p, bins=2) == pytest.approx(0.25)


def test_cal_02_perfectly_calibrated_synthetic() -> None:
    rng = np.random.default_rng(5)
    p = rng.uniform(0.05, 0.95, 200_000)
    y = (rng.random(p.size) < p).astype(np.float64)
    assert ece(y, p, 10) < 0.01
    slope, intercept = calibration_slope(y, p)
    assert slope == pytest.approx(1.0, abs=0.03) and intercept == pytest.approx(0.0, abs=0.02)


def test_slope_detects_overconfidence() -> None:
    p, y = _miscalibrated(100_000, 6, 0.5, 0.0)  # raw scores too extreme
    assert calibration_slope(y, p)[0] == pytest.approx(0.5, abs=0.03)


def test_wilson_ci_hand_computed() -> None:
    lo, hi = wilson_ci(0.5, 100, 0.95)
    assert (lo, hi) == pytest.approx((0.403832, 0.596168), abs=1e-5)
    z = 1.959963984540054
    p, n = 0.2, 50
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z / (1 + z * z / n) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    assert wilson_ci(p, n, 0.95) == pytest.approx((centre - half, centre + half))


def test_reliability_bins_and_gate12_bin_check() -> None:
    """ADR-0009: each checked bin uses the Wilson CI at 1 - (1 - 0.95) / k (k = checked bins);
    the unadjusted 95% result is kept for reference."""
    rng = np.random.default_rng(7)
    p = rng.uniform(0.1, 0.9, 20_000)
    y = (rng.random(p.size) < p).astype(np.float64)
    bins = reliability(y, p, CFG)
    assert len(bins) == 10 and sum(b["n"] for b in bins) == p.size
    assert all(b["checked"] for b in bins)  # every bin has n >= 200
    for b in bins:
        assert b["level"] == pytest.approx(1 - 0.05 / 10)
        lo, hi = wilson_ci(b["mean_pred"], b["n"], 1 - 0.05 / 10)
        assert (b["wilson_lo"], b["wilson_hi"]) == (lo, hi)
        assert b["inside"] == (lo <= b["observed"] <= hi)
        lo95, hi95 = wilson_ci(b["mean_pred"], b["n"], 0.95)
        assert b["inside_95"] == (lo95 <= b["observed"] <= hi95)
    g = gate12(y, p, CFG)
    assert g["ece_ok"] and g["slope_ok"] and g["bin_level"] == pytest.approx(0.995)
    assert g["pass"] == (g["ece_ok"] and g["slope_ok"] and g["bins_failed"] == 0)
    assert g["bins_failed_95"] >= g["bins_failed"]
    bad = gate12(y, np.clip(p + 0.15, 0, 1), CFG)  # systematically too high
    assert not bad["pass"] and bad["bins_failed"] > 0 and bad["ece"] > 0.03


def _false_fail_rates(seeds: int) -> tuple[float, float]:
    adj = raw = 0
    for seed in range(seeds):
        rng = np.random.default_rng(seed)
        p = rng.uniform(0.1, 0.9, 20_000)
        y = (rng.random(p.size) < p).astype(np.float64)
        g = gate12(y, p, CFG)
        adj += not g["bins_ok"]
        raw += g["bins_failed_95"] > 0
    return adj / seeds, raw / seeds


def test_gate12_bin_rule_false_fail_rates() -> None:
    """ADR-0009: the adjusted rule fails a perfectly calibrated model ~5% of the time; the
    original rule (every bin at 95%) failed it ~1 - 0.95^10 = 40% of the time."""
    adj, raw = _false_fail_rates(200)
    assert adj <= 0.10
    assert 0.25 <= raw <= 0.55


# -- fitting on calibration rows only ---------------------------------------------------------
def _block(start: date, n_sessions: int, seed: int) -> tuple[np.ndarray, np.ndarray, list[date]]:
    p, y = _miscalibrated(n_sessions * 50, seed, 0.6, 0.2)
    days = [start + timedelta(days=i // 50) for i in range(p.size)]
    return p, y, days


def test_cal_03_refuses_rows_overlapping_training_or_test() -> None:
    p, y, days = _block(date(2024, 4, 1), 40, 8)
    train_end, test_start = date(2024, 3, 28), date(2024, 6, 1)
    fit_calibration(p, y, days, train_end, test_start, CFG)  # clean block is accepted
    with pytest.raises(ValueError, match="training"):
        fit_calibration(p, y, [date(2024, 3, 28), *days[1:]], train_end, test_start, CFG)
    with pytest.raises(ValueError, match="test"):
        fit_calibration(p, y, [*days[:-1], date(2024, 6, 1)], train_end, test_start, CFG)


def test_method_chosen_on_inner_chronological_split_then_refit() -> None:
    p, y, days = _block(date(2024, 4, 1), 40, 9)
    fit = fit_calibration(p, y, days, date(2024, 3, 28), date(2024, 6, 1), CFG)
    assert set(fit.inner_log_loss) == set(CFG.calibration.methods)
    assert fit.method == min(fit.inner_log_loss, key=lambda m: fit.inner_log_loss[m])
    assert fit.method != "none"  # miscalibrated scores: some correction wins
    assert fit.n_fit == p.size and fit.n_inner_fit < p.size
    refit = fit_method(fit.method, p, y, CFG)  # final calibrator uses the full block
    np.testing.assert_allclose(fit.calibrator.apply(p), refit.apply(p))


# -- rule 6 / T-CAL-04 ------------------------------------------------------------------------
def test_cal_04_uncalibrated_forces_no_trade() -> None:
    d = decide(None, None, None)
    assert (d.decision, d.reasons) == ("NO_TRADE", ("UNCALIBRATED",))
    pc = CalibratedProbability(0.7, "cal-1")
    assert decide(pc, None, None).decision == "NO_TRADE"
    d2 = decide(pc, CalibratedProbability(0.2, "cal-1"), "cal-1")
    assert d2.decision == "NO_TRADE" and "DECISION_RULE_PENDING" in d2.reasons  # M15
    with pytest.raises(TypeError, match="CalibratedProbability"):
        decide(0.7, 0.2, "cal-1")  # type: ignore[arg-type]


def test_calibrated_probability_needs_a_version_and_a_valid_value() -> None:
    with pytest.raises(ValueError):
        CalibratedProbability(0.5, "")
    with pytest.raises(ValueError):
        CalibratedProbability(1.5, "cal-1")
    assert CalibratedProbability(0.5, "cal-1").calibration_version_id == "cal-1"


def test_calibrator_emits_calibrated_probability() -> None:
    c = Calibrator("platt", {"a": 1.0, "b": 0.0}, CFG.calibration.prob_clip)
    out = c.probability(0.3, "cal-9")
    assert isinstance(out, CalibratedProbability) and float(out) == pytest.approx(0.3)


def test_mypy_rejects_a_raw_score_as_probability(tmp_path: Path) -> None:
    snippet = tmp_path / "bad_decision.py"
    snippet.write_text(
        textwrap.dedent("""
        from qqq1dte.execution_sim.decision import decide
        decide(0.7, 0.2, "cal-1")
    """),
        encoding="utf-8",
    )
    out, _, status = api.run(
        [str(snippet), "--config-file", str(ROOT / "pyproject.toml"), "--no-incremental"]
    )
    assert status != 0 and "CalibratedProbability" in out


def test_slope_is_undefined_for_constant_predictions() -> None:
    """A constant prediction has no slope: NaN, so the gate-12 slope check fails, no crash."""
    y = np.array([0.0, 1.0, 1.0, 0.0, 1.0])
    slope, intercept = calibration_slope(y, np.full(5, 0.6))
    assert math.isnan(slope) and intercept == pytest.approx(math.log(0.6 / 0.4))
    g = gate12(np.tile(y, 100), np.full(500, 0.6), CFG)
    assert not g["slope_ok"] and not g["pass"]


def test_extreme_scores_do_not_overflow() -> None:
    with np.errstate(over="raise"):
        p, y = _miscalibrated(1_000, 10, 1.0, 0.0)
        p[:5] = 1 - 1e-12
        calibration_slope(y, p)
        fit_method("platt", p, y, CFG).apply(p)


def test_platt_on_constant_scores_is_the_base_rate() -> None:
    y = np.array([0.0, 1.0, 1.0, 1.0] * 50)
    c = fit_method("platt", np.full(200, 0.4), y, CFG)
    assert c.params["a"] == 0.0
    np.testing.assert_allclose(c.apply(np.array([0.1, 0.9])), [0.75, 0.75])


def test_slope_fit_converges_for_scores_in_a_narrow_range() -> None:
    """Scores spread over 0.27 +/- 0.004 with a real but steep relation (LightGBM-like)."""
    rng = np.random.default_rng(11)
    x = rng.normal(0.0, 1.0, 50_000)
    p = 0.27 + 0.004 * np.tanh(x / 2)
    y = (rng.random(x.size) < _sigmoid(-1.0 + 0.8 * x)).astype(np.float64)
    slope, _ = calibration_slope(y, p)
    assert np.isfinite(slope) and slope > 10  # steep relative to the logit spread, but finite


def test_slope_fit_survives_quasi_separation() -> None:
    """Isotonic floors (p = clip) whose rows are all y = 0 separate the data in one tail."""
    rng = np.random.default_rng(12)
    p = rng.uniform(0.1, 0.45, 4_000)
    y = (rng.random(p.size) < p).astype(np.float64)
    p[:30], y[:30] = 1e-4, 0.0
    slope, intercept = calibration_slope(y, p)
    assert np.isfinite(slope) and np.isfinite(intercept)


def test_slope_fit_converges_with_extreme_clipped_scores() -> None:
    """Real M13 case (gbm fold 1 C_call, isotonic): clipped scores at both ends whose observed
    rates are far from 0 / 1 make undamped Newton oscillate and diverge."""
    rng = np.random.default_rng(13)
    p = rng.uniform(0.1, 0.45, 4_000)
    y = (rng.random(p.size) < p).astype(np.float64)
    p[:55], y[:55] = 1e-4, (rng.random(55) < 0.07)
    p[55:65], y[55:65] = 0.9999, (rng.random(10) < 0.3)
    slope, _ = calibration_slope(y, p)
    assert np.isfinite(slope) and 0 < slope < 1  # extremes pull the slope well below 1


def test_slope_fit_converges_on_the_real_m13_failure_case() -> None:
    """Regression fixture: isotonic-calibrated gbm fold-1 C_call test-block predictions and
    labels (no vendor data) on which undamped Newton diverged (singular Hessian)."""
    f = np.load(ROOT / "tests" / "fixtures" / "m13_gbm_f1_ccall_calibrated.npz")
    slope, intercept = calibration_slope(f["y"], f["p"])
    assert np.isfinite(slope) and np.isfinite(intercept)
    # first-order optimality: the log-likelihood gradient is ~0 at the solution
    x = logit(f["p"])
    q = _sigmoid(slope * x + intercept)
    assert abs(np.sum((q - f["y"]) * x)) < 1e-6 and abs(np.sum(q - f["y"])) < 1e-6
