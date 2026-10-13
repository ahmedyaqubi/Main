"""ADR-0018 (M27): the frozen Connors RSI(2) pullback rule. Pure functions on the daily
dividend-adjusted close; every value at day i uses closes up to day i only.

- **Entry signal** at close i: RSI(`rsi_period`) < `rsi_entry` and close > SMA(`sma_trend`).
- **Exit signal** at close j: close > SMA(`sma_exit`).
- **Orders** go at the next session's open, so a trade is (entry signal i, exit signal j): buy
  at open i+1, sell at open j+1, with j >= i+1. New entry signals are ignored until the position
  is sold.
"""

from __future__ import annotations

from collections.abc import Sequence

_NEUTRAL = 50.0


def rsi_wilder(x: Sequence[float], period: int) -> list[float | None]:
    """Wilder RSI: seeded with the mean gain and loss of the first `period` changes, then
    smoothed with alpha = 1 / period."""
    out: list[float | None] = [None] * len(x)
    if len(x) <= period:
        return out
    ch = [x[i] - x[i - 1] for i in range(1, len(x))]
    gain = sum(max(c, 0.0) for c in ch[:period]) / period
    loss = sum(max(-c, 0.0) for c in ch[:period]) / period

    def value(g: float, lo: float) -> float:
        if lo == 0:
            return 100.0 if g > 0 else _NEUTRAL
        return 100 - 100 / (1 + g / lo)

    out[period] = value(gain, loss)
    for i in range(period + 1, len(x)):
        c = ch[i - 1]
        gain = (gain * (period - 1) + max(c, 0.0)) / period
        loss = (loss * (period - 1) + max(-c, 0.0)) / period
        out[i] = value(gain, loss)
    return out


def sma(x: Sequence[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(x)
    run = 0.0
    for i, v in enumerate(x):
        run += v
        if i >= n:
            run -= x[i - n]
        if i >= n - 1:
            out[i] = run / n
    return out


def signals(
    close: Sequence[float], rsi_period: int, rsi_entry: float, sma_trend: int, sma_exit: int
) -> tuple[list[bool], list[bool]]:
    r, trend, ex = rsi_wilder(close, rsi_period), sma(close, sma_trend), sma(close, sma_exit)
    entry = [
        ri is not None and ti is not None and ri < rsi_entry and c > ti
        for c, ri, ti in zip(close, r, trend, strict=True)
    ]
    exit_ = [e is not None and c > e for c, e in zip(close, ex, strict=True)]
    return entry, exit_


def trade_indices(entry: Sequence[bool], exit_: Sequence[bool]) -> list[tuple[int, int]]:
    """(entry signal i, exit signal j) per completed trade; a trade needs the open after j."""
    out = []
    n, i = len(entry), 0
    while i < n:
        if not entry[i]:
            i += 1
            continue
        j = next((k for k in range(i + 1, n) if exit_[k]), None)
        if j is None or j + 1 >= n:
            break
        out.append((i, j))
        i = j + 1
    return out
