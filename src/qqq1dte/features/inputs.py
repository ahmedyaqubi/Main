"""Input tables for the feature engine. Every table carries `available_at` (UTC).

This is the only feature code that reads files or derives tables. Feature functions
(`features.defs`) never see these frames directly: they receive an `AsOfReader` built from them
(ARCHITECTURE §4). Derived tables (daily stats, volume profiles) are stamped with the maximum
`available_at` of the rows they summarize, so a session's daily row appears only after its close
(T-LEAK-08).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config
from qqq1dte.core.timeutil import ET
from qqq1dte.validation.records import standard_contract

DT = pl.Datetime("ns", "UTC")
STAT_OPEN_INTEREST = 9


def _rth(bars: pl.DataFrame) -> pl.DataFrame:
    return bars.filter(pl.col("is_rth")).sort("ts")


def daily_stats(bars: pl.DataFrame) -> pl.DataFrame:
    """Per-session RTH open/high/low/close/volume; available when the last RTH bar completes."""
    return (
        _rth(bars)
        .group_by("session_date", maintain_order=True)
        .agg(
            open=pl.col("open").first(),
            high=pl.col("high").max(),
            low=pl.col("low").min(),
            close=pl.col("close").last(),
            volume=pl.col("volume").sum(),
            available_at=pl.col("available_at").max(),
        )
        .sort("session_date")
    )


def minute_profile(bars: pl.DataFrame, cal: TradingCalendar) -> pl.DataFrame:
    """Cumulative RTH volume after m completed bars, per session (a daily product: available
    at the session's close)."""
    rth = _rth(bars).filter(
        pl.col("session_date").map_elements(cal.is_session, return_dtype=pl.Boolean)
    )
    return (
        rth.with_columns(
            minute=pl.col("ts").rank("ordinal").over("session_date").cast(pl.Int64),
            cum_volume=pl.col("volume").cum_sum().over("session_date"),
            available_at=pl.col("available_at").max().over("session_date"),
        )
        .select("session_date", "minute", "cum_volume", "available_at")
        .sort(["session_date", "minute"])
    )


def vix_table(path: Path, cfg: Phase1Config) -> pl.DataFrame:
    """Cboe daily VIX history; a date's close is visible from features.vix_available_time ET."""
    raw = pl.read_csv(path)
    t = cfg.features.vix_available_time
    dates = [
        datetime.strptime(s, "%m/%d/%Y").replace(tzinfo=ET).date() for s in raw["DATE"].to_list()
    ]
    avail = [datetime.combine(d, t, tzinfo=ET).astimezone(UTC) for d in dates]
    return pl.DataFrame(
        {"date": dates, "close": raw["CLOSE"].cast(pl.Float64), "available_at": avail},
        schema={"date": pl.Date, "close": pl.Float64, "available_at": DT},
    )


def macro_table(path: Path) -> pl.DataFrame:
    """configs/reference/macro_calendar.csv -> event, session_date, available_at (UTC)."""
    raw = pl.read_csv(path)
    avail = [
        datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=ET).astimezone(UTC)
        for s in raw["available_at_et"].to_list()
    ]
    return pl.DataFrame(
        {
            "event": raw["event"],
            "session_date": [date.fromisoformat(s) for s in raw["session_date"].to_list()],
            "available_at": avail,
        },
        schema={"event": pl.String, "session_date": pl.Date, "available_at": DT},
    )


