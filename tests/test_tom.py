"""M26 (ADR-0017 D1, D4, D5): the frozen turn-of-month rule. Exact synthetic cases."""

from __future__ import annotations

from datetime import date

import pytest

from qqq1dte.strategies.tom import tom_trade, tom_windows

CAL = [
    date(2005, 1, 31),  # partial first month: one session, no window
    date(2005, 2, 1), date(2005, 2, 2), date(2005, 2, 3), date(2005, 2, 4), date(2005, 2, 7),
    date(2005, 2, 24), date(2005, 2, 25), date(2005, 2, 28),
    date(2005, 3, 1), date(2005, 3, 2), date(2005, 3, 3), date(2005, 3, 4),
    date(2005, 3, 30), date(2005, 3, 31),  # no April sessions: March has no window
]  # fmt: skip


def test_windows_enter_day_minus_2_exit_day_plus_3() -> None:
    w = tom_windows(CAL, entry_from_end=2, exit_day=3)
    # January's entry would be the 2nd-to-last January session, which is not in the calendar
    assert w == [(date(2005, 2, 25), date(2005, 3, 3))]


def test_windows_need_the_full_exit() -> None:
    short = [*CAL[:-2], date(2005, 3, 31), date(2005, 4, 1), date(2005, 4, 4)]
    assert tom_windows(short, 2, 3)[-1] == (date(2005, 2, 25), date(2005, 3, 3))


def test_trade_whole_shares_cash_account_hand_case() -> None:
    # $5,000, close $100: 50 shares + $2.50 costs would overdraw -> 49 shares ($4,900):
    #   buy $1 + 3 bps x 4,900 = $2.47, cash 97.53
    # adjusted path 100 -> 97 -> 99 -> 102: exit value 4,998; sell $1 + $1.4994
    # T-bills 1.0005: cash 97.578765; end 5,093.079365 -> net 0.018615873, excess 0.018115873
    t = tom_trade(5000.0, 100.0, [100.0, 97.0, 99.0, 102.0], 1.0005, 0.005, 1.0, 0.01, 3.0)
    assert t.shares == 49
    assert t.costs == pytest.approx(2.47 + 2.4994)
    assert t.net_excess == pytest.approx(5093.079365 / 5000 - 1 - 0.0005)
    assert t.gross_excess == pytest.approx((4998 + 100 * 1.0005) / 5000 - 1 - 0.0005)
    # worst day: 4,997.53 -> 97.53 + 4,753 = 4,850.53
    assert t.worst_day == pytest.approx(4850.53 / 4997.53 - 1)
    t2 = tom_trade(5000.0, 100.0, [100.0, 102.0], 1.0, 0.005, 1.0, 0.01, 3.0, cost_mult=2.0)
    assert t2.costs == pytest.approx(2 * (1 + 0.0003 * 4900) + 2 * (1 + 0.0003 * 4998))
