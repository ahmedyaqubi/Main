"""Quote cursor (T-BT-05): moves forward only and never returns a quote later than the clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from qqq1dte.core.clock import ClockError, SimClock
from qqq1dte.execution_sim.cursor import QuoteCursor

T0 = datetime(2025, 3, 11, 15, 0, tzinfo=UTC)
DT = pl.Datetime("ns", "UTC")


def recs() -> pl.DataFrame:
    rows = [
        {
            "symbol": "X",
            "available_at": T0 + timedelta(minutes=k),
            "bid": 1.0 + k / 100,
            "ask": 1.02 + k / 100,
            "bid_sz": 5,
            "ask_sz": 5,
            "rejected": k == 2,
        }
        for k in range(5)
    ]
    return pl.DataFrame(
        rows,
        schema={
            "symbol": pl.String,
            "available_at": DT,
            "bid": pl.Float64,
            "ask": pl.Float64,
            "bid_sz": pl.Int64,
            "ask_sz": pl.Int64,
            "rejected": pl.Boolean,
        },
    )


def test_bt_05_never_returns_a_quote_later_than_the_clock() -> None:
    clock = SimClock(T0 - timedelta(minutes=1))
    c = QuoteCursor(recs(), clock)
    assert c.advance_to(T0 - timedelta(seconds=1)) == [] and c.latest is None
    new = c.advance_to(T0 + timedelta(minutes=1, seconds=30))
    assert [r.available_at for r in new] == [T0, T0 + timedelta(minutes=1)]
    assert c.latest is not None and c.latest.available_at <= clock.now
    new = c.advance_to(T0 + timedelta(minutes=3))
    assert [(r.available_at, r.rejected) for r in new] == [
        (T0 + timedelta(minutes=2), True),
        (T0 + timedelta(minutes=3), False),
    ]
    assert c.latest is not None and c.latest.bid == pytest.approx(1.03)


def test_bt_05_cursor_cannot_move_backward() -> None:
    clock = SimClock(T0)
    c = QuoteCursor(recs(), clock)
    c.advance_to(T0 + timedelta(minutes=3))
    with pytest.raises(ClockError):
        c.advance_to(T0 + timedelta(minutes=1))


def test_shared_clock_ahead_of_cursor_is_rejected() -> None:
    clock = SimClock(T0)
    c = QuoteCursor(recs(), clock)
    clock.advance_to(T0 + timedelta(minutes=4))
    with pytest.raises(ClockError):
        c.advance_to(T0 + timedelta(minutes=2))  # the shared clock is already later


def test_records_must_be_one_symbol_in_time_order() -> None:
    bad = recs().with_columns(symbol=pl.Series(["X", "Y", "X", "X", "X"]))
    with pytest.raises(ValueError, match="one symbol"):
        QuoteCursor(bad, SimClock(T0))
    with pytest.raises(ValueError, match="order"):
        QuoteCursor(recs().reverse(), SimClock(T0))
