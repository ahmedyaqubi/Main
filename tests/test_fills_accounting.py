"""Conservative fill, tick rounding against the trader (T-FILL-02, conservative part of
T-FILL-01), costs per §4.8, and hand-computed accounting for 5 trades (T-BT-01).

Costs: $0.65 commission + $0.05 fees per contract per side -> $1.40 round trip, 1 contract.
1R = stop_pct (0.20) x entry x 100 + 1.40. Breakeven band = 2% of entry x 100.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qqq1dte.core.config import load_config
from qqq1dte.execution_sim.accounting import account, classify_time_exit
from qqq1dte.execution_sim.fills import Conservative, ceil_tick, floor_tick, round_trip_costs
from qqq1dte.execution_sim.selection import Quote

CFG = load_config()
TS = datetime(2025, 3, 11, 15, 0, tzinfo=UTC)


def q(bid: float | None, ask: float | None) -> Quote:
    return Quote(bid, ask, 10, 10, TS)


def test_ticks_round_against_the_trader() -> None:
    assert ceil_tick(1.071, 0.01) == 1.08 and floor_tick(1.079, 0.01) == 1.07
    assert ceil_tick(1.07, 0.01) == 1.07 and floor_tick(1.07, 0.01) == 1.07  # exact stays
    assert ceil_tick(0.1 + 0.2, 0.01) == 0.3  # float noise does not add a tick


def test_conservative_buys_the_ask_and_sells_the_bid() -> None:
    m = Conservative(CFG)
    assert m.name == "CONSERVATIVE"
    assert m.buy(q(1.00, 1.10)) == 1.10
    assert m.sell(q(1.00, 1.10)) == 1.00
    assert m.buy(q(1.004, 1.105)) == 1.11 and m.sell(q(1.009, 1.10)) == 1.00
    assert m.sell(q(None, 0.05)) == 0.0  # missing bid is worth nothing (M6 Q3)


def test_round_trip_costs() -> None:
    assert round_trip_costs(CFG) == pytest.approx((1.30, 0.10))


CASES = [
    # entry quote, exit quote, entry fill, exit fill, time exit?, gross, net, R, class, spread
    ((1.00, 1.02), (1.33, 1.35), 1.02, 1.33, False, 31.0, 29.6, 29.6 / 21.8, None, 2.0),
    ((2.45, 2.50), (2.00, 2.04), 2.50, 2.00, False, -50.0, -51.4, -1.0, None, 4.5),
    ((0.84, 0.85), (0.86, 0.87), 0.85, 0.86, True, 1.0, -0.4, -0.4 / 18.4, "BREAKEVEN", 1.0),
    (
        (1.08, 1.10),
        (1.30, 1.34),
        1.10,
        1.30,
        True,
        20.0,
        18.6,
        18.6 / 23.4,
        "TIME_EXIT_PROFIT",
        3.0,
    ),
    (
        (2.96, 3.00),
        (2.70, 2.72),
        3.00,
        2.70,
        True,
        -30.0,
        -31.4,
        -31.4 / 61.4,
        "TIME_EXIT_LOSS",
        3.0,
    ),
]


@pytest.mark.parametrize("case", CASES)
def test_bt_01_pnl_accounting(case: tuple) -> None:  # type: ignore[type-arg]
    eq, xq, e_fill, x_fill, time_exit, gross, net, r, cls, spread = case
    a = account(e_fill, x_fill, q(*eq), q(*xq), CFG)
    assert a.gross_pnl == pytest.approx(gross, abs=1e-9)
    assert (a.commissions, a.fees) == pytest.approx((1.30, 0.10))
    assert a.net_pnl == pytest.approx(net, abs=1e-9)
    assert a.r_multiple == pytest.approx(r, abs=1e-12)
    assert a.spread_cost == pytest.approx(spread, abs=1e-9)  # vs mid, entry + exit, in dollars
    if time_exit:
        assert classify_time_exit(a.net_pnl, e_fill, CFG) == cls


def test_spread_cost_unknown_without_a_two_sided_exit_quote() -> None:
    a = account(1.02, 0.0, q(1.00, 1.02), q(None, 0.05), CFG)
    assert a.spread_cost is None and a.net_pnl == pytest.approx(-102 - 1.4)


def test_fill_01_three_models() -> None:
    """T-FILL-01: bid 1.00 / ask 1.10 -> buy 1.10 / 1.08 (1.075 rounded up) / 1.05."""
    from qqq1dte.execution_sim.fills import Moderate, Optimistic  # noqa: PLC0415

    quote = q(1.00, 1.10)
    assert Conservative(CFG).buy(quote) == 1.10
    assert Moderate(CFG, 0.5).buy(quote) == 1.08
    assert Optimistic(CFG).buy(quote) == 1.05
    assert (Moderate(CFG, 0.5).name, Optimistic(CFG).name) == ("MODERATE", "OPTIMISTIC")
    # sells: 1.00 / 1.025 -> 1.02 / 1.05
    assert Conservative(CFG).sell(quote) == 1.00
    assert Moderate(CFG, 0.5).sell(quote) == 1.02
    assert Optimistic(CFG).sell(quote) == 1.05


def test_fill_02_every_model_rounds_against_the_trader() -> None:
    from qqq1dte.execution_sim.fills import Moderate, Optimistic  # noqa: PLC0415

    quote = q(1.01, 1.04)  # mid 1.025
    for m in (Conservative(CFG), Moderate(CFG, 0.25), Moderate(CFG, 0.75), Optimistic(CFG)):
        buy, sell = m.buy(quote), m.sell(quote)
        assert buy == round(buy, 2) and sell == round(sell, 2)
    assert Optimistic(CFG).buy(quote) == 1.03 and Optimistic(CFG).sell(quote) == 1.02
    assert Moderate(CFG, 0.25).buy(quote) == 1.03  # 1.02875 -> up
    assert Moderate(CFG, 0.25).sell(quote) == 1.02  # 1.02125 -> down
    # alpha = 1 is the conservative price, alpha = 0 the optimistic price
    assert Moderate(CFG, 1.0).buy(quote) == Conservative(CFG).buy(quote)
    assert Moderate(CFG, 0.0).sell(quote) == Optimistic(CFG).sell(quote)


def test_missing_bid_sells_at_zero_in_every_model() -> None:
    from qqq1dte.execution_sim.fills import Moderate, Optimistic  # noqa: PLC0415

    for m in (Conservative(CFG), Moderate(CFG, 0.5), Optimistic(CFG)):
        assert m.sell(q(None, 0.05)) == 0.0


def test_cost_multiplier_scales_commission_and_fees_only() -> None:
    from qqq1dte.execution_sim.fills import scaled_costs  # noqa: PLC0415

    cfg = scaled_costs(CFG, 1.5)
    assert round_trip_costs(cfg) == pytest.approx((1.95, 0.15))
    assert round_trip_costs(CFG) == pytest.approx((1.30, 0.10))  # original untouched


def test_net_pnl_type_is_gross_minus_costs() -> None:
    """Gate 9: NetPnl is only built from gross P&L and the round-trip costs."""
    from qqq1dte.execution_sim.accounting import NetPnl  # noqa: PLC0415

    a = account(1.02, 1.33, q(1.00, 1.02), q(1.33, 1.35), CFG)
    assert isinstance(a.net, NetPnl)
    assert float(a.net) == pytest.approx(a.gross_pnl - a.commissions - a.fees)
    assert a.net.gross == a.gross_pnl and a.net.costs == pytest.approx(1.40)
    with pytest.raises(TypeError):
        NetPnl(29.6)  # type: ignore[call-arg]
