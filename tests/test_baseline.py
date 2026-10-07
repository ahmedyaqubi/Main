"""Model 0 (spec Phase 1J): unconditional rate and shrunk conditional rate per
(time-of-day bucket x VIX tercile), fit on training rows only. Synthetic data, exact answers."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
import pytest

from qqq1dte.core.config import Baseline
from qqq1dte.models.baseline import fit_baseline, tod_bucket

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
CFG = Baseline(
    tod_bucket_starts=[time(9, 45), time(11, 0), time(13, 0)],
    vix_quantiles=[1 / 3, 2 / 3],
    shrinkage_prior_n=50,
)


def _ts(d: date, hh: int, mm: int) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=ET).astimezone(UTC)


def _frame(rows: list[tuple[date, datetime, float | None, int]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={
            "session_date": pl.Date,
            "prediction_ts": pl.Datetime("us", "UTC"),
            "vix": pl.Float64,
            "y": pl.Int8,
        },
        orient="row",
    )


def test_tod_bucket_uses_new_york_wall_clock() -> None:
    d = date(2024, 7, 1)  # EDT: 09:45 ET = 13:45 UTC
    ts = pl.Series([_ts(d, 9, 45), _ts(d, 10, 59), _ts(d, 11, 0), _ts(d, 13, 0), _ts(d, 15, 0)])
    assert tod_bucket(ts, CFG.tod_bucket_starts).to_list() == [0, 0, 1, 2, 2]
    w = date(2024, 1, 2)  # EST: same wall clock, different UTC offset
    assert tod_bucket(pl.Series([_ts(w, 11, 0)]), CFG.tod_bucket_starts).to_list() == [1]


def _train() -> pl.DataFrame:
    # Six sessions, VIX 10..15 -> cuts at quantiles 1/3, 2/3 = 11.6667, 13.3333 (linear)
    rows = []
    for i, d in enumerate(date(2024, 3, k) for k in (4, 5, 6, 7, 8, 11)):
        vix = 10.0 + i
        rows.append((d, _ts(d, 10, 0), vix, 1))  # bucket 0: always up
        rows.append((d, _ts(d, 14, 0), vix, 0))  # bucket 2: always down
    return _frame(rows)


def test_fit_rates_and_vix_cuts_exact() -> None:
    m = fit_baseline(_train(), CFG)
    assert m.p0 == pytest.approx(0.5)
    assert m.vix_cuts == pytest.approx((10 + 5 / 3, 10 + 10 / 3))
    # cell (tod 0, tercile 0): sessions with VIX 10, 11 -> k = 2, n = 2
    assert m.cell_rate(0, 0) == pytest.approx((2 + 50 * 0.5) / (2 + 50))
    assert m.cell_rate(2, 1) == pytest.approx((0 + 50 * 0.5) / (2 + 50))
    assert m.cell_rate(1, 2) == pytest.approx(0.5)  # empty cell -> prior p0


def test_predictions_conditional_and_unconditional() -> None:
    m = fit_baseline(_train(), CFG)
    d = date(2024, 6, 3)
    test = _frame(
        [(d, _ts(d, 10, 0), 10.5, 1), (d, _ts(d, 14, 0), 20.0, 0), (d, _ts(d, 10, 0), None, 1)]
    )
    np.testing.assert_allclose(m.predict_unconditional(test), [0.5, 0.5, 0.5])
    np.testing.assert_allclose(
        m.predict(test), [27 / 52, 25 / 52, 0.5]
    )  # null VIX -> unconditional rate


def test_vix_cuts_ignore_test_data_and_duplicate_rows() -> None:
    """Cut points use one VIX value per training session only (T-LEAK-11 analogue)."""
    m1 = fit_baseline(_train(), CFG)
    d = date(2024, 3, 12)
    heavy = pl.concat([_train(), _frame([(d, _ts(d, 9, 45 + k), 10.0, 1) for k in range(10)])])
    m2 = fit_baseline(heavy, CFG)
    # 7 sessions now (VIX 10,10,11,...,15): cuts move by the one added session, not 10 rows
    assert m2.vix_cuts == pytest.approx(
        tuple(np.quantile([10, 10, 11, 12, 13, 14, 15], [1 / 3, 2 / 3]))
    )
    assert m1.vix_cuts != m2.vix_cuts
    # predicting on any test frame never changes the fitted model
    before = (m1.p0, m1.vix_cuts)
    m1.predict(_frame([(d, _ts(d, 10, 0), 99.0, 1)]))
    assert (m1.p0, m1.vix_cuts) == before


def test_null_targets_and_null_vix_rows_in_training() -> None:
    d = date(2024, 3, 13)
    extra = _frame([(d, _ts(d, 10, 0), None, 1), (d, _ts(d, 10, 30), 12.0, None)])  # type: ignore[list-item]
    m = fit_baseline(pl.concat([_train(), extra]), CFG)
    # unresolved target (null y) is excluded; null-VIX row counts towards p0 only
    assert m.p0 == pytest.approx(7 / 13)
    assert m.n_train == 13
