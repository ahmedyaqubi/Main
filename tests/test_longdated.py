"""M23 (ADR-0014 D2, R2, R5): longer-dated SPX trade-definition helpers, exact synthetic cases."""

from __future__ import annotations

import math
from datetime import date

import pytest

from qqq1dte.execution_sim.longdated import (
    choose_expiry,
    exit_session,
    mde_upper_bound,
    select_stored_expiry,
    width_from_close,
)

SESSIONS = [
    date(2024, 6, 3),
    date(2024, 6, 4),
    date(2024, 6, 5),
    date(2024, 6, 6),
    date(2024, 6, 7),
    date(2024, 6, 10),
    date(2024, 6, 11),
    date(2024, 6, 12),
    date(2024, 6, 13),
    date(2024, 6, 14),
    date(2024, 6, 17),
    date(2024, 6, 18),
    date(2024, 6, 20),
    date(2024, 6, 21),
]  # fmt: skip  (2024-06-19 is a holiday)


def test_width_scales_with_close_and_rounds_to_grid() -> None:
    assert width_from_close(5000.0, 0.005, 5.0, 10.0) == 25.0  # 0.5% of 5000
    assert width_from_close(5430.0, 0.005, 5.0, 10.0) == 25.0  # 27.15 -> nearest 5 = 25
    assert width_from_close(5550.0, 0.005, 5.0, 10.0) == 30.0  # 27.75 -> 30
    assert width_from_close(1500.0, 0.005, 5.0, 10.0) == 10.0  # 7.5 -> minimum 10


def test_choose_expiry_closest_dte_ties_to_earlier() -> None:
    d = date(2024, 6, 3)
    exps = {date(2024, 6, 7), date(2024, 6, 10), date(2024, 6, 14)}
    # DTE 4, 7, 11 -> target 7 picks 06-10; target 9 is a tie (7 vs 11 -> |-2| vs |2|): earlier
    assert choose_expiry(exps, d, 7, set(SESSIONS)) == date(2024, 6, 10)
    assert choose_expiry(exps, d, 9, set(SESSIONS)) == date(2024, 6, 10)
    # an expiry that is not a session, or not after d, is never chosen
    assert choose_expiry({date(2024, 6, 19), d}, d, 16, set(SESSIONS)) is None
    assert choose_expiry(set(), d, 7, set(SESSIONS)) is None


def test_exit_session_is_the_session_before_expiry() -> None:
    assert exit_session(date(2024, 6, 21), SESSIONS) == date(2024, 6, 20)
    assert exit_session(date(2024, 6, 20), SESSIONS) == date(2024, 6, 18)  # skips the holiday
    assert exit_session(date(2024, 6, 3), SESSIONS) is None


def test_mde_upper_bound() -> None:
    # sigma <= range / 2 (Popoviciu); MDE = (z_0.95 + z_0.80) * sigma / sqrt(n_eff)
    z = 1.6448536269514722 + 0.8416212335729143
    assert mde_upper_bound(2000.0, 100) == pytest.approx(z * 1000.0 / 10.0)
    assert mde_upper_bound(2000.0, 25, alpha=0.05, power=0.8) == pytest.approx(z * 1000.0 / 5.0)
    assert math.isinf(mde_upper_bound(2000.0, 0))


def test_expiry_not_stored_is_unresolved_not_substituted() -> None:
    d = date(2024, 6, 3)
    e7, e30 = date(2024, 6, 10), date(2024, 6, 21)
    s = set(SESSIONS)
    # E30 was listed before D (known at T_e) but not stored: never substitute E7
    assert select_stored_expiry({e7, e30}, set(), {e7}, d, 18, s) == ("EXPIRY_NOT_STORED", e30)
    assert select_stored_expiry({e7, e30}, set(), {e7, e30}, d, 18, s) == ("OK", e30)
    # an expiry known only from today's definitions (available by T_e) counts as listed
    assert select_stored_expiry(set(), {e7}, {e7}, d, 7, s) == ("OK", e7)
    assert select_stored_expiry(set(), set(), set(), d, 7, s) == ("NO_EXPIRY", None)
