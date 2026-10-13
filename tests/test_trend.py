"""M25 (ADR-0016 D1, D4, D5): the frozen ETF trend rule. Exact synthetic cases."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import polars as pl
import pytest

from qqq1dte.strategies.trend import (
    SlotPeriod,
    cagr,
    commission,
    max_drawdown_pct,
    month_end_signals,
    period_dates,
    sharpe,
    simulate,
    tbill_growth,
    weighted_sharpe_diff,
    worst_window,
)


def daily(dates: list[date], closes: list[float]) -> pl.DataFrame:
    return pl.DataFrame(
        {"date": dates, "ticker": ["X"] * len(dates), "adj_close": [float(c) for c in closes]}
    )


def test_month_end_signals_lookback() -> None:
    # month-end closes 1, 2, 3, 4, 1 (lookback 3): signal = close > mean of the last 3 incl. it
    d = [date(2005, m, 28) for m in range(1, 6)]
    s = month_end_signals(daily(d, [1, 2, 3, 4, 1]), 3)
    assert s["signal"].to_list() == [None, None, True, True, False]
    assert s["month_end"].to_list() == d


def test_month_end_is_last_trading_day_and_no_lookahead() -> None:
    d = [date(2005, 1, 3), date(2005, 1, 31), date(2005, 2, 1), date(2005, 2, 28)]
    s = month_end_signals(daily(d, [5, 6, 7, 8]), 1)
    assert s["month_end"].to_list() == [date(2005, 1, 31), date(2005, 2, 28)]
    # changing data after the January month-end cannot change January's signal
    s2 = month_end_signals(daily(d, [5, 6, 99, 0.1]), 1)
    assert s2["signal"][0] == s["signal"][0]


def test_period_dates_execute_at_next_open() -> None:
    sessions = [date(2005, 1, 31), date(2005, 2, 1), date(2005, 2, 28), date(2005, 3, 1)]
    month_ends = [date(2005, 1, 31), date(2005, 2, 28)]
    assert period_dates(month_ends, sessions) == [(date(2005, 2, 1), date(2005, 3, 1))]


def test_commission_minimum_and_cap() -> None:
    # $1,250 at $100: 12.5 shares x $0.005 = $0.0625 -> $1 minimum
    assert commission(1250.0, 100.0, 0.005, 1.0, 0.01) == pytest.approx(1.0)
    # $50 trade: minimum $1 but capped at 1% of value = $0.50
    assert commission(50.0, 100.0, 0.005, 1.0, 0.01) == pytest.approx(0.5)
    # large share count: 1,000 shares at $10 = $5.00
    assert commission(10_000.0, 10.0, 0.005, 1.0, 0.01) == pytest.approx(5.0)
    assert commission(0.0, 10.0, 0.005, 1.0, 0.01) == 0.0


def test_tbill_growth_uses_previous_published_rate() -> None:
    rates = {date(2005, 1, 3): 3.6, date(2005, 1, 4): None, date(2005, 1, 5): 7.2}
    # days 01-04 .. 01-06 (3 calendar days, start exclusive): rate known the day before each day:
    # 01-04 uses 3.6 (01-03), 01-05 uses 3.6 (01-04 missing -> latest published),
    # 01-06 uses 7.2 (01-05)
    g = tbill_growth(rates, date(2005, 1, 3), date(2005, 1, 6))
    assert g == pytest.approx((1 + 0.036 / 360) ** 2 * (1 + 0.072 / 360))


def test_simulate_one_slot_whole_shares_hand_case() -> None:
    # one slot of weight 1.0, $1,000 account, price $100, spread 10 bps, commission $1 minimum
    periods = [
        SlotPeriod(in_market={"X": True}, growth={"X": 1.10}, open_price={"X": 100.0}, cash=1.0),
        SlotPeriod(in_market={"X": False}, growth={"X": 0.50}, open_price={"X": 110.0}, cash=1.01),
    ]
    r = simulate(periods, ["X"], 1.0, 1000.0, 0.005, 1.0, 0.01, 10.0)
    # month 1: 10 shares ($1,000) + $2 costs would overdraw the cash account -> 9 shares ($900):
    #   commission $1 + spread $0.90 = $1.90; cash 98.10; end 900 x 1.10 + 98.10 = 1,088.10
    # month 2: sell 9 shares at $110 ($990): $1 + $0.99 -> cash 1,086.11 x 1.01 = 1,096.9711
    assert r.returns[0] == pytest.approx(0.0881)
    assert r.returns[1] == pytest.approx(1096.9711 / 1088.1 - 1)
    assert r.costs == pytest.approx([1.9, 1.99])
    assert r.orders == [1, 1]
    assert r.invested == pytest.approx([900 / 1000, 0.0])
    # 2x costs: 9 shares, $2 + $1.80 = $3.80 -> end 990 + 96.20 = 1,086.20
    r2 = simulate(periods, ["X"], 1.0, 1000.0, 0.005, 1.0, 0.01, 10.0, cost_mult=2.0)
    assert r2.returns[0] == pytest.approx(0.0862)


def test_simulate_dividend_cash_and_unchanged_slot() -> None:
    # A and B at 50%; A's adjusted open grows 2% while its raw open stays $100 ($2/share dividend)
    p1 = SlotPeriod(in_market={"A": True, "B": True}, growth={"A": 1.02, "B": 1.0},
                    open_price={"A": 100.0, "B": 50.0}, cash=1.0)  # fmt: skip
    p2 = SlotPeriod(in_market={"A": True, "B": True}, growth={"A": 1.0, "B": 1.0},
                    open_price={"A": 100.0, "B": 50.0}, cash=1.0)  # fmt: skip
    r = simulate([p1, p2], ["A", "B"], 0.5, 1000.0, 0.005, 1.0, 0.01, 0.0)
    # month 1: A 5 sh, B 10 sh, $2 costs overdraw by $2 -> trim the largest slot (tie: first
    #   ticker) A to 4 sh. Cash 1000 - 2 - 400 - 500 = 98. End 408 + 500 + 98 = 1,006
    # month 2: the $8 dividend moves to cash (106); targets A 5 sh (+1, $1), B 10 sh (no order);
    #   cash 1006 - 1 - 1000 = 5; end 1,005
    assert r.returns == pytest.approx([0.006, 1005 / 1006 - 1])
    assert r.costs == pytest.approx([2.0, 1.0])
    assert r.orders == [2, 1]


def test_sharpe_and_weighted_diff() -> None:
    x = np.array([0.01, 0.03, -0.02, 0.02])
    expected = x.mean() / x.std(ddof=1) * math.sqrt(12)
    assert sharpe(x) == pytest.approx(expected)
    y = np.array([0.0, 0.01, 0.0, 0.01])
    w = np.ones((1, 4), dtype=np.int64)
    assert weighted_sharpe_diff(x, y, w)[0] == pytest.approx(sharpe(x) - sharpe(y))


def test_descriptive_helpers() -> None:
    r = np.array([0.1, -0.5, 0.2])
    # equity 1 -> 1.1 -> 0.55 -> 0.66: the fall from 1.1 to 0.55 is 50%
    assert max_drawdown_pct(r) == pytest.approx(0.5)
    # 2-month windows: 1.1 x 0.5 - 1 = -0.45, 0.5 x 1.2 - 1 = -0.40
    assert worst_window(r, 2) == pytest.approx(-0.45)
    assert cagr(np.array([0.1, -0.1])) == pytest.approx(0.99**6 - 1)
