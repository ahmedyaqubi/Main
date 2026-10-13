"""M25 (ADR-0016 D2-D3): Tiingo / FRED parsing and the development-only holdout lock."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from qqq1dte.ingestion.etf_data import (
    HoldoutLockedError,
    dev_only,
    parse_fred,
    parse_tiingo,
    with_holdout,
)

TIINGO = [
    {"date": "2015-12-30T00:00:00.000Z", "open": 10.0, "close": 11.0, "adjOpen": 9.0,
     "adjClose": 9.9, "divCash": 0.0, "splitFactor": 1.0},
    {"date": "2015-12-31T00:00:00.000Z", "open": 11.0, "close": 12.0, "adjOpen": 9.9,
     "adjClose": 10.8, "divCash": 0.1, "splitFactor": 1.0},
    {"date": "2016-01-04T00:00:00.000Z", "open": 12.0, "close": 13.0, "adjOpen": 10.8,
     "adjClose": 11.7, "divCash": 0.0, "splitFactor": 1.0},
]  # fmt: skip


def test_parse_tiingo() -> None:
    df = parse_tiingo(TIINGO, "SPY")
    assert df.columns == ["date", "ticker", "open", "close", "adj_open", "adj_close", "div_cash",
                          "split_factor"]  # fmt: skip
    assert df["date"].to_list() == [date(2015, 12, 30), date(2015, 12, 31), date(2016, 1, 4)]
    assert df["adj_close"].to_list() == [9.9, 10.8, 11.7]
    with pytest.raises(ValueError, match="duplicate"):
        parse_tiingo([TIINGO[0], TIINGO[0]], "SPY")


def test_parse_fred_missing_values_are_null_not_filled() -> None:
    for header in ("observation_date", "DATE"):
        csv = f"{header},DTB3\n2015-12-30,0.23\n2015-12-31,.\n2016-01-04,\n2016-01-05,0.20\n"
        df = parse_fred(csv, "DTB3")
        assert df["date"].to_list()[0] == date(2015, 12, 30)
        assert df["rate"].to_list() == [0.23, None, None, 0.20]


def test_holdout_lock() -> None:
    df = parse_tiingo(TIINGO, "SPY")
    dev = dev_only(df, date(2015, 12, 31))
    assert dev["date"].max() == date(2015, 12, 31)
    with pytest.raises(HoldoutLockedError):
        dev_only(df, date(2015, 12, 31), requested_end=date(2016, 1, 4))
    assert dev_only(pl.DataFrame(schema=df.schema), date(2015, 12, 31)).height == 0


def test_with_holdout_requires_an_adr_reference() -> None:
    df = pl.DataFrame({"date": [date(2015, 12, 31), date(2016, 1, 4), date(2026, 10, 1)]})
    with pytest.raises(HoldoutLockedError):
        with_holdout(df, date(2026, 9, 30), adr_ref="")
    out = with_holdout(df, date(2026, 9, 30), adr_ref="ADR-0019")
    assert out["date"].to_list() == [date(2015, 12, 31), date(2016, 1, 4)]
