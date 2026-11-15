"""M29 (ADR-0021 D6, amendment A1): the S1 rule and its screen. Synthetic cases with exactly
known answers; no market data is read."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from qqq1dte.backtesting.orb_screen import (
    Candidate,
    cap_hit_index,
    exit_quote,
    longest_losing_run,
    max_drawdown,
    mean_bounds,
    pick_one,
    screen_outcome,
    session_decision,
    trade_pnl,
)
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import BrokerFees, load_config
from qqq1dte.execution_sim.selection import Contract, Quote
from qqq1dte.strategies.orb import orb_exit, orb_signal

CFG = load_config()
CAL = TradingCalendar(CFG)
FLAT = BrokerFees(
    commission_per_contract=1.0,
    min_per_order=0.0,
    occ_clearing_per_contract=0.0,
    cat_per_contract=0.0,
    sec_fee_rate_on_sales=0.0,
)
D = date(2024, 3, 5)  # a regular session; 09:30 ET = 14:30 UTC
EXP = date(2024, 3, 6)
OPEN = datetime(2024, 3, 5, 14, 30, tzinfo=UTC)
LISTED = datetime(2024, 3, 4, 12, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return OPEN + timedelta(minutes=minutes)


# the rule (strategies.orb) ------------------------------------------------------------------
def test_up_candle_is_a_call_with_stop_at_the_low_and_target_at_ten_r() -> None:
    s = orb_signal([100.0, 99.8, 100.1, 100.3, 100.2, 100.4], 10.0)
    assert s is not None
    assert (s.side, s.entry, s.stop) == ("C", 100.4, 99.8)
    assert s.stop_distance == pytest.approx(0.6)
    assert s.target == pytest.approx(106.4)


def test_down_candle_is_a_put_with_stop_at_the_high() -> None:
    s = orb_signal([50.0, 50.2, 49.9, 49.8, 49.9, 49.7], 10.0)
    assert s is not None
    assert (s.side, s.entry, s.stop) == ("P", 49.7, 50.2)
    assert s.target == pytest.approx(49.7 - 10 * 0.5)


def test_flat_candle_has_no_signal_whatever_happened_inside_it() -> None:
    assert orb_signal([100.0, 101.0, 99.0, 100.0], 10.0) is None


def test_signal_needs_an_open_and_a_close() -> None:
    with pytest.raises(ValueError):
        orb_signal([100.0], 10.0)


def test_exit_is_the_first_minute_at_or_beyond_the_stop() -> None:
    s = orb_signal([100.0, 99.8, 100.4], 10.0)
    assert s is not None
    path = [(at(6), 100.5), (at(7), 99.8), (at(8), 99.0), (at(9), 107.0)]
    assert orb_exit(s, path) == (at(7), "STOP", 99.8)


def test_exit_at_the_target_and_none_when_neither_is_reached() -> None:
    s = orb_signal([50.0, 50.2, 49.7], 10.0)  # put: stop 50.2, target 44.7
    assert s is not None
    assert orb_exit(s, [(at(6), 50.19), (at(7), 44.7)]) == (at(7), "TARGET", 44.7)
    assert orb_exit(s, [(at(6), 50.19), (at(7), 44.71)]) is None


# P&L ----------------------------------------------------------------------------------------
def test_trade_pnl_is_exact_with_flat_fees() -> None:
    # buy 2.00, sell 2.50: +$50, less $1 each way = $48 on $200 of premium
    net, ret = trade_pnl(2.00, 2.50, FLAT)
    assert net == pytest.approx(48.0)
    assert ret == pytest.approx(0.24)


def test_trade_pnl_of_a_worthless_exit_loses_the_premium_and_both_fees() -> None:
    net, ret = trade_pnl(1.00, 0.0, FLAT)
    assert net == pytest.approx(-102.0)
    assert ret == pytest.approx(-1.02)


def test_trade_pnl_with_ibkr_fees() -> None:
    ibkr = CFG.study_options_day.broker_fees["ibkr_canada"]
    net, _ = trade_pnl(1.10, 1.00, ibkr)
    assert net == pytest.approx(-10.0 - 2 * 1.0253 - 0.00206)


# one position at a time (D3) ----------------------------------------------------------------
def test_pick_one_takes_the_lowest_cost_share_and_breaks_ties_by_order() -> None:
    assert pick_one([("QQQ", 0.03), ("SPY", 0.02), ("IWM", 0.04)]) == "SPY"
    assert pick_one([("QQQ", 0.02), ("SPY", 0.02)]) == "QQQ"
    assert pick_one([]) is None


# exit quote (owner ruling 7) ----------------------------------------------------------------
def q(minutes: float, bid: float | None, ask: float | None, rejected: bool = False) -> Quote:
    return Quote(bid, ask, 10, 10, at(minutes), rejected)


def test_exit_quote_waits_for_the_first_usable_minute() -> None:
    recs = [q(10, 1.0, 1.1), q(11, None, None, rejected=True), q(13, 0.9, 1.0)]
    # trigger at minute 11: rejected; minute 12: the 11 record is still the latest; minute 13 ok
    t, quote = exit_quote(recs, at(11), at(20), CFG)  # type: ignore[misc]
    assert t == at(13) and quote.bid == 0.9


def test_exit_quote_never_uses_a_record_from_after_the_minute() -> None:
    recs = [q(10, 1.0, 1.1), q(10.2, 5.0, 5.1)]  # the second arrives after 10:00 + latency
    t, quote = exit_quote(recs, at(10), at(10), CFG)  # type: ignore[misc]
    assert t == at(10) and quote.bid == 1.0


def test_exit_quote_with_no_bid_sells_at_zero_and_none_when_nothing_is_usable() -> None:
    t, quote = exit_quote([q(10, 0.0, 0.05)], at(10), at(10), CFG)  # type: ignore[misc]
    assert t == at(10) and quote.bid is None
    assert exit_quote([q(5, 1.0, 1.1)], at(10), at(12), CFG) is None  # stale throughout


# one ticker-session -------------------------------------------------------------------------
def chain() -> list[Contract]:
    return [
        Contract(f"X{k}{r}", float(k), r, EXP, LISTED) for k in (99, 100, 101, 102) for r in "CP"
    ]


def und(mids: dict[int, float]) -> list[Quote]:
    return [Quote(m - 0.005, m + 0.005, 100, 100, at(i)) for i, m in sorted(mids.items())]


def flat_path(first: dict[int, float], level: float, last: int = 380) -> dict[int, float]:
    return {**{i: level for i in range(6, last + 1)}, **first}


CANDLE_UP = {0: 100.0, 1: 99.8, 2: 100.1, 3: 100.3, 4: 100.2, 5: 100.4}


def opt(symbol: str, quotes: list[tuple[float, float, float]]) -> dict[str, list[Quote]]:
    return {symbol: [Quote(b, a, 10, 10, at(m)) for m, b, a in quotes]}


def decide(mids: dict[int, float], quotes: dict[str, list[Quote]], **kw: object) -> Candidate:
    return session_decision(
        "QQQ", D, und(mids), chain(), lambda sym: quotes.get(sym, []), CFG, CAL, FLAT,
        **kw,  # type: ignore[arg-type]
    )  # fmt: skip


def test_time_exit_trade_is_priced_at_ask_then_bid_and_at_the_mid() -> None:
    mids = flat_path(CANDLE_UP, 100.9)  # never at the stop 99.8 or the target 106.4
    quotes = opt("X101C", [(5, 1.00, 1.04), (380, 1.50, 1.54)])  # 15:50 = minute 380
    c = decide(mids, quotes)
    assert (c.status, c.side, c.symbol) == ("CANDIDATE", "C", "X101C")
    assert (c.und_exit_reason, c.exit_reason) == ("TIME", "TIME")
    assert c.und_return == pytest.approx(100.9 / 100.4 - 1)
    assert (c.entry_fill, c.exit_fill) == (1.04, 1.50)
    assert c.ret == pytest.approx((46.0 - 2.0) / 104.0)
    assert (c.entry_mid, c.exit_mid) == (1.02, 1.52)
    assert c.ret_mid == pytest.approx((50.0 - 2.0) / 102.0)
    assert c.cost_share == pytest.approx((4.0 + 2.0) / 105.0)


def test_stop_exit_sells_at_the_bid_of_the_stop_minute() -> None:
    mids = flat_path({**CANDLE_UP, 30: 99.7}, 100.5)
    quotes = opt("X101C", [(5, 1.00, 1.04), (30, 0.60, 0.64), (380, 1.50, 1.54)])
    c = decide(mids, quotes)
    assert (c.und_exit_reason, c.exit_time, c.exit_fill) == ("STOP", at(30), 0.60)
    assert c.und_return == pytest.approx(99.7 / 100.4 - 1)


def test_put_on_a_down_candle_picks_the_highest_strike_at_or_below_spot() -> None:
    mids = flat_path({0: 100.9, 1: 101.0, 2: 100.8, 3: 100.7, 4: 100.6, 5: 100.5}, 100.2)
    quotes = opt("X100P", [(5, 0.80, 0.84), (380, 0.90, 0.94)])
    c = decide(mids, quotes)
    assert (c.side, c.symbol, c.stop) == ("P", "X100P", 101.0)
    assert c.und_return == pytest.approx(-(100.2 / 100.5 - 1))


def test_no_trade_reasons() -> None:
    good = opt("X101C", [(5, 1.00, 1.04), (380, 1.50, 1.54)])
    mids = flat_path(CANDLE_UP, 100.9)
    assert decide(flat_path({**CANDLE_UP, 5: 100.0}, 100.0), good).status == "FLAT_FIRST_CANDLE"
    assert decide({k: v for k, v in mids.items() if k != 0}, good).status == "NO_UNDERLYING_QUOTE"
    assert decide(mids, good, excluded=True).status == "EARNINGS_WINDOW"
    assert decide(mids, {}).status == "NO_OPTION_QUOTE"
    wide = decide(mids, opt("X101C", [(5, 1.00, 1.20)]))
    assert wide.status == "SELECTED_CONTRACT_ILLIQUID" and "SPREAD_TOO_WIDE" in wide.detail
    dear = decide(mids, opt("X101C", [(5, 4.95, 5.00), (380, 5.0, 5.1)]))
    assert dear.status == "PREMIUM_OVER_CAP"  # $500 + $1 of fees is over the $500 ceiling
    # the underlying leg (Step A) is still measured on every signal
    assert wide.und_return == dear.und_return == pytest.approx(100.9 / 100.4 - 1)


def test_a_quote_that_arrives_after_the_entry_is_never_the_entry_quote() -> None:
    mids = flat_path(CANDLE_UP, 100.9)
    late = opt("X101C", [(5.5, 1.00, 1.04), (380, 1.50, 1.54)])  # 30 s after 09:35
    assert decide(mids, late).status == "NO_OPTION_QUOTE"


def test_a_contract_listed_after_the_entry_cannot_be_chosen() -> None:
    mids = flat_path(CANDLE_UP, 100.9)
    quotes = {
        **opt("X101C", [(5, 1.00, 1.04), (380, 1.5, 1.54)]),
        **opt("X100.5C", [(5, 1.2, 1.24), (380, 1.7, 1.74)]),
    }
    newer = [*chain(), Contract("X100.5C", 100.5, "C", EXP, at(6))]
    c = session_decision("QQQ", D, und(mids), newer, lambda s: quotes.get(s, []), CFG, CAL, FLAT)
    assert c.symbol == "X101C"


def test_unresolved_exit_is_counted_not_priced() -> None:
    mids = flat_path(CANDLE_UP, 100.9)
    c = decide(mids, opt("X101C", [(5, 1.00, 1.04)]))  # no quote near 15:50
    assert (c.status, c.exit_reason, c.ret) == ("CANDIDATE", "UNRESOLVED_DATA", None)


def test_early_close_session_exits_ten_minutes_before_the_close() -> None:
    d = date(2024, 7, 3)  # 13:00 close -> forced exit 12:50 ET
    o = datetime(2024, 7, 3, 13, 30, tzinfo=UTC)
    mids = flat_path(CANDLE_UP, 100.9, last=200)
    u = [
        Quote(m - 0.005, m + 0.005, 100, 100, o + timedelta(minutes=i))
        for i, m in sorted(mids.items())
    ]
    ch = [Contract("X101C", 101.0, "C", date(2024, 7, 5), LISTED)]
    quotes = {
        "X101C": [
            Quote(b, a, 10, 10, o + timedelta(minutes=m))
            for m, b, a in ((5, 1.0, 1.04), (200, 1.5, 1.54))
        ]
    }
    c = session_decision("QQQ", d, u, ch, lambda s: quotes.get(s, []), CFG, CAL, FLAT)
    assert c.exit_time == o + timedelta(minutes=200) and c.exit_fill == 1.5


# statistics ---------------------------------------------------------------------------------
def test_mean_bounds_of_a_constant_are_that_constant() -> None:
    b = mean_bounds([1, 1, 2, 3], [0.5, 0.5, 0.5, 0.5], reps=200, seed=1, lower_level=0.95)
    assert b.mean == b.lower == b.two_sided_low == b.two_sided_high == pytest.approx(0.5)


def test_mean_bounds_resample_sessions_and_order_correctly() -> None:
    rng = np.random.default_rng(0)
    v = rng.normal(0.1, 1.0, 400)
    sid = np.repeat(np.arange(200), 2)
    b = mean_bounds(sid, v, reps=2000, seed=7, lower_level=0.95)
    assert b.two_sided_low < b.lower < b.mean < b.two_sided_high
    assert b.mean == pytest.approx(float(v.mean()))
    # a stricter one-sided level gives a lower bound
    assert mean_bounds(sid, v, reps=2000, seed=7, lower_level=0.9833).lower < b.lower
    # same seed, same answer
    assert mean_bounds(sid, v, reps=2000, seed=7, lower_level=0.95) == b


def test_outcome_rules() -> None:
    ok = {"step_a_lower": 0.001, "b_lower": 0.01, "trades": 60, "min_trades": 60,
          "kill_upper": 0.2}  # fmt: skip
    assert screen_outcome(**ok) == "ADVANCE"
    assert screen_outcome(**{**ok, "trades": 59}) == "AMBIGUOUS"
    assert screen_outcome(**{**ok, "b_lower": 0.0}) == "AMBIGUOUS"
    assert screen_outcome(**{**ok, "step_a_lower": 0.0}) == "AMBIGUOUS"  # stops at Step A
    assert screen_outcome(**{**ok, "b_lower": -0.2, "kill_upper": -0.01}) == "KILL"
    assert screen_outcome(**{**ok, "step_a_lower": -1.0, "kill_upper": -0.01}) == "KILL"


def test_risk_rows() -> None:
    pnl = [10.0, -5.0, -5.0, 0.0, -1.0, 20.0, -30.0]
    assert longest_losing_run(pnl) == 2  # a zero is not a loss
    assert max_drawdown(pnl) == pytest.approx(30.0)
    assert max_drawdown([5.0, 5.0]) == 0.0
    assert cap_hit_index([-400.0, -500.0, -100.0, 50.0], 1000.0) == 2
    assert cap_hit_index([-400.0, 500.0], 1000.0) is None
