"""ADR-0021 D1: earnings sessions of the single stocks, from a dated, sourced calendar file.
The exclusion must be knowable beforehand (rule 2): every date needs a verified `available_at`
no later than the open of the first session it excludes."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.validation.earnings_calendar import (
    UnverifiedEarningsDateError,
    earnings_exclusions,
    earnings_table,
)

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "configs" / "reference" / "earnings_calendar.csv"
CFG = load_config()
CAL = TradingCalendar(CFG)
DT = pl.Datetime("us", "UTC")


def _table(rows: list[tuple[str, str, date, datetime | None]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={"ticker": pl.String, "event": pl.String, "session_date": pl.Date,
                "available_at": DT},
        orient="row",
    )  # fmt: skip


def test_exclusion_is_the_earnings_session_and_n_sessions_each_side() -> None:
    # Wednesday 2024-05-22; known three weeks ahead
    t = _table([("XYZ", "EARNINGS", date(2024, 5, 22), datetime(2024, 5, 2, 4, tzinfo=UTC))])
    assert earnings_exclusions(t, "XYZ", CAL, 1) == {
        date(2024, 5, 21): date(2024, 5, 22),
        date(2024, 5, 22): date(2024, 5, 22),
        date(2024, 5, 23): date(2024, 5, 22),
    }
    # the neighbours are sessions, not calendar days: Friday -> Monday across a weekend
    t = _table([("XYZ", "EARNINGS", date(2024, 5, 17), datetime(2024, 5, 2, 4, tzinfo=UTC))])
    assert sorted(earnings_exclusions(t, "XYZ", CAL, 1)) == [
        date(2024, 5, 16), date(2024, 5, 17), date(2024, 5, 20)]  # fmt: skip
    assert earnings_exclusions(t, "XYZ", CAL, 0) == {date(2024, 5, 17): date(2024, 5, 17)}


def test_only_earnings_rows_of_the_ticker_exclude() -> None:
    t = _table(
        [
            ("XYZ", "DELIVERIES", date(2024, 7, 2), datetime(2024, 7, 2, 13, 25, tzinfo=UTC)),
            ("ABC", "EARNINGS", date(2024, 5, 22), datetime(2024, 5, 2, 4, tzinfo=UTC)),
        ]
    )
    assert earnings_exclusions(t, "XYZ", CAL, 1) == {}


def test_a_date_without_verified_advance_knowledge_is_refused() -> None:
    t = _table([("XYZ", "EARNINGS", date(2024, 5, 22), None)])
    with pytest.raises(UnverifiedEarningsDateError, match="2024-05-22"):
        earnings_exclusions(t, "XYZ", CAL, 1)
    # known only after the first excluded session (2024-05-21) opened: look-ahead
    late = datetime(2024, 5, 21, 13, 31, tzinfo=UTC)  # 09:31 ET
    t = _table([("XYZ", "EARNINGS", date(2024, 5, 22), late)])
    with pytest.raises(UnverifiedEarningsDateError, match="2024-05-22"):
        earnings_exclusions(t, "XYZ", CAL, 1)
    on_time = datetime(2024, 5, 21, 13, 30, tzinfo=UTC)  # exactly the open: allowed
    t = _table([("XYZ", "EARNINGS", date(2024, 5, 22), on_time)])
    assert len(earnings_exclusions(t, "XYZ", CAL, 1)) == 3


def test_calendar_file_nvda_and_tsla_verified_aapl_not() -> None:
    t = earnings_table(PATH)
    e = t.filter(pl.col("event") == "EARNINGS")
    counts = dict(e.group_by("ticker").len().iter_rows())
    assert counts == {"NVDA": 10, "TSLA": 10, "AAPL": 10}
    assert all(CAL.is_session(d) for d in e["session_date"].to_list())
    n = CFG.study_options_day.earnings_exclusion_sessions
    for ticker in ("NVDA", "TSLA"):
        assert len(earnings_exclusions(t, ticker, CAL, n)) == 30  # no overlaps
    # AAPL: advance knowledge verified for 5 of 10 dates only -> refused (D1, rule 9)
    aapl = e.filter(pl.col("ticker") == "AAPL")
    assert aapl["available_at"].null_count() == 5
    with pytest.raises(UnverifiedEarningsDateError):
        earnings_exclusions(t, "AAPL", CAL, n)
    # TSLA delivery reports are listed, never excluded
    assert t.filter(pl.col("event") == "DELIVERIES")["ticker"].unique().to_list() == ["TSLA"]
    assert t.filter(pl.col("event") == "DELIVERIES").height == 11
