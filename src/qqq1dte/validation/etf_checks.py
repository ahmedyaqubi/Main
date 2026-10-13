"""ADR-0016 D2 amendment A1 (M25): data-quality checks for the Tiingo ETF series.

Each check returns its findings; the caller stops the study if any check fails (rule 11). Inputs
are development-period rows only (the loader applies the holdout lock).
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import polars as pl

_EPS = 1e-6


def completeness(dates: Sequence[date], sessions: Sequence[date]) -> tuple[list[date], list[date]]:
    have, want = set(dates), set(sessions)
    return sorted(want - have), sorted(have - want)


def adjustment_violations(df: pl.DataFrame, tol: float) -> list[tuple[date, str]]:
    """Back-adjusted series: on a dividend day i, ratio(i-1) / ratio(i) should equal
    1 - div(i) / close(i-1). Without a dividend or a split, the ratio must not change."""
    d = df.sort("date")
    ratio = (d["adj_close"] / d["close"]).to_list()
    close, div, split, dates = d["close"].to_list(), d["div_cash"].to_list(), \
        d["split_factor"].to_list(), d["date"].to_list()  # fmt: skip
    out = []
    for i in range(1, len(dates)):
        change = ratio[i - 1] / ratio[i]
        if split[i] != 1.0:
            continue
        if div[i] > 0:
            expected = 1 - div[i] / close[i - 1]
            if abs(change - expected) > tol:
                out.append(
                    (dates[i], f"dividend {div[i]}: ratio change {change:.6f} vs {expected:.6f}")
                )
        elif abs(change - 1) > _EPS:
            out.append((dates[i], f"ratio changed {change:.6f} without a dividend or split"))
    return out


def jump_scan(df: pl.DataFrame, threshold: float) -> list[dict[str, Any]]:
    d = df.sort("date")
    close, split, dates = d["close"].to_list(), d["split_factor"].to_list(), d["date"].to_list()
    out = []
    for i in range(1, len(dates)):
        r = close[i] / close[i - 1] - 1
        if abs(r) > threshold:
            out.append({"date": dates[i], "move": r, "split": split[i] != 1.0})
    return out


def dividend_counts(df: pl.DataFrame) -> dict[int, int]:
    g = (
        df.filter(pl.col("div_cash") > 0)
        .group_by(pl.col("date").dt.year().alias("y"))
        .agg(n=pl.len())
        .sort("y")
    )
    return dict(zip(g["y"].to_list(), g["n"].to_list(), strict=True))


def shiller_violations(
    months: Sequence[str],
    spy_avg: Mapping[str, float],
    shiller_p: Mapping[str, float],
    scale: float,
    tol: float,
) -> list[tuple[str, float]]:
    """Months where P / (scale x SPY monthly-average close) deviates from its median by > tol."""
    ratios = {
        m: shiller_p[m] / (scale * spy_avg[m]) for m in months if m in spy_avg and m in shiller_p
    }
    if not ratios:
        return []
    med = statistics.median(ratios.values())
    return [(m, r / med - 1) for m, r in ratios.items() if abs(r / med - 1) > tol]


def open_ratio_violations(df: pl.DataFrame, tol: float) -> list[tuple[date, float]]:
    """ADR-0018 D2: the open must carry the same adjustment as that day's close."""
    d = df.sort("date").with_columns(
        diff=(pl.col("adj_open") / pl.col("open")) / (pl.col("adj_close") / pl.col("close")) - 1
    )
    return [(r, x) for r, x in d.select("date", "diff").iter_rows() if abs(x) > tol]


def open_gaps(df: pl.DataFrame, threshold: float) -> list[tuple[date, float]]:
    """ADR-0018 D2: opens more than `threshold` away from the previous close."""
    d = df.sort("date")
    o, c, dates = d["open"].to_list(), d["close"].to_list(), d["date"].to_list()
    out = []
    for i in range(1, len(dates)):
        g = o[i] / c[i - 1] - 1
        if abs(g) > threshold:
            out.append((dates[i], g))
    return out
