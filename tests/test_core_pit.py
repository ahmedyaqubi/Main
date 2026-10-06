"""T-LEAK-01/02 (AsOfReader), T-CFG-02 (config hash), SimClock monotonicity."""

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from qqq1dte.core.clock import ClockError, SimClock
from qqq1dte.core.config import config_hash, load_config
from qqq1dte.core.pit import AsOfReader, LookAheadError
from qqq1dte.core.timeutil import NaiveDatetimeError

T0 = datetime(2025, 3, 10, 14, 0, tzinfo=UTC)


def frame(offsets_s: list[int]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "available_at": [T0 + timedelta(seconds=s) for s in offsets_s],
            "value": list(range(len(offsets_s))),
        },
        schema={"available_at": pl.Datetime("ns", "UTC"), "value": pl.Int64},
    )


# T-LEAK-01 ---------------------------------------------------------------------------
@settings(max_examples=200, deadline=None)
@given(
    offsets=st.lists(st.integers(-3600, 3600), min_size=0, max_size=50),
    cutoff_s=st.integers(-3600, 3600),
)
def test_leak_01_reader_returns_exactly_rows_available_at_or_before_cutoff(
    offsets: list[int], cutoff_s: int
) -> None:
    cutoff = T0 + timedelta(seconds=cutoff_s)
    reader = AsOfReader({"bars": frame(offsets)}, cutoff)
    got = reader.get("bars")
    expected = sorted(i for i, s in enumerate(offsets) if s <= cutoff_s)
    assert sorted(got["value"].to_list()) == expected
    assert (got["available_at"] <= cutoff).all()


def test_leak_01_boundary_is_inclusive() -> None:
    reader = AsOfReader({"bars": frame([0, 1])}, T0)
    assert reader.get("bars")["value"].to_list() == [0]


# T-LEAK-02 ---------------------------------------------------------------------------
def test_leak_02_window_past_cutoff_raises() -> None:
    reader = AsOfReader({"bars": frame([0, 60, 120])}, T0 + timedelta(seconds=60))
    assert reader.window("bars", T0, T0 + timedelta(seconds=60))["value"].to_list() == [1]
    with pytest.raises(LookAheadError):
        reader.window("bars", T0, T0 + timedelta(seconds=61))


def test_leak_02_latest_after_cutoff_raises() -> None:
    reader = AsOfReader({"bars": frame([0, 60])}, T0)
    assert reader.latest("bars")["value"].to_list() == [0]
    with pytest.raises(LookAheadError):
        reader.latest("bars", at=T0 + timedelta(seconds=1))


def test_leak_02_naive_cutoff_rejected() -> None:
    with pytest.raises(NaiveDatetimeError):
        AsOfReader({"bars": frame([0])}, datetime(2025, 3, 10, 14, 0))  # noqa: DTZ001


def test_leak_02_table_without_utc_available_at_rejected() -> None:
    no_col = pl.DataFrame({"value": [1]})
    with pytest.raises(ValueError, match="available_at"):
        AsOfReader({"x": no_col}, T0)
    naive_col = pl.DataFrame({"available_at": [datetime(2025, 3, 10)], "value": [1]})  # noqa: DTZ001
    with pytest.raises(ValueError, match="UTC"):
        AsOfReader({"x": naive_col}, T0)


def test_leak_02_unknown_table_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        AsOfReader({}, T0).get("missing")


# SimClock --------------------------------------------------------------------------------
def test_clock_only_moves_forward() -> None:
    clock = SimClock(T0)
    clock.advance_to(T0 + timedelta(minutes=1))
    assert clock.now == T0 + timedelta(minutes=1)
    clock.advance_to(clock.now)  # staying put is allowed
    with pytest.raises(ClockError):
        clock.advance_to(T0)


# T-CFG-02 --------------------------------------------------------------------------------
def test_cfg_02_hash_ignores_key_order_and_detects_changes() -> None:
    a = {"x": 1, "y": {"b": [1, 2], "a": "s"}}
    b = {"y": {"a": "s", "b": [1, 2]}, "x": 1}
    assert config_hash(a) == config_hash(b)
    assert config_hash(a) != config_hash({**a, "x": 2})
    assert len(config_hash(a)) == 64


def test_cfg_02_loaded_config_hash_is_stable() -> None:
    cfg = load_config()
    assert config_hash(cfg.model_dump(mode="json")) == config_hash(
        load_config().model_dump(mode="json")
    )
