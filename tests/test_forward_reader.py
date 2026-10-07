"""ForwardWindowReader: the only object that exposes data after T, and only within (start, end]."""

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from qqq1dte.core.pit import ForwardWindowReader

T0 = datetime(2025, 3, 11, 15, 0, tzinfo=UTC)


def frame() -> pl.DataFrame:
    return pl.DataFrame(
        {"available_at": [T0 + timedelta(minutes=k) for k in range(-2, 5)], "v": list(range(7))},
        schema={"available_at": pl.Datetime("ns", "UTC"), "v": pl.Int64},
    )


def test_window_is_half_open_start_exclusive_end_inclusive() -> None:
    r = ForwardWindowReader({"q": frame()}, start=T0, end=T0 + timedelta(minutes=2))
    assert r.get("q")["v"].to_list() == [3, 4]  # minutes +1, +2


def test_end_before_start_rejected() -> None:
    with pytest.raises(ValueError, match="end"):
        ForwardWindowReader({"q": frame()}, start=T0, end=T0 - timedelta(minutes=1))


def test_requires_utc_available_at() -> None:
    with pytest.raises(ValueError, match="available_at"):
        ForwardWindowReader({"q": pl.DataFrame({"v": [1]})}, start=T0, end=T0)
