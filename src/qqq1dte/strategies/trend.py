"""ADR-0016 (M25): the frozen ETF trend rule and its accounting. Pure functions.

- **Signal (D1):** on each month's last trading day, an ETF is held next month if its adjusted
  close is above the mean of the last `lookback` month-end adjusted closes (the current one
  included). Only data up to that month-end is used.
- **Execution:** at the next session's open. Each period runs from the first open after month-end
  k to the first open after month-end k+1.
- **Accounting (whole shares, D4; a cash account):** each month a held slot is set to
  floor(`weight` x value / open) shares at the unadjusted open, and to 0 shares otherwise.
  - Each order pays the IBKR commission (per share, a minimum per order, capped at a share of
    the trade value) plus `spread_bps` per side.
  - Cash may not go negative: while costs would overdraw it, the largest slot (ties: the first
    ticker) is cut by one share.
  - A position grows by the adjusted-open ratio. At the next open, the part above
    shares x unadjusted open (the dividends) moves to cash.
- **Cash:** the 3-month T-bill rate published before each calendar day, accrued as r / 360 per
  day.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise

import numpy as np
import numpy.typing as npt
import polars as pl

Arr = npt.NDArray[np.float64]
_EPS = 1e-9


def month_end_signals(daily: pl.DataFrame, lookback: int) -> pl.DataFrame:
    """Per ticker: month_end, adj_close, signal (null until `lookback` month-ends exist)."""
    me = (
        daily.sort("date")
        .with_columns(ym=pl.col("date").dt.strftime("%Y-%m"))
        .group_by("ticker", "ym", maintain_order=True)
        .last()
        .sort("ticker", "date")
    )
    me = me.with_columns(
        avg=pl.col("adj_close").rolling_mean(window_size=lookback).over("ticker")
    ).with_columns(
        signal=pl.when(pl.col("avg").is_null())
        .then(None)
        .otherwise(pl.col("adj_close") > pl.col("avg"))
    )
    return me.select(
        "ticker", month_end=pl.col("date"), adj_close=pl.col("adj_close"), signal="signal"
    )


def period_dates(month_ends: Sequence[date], sessions: Sequence[date]) -> list[tuple[date, date]]:
    """(start, end) opens for each pair of consecutive month-ends: the first session after each."""
    s = sorted(sessions)

    def after(d: date) -> date | None:
        nxt = [x for x in s if x > d]
        return nxt[0] if nxt else None

    out = []
    for a, b in pairwise(month_ends):
        start, end = after(a), after(b)
        if start is not None and end is not None:
            out.append((start, end))
    return out


def commission(
    value: float, price: float, per_share: float, minimum: float, max_pct: float
) -> float:
    if value <= 0:
        return 0.0
    c = max(minimum, value / price * per_share)
    return min(c, max_pct * value)


def tbill_growth(rates: Mapping[date, float | None], start: date, end: date) -> float:
    """Growth of $1 in T-bills over the calendar days (start, end], each day at the latest rate
    published strictly before it (missing values are skipped, never filled)."""
    known = sorted((d, r) for d, r in rates.items() if r is not None)
    g = 1.0
    d = start + timedelta(days=1)
    i, last = 0, None
    while d <= end:
        while i < len(known) and known[i][0] < d:
            last = known[i][1]
            i += 1
        if last is not None:
            g *= 1 + last / 100 / 360
        d += timedelta(days=1)
    return g


@dataclass(frozen=True)
class SlotPeriod:
    in_market: dict[str, bool]
    growth: dict[str, float]  # adj open (end) / adj open (start)
    open_price: dict[str, float]  # unadjusted open at the start (for share counts)
    cash: float  # T-bill growth over the period


@dataclass(frozen=True)
class SimResult:
    returns: list[float]  # net return per period
    costs: list[float]  # commission + spread paid per period ($)
    orders: list[int]  # orders per period
    invested: list[float]  # share of the starting value in ETFs after trading


def simulate(  # noqa: PLR0913 (frozen cost model parameters)
    periods: Sequence[SlotPeriod],
    tickers: Sequence[str],
    weight: float,
    account: float,
    per_share: float,
    minimum: float,
    max_pct: float,
    spread_bps: float,
    *,
    cost_mult: float = 1.0,
) -> SimResult:
    """Monthly net results with whole shares. The portfolio starts in cash."""
    shares = dict.fromkeys(tickers, 0)
    value = dict.fromkeys(tickers, 0.0)  # position value at the coming open (adjusted growth)
    cash = account
    res = SimResult([], [], [], [])

    def order_cost(n: int, price: float) -> float:
        trade = n * price
        c = commission(trade, price, per_share, minimum, max_pct) + spread_bps / 10_000 * trade
        return cost_mult * c

    for p in periods:
        cash += sum(value[t] - shares[t] * p.open_price[t] for t in tickers)  # dividends
        v = cash + sum(shares[t] * p.open_price[t] for t in tickers)
        target = {
            t: math.floor(weight * v / p.open_price[t] + _EPS) if p.in_market[t] else 0
            for t in tickers
        }
        while True:
            costs = sum(order_cost(abs(target[t] - shares[t]), p.open_price[t]) for t in tickers)
            spent = sum(target[t] * p.open_price[t] for t in tickers)
            if v - costs - spent >= -_EPS or not any(target.values()):
                break
            big = max(tickers, key=lambda t: (target[t] * p.open_price[t], -tickers.index(t)))
            target[big] -= 1
        res.orders.append(sum(target[t] != shares[t] for t in tickers))
        res.costs.append(costs)
        res.invested.append(spent / v)
        cash = (v - costs - spent) * p.cash
        shares = target
        value = {t: shares[t] * p.open_price[t] * p.growth[t] for t in tickers}
        res.returns.append((cash + sum(value.values())) / v - 1)
    return res


def sharpe(x: Arr) -> float:
    sd = float(np.std(x, ddof=1))
    return float(np.mean(x)) / sd * math.sqrt(12) if sd > 0 else math.nan


def weighted_sharpe_diff(x: Arr, y: Arr, weights: npt.NDArray[np.int64]) -> Arr:
    """Per resample: Sharpe(x) - Sharpe(y) with count weights (paired months)."""
    w = weights.astype(np.float64)
    tot = w.sum(axis=1)

    def ws(v: Arr) -> Arr:
        m = (w * v).sum(axis=1) / tot
        var = (w * (v[None, :] - m[:, None]) ** 2).sum(axis=1) / (tot - 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.asarray(m / np.sqrt(var) * math.sqrt(12), dtype=np.float64)

    return ws(x) - ws(y)


def cagr(r: Arr) -> float:
    """Annualised compound growth of monthly returns."""
    return float(np.prod(1 + r) ** (12 / len(r)) - 1)


def max_drawdown_pct(r: Arr) -> float:
    """Largest peak-to-trough fall of the equity curve (starting at 1), as a fraction."""
    eq = np.concatenate([[1.0], np.cumprod(1 + r)])
    return float(np.max(1 - eq / np.maximum.accumulate(eq)))


def worst_window(r: Arr, months: int) -> float:
    """Worst compounded return over any `months` consecutive months."""
    g = np.log1p(r)
    c = np.concatenate([[0.0], np.cumsum(g)])
    return float(np.expm1(np.min(c[months:] - c[:-months])))
