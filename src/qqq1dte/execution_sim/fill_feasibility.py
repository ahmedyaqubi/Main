"""M24 (ADR-0015, docs/ROADMAP.md): fill feasibility of hypothetical retail limit orders. Pure.

For a usable quote at time t:
- A hypothetical limit is placed at mid +/- `frac` x spread (buys up, sells down), rounded to
  the tick so it is never better than that level (buys round down, sells round up).
- A fill is judged from trade prints in (t, t + k]:
  - **touch:** a print at or through the limit;
  - **through:** a print strictly better than the limit. This is conservative: a print exactly
    at our price doesn't prove we would have been filled (queue position).

Chase cost: if the order is unfilled after k minutes, it pays the opposite quote in force then.
The cost vs the mid at t is expressed as a share of the quoted half-spread (1.0 = paying the
full half-spread; negative = better than the mid).

These are estimates from prints, not proof of fills; paper trading is the real check.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from qqq1dte.execution_sim.fills import ceil_tick, floor_tick


def quote_usable(
    bid: float | None,
    ask: float | None,
    rejected: bool,
    quote_at: datetime,
    t: datetime,
    max_age_s: float,
) -> bool:
    return (
        bid is not None
        and ask is not None
        and bid > 0
        and ask >= bid
        and not rejected
        and t - quote_at <= timedelta(seconds=max_age_s)
    )


def limit_price(bid: float, ask: float, side: str, frac: float, tick: float) -> float:
    mid = (bid + ask) / 2
    spread = ask - bid
    if side == "buy":
        return floor_tick(mid + frac * spread, tick)
    return ceil_tick(mid - frac * spread, tick)


def check_fill(
    side: str,
    limit: float,
    t: datetime,
    k_minutes: float,
    times: Sequence[datetime],
    prices: Sequence[float],
) -> tuple[bool, bool]:
    """(touch, through) from prints with t < time <= t + k."""
    end = t + timedelta(minutes=k_minutes)
    window = [p for ts, p in zip(times, prices, strict=True) if t < ts <= end]
    if side == "buy":
        return any(p <= limit + 1e-9 for p in window), any(p < limit - 1e-9 for p in window)
    return any(p >= limit - 1e-9 for p in window), any(p > limit + 1e-9 for p in window)


def chase_cost_share(
    side: str,
    filled: bool,
    limit: float,
    mid0: float,
    half_spread: float,
    later_ask: float | None = None,
    later_bid: float | None = None,
) -> float:
    if side == "buy":
        price = limit if filled else (later_ask if later_ask is not None else float("nan"))
        cost = price - mid0
    else:
        price = limit if filled else (later_bid if later_bid is not None else float("nan"))
        cost = mid0 - price
    return cost / half_spread if half_spread > 0 else float("nan")
