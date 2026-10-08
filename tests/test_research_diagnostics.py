"""M19R diagnostics: implied-move benchmark inputs and fit (D1), lift tables (D2), feature-group
declaration (D3). Synthetic data with exact answers."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, time
from statistics import NormalDist

import numpy as np
import polars as pl
import pytest

from qqq1dte.calibration.metrics import wilson_ci
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import ET
from qqq1dte.features.engine import FEATURE_NAMES
from qqq1dte.models.implied import ImpliedBenchmark, implied_inputs
from qqq1dte.models.lift import lift_table

CFG = load_config()
CAL = TradingCalendar(CFG)
D = date(2025, 3, 11)  # a full session (close 16:00, forced exit 15:50)


def _ts(hh: int, mm: int) -> datetime:
    return datetime.combine(D, time(hh, mm), tzinfo=ET).astimezone(UTC)


def _rows(times: list[datetime], straddle: list[float | None]) -> pl.DataFrame:
    return pl.DataFrame(
        {"session_date": [D] * len(times), "prediction_ts": times, "straddle_move": straddle},
        schema={
            "session_date": pl.Date,
            "prediction_ts": pl.Datetime("ns", "UTC"),
            "straddle_move": pl.Float64,
        },
    )


def test_implied_inputs_hand_computed() -> None:
    x = implied_inputs(_rows([_ts(11, 0), _ts(15, 0)], [0.01, 0.01]), 0.0025, CAL, CFG)
    sigma = 0.01 * math.sqrt(math.pi / 2)  # ATM straddle ~ sigma sqrt(tau) S sqrt(2/pi)
    assert x[0, 0] == pytest.approx(math.log(0.0025 / sigma))
    assert x[0, 1] == pytest.approx(math.log(90))  # window: min(T + 90, 15:50)
    assert x[0, 2] == pytest.approx(math.log(300 + 390))  # to today's close + next session
    assert x[1, 1] == pytest.approx(math.log(50)) and x[1, 2] == pytest.approx(math.log(60 + 390))


def test_missing_straddle_falls_back_to_the_training_base_rate() -> None:
    rng = np.random.default_rng(0)
    n = 4000
    times = [_ts(10 + (i % 5), 0) for i in range(n)]
    straddle = list(rng.uniform(0.006, 0.02, n))
    rows = _rows(times, straddle)
    y = rng.random(n) < 0.3
    b = ImpliedBenchmark.fit(rows, y.astype(float), 0.0025, CAL, CFG)
    test = _rows([_ts(11, 0)], [None])
    assert b.predict(test, CAL, CFG)[0] == pytest.approx(y.mean())


def test_benchmark_learns_the_theoretical_touch_relation() -> None:
    """y ~ Bernoulli(2(1 - Phi(z))), z = m / (sigma_exp sqrt(window / tau_exp)): the fitted
    coefficients have the theoretical signs (move up -> less touch, window up -> more,
    time to expiry up -> less)."""
    rng = np.random.default_rng(1)
    n = 40_000
    hh = rng.integers(10, 15, n)
    times = [_ts(int(h), 0) for h in hh]
    straddle = rng.uniform(0.004, 0.025, n)
    rows = _rows(times, list(straddle))
    x = implied_inputs(rows, 0.0025, CAL, CFG)
    z = np.exp(x[:, 0] - 0.5 * x[:, 1] + 0.5 * x[:, 2])
    p = 2 * (1 - np.array([NormalDist().cdf(v) for v in z]))
    y = (rng.random(n) < p).astype(float)
    b = ImpliedBenchmark.fit(rows, y, 0.0025, CAL, CFG)
    assert b.coef[0] < 0 and b.coef[1] > 0 and b.coef[2] < 0
    pred = b.predict(rows, CAL, CFG)
    assert np.mean((pred - p) ** 2) < 0.002  # close to the true probabilities


def test_lift_table_hand_computed() -> None:
    score = np.arange(10, dtype=float)  # 0..9
    y = np.array([0, 0, 0, 0, 0, 1, 0, 1, 1, 1], dtype=float)
    rows = lift_table(y, score, deciles=False, top=[0.8, 0.5], level=0.95)
    top20, top50 = rows
    assert (top20["bucket"], top20["n"], top20["observed"]) == ("top 20%", 2, 1.0)
    assert (top50["n"], top50["observed"]) == (5, 0.8)
    assert (top50["wilson_lo"], top50["wilson_hi"]) == pytest.approx(wilson_ci(0.8, 5, 0.95))
    deciles = lift_table(y, score, deciles=True, top=[], level=0.95)
    assert [r["n"] for r in deciles] == [1] * 10 and deciles[-1]["observed"] == 1.0


def test_feature_groups_cover_every_feature_exactly_once() -> None:
    groups = CFG.research.feature_groups
    flat = [f for g in groups.values() for f in g]
    assert sorted(flat) == sorted(FEATURE_NAMES) and len(flat) == len(set(flat))
