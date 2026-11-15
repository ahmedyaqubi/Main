"""ADR-0021 D1: earnings sessions of the single stocks.

`configs/reference/earnings_calendar.csv` holds, per ticker, each results date (from the
company's 8-K Item 2.02 on SEC EDGAR) and `available_at_et`: when that date was verifiably
public beforehand (a dated company notice, a timestamped SEC filing, or a timestamped archive
capture). An empty `available_at_et` means advance knowledge is NOT verified.

D1 excludes the earnings session and `earnings_exclusion_sessions` on each side. Excluding the
session before the release needs the date in advance, so an exclusion is built only from dates
known by the open of the first session they exclude (rule 2); anything else raises.
Rows with another event (TSLA `DELIVERIES`) are listed for the record and never exclude.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.timeutil import ET

DT = pl.Datetime("us", "UTC")
EARNINGS = "EARNINGS"


class UnverifiedEarningsDateError(ValueError):
    """An earnings date whose advance knowledge is not verified, or came too late."""


def earnings_table(path: Path) -> pl.DataFrame:
    """The calendar file -> ticker, event, session_date, available_at (UTC; null = unverified)."""
    raw = pl.read_csv(path, schema_overrides={"available_at_et": pl.String})
    avail = [
        datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=ET).astimezone(UTC) if s else None
        for s in raw["available_at_et"].to_list()
    ]
    return pl.DataFrame(
        {
            "ticker": raw["ticker"],
            "event": raw["event"],
            "session_date": [date.fromisoformat(s) for s in raw["session_date"].to_list()],
            "available_at": avail,
        },
        schema={"ticker": pl.String, "event": pl.String, "session_date": pl.Date,
                "available_at": DT},
    )  # fmt: skip


def earnings_exclusions(
    table: pl.DataFrame, ticker: str, cal: TradingCalendar, n_each_side: int
) -> dict[date, date]:
    """Excluded session -> the earnings date that excludes it, for one ticker."""
    out: dict[date, date] = {}
    rows = table.filter((pl.col("ticker") == ticker) & (pl.col("event") == EARNINGS))
    for r in rows.sort("session_date").iter_rows(named=True):
        e: date = r["session_date"]
        earlier = cal.sessions(e - timedelta(days=10 * (n_each_side + 1)), e - timedelta(days=1))
        before = earlier[len(earlier) - n_each_side :] if n_each_side else []
        after: list[date] = []
        d = e
        for _ in range(n_each_side):
            d = cal.next_session(d)
            after.append(d)
        first = min([e, *before])
        open_, _ = cal.open_close(first)
        known = r["available_at"]
        if known is None:
            raise UnverifiedEarningsDateError(f"{ticker} {e}: advance knowledge not verified")
        if known > open_:
            raise UnverifiedEarningsDateError(
                f"{ticker} {e}: known {known}, after the open of {first}"
            )
        for x in (*before, e, *after):
            out[x] = e
    return out
