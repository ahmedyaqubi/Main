"""Event-driven session backtester (M11): frozen selection at T_e, target/stop on the bid,
forced flat, one position, max entries per day (T-BT-02...04), unresolved paths, candidates.

Fixture: D = 2025-03-11. QQQ mid 500.40 -> call 501 / put 500 (D+1 expiry). Option quotes every
minute, default bid 1.00 / ask 1.02 -> entry 1.02, target bid >= 1.326, stop bid <= 0.816.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import polars as pl
import pytest

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import ET
from qqq1dte.execution_sim.engine import Signal, run_session

CFG = load_config()
CAL = TradingCalendar(CFG)
D, NEXT = date(2025, 3, 11), date(2025, 3, 12)
CALL = "QQQ   250312C00501000"
PUT = "QQQ   250312P00500000"
DT = pl.Datetime("ns", "UTC")
LAT = timedelta(seconds=CFG.fills.latency_s)


def et(hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime.combine(D, time(hh, mm, ss), tzinfo=ET).astimezone(UTC)


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


Path = dict[datetime, tuple[float | None, float | None, bool]]


def records(
    path: Path | None = None,
    symbol: str = CALL,
    start: datetime | None = None,
    end: datetime | None = None,
    skip: set[datetime] | None = None,
) -> pl.DataFrame:
    """Quotes every minute from `start` to `end`; path[ts] = (bid, ask, rejected)."""
    path, skip = path or {}, skip or set()
    rows, ts = [], start or et(10, 50)
    while ts <= (end or et(15, 59)):
        if ts not in skip:
            bid, ask, rej = path.get(ts, (1.00, 1.02, False))
            rows.append(
                {
                    "symbol": symbol,
                    "available_at": ts,
                    "bid": bid,
                    "ask": ask,
                    "bid_sz": 10,
                    "ask_sz": 10,
                    "rejected": rej,
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


def run(signals: list[tuple[datetime, str]], recs: pl.DataFrame):  # type: ignore[no-untyped-def]
    res = run_session(D, [Signal(t, s) for t, s in signals], und(), chain(), recs, CAL, CFG)
    for c in res.candidates:  # selection only ever sees quotes known at T_e (spec §5)
        assert c.quote_ts is None or c.quote_ts <= c.prediction_ts + LAT
    return res


def test_target_first_on_the_bid_with_full_accounting() -> None:
    res = run(
        [(et(11, 0), "C")],
        records({et(11, 10): (1.20, 1.22, False), et(11, 20): (1.33, 1.35, False)}),
    )
    (tr,) = res.trades
    assert (tr.symbol, tr.strike, tr.entry_ts, tr.entry_price) == (
        CALL,
        501.0,
        et(11, 0) + LAT,
        1.02,
    )
    assert (tr.outcome, tr.exit_reason, tr.exit_ts, tr.exit_price) == (
        "WIN",
        "TARGET",
        et(11, 20),
        1.33,
    )
    assert tr.net_pnl == pytest.approx(29.6) and tr.r_multiple == pytest.approx(29.6 / 21.8)
    assert tr.holding_seconds == 19 * 60 + 55
    assert tr.mfe == pytest.approx(0.31 / 1.02) and tr.mae == pytest.approx(-0.02 / 1.02)
    assert tr.target_price == pytest.approx(1.326) and tr.stop_price == pytest.approx(0.816)
    assert [d.decision for d in res.decisions] == ["ENTERED"]


def test_mid_reaching_target_does_not_trigger() -> None:
    res = run([(et(11, 0), "C")], records({et(11, 20): (1.30, 1.40, False)}))  # mid 1.35
    assert res.trades[0].outcome != "WIN"


def test_bt_02_one_position_at_a_time() -> None:
    res = run(
        [(et(11, 0), "C"), (et(11, 5), "C"), (et(11, 10), "C"), (et(11, 20), "C")],
        records({et(11, 20): (1.33, 1.35, False)}),
    )
    assert [d.decision for d in res.decisions] == [
        "ENTERED",
        "BLOCKED_POSITION_OPEN",
        "BLOCKED_POSITION_OPEN",
        "ENTERED",
    ]
    assert len(res.trades) == 2  # the 11:20 signal enters after the 11:20 exit (T_e 11:20:05)


def test_bt_03_max_entries_per_day() -> None:
    stops: Path = {et(11, m): (0.80, 0.82, False) for m in (1, 6, 11, 16)}
    sig = [(et(11, m), "C") for m in (0, 5, 10, 15)]
    res = run(sig, records(stops))
    assert [t.outcome for t in res.trades] == ["LOSS"] * 3
    assert res.decisions[-1].decision == "NO_TRADE"
    assert res.decisions[-1].reason == "MAX_ENTRIES_PER_DAY"


def test_bt_04_forced_flat_at_1550_and_never_expired() -> None:
    res = run([(et(15, 0), "C")], records({et(15, 50): (1.05, 1.07, False)}))
    (tr,) = res.trades
    assert tr.exit_ts == CAL.forced_exit_time(D) == et(15, 50)
    assert tr.exit_reason == "TIME_EXIT" and tr.exit_price == 1.05
    assert tr.outcome in ("BREAKEVEN", "TIME_EXIT_PROFIT", "TIME_EXIT_LOSS")
    assert tr.outcome != "EXPIRED"


def test_time_exit_at_entry_plus_max_holding() -> None:
    res = run([(et(11, 0), "C")], records({et(12, 30): (1.10, 1.12, False)}))
    (tr,) = res.trades
    assert tr.exit_ts == et(11, 0) + LAT + timedelta(minutes=CFG.trade.max_holding_minutes)
    assert tr.exit_price == 1.10 and tr.outcome == "TIME_EXIT_PROFIT"


def test_long_path_gap_is_unresolved_and_keeps_the_position_open() -> None:
    gap = {et(11, 0) + timedelta(minutes=k) for k in range(31, 120)}
    res = run([(et(11, 0), "C"), (et(12, 0), "C")], records(skip=gap))
    assert res.trades[0].outcome == "UNRESOLVED_DATA"
    assert res.trades[0].exit_reason == "PATH_GAP_TOO_LONG" and res.trades[0].net_pnl is None
    assert res.decisions[1].decision == "BLOCKED_POSITION_OPEN"


def test_no_bid_counts_as_zero_and_stops() -> None:
    res = run([(et(11, 0), "C")], records({et(11, 7): (None, 0.05, False)}))
    tr = res.trades[0]
    assert (tr.outcome, tr.exit_price, tr.exit_ts) == ("LOSS", 0.0, et(11, 7))
    assert "NO_BID_AS_ZERO" in tr.flags


def test_rejected_record_is_skipped_and_flagged() -> None:
    res = run([(et(11, 0), "C")], records({et(11, 7): (0.10, 0.12, True)}))
    tr = res.trades[0]
    assert tr.outcome != "LOSS" and "PATH_GAP" in tr.flags


def test_illiquid_selection_is_no_trade_with_a_candidate_and_no_entry_used() -> None:
    res = run([(et(11, 0), "C"), (et(11, 5), "C")], records({et(11, 0): (1.00, 1.30, False)}))
    d0 = res.decisions[0]
    assert (d0.decision, d0.reason) == ("NO_TRADE", "SELECTED_CONTRACT_ILLIQUID")
    c0 = res.candidates[0]
    assert not c0.passed_gates and "SPREAD_TOO_WIDE" in c0.gate_failures and not c0.selected
    assert res.decisions[1].decision == "ENTERED"


def test_put_side_selects_highest_strike_at_or_below_spot() -> None:
    res = run([(et(11, 0), "P")], records(symbol=PUT))
    assert res.trades[0].symbol == PUT and res.trades[0].strike == 500.0


def test_signals_must_be_prediction_timestamps_in_order() -> None:
    with pytest.raises(ValueError, match="prediction timestamp"):
        run([(et(11, 1), "C")], records())
    with pytest.raises(ValueError, match="order"):
        run([(et(11, 5), "C"), (et(11, 0), "C")], records())


def _cfg_latency(seconds: int):  # type: ignore[no-untyped-def]
    return CFG.model_copy(update={"fills": CFG.fills.model_copy(update={"latency_s": seconds})})


def test_fill_03_optimistic_does_not_trigger_on_the_mid() -> None:
    from qqq1dte.execution_sim.fills import Optimistic  # noqa: PLC0415

    recs = records({et(11, 20): (1.30, 1.40, False)})  # mid 1.35 >= 1.313, bid 1.30 is not
    res = run_session(D, [Signal(et(11, 0), "C")], und(), chain(), recs, CAL, CFG,
                      Optimistic(CFG))  # fmt: skip
    tr = res.trades[0]
    assert tr.fill_model == "OPTIMISTIC" and tr.entry_price == 1.01
    assert tr.outcome != "WIN"


def test_each_model_sets_target_and_stop_from_its_own_entry_fill() -> None:
    from qqq1dte.execution_sim.fills import Optimistic  # noqa: PLC0415

    recs = records({et(11, 0): (1.00, 1.04, False), et(11, 20): (1.33, 1.35, False)})
    sig = [Signal(et(11, 0), "C")]
    cons = run_session(D, sig, und(), chain(), recs, CAL, CFG).trades[0]
    opt = run_session(D, sig, und(), chain(), recs, CAL, CFG, Optimistic(CFG)).trades[0]
    assert (cons.entry_price, cons.target_price) == (1.04, pytest.approx(1.352))
    assert cons.outcome != "WIN"  # bid 1.33 < 1.352
    assert (opt.entry_price, opt.target_price) == (1.02, pytest.approx(1.326))
    assert (opt.outcome, opt.exit_ts, opt.exit_price) == ("WIN", et(11, 20), 1.34)  # sells mid


def test_latency_60s_selects_and_fills_on_the_later_snapshot() -> None:
    cfg = _cfg_latency(60)
    recs = records({et(11, 1): (1.10, 1.12, False)})
    res = run_session(D, [Signal(et(11, 0), "C")], und(), chain(), recs, CAL, cfg)
    c, tr = res.candidates[0], res.trades[0]
    assert c.quote_ts == et(11, 1) and c.latency_s == 60
    assert c.quote_ts <= c.prediction_ts + timedelta(seconds=60)
    assert (tr.entry_ts, tr.entry_price) == (et(11, 1), 1.12)
    assert tr.slippage == pytest.approx((1.12 - 1.02) * 100)  # vs the same fill on T's quote


def test_latency_0_and_5_use_the_same_minute_snapshot() -> None:
    sig = [Signal(et(11, 0), "C")]
    a = run_session(D, sig, und(), chain(), records(), CAL, _cfg_latency(0)).trades[0]
    b = run_session(D, sig, und(), chain(), records(), CAL, _cfg_latency(5)).trades[0]
    assert (a.entry_price, a.outcome, a.net_pnl) == (b.entry_price, b.outcome, b.net_pnl)
    assert a.slippage == 0.0 and b.slippage == 0.0
