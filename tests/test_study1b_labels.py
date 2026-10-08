"""ADR-0012 D1 study label engine (M19S): time exits, other option brackets, the QQQ-bracket exit,
the strike offset, horizon caps and the underlying move at horizon h. Synthetic, exact answers.

Fixture as tests/test_labels_option.py: D = 2025-03-11, T = 11:00 ET, QQQ NBBO mid 500.40 ->
call 501 / put 500; entry quote bid 1.00 / ask 1.02 -> entry 1.02; costs $1.40/contract.
QQQ bars flat at 500.00 (P_T = close of the 10:59 bar); QQQ bracket for T2: stop 0.19% (499.05),
target 0.30% (501.50).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import polars as pl
import pytest

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import ET
from qqq1dte.execution_sim.selection import (
    NO_OFFSET_STRIKE,
    Contract,
    NoTrade,
    Quote,
    Selected,
    choose_contract,
    select_contract,
)
from qqq1dte.labels.common import label_t_end
from qqq1dte.labels.option import ExitRule, option_label
from qqq1dte.labels.underlying import underlying_move

CFG = load_config()
CAL = TradingCalendar(CFG)
D, NEXT = date(2025, 3, 11), date(2025, 3, 12)
CALL = "QQQ   250312C00501000"
DT = pl.Datetime("ns", "UTC")
P0 = 500.0
DEFS = CFG.study_1b.definitions


def et(hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime.combine(D, time(hh, mm, ss), tzinfo=ET).astimezone(UTC)


T = et(11, 0)
T_END = et(12, 30)


def und() -> pl.DataFrame:
    rows = [
        {"available_at": et(9, 31) + timedelta(minutes=k), "bid": 500.39, "ask": 500.41}
        for k in range(390)
    ]
    return pl.DataFrame(rows, schema={"available_at": DT, "bid": pl.Float64, "ask": pl.Float64})


def chain() -> pl.DataFrame:
    rows = [
        {
            "session_date": D,
            "raw_symbol": f"QQQ   250312{r}{k * 1000:08d}",
            "expiration": NEXT,
            "strike": float(k),
            "right": r,
            "available_at": et(6, 30),
        }
        for k in (499, 500, 501, 502)
        for r in "CP"
    ]
    return pl.DataFrame(
        rows,
        schema={
            "session_date": pl.Date,
            "raw_symbol": pl.String,
            "expiration": pl.Date,
            "strike": pl.Float64,
            "right": pl.String,
            "available_at": DT,
        },
    )


def records(
    path: dict[datetime, float] | None = None,
    flat_bid: float = 1.00,
    end: datetime | None = None,
    symbol: str = CALL,
) -> pl.DataFrame:
    """Quotes every minute from 10:58 to `end`; path[ts] = bid (ask = bid + 0.02)."""
    path = path or {}
    end = end or et(15, 50)
    rows = []
    ts = et(10, 58)
    while ts <= end:
        bid = 1.00 if ts == T else path.get(ts, flat_bid)
        rows.append(
            {
                "symbol": symbol,
                "available_at": ts,
                "bid": bid,
                "ask": round(bid + 0.02, 2),
                "bid_sz": 10,
                "ask_sz": 10,
                "rejected": False,
            }
        )
        ts += timedelta(minutes=1)
    return pl.DataFrame(
        rows,
        schema={
            "symbol": pl.String,
            "available_at": DT,
            "bid": pl.Float64,
            "ask": pl.Float64,
            "bid_sz": pl.Int64,
            "ask_sz": pl.Int64,
            "rejected": pl.Boolean,
        },
    )


def bars(path: dict[int, tuple[float, float, float]] | None = None, skip: tuple[int, ...] = ()):  # type: ignore[no-untyped-def]
    """RTH bars, minute i labelled 09:30 + i, flat at P0; path[i] = (high, low, close)."""
    path = path or {}
    rows = []
    for i in range(390):
        if i in skip:
            continue
        h, lo, c = path.get(i, (P0, P0, P0))
        ts = et(9, 30) + timedelta(minutes=i)
        rows.append(
            {
                "session_date": D,
                "ts": ts,
                "available_at": ts + timedelta(minutes=1),
                "open": P0,
                "high": h,
                "low": lo,
                "close": c,
                "volume": 100,
                "is_rth": True,
            }
        )
    return pl.DataFrame(
        rows,
        schema={
            "session_date": pl.Date,
            "ts": DT,
            "available_at": DT,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Int64,
            "is_rth": pl.Boolean,
        },
    )


def lab(defn: str, recs: pl.DataFrame, b: pl.DataFrame | None = None, side: str = "C"):  # type: ignore[no-untyped-def]
    rule = ExitRule.from_study(DEFS[defn])
    return option_label(side, T, D, und(), chain(), recs, CAL, CFG, rule=rule, bars=b)


def i_of(hh: int, mm: int) -> int:
    return (hh - 9) * 60 + mm - 30


# --- exit rules -------------------------------------------------------------------------------


def test_phase1_rule_is_the_default() -> None:
    recs = records({et(11, 20): 1.40})
    assert option_label("C", T, D, und(), chain(), recs, CAL, CFG) == option_label(
        "C", T, D, und(), chain(), recs, CAL, CFG, rule=ExitRule.phase1(CFG)
    )
    assert lab("T0", recs) == option_label("C", T, D, und(), chain(), recs, CAL, CFG)


def test_time_exit_ignores_bracket_crossings() -> None:
    row, oc = lab("T1b", records({et(11, 20): 1.40, et(11, 30): 0.50}))
    assert (oc.outcome_class, oc.exit_ts, oc.exit_price) == ("TIME_EXIT_LOSS", T_END, 1.00)
    assert oc.net_pnl == pytest.approx((1.00 - 1.02) * 100 - 1.40)
    assert row.t_end == T_END


def test_time_exit_at_45_minutes() -> None:
    _, oc = lab("T1a", records(flat_bid=1.10))
    assert (oc.outcome_class, oc.exit_ts, oc.exit_price) == ("TIME_EXIT_PROFIT", et(11, 45), 1.10)


def test_symmetric_bracket_stop_at_30_percent() -> None:
    # entry 1.02 -> stop bid <= 0.714: 0.72 does not trigger, 0.71 does
    _, oc = lab("T4", records({et(11, 10): 0.72, et(11, 15): 0.71}))
    assert (oc.outcome_class, oc.exit_ts, oc.exit_price) == ("LOSS", et(11, 15), 0.71)
    _, base = lab("T0", records({et(11, 10): 0.72, et(11, 15): 0.71}))
    assert (base.outcome_class, base.exit_ts) == ("LOSS", et(11, 10))  # -20% stop is 0.816


def test_horizon_cap_and_forced_flat() -> None:
    assert label_t_end(T, D, CAL, CFG, horizon_minutes=150) == et(13, 30)
    assert label_t_end(et(14, 30), D, CAL, CFG, horizon_minutes=150) == et(15, 50)
    assert label_t_end(T, D, CAL, CFG) == T_END  # default: labels.horizon_minutes


# --- QQQ-bracket exit (T2) ---------------------------------------------------------------------


def test_und_stop_exits_at_option_bid_when_the_bar_is_known() -> None:
    i = i_of(11, 10)  # bar 11:10-11:11, known at 11:11
    row, oc = lab("T2", records({et(11, 11): 0.90}), bars({i: (P0, 499.00, 499.2)}))
    assert (oc.outcome_class, oc.exit_ts, oc.exit_price) == ("UND_STOP", et(11, 11), 0.90)
    assert oc.net_pnl == pytest.approx((0.90 - 1.02) * 100 - 1.40)
    assert not row.ambiguous_bar


def test_und_target_first() -> None:
    i = i_of(11, 5)
    _, oc = lab("T2", records({et(11, 6): 1.25}), bars({i: (501.60, P0, 501.5)}))
    assert (oc.outcome_class, oc.exit_ts, oc.exit_price) == ("UND_TARGET", et(11, 6), 1.25)


def test_und_same_bar_is_stop_first_and_flagged() -> None:
    i = i_of(11, 5)
    row, oc = lab("T2", records({et(11, 6): 1.25}), bars({i: (501.60, 499.00, P0)}))
    assert oc.outcome_class == "UND_STOP" and row.ambiguous_bar


def test_und_put_side_is_mirrored() -> None:
    put = "QQQ   250312P00500000"
    i = i_of(11, 10)  # QQQ up 0.30% -> stop for the put
    _, oc = lab(
        "T2", records({et(11, 11): 0.80}, symbol=put), bars({i: (501.60, P0, 501.5)}), side="P"
    )
    assert (oc.outcome_class, oc.exit_price) == ("UND_STOP", 0.80)


def test_und_no_trigger_is_a_time_exit() -> None:
    _, oc = lab("T2", records(flat_bid=1.10), bars())
    assert (oc.outcome_class, oc.exit_ts) == ("TIME_EXIT_PROFIT", T_END)


def test_und_missing_bar_is_unresolved_not_filled() -> None:
    row, oc = lab("T2", records(), bars(skip=(i_of(11, 30),)))
    assert (oc.outcome_class, oc.reason) == ("UNRESOLVED_DATA", "MISSING_BAR")
    assert row.value is None


def test_und_exit_ignores_data_after_the_trigger() -> None:
    i = i_of(11, 10)
    b1 = bars({i: (P0, 499.00, 499.2)})
    b2 = bars({i: (P0, 499.00, 499.2), i + 5: (510.0, 480.0, 505.0)})
    r1 = records({et(11, 11): 0.90})
    r2 = records({et(11, 11): 0.90, et(11, 12): 3.00, et(11, 40): 0.01})
    assert lab("T2", r1, b1) == lab("T2", r2, b2)


# --- strike offset (T3) ------------------------------------------------------------------------


def _contracts() -> list[Contract]:
    return [
        Contract(r["raw_symbol"], r["strike"], r["right"], r["expiration"], r["available_at"])
        for r in chain().iter_rows(named=True)
    ]


def test_offset_moves_listed_strikes_in_the_money() -> None:
    cs, spot, te = _contracts(), 500.40, T + timedelta(seconds=5)
    assert choose_contract(cs, spot, "C", te).strike == 501  # type: ignore[union-attr]
    assert choose_contract(cs, spot, "C", te, strike_offset=2).strike == 499  # type: ignore[union-attr]
    assert choose_contract(cs, spot, "P", te).strike == 500  # type: ignore[union-attr]
    assert choose_contract(cs, spot, "P", te, strike_offset=2).strike == 502  # type: ignore[union-attr]
    assert choose_contract(cs, spot, "C", te, strike_offset=3) is None


def test_missing_offset_strike_is_a_logged_no_trade() -> None:
    cs, te = _contracts(), T + timedelta(seconds=5)
    q = {c.symbol: Quote(1.0, 1.02, 10, 10, T) for c in cs}
    out = select_contract(cs, 500.40, "C", q, te, CFG, strike_offset=3)
    assert isinstance(out, NoTrade) and out.reason == NO_OFFSET_STRIKE
    ok = select_contract(cs, 500.40, "C", q, te, CFG, strike_offset=2)
    assert isinstance(ok, Selected) and ok.contract.strike == 499


def test_itm_label_trades_the_offset_contract() -> None:
    itm = "QQQ   250312C00499000"
    _, oc = lab("T3", records(flat_bid=1.10, symbol=itm))
    assert (oc.contract, oc.strike, oc.exit_ts) == (itm, 499.0, T_END)


# --- underlying move at horizon h --------------------------------------------------------------


def test_underlying_move_at_horizons() -> None:
    b = bars({i_of(12, 29): (P0, P0, P0 * 1.0006), i_of(11, 44): (P0, P0, P0 * 0.999)})
    r90, end90, why = underlying_move(b, D, T, CAL, CFG, 90)
    assert r90 == pytest.approx(0.0006) and end90 == T_END and why is None
    r45, end45, _ = underlying_move(b, D, T, CAL, CFG, 45)
    assert r45 == pytest.approx(-0.001) and end45 == et(11, 45)


def test_underlying_move_missing_bar() -> None:
    r, _, why = underlying_move(bars(skip=(i_of(11, 30),)), D, T, CAL, CFG, 90)
    assert r is None and why == "MISSING_BAR"
