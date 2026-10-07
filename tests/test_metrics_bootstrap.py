"""Probability metrics (hand-computed) and the session-block bootstrap (known variance)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from qqq1dte.backtesting.bootstrap import session_bootstrap_ci
from qqq1dte.models.metrics import brier, ece, log_loss, n_effective


def test_brier_hand_computed() -> None:
    y, p = np.array([1, 0, 1, 0]), np.array([0.9, 0.2, 0.6, 0.5])
    assert brier(y, p) == pytest.approx((0.01 + 0.04 + 0.16 + 0.25) / 4)


def test_log_loss_hand_computed_and_clipped() -> None:
    y, p = np.array([1, 0]), np.array([0.8, 0.1])
    assert log_loss(y, p) == pytest.approx(-(math.log(0.8) + math.log(0.9)) / 2)
    assert math.isfinite(log_loss(np.array([1]), np.array([0.0])))  # clipped, not inf


def test_ece_equal_count_bins_hand_computed() -> None:
    y, p = np.array([0, 1, 1, 1]), np.array([0.2, 0.2, 0.8, 0.8])
    # bin 1: mean p 0.2, mean y 0.5 -> 0.3; bin 2: 0.8 vs 1.0 -> 0.2; equal weights
    assert ece(y, p, bins=2) == pytest.approx(0.25)


def test_ece_keeps_identical_predictions_in_one_bin() -> None:
    y, p = np.array([0, 1, 1, 0, 1]), np.full(5, 0.5)
    assert ece(y, p, bins=10) == pytest.approx(abs(0.6 - 0.5))


def test_weights_equal_repeated_rows() -> None:
    y, p = np.array([1, 0, 1]), np.array([0.7, 0.4, 0.2])
    w = np.array([2.0, 1.0, 3.0])
    rep_y, rep_p = np.repeat(y, [2, 1, 3]), np.repeat(p, [2, 1, 3])
    assert brier(y, p, w) == pytest.approx(brier(rep_y, rep_p))
    assert log_loss(y, p, w) == pytest.approx(log_loss(rep_y, rep_p))
    assert ece(y, p, 2, w) == pytest.approx(ece(rep_y, rep_p, 2))


def test_n_effective() -> None:
    assert n_effective(n_sessions=64, minutes_in_window=315, horizon_minutes=90) == 64 * 3


def test_session_bootstrap_respects_within_session_dependence() -> None:
    """Rows within a session are identical copies (perfect intraday dependence). The CI of the
    mean must reflect n_sessions, not n_rows: half-width ~ 1.96 * sigma / sqrt(n_sessions)."""
    rng = np.random.default_rng(0)
    n_sess, rows, sigma = 200, 50, 1.0
    session_means = rng.normal(0.0, sigma, n_sess)
    sessions = np.repeat(np.arange(n_sess), rows)
    values = np.repeat(session_means, rows)
    lo, hi = session_bootstrap_ci(
        sessions, lambda w: float(np.average(values, weights=w)), reps=2000, seed=1, level=0.95
    )
    expected_half = 1.96 * session_means.std(ddof=1) / math.sqrt(n_sess)
    assert (hi - lo) / 2 == pytest.approx(expected_half, rel=0.15)
    naive_half = 1.96 * values.std(ddof=1) / math.sqrt(len(values))
    assert (hi - lo) / 2 > 3 * naive_half  # row-level CI would be far too narrow


def test_session_bootstrap_is_reproducible() -> None:
    sessions = np.repeat(np.arange(30), 4)
    vals = np.arange(120, dtype=float)

    def stat(w: np.ndarray) -> float:
        return float(np.average(vals, weights=w))

    assert session_bootstrap_ci(sessions, stat, 500, 7, 0.95) == session_bootstrap_ci(
        sessions, stat, 500, 7, 0.95
    )


def test_auc_hand_computed_and_ties() -> None:
    from qqq1dte.models.metrics import auc  # noqa: PLC0415

    # pairs (pos, neg): (0.35 > 0.1), (0.35 < 0.4), (0.8 > 0.1), (0.8 > 0.4) -> 3/4
    assert auc(np.array([0, 0, 1, 1]), np.array([0.1, 0.4, 0.35, 0.8])) == pytest.approx(0.75)
    assert auc(np.array([0, 1]), np.array([0.5, 0.5])) == pytest.approx(0.5)  # tie = 1/2
    assert auc(np.array([0, 1, 1]), np.array([0.2, 0.2, 0.9])) == pytest.approx(0.75)
    with pytest.raises(ValueError, match="both classes"):
        auc(np.array([1, 1]), np.array([0.2, 0.3]))
