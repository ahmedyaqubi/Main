"""M27 (ADR-0018 D1): the frozen RSI(2) pullback rule. Exact synthetic cases."""

from __future__ import annotations

import pytest

from qqq1dte.strategies.pullback import rsi_wilder, signals, sma, trade_indices


def test_rsi_wilder_hand_case() -> None:
    # changes +1, -1, -1, +3. Seed (index 2): gain 0.5, loss 0.5 -> 50
    # index 3: gain 0.25, loss 0.75 -> 25; index 4: gain 1.625, loss 0.375 -> 81.25
    r = rsi_wilder([10.0, 11.0, 10.0, 9.0, 12.0], 2)
    assert r[:2] == [None, None]
    assert r[2:] == pytest.approx([50.0, 25.0, 81.25])
    assert rsi_wilder([1.0, 2.0, 3.0], 2)[2] == 100.0  # no losses
    assert rsi_wilder([1.0, 1.0, 1.0], 2)[2] == 50.0  # no moves


def test_sma_includes_current_day() -> None:
    assert sma([1.0, 2.0, 3.0, 4.0], 3) == [None, None, pytest.approx(2.0), pytest.approx(3.0)]


def test_signals_use_only_past_closes() -> None:
    x = [10.0, 11.0, 12.0, 13.0, 12.5, 12.0, 13.5, 14.0]
    e1, x1 = signals(x, rsi_period=2, rsi_entry=30.0, sma_trend=3, sma_exit=2)
    y = [*x[:5], 1.0, 99.0, 0.5]  # change everything after index 4
    e2, x2 = signals(y, rsi_period=2, rsi_entry=30.0, sma_trend=3, sma_exit=2)
    assert e1[:5] == e2[:5] and x1[:5] == x2[:5]


def test_signals_hand_case() -> None:
    # closes 10, 11, 12, 13, 12: RSI(2) at index 4 = 100 - 100 / (1 + 0.5 / 0.5) = 50
    #   (seed at 2: gain 1, loss 0; index 3: gain 1, loss 0; index 4: gain 0.5, loss 0.5)
    # SMA(3) at 4 = 12.333 > 12 -> no trend; exit: close 12 > SMA(2) 12.5? no
    e, x = signals([10.0, 11.0, 12.0, 13.0, 12.0], 2, 60.0, 3, 2)
    assert e == [False, False, False, False, False]
    assert x == [False, True, True, True, False]


def test_trade_indices() -> None:
    entry = [False, True, True, False, False, True, False, False, True]
    exit_ = [True, False, True, True, False, False, True, False, False]
    # entry at close 1 -> exit signal at close 2 (sell at open 3); the entry at 2 is ignored;
    # entry at close 5 -> exit at close 6; entry at close 8 has no exit -> dropped
    assert trade_indices(entry, exit_) == [(1, 2), (5, 6)]
    # an exit signal on the last close has no next open -> the trade is dropped
    assert trade_indices([True, False, False], [False, False, True]) == []
