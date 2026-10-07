"""Underlying labels A/B/D (spec §3): T-LBL-01, 02, 04, 05, 06, 07."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import polars as pl

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import ET
from qqq1dte.labels.underlying import underlying_labels

CFG = load_config()
CAL = TradingCalendar(CFG)
D = date(2025, 3, 11)
P0 = 500.0


def et(hh: int, mm: int) -> datetime:
    return datetime.combine(D, time(hh, mm), tzinfo=ET).astimezone(UTC)


def bars(
    path: dict[int, tuple[float, float, float]] | None = None, skip: tuple[int, ...] = ()
) -> pl.DataFrame:
    """RTH bars, minute i labelled 09:30 + i. Default flat at P0 (H = L = C = P0).
    path[i] = (high, low, close) overrides minute i."""
    path = path or {}
    rows = []
    for i in range(390):
        if i in skip:
            continue
        h, lo, c = path.get(i, (P0, P0, P0))
        ts = et(9, 30) + timedelta(minutes=i)
        rows.append({"session_date": D, "ts": ts, "available_at": ts + timedelta(minutes=1),
                     "open": P0, "high": h, "low": lo, "close": c, "volume": 100,
                     "is_rth": True})  # fmt: skip
    return pl.DataFrame(rows, schema={"session_date": pl.Date, "ts": pl.Datetime("ns", "UTC"),
                                      "available_at": pl.Datetime("ns", "UTC"), "open": pl.Float64,
                                      "high": pl.Float64, "low": pl.Float64, "close": pl.Float64,
                                      "volume": pl.Int64, "is_rth": pl.Boolean})  # fmt: skip


T = et(11, 0)  # P_T = close of bar 10:59 (i = 89) = P0; W = (11:00, 12:30], bars i = 90..179
LAST = 179  # bar labelled 12:29 ends at T_end = 12:30


def by_id(rows: list) -> dict[tuple[str, str], object]:  # type: ignore[type-arg]
    return {(r.label_id, r.variant): r for r in rows}


def test_lbl_01_direction_deadband() -> None:
    up4 = by_id(underlying_labels(bars({LAST: (P0, P0, P0 * 1.0004)}), D, T, CAL, CFG))
    up6 = by_id(underlying_labels(bars({LAST: (P0, P0, P0 * 1.0006)}), D, T, CAL, CFG))
    assert up4[("A_up", "")].value == 0  # +4 bp inside the 5 bp deadband
    assert up6[("A_up", "")].value == 1
    dn6 = by_id(underlying_labels(bars({LAST: (P0, P0, P0 * 0.9994)}), D, T, CAL, CFG))
    assert dn6[("A_dn", "")].value == 1 and dn6[("A_up", "")].value == 0


def test_lbl_02_magnitude_touch_is_inclusive() -> None:
    hit = P0 * 1.0025
    rows = by_id(underlying_labels(bars({120: (hit, P0, P0)}), D, T, CAL, CFG))
    assert rows[("B_up", "m=0.0025")].value == 1
    assert rows[("B_up", "m=0.005")].value == 0
    just_below = by_id(underlying_labels(bars({120: (hit - 0.001, P0, P0)}), D, T, CAL, CFG))
    assert just_below[("B_up", "m=0.0025")].value == 0


STOP, TARGET = CFG.labels.risk.stop, CFG.labels.risk.target


def test_risk_defaults_are_adr_0007() -> None:
    assert (STOP, TARGET) == (0.0019, 0.0030)  # option-bracket mirror, pre-holdout M6 evidence


def test_risk_label_stop_first_target_first_unresolved() -> None:
    stop, target = P0 * (1 - STOP), P0 * (1 + TARGET)
    s_first = by_id(
        underlying_labels(bars({100: (P0, stop, P0), 110: (target, P0, P0)}), D, T, CAL, CFG)
    )
    assert (s_first[("D_call", "")].value, s_first[("D_call", "")].outcome_class) == (
        1,
        "STOP_FIRST",
    )
    t_first = by_id(
        underlying_labels(bars({100: (target, P0, P0), 110: (P0, stop, P0)}), D, T, CAL, CFG)
    )
    assert (t_first[("D_call", "")].value, t_first[("D_call", "")].outcome_class) == (
        0,
        "TARGET_FIRST",
    )
    flat = by_id(underlying_labels(bars(), D, T, CAL, CFG))
    assert (flat[("D_call", "")].value, flat[("D_call", "")].outcome_class) == (None, "UNRESOLVED")
    # put side mirrors: stop = +0.15%, target = -0.25%
    p = by_id(underlying_labels(bars({100: (P0 * (1 + STOP), P0, P0)}), D, T, CAL, CFG))
    assert p[("D_put", "")].outcome_class == "STOP_FIRST"


def test_lbl_04_ambiguous_bar_counts_as_stop_first() -> None:
    both = (P0 * (1 + TARGET), P0 * (1 - STOP), P0)
    rows = by_id(underlying_labels(bars({100: both}), D, T, CAL, CFG))
    r = rows[("D_call", "")]
    assert (r.value, r.outcome_class, r.ambiguous_bar) == (1, "STOP_FIRST", True)


def test_lbl_05_horizon_clipped_at_forced_exit() -> None:
    t = et(15, 0)
    rows = underlying_labels(bars(), D, t, CAL, CFG)
    assert {r.t_end for r in rows} == {et(15, 50)}  # not 16:30


def test_lbl_06_missing_bar_inside_window_is_invalid() -> None:
    rows = underlying_labels(bars(skip=(150,)), D, T, CAL, CFG)
    assert all(r.outcome_class == "INVALID" and r.value is None for r in rows)
    assert {r.reason for r in rows} == {"MISSING_BAR"}
    # a gap outside the window does not matter
    ok = underlying_labels(bars(skip=(300,)), D, T, CAL, CFG)
    assert all(r.outcome_class != "INVALID" for r in ok)


def test_lbl_07_up_and_down_are_not_complements() -> None:
    rows = by_id(underlying_labels(bars(), D, T, CAL, CFG))
    assert rows[("B_up", "m=0.0025")].value == 0 and rows[("B_dn", "m=0.0025")].value == 0
    assert rows[("A_up", "")].value == 0 and rows[("A_dn", "")].value == 0


def test_window_starts_after_t_bar_ending_at_t_is_not_in_window() -> None:
    # Bar labelled 10:59 ends at 11:00 = T: it sets P_T and is NOT part of W = (T, T_end].
    rows = by_id(underlying_labels(bars({89: (P0 * 1.01, P0, P0)}), D, T, CAL, CFG))
    assert rows[("B_up", "m=0.0025")].value == 0


def test_risk_target_is_independent_of_magnitude_threshold() -> None:
    """A +0.25% touch (B's primary threshold) no longer resolves D: its target is 0.30%."""
    rows = by_id(underlying_labels(bars({100: (P0 * 1.0026, P0, P0)}), D, T, CAL, CFG))
    assert rows[("B_up", "m=0.0025")].value == 1
    assert rows[("D_call", "")].outcome_class == "UNRESOLVED"
