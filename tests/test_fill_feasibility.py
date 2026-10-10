"""M24 (ADR-0015, ROADMAP): fill feasibility of hypothetical retail limit orders. Exact cases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qqq1dte.execution_sim.fill_feasibility import (
    chase_cost_share,
    check_fill,
    limit_price,
    quote_usable,
)

T = datetime(2024, 6, 12, 14, 0, tzinfo=UTC)


def m(x: float) -> datetime:
    return T + timedelta(minutes=x)


def test_limit_price_on_tick_never_better_than_mid() -> None:
    # bid 1.00 / ask 1.03: mid 1.015 -> buy at mid rounds DOWN to 1.01, sell at mid UP to 1.02
    assert limit_price(1.00, 1.03, "buy", 0.0, 0.01) == 1.01
    assert limit_price(1.00, 1.03, "sell", 0.0, 0.01) == 1.02
    # mid + 25% of the spread: 1.015 + 0.0075 = 1.0225 -> 1.02 (buy); sell 1.0075 -> 1.01
    assert limit_price(1.00, 1.03, "buy", 0.25, 0.01) == 1.02
    assert limit_price(1.00, 1.03, "sell", 0.25, 0.01) == 1.01
    # mid + 50% = the ask exactly
    assert limit_price(1.00, 1.04, "buy", 0.5, 0.01) == 1.04


def test_touch_vs_through_and_window_edges() -> None:
    times = [m(0), m(1), m(3), m(6)]
    prices = [0.90, 1.02, 1.01, 0.95]
    # buy at 1.01: prints in (t, t+k]; the print AT t (0.90) is excluded
    assert check_fill("buy", 1.01, T, 1, times, prices) == (False, False)  # 1.02 only
    assert check_fill("buy", 1.01, T, 5, times, prices) == (True, False)  # 1.01 touches
    assert check_fill("buy", 1.01, T, 6, times, prices) == (True, True)  # 0.95 at t+6 counts
    assert check_fill("buy", 1.01, T, 15, [], []) == (False, False)


def test_sell_side_symmetry() -> None:
    times, prices = [m(2), m(4)], [1.02, 1.05]
    assert check_fill("sell", 1.02, T, 3, times, prices) == (True, False)
    assert check_fill("sell", 1.02, T, 5, times, prices) == (True, True)


def test_quote_usable() -> None:
    assert quote_usable(1.00, 1.03, False, T - timedelta(seconds=30), T, 60)
    assert not quote_usable(1.00, 1.03, True, T, T, 60)  # rejected record
    assert not quote_usable(0.0, 1.03, False, T, T, 60)  # no real bid
    assert not quote_usable(None, 1.03, False, T, T, 60)
    assert not quote_usable(1.00, 1.03, False, T - timedelta(seconds=61), T, 60)  # stale


def test_chase_cost_share() -> None:
    # buy, mid 1.015, half-spread 0.015. Filled at 1.01 -> cost -0.005 -> share -1/3.
    assert chase_cost_share("buy", True, 1.01, 1.015, 0.015, later_ask=1.06) == pytest.approx(
        -1 / 3
    )
    # not filled: chase to the ask in force at t+k (1.03) -> cost 0.015 -> share 1.0
    assert chase_cost_share("buy", False, 1.01, 1.015, 0.015, later_ask=1.03) == pytest.approx(1.0)
    # sell, mid 1.015: filled at 1.02 -> price above mid = negative cost
    assert chase_cost_share("sell", True, 1.02, 1.015, 0.015, later_bid=1.0) == pytest.approx(
        -1 / 3
    )
    assert chase_cost_share("sell", False, 1.02, 1.015, 0.015, later_bid=1.00) == pytest.approx(1.0)
