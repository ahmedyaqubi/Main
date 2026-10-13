"""M25 (ADR-0016 D2-D3): free ETF data, meaning Tiingo daily prices and FRED T-bill rates, with a
development-only holdout lock.

Raw downloads are stored unchanged by the fetch script. These functions only parse them. Missing
values stay null: the strategy uses the latest *published* value, never a fill. Dates after
`dev_end` cannot be read until a holdout ADR (`dev_only`).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import date
from typing import Any

import polars as pl

TIINGO_URL = "https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate={start}&endDate={end}"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
STOOQ_URL = "https://stooq.com/q/d/l/?s={ticker}.us&i=d"


class HoldoutLockedError(PermissionError):
    """ADR-0016 D3: data after the development end may only be read under a holdout ADR."""


def parse_tiingo(rows: Sequence[dict[str, Any]], ticker: str) -> pl.DataFrame:
    df = pl.DataFrame(
        {
            "date": [date.fromisoformat(r["date"][:10]) for r in rows],
            "ticker": [ticker] * len(rows),
            "open": [float(r["open"]) for r in rows],
            "close": [float(r["close"]) for r in rows],
            "adj_open": [float(r["adjOpen"]) for r in rows],
            "adj_close": [float(r["adjClose"]) for r in rows],
            "div_cash": [float(r["divCash"]) for r in rows],
            "split_factor": [float(r["splitFactor"]) for r in rows],
        },
        schema={"date": pl.Date, "ticker": pl.String, "open": pl.Float64, "close": pl.Float64,
                "adj_open": pl.Float64, "adj_close": pl.Float64, "div_cash": pl.Float64,
                "split_factor": pl.Float64},
    ).sort("date")  # fmt: skip
    if df["date"].n_unique() != df.height:
        raise ValueError(f"{ticker}: duplicate dates in Tiingo data")
    return df


def parse_fred(text: str, series: str) -> pl.DataFrame:
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    i_date, i_val = 0, header.index(series)
    dates, vals = [], []
    for row in reader:
        if not row:
            continue
        dates.append(date.fromisoformat(row[i_date]))
        v = row[i_val].strip()
        vals.append(None if v in ("", ".") else float(v))
    return pl.DataFrame({"date": dates, "rate": vals}, schema={"date": pl.Date, "rate": pl.Float64})


def dev_only(df: pl.DataFrame, dev_end: date, requested_end: date | None = None) -> pl.DataFrame:
    if requested_end is not None and requested_end > dev_end:
        raise HoldoutLockedError(
            f"requested data to {requested_end}, after the development end {dev_end} (ADR-0016 D3)"
        )
    return df.filter(pl.col("date") <= dev_end)