def open_interest_table(
    stats: pl.DataFrame, cal: TradingCalendar, cfg: Phase1Config
) -> pl.DataFrame:
    """OPRA OI (statistics stat_type 9) received on session D reflects D-1's close; visible from
    max(receipt, D at pit.oi_available_time ET) (spec §7, T-LEAK-07). Not used by f1 (ADR-0004)."""
    oi = stats.filter(pl.col("stat_type") == STAT_OPEN_INTEREST)
    rows = []
    for ts, sym, q in zip(oi["ts_recv"].to_list(), oi["symbol"].to_list(),
                          oi["quantity"].to_list(), strict=True):  # fmt: skip
        d = ts.astimezone(ET).date()
        gate = datetime.combine(d, cfg.pit.oi_available_time, tzinfo=ET).astimezone(UTC)
        prev = cal.sessions(date(d.year - 1, 1, 1), d)
        as_of = [s for s in prev if s < d][-1]
        rows.append({"symbol": sym, "open_interest": q, "as_of_session": as_of,
                     "available_at": max(ts, gate)})  # fmt: skip
    return pl.DataFrame(
        rows,
        schema={"symbol": pl.String, "open_interest": pl.Int64, "as_of_session": pl.Date,
                "available_at": DT},
    )  # fmt: skip


def option_quotes_table(cleaned: pl.DataFrame, rejected: pl.DataFrame) -> pl.DataFrame:
    """Cleaned and rejected option records with a validity flag. A rejected record is a real
    minute without a usable quote, so it hides any older quote (M4 open issue 1)."""
    good = cleaned.select(
        symbol=pl.col("symbol"),
        available_at=pl.col("available_at"),
        bid=pl.col("bid"),
        ask=pl.col("ask"),
        valid=pl.col("bid").is_not_null()
        & pl.col("ask").is_not_null()
        & (pl.col("bid") > 0)
        & (pl.col("bid") <= pl.col("ask")),
    )
    bad = rejected.select(
        symbol=pl.col("symbol"),
        available_at=pl.col("ts"),
        bid=pl.lit(None, pl.Float64),
        ask=pl.lit(None, pl.Float64),
        valid=pl.lit(False),
    )
    return pl.concat([good, bad]).sort(["symbol", "available_at"])


def chain_table(defs: pl.DataFrame, cfg: Phase1Config) -> pl.DataFrame:
    """Standard contracts (ADR-0005) with when each definition became known."""
    return defs.filter(standard_contract(cfg)).select(
        "session_date", "raw_symbol", "expiration", "strike", "right", "available_at"
    )


def qqq_reference(
    bars: pl.DataFrame, t: datetime, cal: TradingCalendar, session: date
) -> tuple[float | None, datetime | None]:
    """Price "at time t" from bars already restricted to the reader's cutoff: close of the last
    RTH bar of `session` complete by t; at the open itself, the first RTH bar's opening price;
    before the open, unavailable. Returns (price, available_at)."""
    open_, _ = cal.open_close(session)
    if t < open_:
        return None, None
    rth = bars.filter((pl.col("session_date") == session) & pl.col("is_rth")).sort("ts")
    done = rth.filter(pl.col("available_at") <= t)
    if done.height:
        row = done.row(-1, named=True)
        return float(row["close"]), row["available_at"]
    if rth.height:  # t is the open: the opening price, known once the first bar is visible
        row = rth.row(0, named=True)
        return float(row["open"]), row["available_at"]
    return None, None


def quote_reference(
    quotes: pl.DataFrame,
    t: datetime,
    cal: TradingCalendar,
    session: date,
    max_age_s: int,
) -> tuple[float | None, datetime | None, str | None]:
    """NBBO mid "at time t" from quotes already restricted to the reader's cutoff (f2 cross-
    market prices, ADR-0004 amendment). The latest record with available_at <= t defines the
    book. It must be two-sided with 0 < bid <= ask and at most max_age_s old, otherwise the price
    is unavailable. There is no fallback to an older quote. Before the open: unavailable.
    Returns (mid, available_at, missing_reason)."""
    open_, _ = cal.open_close(session)
    if t < open_:
        return None, None, "window_before_open"
    q = quotes.filter(pl.col("available_at") <= t).sort("available_at")
    if not q.height:
        return None, None, "no_valid_quote"
    row = q.row(-1, named=True)
    bid, ask, at = row["bid"], row["ask"], row["available_at"]
    if (t - at).total_seconds() > max_age_s:
        return None, None, "no_valid_quote"
    if bid is None or ask is None or not 0 < bid <= ask:
        return None, None, "no_valid_quote"
    return (bid + ask) / 2, at, None
