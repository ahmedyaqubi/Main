"""ADR-0021 D5 (M28 step 6): cost map arithmetic, computed before any signal.

- Round trip at one instant: buy one contract at the ask, sell it at the bid, both orders'
  commissions and fees (`study_options_day.broker_fees`, never the Phase 1 `costs` block).
- Break-even move: the underlying move, in the contract's favour, after which the exit bid pays
  back the entry ask plus both orders' fees. Assumptions, stated: Black-Scholes with r = 0 and
  no dividend; the implied volatility from the entry mid stays unchanged to the exit; the exit
  half-spread equals the entry half-spread; time in calendar years to the 16:00 expiry.
- Required edge: the mean net return per trade whose one-sided bound at `level` just clears 0
  with n trades of standard deviation sd (normal approximation of the D6 bootstrap).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime
from statistics import NormalDist

import numpy as np
import numpy.typing as npt

from qqq1dte.core.config import BrokerFees

MULT = 100
_N = NormalDist()
_MAX_MOVE = 0.5  # break-even search range: 0..50% of the underlying
_TOL = 1e-10


def _check(bid: float, ask: float) -> None:
    if not (bid > 0 and ask > 0 and ask >= bid):
        raise ValueError(f"not a valid two-sided quote: bid {bid}, ask {ask}")


def outlay(ask: float, fees: BrokerFees, contracts: int = 1) -> float:
    """Cash paid to open: premium at the ask plus the buy order's fees (D2 $500 ceiling)."""
    return ask * MULT * contracts + fees.order_cost(contracts, ask, sell=False)


def round_trip_cost(bid: float, ask: float, fees: BrokerFees, contracts: int = 1) -> float:
    """Dollars lost buying at the ask and selling at the bid in the same instant."""
    _check(bid, ask)
    return (
        (ask - bid) * MULT * contracts
        + fees.order_cost(contracts, ask, sell=False)
        + fees.order_cost(contracts, bid, sell=True)
    )


def cost_share(bid: float, ask: float, fees: BrokerFees, contracts: int = 1) -> float:
    """Round-trip cost as a share of the outlay."""
    return round_trip_cost(bid, ask, fees, contracts) / outlay(ask, fees, contracts)


def bs_price(s: float, k: float, t: float, sigma: float, right: str) -> float:
    """Black-Scholes value per share, r = 0, no dividend; t in years."""
    if t <= 0 or sigma <= 0:
        return max(s - k, 0.0) if right == "C" else max(k - s, 0.0)
    v = sigma * math.sqrt(t)
    d1 = (math.log(s / k) + 0.5 * v * v) / v
    d2 = d1 - v
    if right == "C":
        return s * _N.cdf(d1) - k * _N.cdf(d2)
    return k * _N.cdf(-d2) - s * _N.cdf(-d1)


def implied_vol(price: float, s: float, k: float, t: float, right: str) -> float | None:
    """Volatility reproducing `price` (bisection); None when price is at or below intrinsic
    value or above what any volatility up to 1000% gives."""
    lo, hi = 1e-6, 10.0
    if not bs_price(s, k, t, lo, right) < price < bs_price(s, k, t, hi, right):
        return None
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if bs_price(s, k, t, mid, right) < price:
            lo = mid
        else:
            hi = mid
        if hi - lo < _TOL:
            break
    return 0.5 * (lo + hi)


def breakeven_move(
    s: float,
    k: float,
    right: str,
    t_entry: float,
    t_exit: float,
    bid: float,
    ask: float,
    fees: BrokerFees,
) -> float | None:
    """Smallest relative move m >= 0 of the underlying (up for a call, down for a put) with
    exit bid >= ask + (buy fees + sell fees) / 100, where exit bid = BS(s(1 +/- m), k, t_exit,
    sigma_entry) - half-spread. None when no implied volatility exists or m > 50%."""
    _check(bid, ask)
    sigma = implied_vol(0.5 * (bid + ask), s, k, t_entry, right)
    if sigma is None:
        return None
    half = 0.5 * (ask - bid)
    buy = fees.order_cost(1, ask, sell=False)

    def gap(m: float) -> float:
        s1 = s * (1 + m) if right == "C" else s * (1 - m)
        exit_bid = bs_price(s1, k, t_exit, sigma, right) - half
        return exit_bid - ask - (buy + fees.order_cost(1, max(exit_bid, 0.0), sell=True)) / MULT

    if gap(0.0) >= 0:
        return 0.0
    if gap(_MAX_MOVE) < 0:
        return None
    lo, hi = 0.0, _MAX_MOVE
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if gap(mid) < 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < _TOL:
            break
    return hi


def required_edge(sd: float, n_trades: int, level: float) -> float:
    """Mean per-trade return at which the one-sided `level` lower bound is exactly 0."""
    if n_trades <= 0:
        raise ValueError("n_trades must be positive")
    return _N.inv_cdf(level) * sd / math.sqrt(n_trades)


def passes_breakeven_rule(
    breakevens: npt.ArrayLike, moves: npt.ArrayLike, percentile: float
) -> bool:
    """D5: kept unless the median break-even move exceeds the given percentile of |move|."""
    be = np.asarray(breakevens, dtype=float)
    mv = np.abs(np.asarray(moves, dtype=float))
    return bool(np.median(be) <= np.quantile(mv, percentile))


def remaining_session_seconds(t: datetime, windows: Sequence[tuple[datetime, datetime]]) -> float:
    """Open-market seconds from t to the end of the last (open, close) window: the time measure
    for the trading-hours sensitivity of the break-even move, where nights carry no decay."""
    return float(sum(max(0.0, (c - max(o, t)).total_seconds()) for o, c in windows))
