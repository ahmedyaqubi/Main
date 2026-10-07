"""Synthetic cleaned-layer tables for feature tests: simple linear paths with hand-checkable
values. Session D = 2025-03-11 (Tue); 15 prior sessions with flat daily ranges."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import polars as pl

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import ET
from qqq1dte.features.inputs import daily_stats, minute_profile

CFG = load_config()
CAL = TradingCalendar(CFG)
D = date(2025, 3, 11)
NEXT = date(2025, 3, 12)
PRIOR = CAL.sessions(date(2025, 2, 1), date(2025, 3, 10))[-15:]  # 15 prior sessions
DT = pl.Datetime("ns", "UTC")


def et(d: date, hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm, ss), tzinfo=ET).astimezone(UTC)


# QQQ: prior sessions flat (O 100, H 101, L 99, C 100.5, vol 100/min).
# Session D: RTH minute i has open 101 + 0.01 i, close 101 + 0.01 (i + 1),
# high = close + 0.02, low = open - 0.02, volume 200; plus one pre-market bar at 09:00.
def qqq_open(i: int) -> float:
    return 101 + 0.01 * i


def qqq_close(i: int) -> float:
    return 101 + 0.01 * (i + 1)


def _bar_rows(d: date, n: int, o, c, h, lo, vol: int, symbol: str) -> list[dict[str, object]]:  # type: ignore[no-untyped-def]
    rows = []
    for i in range(n):
        ts = et(d, 9, 30) + timedelta(minutes=i)
        rows.append({"session_date": d, "ts": ts, "available_at": ts + timedelta(minutes=1),
                     "open": o(i), "high": h(i), "low": lo(i), "close": c(i), "volume": vol,
                     "is_rth": True, "symbol": symbol})  # fmt: skip
    return rows


def qqq_bars() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for d in PRIOR:
        rows += _bar_rows(d, 390, lambda i: 100.0, lambda i: 100.5, lambda i: 101.0,
                          lambda i: 99.0, 100, "QQQ")  # fmt: skip
    pre = et(D, 9, 0)
    rows.append({"session_date": D, "ts": pre, "available_at": pre + timedelta(minutes=1),
                 "open": 150.0, "high": 150.0, "low": 150.0, "close": 150.0, "volume": 5,
                 "is_rth": False, "symbol": "QQQ"})  # fmt: skip
    rows += _bar_rows(D, 390, qqq_open, qqq_close, lambda i: qqq_close(i) + 0.02,
                      lambda i: qqq_open(i) - 0.02, 200, "QQQ")  # fmt: skip
    return _frame(rows)


# Cross-market on D: symbol-specific slopes (prices start at base, +slope per minute).
CROSS = {"SPY": (50.0, 0.02), "SOXX": (200.0, -0.03), "NVDA": (100.0, 0.05),
         "AMD": (80.0, 0.01), "AVGO": (150.0, -0.02), "TSM": (120.0, 0.04),
         "UUP": (28.0, 0.001), "IEF": (95.0, -0.005), "SHY": (82.0, 0.0005)}  # fmt: skip


def cross_close(sym: str, i: int) -> float:
    base, slope = CROSS[sym]
    return base + slope * (i + 1)


def cross_quotes() -> pl.DataFrame:
    """Cross-market NBBO (bbo-1m style, stamped at interval end): the record stamped 09:30 holds
    the pre-open book (mid = base); the record stamped open + (i + 1) min has mid =
    cross_close(sym, i), i.e. the same values as a bar closing then. Half-spread 0.005."""
    rows: list[dict[str, object]] = []
    for sym, (base, _) in CROSS.items():
        stamps = [(et(D, 9, 30), base)] + [
            (et(D, 9, 31) + timedelta(minutes=i), cross_close(sym, i)) for i in range(390)
        ]
        for ts, mid in stamps:
            rows.append(
                {
                    "session_date": D,
                    "symbol": sym,
                    "ts": ts,
                    "available_at": ts,
                    "bid": mid - 0.005,
                    "ask": mid + 0.005,
                }
            )
    return pl.DataFrame(
        rows,
        schema={
            "session_date": pl.Date,
            "symbol": pl.String,
            "ts": DT,
            "available_at": DT,
            "bid": pl.Float64,
            "ask": pl.Float64,
        },
    )


def _frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={"session_date": pl.Date, "ts": DT, "available_at": DT, "open": pl.Float64,
                "high": pl.Float64, "low": pl.Float64, "close": pl.Float64,
                "volume": pl.Int64, "is_rth": pl.Boolean, "symbol": pl.String},
    )  # fmt: skip


def vix_table() -> pl.DataFrame:
    rows = [{"date": d, "close": 15.5, "available_at": et(d, 18, 0)} for d in PRIOR]
    rows.append({"date": D, "close": 99.0, "available_at": et(D, 18, 0)})  # must stay hidden
    return pl.DataFrame(rows, schema={"date": pl.Date, "close": pl.Float64, "available_at": DT})


def macro_table() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {"event": "CPI", "session_date": D, "available_at": et(D, 8, 30)},
            {"event": "FOMC", "session_date": NEXT, "available_at": et(date(2024, 12, 31), 0, 0)},
        ],
        schema={"event": pl.String, "session_date": pl.Date, "available_at": DT},
    )


SPOT_BID, SPOT_ASK = 101.89, 101.91


def und_quotes() -> pl.DataFrame:
    """QQQ NBBO every minute 09:31..16:00 at a constant 101.89 / 101.91."""
    rows = [{"ts": et(D, 9, 31) + timedelta(minutes=k), "bid": SPOT_BID, "ask": SPOT_ASK}
            for k in range(390)]  # fmt: skip
    return pl.DataFrame(rows, schema={"ts": DT, "bid": pl.Float64, "ask": pl.Float64}).with_columns(
        available_at=pl.col("ts"), session_date=pl.lit(D)
    )


CALL, PUT = "QQQ   250312C00102000", "QQQ   250312P00101000"


def chain() -> pl.DataFrame:
    rows = []
    for k in (101.0, 102.0, 103.0):
        for r in ("C", "P"):
            rows.append({"session_date": D, "raw_symbol": f"QQQ   250312{r}{int(k * 1000):08d}",
                         "expiration": NEXT, "strike": k, "right": r,
                         "available_at": et(D, 6, 30)})  # fmt: skip
    return pl.DataFrame(
        rows,
        schema={"session_date": pl.Date, "raw_symbol": pl.String, "expiration": pl.Date,
                "strike": pl.Float64, "right": pl.String, "available_at": DT},
    )  # fmt: skip


def options() -> pl.DataFrame:
    """Frozen-rule quotes at 10:59 ET; later quotes at 11:01 must never be seen at 11:00."""
    rows = [
        {"symbol": CALL, "available_at": et(D, 10, 59), "bid": 0.50, "ask": 0.52, "valid": True},
        {"symbol": PUT, "available_at": et(D, 10, 59), "bid": 0.40, "ask": 0.42, "valid": True},
        {"symbol": CALL, "available_at": et(D, 11, 1), "bid": 9.00, "ask": 9.50, "valid": True},
        {"symbol": PUT, "available_at": et(D, 11, 1), "bid": 9.00, "ask": 9.50, "valid": True},
    ]
    return pl.DataFrame(
        rows,
        schema={"symbol": pl.String, "available_at": DT, "bid": pl.Float64, "ask": pl.Float64,
                "valid": pl.Boolean},
    )  # fmt: skip


def tables() -> dict[str, pl.DataFrame]:
    bars = qqq_bars()
    return {
        "qqq_bars": bars,
        "cross_quotes": cross_quotes(),
        "daily": daily_stats(bars),
        "profile": minute_profile(bars, CAL),
        "vix": vix_table(),
        "macro": macro_table(),
        "und_quotes": und_quotes(),
        "options": options(),
        "chain": chain(),
    }
