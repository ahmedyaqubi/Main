"""ADR-0021 D5 / M28 step 6: cost map arithmetic. Synthetic cases with exactly known answers.
No signal or return is computed by these functions."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from statistics import NormalDist

import numpy as np
import pytest

from qqq1dte.backtesting.cost_map import (
    breakeven_move,
    bs_price,
    cost_share,
    implied_vol,
    outlay,
    passes_breakeven_rule,
    remaining_session_seconds,
    required_edge,
    round_trip_cost,
)
from qqq1dte.core.config import BrokerFees, load_config

S = load_config().study_options_day
IBKR = S.broker_fees["ibkr_canada"]
FLAT = BrokerFees(
    commission_per_contract=1.0,
    min_per_order=0.0,
    occ_clearing_per_contract=0.0,
    cat_per_contract=0.0,
    sec_fee_rate_on_sales=0.0,
)


def test_round_trip_at_ibkr_for_one_contract() -> None:
    # bid 1.00 / ask 1.10: spread $10; buy side $1.00 + 0.0253; sell side $1.00 + 0.0253
    # + 0.0000206 * 100 = 0.00206
    expected = 10.0 + 2 * (1.0 + 0.0253) + 0.00206
    assert round_trip_cost(1.00, 1.10, IBKR) == pytest.approx(expected)
    assert outlay(1.10, IBKR) == pytest.approx(110.0 + 1.0253)
    assert cost_share(1.00, 1.10, IBKR) == pytest.approx(expected / (110.0 + 1.0253))


def test_cost_share_with_flat_fees_is_exact() -> None:
    # spread 0.10 -> $10, commissions $2: cost $12 on an outlay of $201
    assert round_trip_cost(1.90, 2.00, FLAT) == pytest.approx(12.0)
    assert cost_share(1.90, 2.00, FLAT) == pytest.approx(12.0 / 201.0)


def test_cost_share_refuses_a_bad_quote() -> None:
    for bid, ask in ((0.0, 1.0), (1.2, 1.1), (1.0, 0.0)):
        with pytest.raises(ValueError):
            cost_share(bid, ask, FLAT)


def test_bs_put_call_parity_and_implied_vol_round_trip() -> None:
    s, k, t = 100.0, 101.0, 1 / 365
    c, p = bs_price(s, k, t, 0.25, "C"), bs_price(s, k, t, 0.25, "P")
    assert c - p == pytest.approx(s - k, abs=1e-9)  # r = 0
    assert implied_vol(c, s, k, t, "C") == pytest.approx(0.25, abs=1e-6)
    assert implied_vol(p, s, k, t, "P") == pytest.approx(0.25, abs=1e-6)
    # below intrinsic value there is no implied volatility
    assert implied_vol(0.5, 100.0, 99.0, t, "C") is None


def test_bs_at_expiry_is_intrinsic() -> None:
    assert bs_price(105.0, 100.0, 0.0, 0.3, "C") == pytest.approx(5.0)
    assert bs_price(95.0, 100.0, 0.0, 0.3, "C") == pytest.approx(0.0)
    assert bs_price(95.0, 100.0, 0.0, 0.3, "P") == pytest.approx(5.0)


def test_breakeven_move_with_no_spread_no_fees_no_time_is_zero() -> None:
    # same instant, zero spread, zero commission: break-even is no move at all
    m = breakeven_move(
        100.0,
        100.0,
        "C",
        1 / 365,
        1 / 365,
        2.0,
        2.0,
        BrokerFees(
            commission_per_contract=0.0,
            min_per_order=0.0,
            occ_clearing_per_contract=0.0,
            cat_per_contract=0.0,
            sec_fee_rate_on_sales=0.0,
        ),
    )
    assert m == pytest.approx(0.0, abs=1e-6)


def test_breakeven_move_solves_the_stated_equation() -> None:
    s, k, t0, t1 = 100.0, 100.0, 2 / 365, 1.5 / 365
    bid, ask = 1.90, 2.10
    for right in ("C", "P"):
        m = breakeven_move(s, k, right, t0, t1, bid, ask, FLAT)
        assert m is not None and m > 0
        sig = implied_vol(2.0, s, k, t0, right)
        assert sig is not None
        s1 = s * (1 + m) if right == "C" else s * (1 - m)
        # exit bid = model value at exit minus the entry half-spread; equals ask + $2 / 100
        exit_bid = bs_price(s1, k, t1, sig, right) - 0.10
        assert exit_bid == pytest.approx(
            ask
            + (FLAT.order_cost(1, ask, sell=False) + FLAT.order_cost(1, exit_bid, sell=True)) / 100,
            abs=1e-6,
        )


def test_breakeven_grows_with_spread() -> None:
    a = breakeven_move(100.0, 100.0, "C", 1 / 365, 0.9 / 365, 1.95, 2.05, FLAT)
    b = breakeven_move(100.0, 100.0, "C", 1 / 365, 0.9 / 365, 1.80, 2.20, FLAT)
    assert a is not None and b is not None and b > a


def test_required_edge_is_z_times_sd_over_root_n() -> None:
    z = NormalDist().inv_cdf(S.advance_level)
    assert required_edge(0.6, 400, S.advance_level) == pytest.approx(z * 0.6 / 20)
    assert required_edge(1.0, 1, 0.5) == pytest.approx(0.0, abs=1e-12)
    with pytest.raises(ValueError):
        required_edge(0.6, 0, S.advance_level)


def test_breakeven_rule_uses_the_75th_percentile_of_absolute_moves() -> None:
    moves = np.array([0.001, -0.002, 0.003, -0.004])  # |.| -> 0.001..0.004; p75 = 0.00325
    assert math.isclose(float(np.quantile(np.abs(moves), 0.75)), 0.00325)
    assert passes_breakeven_rule(np.array([0.003, 0.003, 0.0032]), moves, 0.75)
    assert not passes_breakeven_rule(np.array([0.0033, 0.0034, 0.001]), moves, 0.75)
    # the line itself passes (rule: drop only when the median EXCEEDS the percentile)
    assert passes_breakeven_rule(np.array([0.00325]), moves, 0.75)


def test_remaining_session_seconds_counts_only_open_market_time() -> None:

    def at(day: int, h: int, m: int = 0) -> datetime:
        return datetime(2024, 5, day, h, m, tzinfo=UTC)

    windows = [(at(1, 13, 30), at(1, 20)), (at(2, 13, 30), at(2, 20))]  # two 6.5 h sessions
    assert remaining_session_seconds(at(1, 13, 35), windows) == 2 * 6.5 * 3600 - 300
    assert remaining_session_seconds(at(1, 22), windows) == 6.5 * 3600  # overnight: none
    assert remaining_session_seconds(at(1, 12), windows) == 13 * 3600  # before the open
    assert remaining_session_seconds(at(2, 20), windows) == 0
