"""ADR-0017 (M26): the frozen turn-of-month rule and its per-trade accounting. Pure functions.

- **Window (D1):** buy at the close of the `entry_from_end`-th last session of a month (2: day
  -2), sell at the close of the `exit_day`-th session of the next month (3: day +3). Windows come
  from the exchange calendar, so a month whose entry or exit session is outside it has none.
- **Trade (D1, D4):** a fixed account buys whole shares at the unadjusted close. Cash may not go
  negative, so the share count drops by one while the buy costs would overdraw it. The position
  grows with the adjusted close (total return). The rest of the account earns T-bills. Each side
  pays the IBKR commission plus `slippage_bps`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from itertools import groupby, pairwise

from qqq1dte.strategies.trend import commission

_EPS = 1e-9


def tom_windows(
    sessions: Sequence[date], entry_from_end: int, exit_day: int
) -> list[tuple[date, date]]:
    """(entry, exit) per month with both sessions in `sessions` (which must be complete
    calendar months, except possibly at either end)."""
    months = [list(g) for _, g in groupby(sorted(sessions), key=lambda d: (d.year, d.month))]
    out = []
    for cur, nxt in pairwise(months):
        first_month = cur is months[0]
        if first_month or len(cur) < entry_from_end or len(nxt) < exit_day:
            continue  # the first month may be partial: its true day -2 is unknown
        out.append((cur[-entry_from_end], nxt[exit_day - 1]))
    return out


@dataclass(frozen=True)
class TomTrade:
    shares: int
    costs: float  # $ paid on both sides
    net_excess: float  # (end value - account) / account - T-bill return
    gross_excess: float  # the same without costs
    worst_day: float  # worst one-day change of the account value inside the trade


def tom_trade(  # noqa: PLR0913 (frozen cost model parameters)
    account: float,
    entry_close: float,
    adj_path: Sequence[float],
    tbill: float,
    per_share: float,
    minimum: float,
    max_pct: float,
    slippage_bps: float,
    *,
    cost_mult: float = 1.0,
) -> TomTrade:
    """`adj_path`: adjusted closes from the entry session to the exit session, inclusive.
    `tbill`: growth of $1 in T-bills over the trade's calendar days."""

    def side(n: int, value: float) -> float:
        if n == 0:
            return 0.0
        c = commission(value, value / n, per_share, minimum, max_pct)
        return cost_mult * (c + slippage_bps / 10_000 * value)

    n = math.floor(account / entry_close + _EPS)
    while n > 0 and account - n * entry_close - side(n, n * entry_close) < -_EPS:
        n -= 1
    buy = n * entry_close
    buy_cost = side(n, buy)
    cash = account - buy - buy_cost
    pos = [buy * a / adj_path[0] for a in adj_path]
    sell_cost = side(n, pos[-1])
    end = cash * tbill + pos[-1] - sell_cost
    gross_end = (account - buy) * tbill + pos[-1]
    values = [cash + p for p in pos]
    worst = min((b / a - 1 for a, b in pairwise(values)), default=0.0)
    return TomTrade(
        shares=n,
        costs=buy_cost + sell_cost,
        net_excess=end / account - 1 - (tbill - 1),
        gross_excess=gross_end / account - 1 - (tbill - 1),
        worst_day=worst,
    )
