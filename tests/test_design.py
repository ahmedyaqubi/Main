"""Model-input design (M8): wide pivot, weekday one-hot, train-only standardisation (T-LEAK-11),
mean fill with missing indicators, z clipping. Synthetic data with exact answers."""

from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import polars as pl
import pytest

from qqq1dte.models.design import fit_design, transform, wide_features

D = date(2024, 6, 3)


def _long(rows: list[tuple[int, str, float | None]]) -> pl.DataFrame:
    """rows: (minute offset, feature, value) for session D."""
    return pl.DataFrame(
        [
            (D, datetime(2024, 6, 3, 14, m, tzinfo=UTC), f, v, None if v is not None else "x")
            for m, f, v in rows
        ],
        schema={
            "session_date": pl.Date,
            "prediction_ts": pl.Datetime("ns", "UTC"),
            "feature_name": pl.String,
            "value": pl.Float64,
            "missing_reason": pl.String,
        },
        orient="row",
    )


def _train() -> pl.DataFrame:
    return wide_features(
        _long(
            [
                (0, "a", 1.0),
                (0, "b", 10.0),
                (0, "day_of_week", 0.0),
                (1, "a", 3.0),
                (1, "b", None),
                (1, "day_of_week", 2.0),
                (2, "a", 5.0),
                (2, "b", 30.0),
                (2, "day_of_week", 4.0),
            ]
        ),
        ["a", "b", "day_of_week"],
    )


def test_wide_pivot_and_weekday_one_hot() -> None:
    w = _train()
    assert w.columns == [
        "session_date",
        "prediction_ts",
        "a",
        "b",
        "dow_1",
        "dow_2",
        "dow_3",
        "dow_4",
    ]
    assert w["dow_2"].to_list() == [0.0, 1.0, 0.0]
    assert w["dow_4"].to_list() == [0.0, 0.0, 1.0]
    assert w["b"].to_list() == [10.0, None, 30.0]


def test_fit_design_statistics_equal_training_statistics_exactly() -> None:
    """T-LEAK-11: mean/std are the training-fold statistics (population std, nulls ignored)."""
    spec = fit_design(_train(), z_clip=5.0)
    stats = dict(zip(spec.columns, zip(spec.mean, spec.std, strict=True), strict=True))
    assert stats["a"] == pytest.approx((3.0, np.std([1.0, 3.0, 5.0])))
    assert stats["b"] == pytest.approx((20.0, 10.0))
    assert stats["dow_3"] == (0.0, 1.0)  # constant column: std set to 1 (no division by 0)
    assert spec.indicator_for == ("b",)  # only features with missing training values


def test_test_data_changes_nothing() -> None:
    spec = fit_design(_train(), z_clip=5.0)
    other = wide_features(
        _long([(9, "a", 1000.0), (9, "b", -50.0), (9, "day_of_week", 3.0)]),
        ["a", "b", "day_of_week"],
    )
    before = spec
    transform(spec, other)
    assert spec == before
    assert fit_design(_train(), z_clip=5.0) == spec


def test_transform_fill_indicator_and_clip() -> None:
    spec = fit_design(_train(), z_clip=1.0)
    x, fills = transform(spec, _train())
    sd_a = float(np.std([1.0, 3.0, 5.0]))
    assert spec.out_columns == ("a", "b", "dow_1", "dow_2", "dow_3", "dow_4", "missing_b")
    np.testing.assert_allclose(x[:, 0], np.clip([-2 / sd_a, 0.0, 2 / sd_a], -1, 1))
    np.testing.assert_allclose(x[:, 1], [-1.0, 0.0, 1.0])  # null -> train mean -> z = 0
    np.testing.assert_allclose(x[:, -1], [0.0, 1.0, 0.0])  # missing indicator
    assert fills == {"b": 1}


def test_missing_in_test_without_training_indicator_is_filled_and_counted() -> None:
    spec = fit_design(_train(), z_clip=5.0)
    t = wide_features(
        _long([(9, "a", None), (9, "b", 20.0), (9, "day_of_week", 1.0)]), ["a", "b", "day_of_week"]
    )
    x, fills = transform(spec, t)
    assert x[0, 0] == 0.0 and fills == {"a": 1}
    assert x.shape == (1, len(spec.out_columns))
