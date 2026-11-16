"""M33 (ADR-0021 amendment A3, setup S3): the noise-area breakout and its screen. Synthetic
cases with exactly known answers; no market data is read.

Owner rulings of 2026-11-16 (plan approved) tested here:
1. today's open is the quote in force one minute after the open (09:31:00);
2. the previous close is the quote in force one minute before the previous session's close;
3. boundaries and the 14-session average use mids; a signal needs the whole quote outside (call:
   bid above the upper boundary; put: ask below the lower), and so does an exit; a check with no
   usable quote is skipped;
4. the 14 most recent usable sessions; early closes and sessions with a missing quote are not
   usable; fewer than 14 -> NO_HISTORY; a split session -> CORPORATE_ACTION;
5. one position at a time across times of day;
6. Step A = signed mid(exit) / mid(entry check) - 1 on every ticker-session with a signal.
"""

from __future__ import annotations

import copy
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from qqq1dte.backtesting.noise_area_screen import (
    S3Candidate,
    SessionMoves,
    apply_one_position_timed,
    check_times,
    session_decision,
    session_moves,
)
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import BrokerFees, Phase1Config, load_config
from qqq1dte.execution_sim.selection import Contract, Quote
from qqq1dte.strategies.noise_area import boundaries, noise_exit, noise_signal, sigma

CFG = load_config()
CAL = TradingCalendar(CFG)
NA = CFG.study_options_day.noise_area
FLAT = BrokerFees(
    commission_per_contract=1.0,
    min_per_order=0.0,
    occ_clearing_per_contract=0.0,
    cat_per_contract=0.0,
    sec_fee_rate_on_sales=0.0,
)
PREV = date(2024, 3, 4)
D = date(2024, 3, 5)  # a regular session; 09:30 ET = 14:30 UTC
EXP = date(2024, 3, 6)
OPEN = datetime(2024, 3, 5, 14, 30, tzinfo=UTC)
PREV_CLOSE = datetime(2024, 3, 4, 21, 0, tzinfo=UTC)  # 16:00 ET
LISTED = datetime(2024, 3, 1, 12, 0, tzinfo=UTC)
CHECKS = check_times(NA.first_check, NA.last_exit_check, NA.check_interval_minutes)
CHECK_MIN = [30 * i for i in range(1, 13)]  # minutes after the open: 10:00 ... 15:30
EXIT = 380  # 15:50
EARLIER = CAL.sessions(date(2024, 1, 2), date(2024, 3, 1))  # sessions before PREV


def at(minutes: float) -> datetime:
    return OPEN + timedelta(minutes=minutes)


def uq(t: datetime, mid: float, half: float = 0.005) -> Quote:
    return Quote(mid - half, mid + half, 100, 100, t)


def und(prev: float | None, open_: float | None, mids: dict[float, float]) -> list[Quote]:
    """Previous-close quote stamped 15:59 of PREV, the open quote stamped 09:31, then one quote
    at every check and at 15:50: 100.0 (inside the noise area) unless `mids` says otherwise."""
    path = {**dict.fromkeys([*CHECK_MIN, EXIT], 100.0), **mids}
    out = [] if prev is None else [uq(PREV_CLOSE - timedelta(minutes=1), prev)]
    if open_ is not None:
        out.append(uq(at(1), open_))
    return out + [uq(at(i), m) for i, m in sorted(path.items())]


def hist(n: int = 14, move: float = 0.01, **at_time: float) -> list[SessionMoves]:
    """n earlier sessions whose absolute move from the open is `move` at every check, except
    the times given as e.g. t1000=0.005."""
    moves = dict.fromkeys(CHECKS, move)
    for key, v in at_time.items():
        moves[time(int(key[1:3]), int(key[3:5]))] = v
    return [SessionMoves(d, dict(moves)) for d in EARLIER[-n:]]


def chain() -> list[Contract]:
    return [Contract(f"X{k}{r}", float(k), r, EXP, LISTED) for k in range(96, 105) for r in "CP"]


def opt(symbol: str, quotes: list[tuple[float, float, float]]) -> dict[str, list[Quote]]:
    return {symbol: [Quote(b, a, 10, 10, at(m)) for m, b, a in quotes]}


def decide(underlying: list[Quote], quotes: dict[str, list[Quote]], **kw: Any) -> S3Candidate:
    args: dict[str, Any] = {"prev_session": PREV, "history": hist(), **kw}
    return session_decision(
        "QQQ", D, underlying, chain(), lambda sym: quotes.get(sym, []), CFG, CAL, FLAT, **args
    )


# with open = previous close = 100 and sigma = 1%: upper 101, lower 99
UP_1030 = {60: 101.2, EXIT: 101.5}
CALL_1030 = opt("X102C", [(60, 1.00, 1.04), (EXIT, 1.50, 1.54)])


# the rule (strategies.noise_area) -----------------------------------------------------------
def test_sigma_is_the_mean_absolute_move() -> None:
    assert sigma([0.01, -0.02, 0.03]) == pytest.approx(0.02)
    with pytest.raises(ValueError):
        sigma([])


def test_boundaries_anchor_on_the_higher_and_the_lower_of_open_and_previous_close() -> None:
    assert boundaries(100.0, 100.0, 0.01) == pytest.approx((101.0, 99.0))
    assert boundaries(100.0, 102.0, 0.01) == pytest.approx((103.02, 99.0))  # gap down
    assert boundaries(100.0, 99.0, 0.01) == pytest.approx((101.0, 98.01))  # gap up
    with pytest.raises(ValueError):
        boundaries(0.0, 100.0, 0.01)


def test_a_signal_needs_the_whole_quote_outside_the_noise_area() -> None:
    assert noise_signal(101.01, 101.03, 101.0, 99.0) == "C"
    assert noise_signal(98.97, 98.99, 101.0, 99.0) == "P"
    assert noise_signal(101.0, 101.02, 101.0, 99.0) is None  # the bid only touches the boundary
    assert noise_signal(98.98, 99.0, 101.0, 99.0) is None  # the ask only touches it
    assert noise_signal(100.9, 101.3, 101.0, 99.0) is None  # mid above, bid not
    assert noise_signal(98.0, 102.0, 101.0, 99.0) is None  # a wide quote says nothing
    with pytest.raises(ValueError):
        noise_signal(101.5, 101.4, 101.0, 99.0)  # crossed


def test_an_exit_needs_the_whole_quote_beyond_the_opposite_boundary() -> None:
    assert noise_exit("C", 98.97, 98.99, 101.0, 99.0) is True
    assert noise_exit("C", 98.99, 99.01, 101.0, 99.0) is False
    assert noise_exit("C", 99.9, 100.1, 101.0, 99.0) is False  # back inside is not an exit
    assert noise_exit("P", 101.01, 101.03, 101.0, 99.0) is True
    assert noise_exit("P", 100.99, 101.01, 101.0, 99.0) is False
    assert noise_exit("P", 98.0, 98.02, 101.0, 99.0) is False  # its own side


def test_checks_are_every_half_hour() -> None:
    assert CHECKS[0] == time(10, 0) and CHECKS[-1] == time(15, 30) and len(CHECKS) == 12
    assert time(10, 15) not in CHECKS


# one history session ------------------------------------------------------------------------
def test_session_moves_are_absolute_moves_from_the_0931_quote() -> None:
    u = und(None, 100.0, {30: 100.5, 60: 99.0})
    u.insert(0, uq(at(0), 105.0))  # the 09:30:00 pre-open record is not the open
    m = session_moves(D, u, CFG, CAL)
    assert m is not None and m.session_date == D
    assert m.moves[time(10, 0)] == pytest.approx(0.005)
    assert m.moves[time(10, 30)] == pytest.approx(0.01)
    assert m.moves[time(15, 30)] == pytest.approx(0.0)
    assert set(m.moves) == set(CHECKS)


def test_a_session_with_a_missing_quote_or_an_early_close_is_not_usable_history() -> None:
    assert session_moves(D, und(None, None, {}), CFG, CAL) is None  # no open
    stale_open = [uq(at(0), 100.0), *und(None, None, {})]
    assert session_moves(D, stale_open, CFG, CAL) is not None  # 60 s old at 09:31: still in force
    gap = [q for q in und(None, 100.0, {}) if q.available_at != at(120)]  # no 11:30 quote
    assert session_moves(D, gap, CFG, CAL) is None
    one_sided = [*und(None, 100.0, {}), Quote(0.0, 100.0, 100, 100, at(120))]
    assert session_moves(D, sorted(one_sided, key=lambda q: q.available_at), CFG, CAL) is None
    early = date(2024, 7, 3)  # closed at 13:00 ET
    o = datetime(2024, 7, 3, 13, 30, tzinfo=UTC)
    full = [uq(o + timedelta(minutes=i), 100.0) for i in (1, *CHECK_MIN)]
    assert session_moves(early, full, CFG, CAL) is None


# one ticker-session -------------------------------------------------------------------------
def test_first_check_above_the_upper_boundary_buys_the_call_and_holds_to_1550() -> None:
    c = decide(und(100.0, 100.0, UP_1030), CALL_1030)
    assert (c.status, c.side, c.symbol) == ("CANDIDATE", "C", "X102C")
    assert (c.open_mid, c.prev_close) == pytest.approx((100.0, 100.0))
    assert (c.sigma, c.upper, c.lower) == pytest.approx((0.01, 101.0, 99.0))
    assert c.entry_time == at(60) and c.und_entry == pytest.approx(101.2)
    assert (c.und_exit_reason, c.und_exit_time) == ("TIME", at(EXIT))
    assert c.und_return == pytest.approx(101.5 / 101.2 - 1)  # Step A
    assert (c.exit_reason, c.exit_time, c.exit_delay_minutes) == ("TIME", at(EXIT), 0)
    assert (c.entry_fill, c.exit_fill) == (1.04, 1.50)
    assert c.ret == pytest.approx((46.0 - 2.0) / 104.0)
    assert (c.entry_mid, c.exit_mid) == (1.02, 1.52)
    assert c.ret_mid == pytest.approx((50.0 - 2.0) / 102.0)
    assert c.cost_share == pytest.approx((4.0 + 2.0) / 105.0)
    assert c.checks_skipped == 0 and len(c.history_dates) == 14


def test_first_check_below_the_lower_boundary_buys_the_put() -> None:
    u = und(100.0, 100.0, {30: 98.8, EXIT: 99.1})
    c = decide(u, opt("X98P", [(30, 0.80, 0.84), (EXIT, 0.70, 0.74)]))
    assert (c.status, c.side, c.symbol, c.entry_time) == ("CANDIDATE", "P", "X98P", at(30))
    assert c.und_return == pytest.approx(-(99.1 / 98.8 - 1))
    assert c.ret == pytest.approx((-14.0 - 2.0) / 84.0)


def test_the_gap_moves_one_boundary_only() -> None:
    # previous close 100.6 above the open: upper = 100.6 x 1.01 = 101.606, lower stays 99
    up = decide(und(100.6, 100.0, UP_1030), CALL_1030)
    assert up.status == "NO_SIGNAL" and up.side is None and up.und_return is None
    dn = decide(und(100.6, 100.0, {30: 98.8}), {})
    assert dn.side == "P" and (dn.upper, dn.lower) == pytest.approx((101.606, 99.0))
    # previous close 99.4 below the open: lower = 99.4 x 0.99 = 98.406, upper stays 101
    assert decide(und(99.4, 100.0, {30: 98.8}), {}).status == "NO_SIGNAL"
    assert decide(und(99.4, 100.0, UP_1030), CALL_1030).side == "C"


def test_each_check_uses_its_own_time_of_day_average() -> None:
    h = hist(t1000=0.005, t1030=0.02)
    early = decide(und(100.0, 100.0, {30: 100.8}), {}, history=h)
    assert early.side == "C" and early.entry_time == at(30)
    assert (early.sigma, early.upper) == pytest.approx((0.005, 100.5))
    late = decide(und(100.0, 100.0, {60: 101.2}), {}, history=h)  # 101.2 < 102 at 10:30
    assert late.status == "NO_SIGNAL"


def test_only_the_latest_fourteen_usable_sessions_are_averaged() -> None:
    old = [SessionMoves(d, dict.fromkeys(CHECKS, 0.50)) for d in EARLIER[-16:-14]]
    c = decide(und(100.0, 100.0, UP_1030), CALL_1030, history=[*old, *hist()])
    assert c.sigma == pytest.approx(0.01) and c.history_dates[0] == EARLIER[-14]
    mixed = [*hist(13), SessionMoves(PREV, dict.fromkeys(CHECKS, 0.15))]  # mean = 2%
    assert decide(und(100.0, 100.0, UP_1030), CALL_1030, history=mixed).status == "NO_SIGNAL"


def test_a_breakout_between_checks_is_not_seen() -> None:
    u = und(100.0, 100.0, {45: 102.0, 46: 102.0, 59: 102.0})  # 10:15 to 10:29, inside at 10:30
    c = decide(u, CALL_1030)
    assert c.status == "NO_SIGNAL" and c.side is None


def test_no_entry_after_the_last_entry_check() -> None:
    assert decide(und(100.0, 100.0, {360: 101.5, EXIT: 101.5}), {}).status == "NO_SIGNAL"
    last = decide(und(100.0, 100.0, {330: 101.5}), {})  # 15:00 is still an entry check
    assert last.side == "C" and last.entry_time == at(330)


def test_exit_at_the_first_later_check_beyond_the_opposite_boundary_and_no_reversal() -> None:
    u = und(100.0, 100.0, {30: 101.2, 60: 100.0, 90: 98.8, 120: 98.5, EXIT: 97.0})
    quotes = opt("X102C", [(30, 1.00, 1.04), (90, 0.30, 0.34), (EXIT, 0.21, 0.25)])
    c = decide(u, quotes)
    assert (c.side, c.entry_time) == ("C", at(30))  # one trade: no put at 11:00
    assert (c.und_exit_reason, c.und_exit_time) == ("OPPOSITE", at(90))
    assert c.und_return == pytest.approx(98.8 / 101.2 - 1)
    assert (c.exit_reason, c.exit_time, c.exit_fill) == ("OPPOSITE", at(90), 0.30)
    assert c.ret == pytest.approx((-74.0 - 2.0) / 104.0)


def test_exit_checks_run_to_1530_and_need_the_whole_quote_outside() -> None:
    late = decide(und(100.0, 100.0, {30: 101.2, 360: 98.8}), {})
    assert (late.und_exit_reason, late.und_exit_time) == ("OPPOSITE", at(360))
    u = und(100.0, 100.0, {30: 101.2, EXIT: 100.4})
    u = [q for q in u if q.available_at != at(90)] + [Quote(98.0, 99.5, 100, 100, at(90))]
    wide = decide(sorted(u, key=lambda q: q.available_at), {})
    assert (wide.und_exit_reason, wide.und_exit_time) == ("TIME", at(EXIT))  # ask 99.5 > 99
    put = decide(und(100.0, 100.0, {30: 98.8, 150: 101.2}), {})
    assert (put.side, put.und_exit_reason, put.und_exit_time) == ("P", "OPPOSITE", at(150))
    assert put.und_return == pytest.approx(-(101.2 / 98.8 - 1))


def test_a_check_with_no_usable_quote_is_skipped_and_counted() -> None:
    u = [q for q in und(100.0, 100.0, {30: 101.5, 60: 101.2}) if q.available_at != at(30)]
    c = decide(u, CALL_1030)
    assert (c.side, c.entry_time, c.checks_skipped) == ("C", at(60), 1)
    # after the entry: the 11:00 quote that would have been an exit is missing
    v = [q for q in und(100.0, 100.0, {30: 101.2, 90: 98.8}) if q.available_at != at(90)]
    d = decide(v, {})
    assert (d.und_exit_reason, d.checks_skipped) == ("TIME", 1)


def test_no_history() -> None:
    c = decide(und(100.0, 100.0, UP_1030), CALL_1030, history=hist(13))
    assert c.status == "NO_HISTORY" and c.side is None
    assert decide(und(100.0, 100.0, UP_1030), CALL_1030, history=hist(14)).side == "C"


def test_history_from_today_or_later_is_refused() -> None:
    for bad in (D, date(2024, 3, 6)):
        h = [*hist(13), SessionMoves(bad, dict.fromkeys(CHECKS, 0.01))]
        with pytest.raises(ValueError, match="before"):
            decide(und(100.0, 100.0, UP_1030), CALL_1030, history=h)


def test_no_trade_reasons_before_any_price_is_read() -> None:
    u = und(100.0, 100.0, UP_1030)
    assert decide(u, CALL_1030, excluded=True).status == "EARNINGS_WINDOW"
    assert decide(u, CALL_1030, split=True).status == "CORPORATE_ACTION"
    early = session_decision(
        "QQQ", date(2024, 7, 3), u, chain(), lambda s: [], CFG, CAL, FLAT,
        prev_session=date(2024, 7, 2), history=hist(),
    )  # fmt: skip
    assert early.status == "EARLY_CLOSE"


def test_no_previous_close_and_no_open() -> None:
    u = und(100.0, 100.0, UP_1030)
    assert decide(u, CALL_1030, prev_session=None).status == "NO_PREV_CLOSE"
    assert decide(und(None, 100.0, UP_1030), CALL_1030).status == "NO_PREV_CLOSE"
    stale = [uq(PREV_CLOSE - timedelta(minutes=5), 100.0), *und(None, 100.0, UP_1030)]
    assert decide(stale, CALL_1030).status == "NO_PREV_CLOSE"  # 4 minutes old at 15:59
    no_open = decide(und(100.0, None, UP_1030), CALL_1030)
    assert (no_open.status, no_open.detail) == ("NO_UNDERLYING_QUOTE", "open")


def test_previous_close_is_read_at_1559_and_the_open_at_0931() -> None:
    u = und(100.0, 100.0, UP_1030)
    u.insert(1, uq(PREV_CLOSE, 103.0))  # the 16:00:00 record would lift the upper boundary
    u.insert(2, uq(at(0), 97.0))  # the 09:30:00 record would drop the lower boundary
    u.insert(4, uq(at(1.5), 103.0))  # known only after 09:31:00
    c = decide(u, CALL_1030)
    assert c.side == "C" and (c.prev_close, c.open_mid) == pytest.approx((100.0, 100.0))


def test_previous_close_after_an_early_close_is_read_at_1259() -> None:
    d, prev = date(2024, 7, 5), date(2024, 7, 3)  # 2024-07-03 closed at 13:00 ET = 17:00 UTC
    o = datetime(2024, 7, 5, 13, 30, tzinfo=UTC)
    path = {**dict.fromkeys([1, *CHECK_MIN, EXIT], 100.0), **UP_1030}
    u = [
        uq(datetime(2024, 7, 3, 16, 59, tzinfo=UTC), 100.0),
        *[uq(o + timedelta(minutes=i), m) for i, m in sorted(path.items())],
    ]
    c = session_decision(
        "QQQ", d, u, [], lambda s: [], CFG, CAL, FLAT, prev_session=prev, history=hist()
    )
    assert (c.side, c.prev_close, c.status) == ("C", pytest.approx(100.0), "NO_CONTRACT")


def test_nothing_after_a_check_changes_what_was_decided_at_it() -> None:
    base = decide(und(100.0, 100.0, UP_1030), CALL_1030)
    later = {60.5: 90.0, 61: 90.0, 90: 95.0, 200: 120.0, EXIT: 80.0}
    c = decide(und(100.0, 100.0, {**UP_1030, **later}), CALL_1030)
    same = ("side", "entry_time", "und_entry", "sigma", "upper", "lower", "symbol", "entry_fill")
    assert all(getattr(c, k) == getattr(base, k) for k in same)


def test_step_a_is_measured_whatever_the_option_does() -> None:
    u = und(100.0, 100.0, UP_1030)
    r = 101.5 / 101.2 - 1
    none = decide(u, {})
    assert none.status == "NO_OPTION_QUOTE" and none.und_return == pytest.approx(r)
    wide = decide(u, opt("X102C", [(60, 1.00, 1.20)]))
    assert wide.status == "SELECTED_CONTRACT_ILLIQUID" and "SPREAD_TOO_WIDE" in wide.detail
    dear = decide(u, opt("X102C", [(60, 4.95, 5.00), (EXIT, 5.0, 5.1)]))
    assert dear.status == "PREMIUM_OVER_CAP"  # $500 + $1 of fees is over the $500 ceiling
    assert wide.und_return == dear.und_return == pytest.approx(r)


def test_no_underlying_quote_at_1550_leaves_step_a_out_but_prices_the_option() -> None:
    u = [q for q in und(100.0, 100.0, UP_1030) if q.available_at != at(EXIT)]
    c = decide(u, CALL_1030)
    assert (c.status, c.und_exit_reason, c.und_return) == ("CANDIDATE", "NO_EXIT_QUOTE", None)
    assert (c.exit_reason, c.ret) == ("TIME", pytest.approx((46.0 - 2.0) / 104.0))


def test_entry_quote_and_contract_must_be_known_at_the_check_plus_latency() -> None:
    late = opt("X102C", [(60.5, 1.00, 1.04), (EXIT, 1.50, 1.54)])
    assert decide(und(100.0, 100.0, UP_1030), late).status == "NO_OPTION_QUOTE"
    quotes = {**CALL_1030, **opt("X101.5C", [(60, 1.2, 1.24), (EXIT, 1.7, 1.74)])}
    newer = [*chain(), Contract("X101.5C", 101.5, "C", EXP, at(61))]
    c = session_decision(
        "QQQ", D, und(100.0, 100.0, UP_1030), newer, lambda s: quotes.get(s, []), CFG, CAL, FLAT,
        prev_session=PREV, history=hist(),
    )  # fmt: skip
    assert c.symbol == "X102C"


def test_option_exit_waits_for_a_usable_quote_or_is_unresolved() -> None:
    u = und(100.0, 100.0, {30: 101.2, 90: 98.8})
    delayed = decide(u, opt("X102C", [(30, 1.00, 1.04), (93, 0.30, 0.34)]))
    assert (delayed.exit_time, delayed.exit_delay_minutes) == (at(93), 3)
    assert delayed.exit_reason == "OPPOSITE" and delayed.exit_fill == 0.30
    never = decide(u, opt("X102C", [(30, 1.00, 1.04), (EXIT + 1, 0.30, 0.34)]))
    assert (never.status, never.exit_reason, never.ret) == ("CANDIDATE", "UNRESOLVED_DATA", None)
    no_bid = decide(u, opt("X102C", [(30, 1.00, 1.04), (90, 0.0, 0.05)]))
    assert no_bid.exit_no_bid is True and no_bid.exit_fill == 0.0


# one position at a time, across times of day (ruling 5) -------------------------------------
def row(ticker: str, entry: float, sale: float | None, cost: float, d: date = D) -> dict[str, Any]:
    return {
        "ticker": ticker, "session_date": d, "status": "CANDIDATE", "entry_time": at(entry),
        "cost_share": cost, "exit_time": None if sale is None else at(sale),
        "exit_reason": "TIME" if sale is not None else "UNRESOLVED_DATA",
        "exit_delay_minutes": 0, "exit_no_bid": False, "exit_fill": 1.0, "net_usd": 5.0,
        "ret": 0.05, "exit_mid": 1.0, "net_usd_mid": 6.0, "ret_mid": 0.06,
    }  # fmt: skip


ORDER = ["QQQ", "SPY", "IWM", "NVDA", "TSLA"]


def statuses(rows: list[dict[str, Any]]) -> dict[str, str]:
    return {r["ticker"]: r["status"] for r in apply_one_position_timed(rows, ORDER)}


def test_a_later_signal_is_blocked_while_the_position_is_open() -> None:
    rows = [row("SPY", 60, EXIT, 0.01), row("QQQ", 30, EXIT, 0.05)]
    out = apply_one_position_timed(rows, ORDER)
    assert {r["ticker"]: r["status"] for r in out} == {"QQQ": "TRADE", "SPY": "POSITION_OPEN"}
    blocked = next(r for r in out if r["ticker"] == "SPY")
    assert blocked["ret"] is None and blocked["exit_time"] is None and blocked["net_usd"] is None


def test_a_signal_after_the_sale_trades_but_not_at_the_check_of_the_sale() -> None:
    assert statuses([row("QQQ", 30, 90, 0.05), row("SPY", 120, EXIT, 0.02)]) == {
        "QQQ": "TRADE", "SPY": "TRADE",
    }  # fmt: skip
    assert statuses([row("QQQ", 30, 90, 0.05), row("SPY", 90, EXIT, 0.02)]) == {
        "QQQ": "TRADE", "SPY": "POSITION_OPEN",
    }  # fmt: skip
    # a sale delayed to 11:03 still blocks the 11:00 check; an unresolved exit blocks the day
    assert statuses([row("QQQ", 30, 93, 0.05), row("SPY", 120, EXIT, 0.02)])["SPY"] == "TRADE"
    assert statuses([row("QQQ", 30, None, 0.05), row("SPY", 300, EXIT, 0.02)]) == {
        "QQQ": "TRADE", "SPY": "POSITION_OPEN",
    }  # fmt: skip


def test_same_check_ties_go_to_the_lowest_cost_share_then_the_ticker_order() -> None:
    assert statuses([row("QQQ", 30, EXIT, 0.05), row("TSLA", 30, EXIT, 0.02)]) == {
        "QQQ": "POSITION_OPEN", "TSLA": "TRADE",
    }  # fmt: skip
    assert statuses([row("SPY", 30, EXIT, 0.02), row("QQQ", 30, EXIT, 0.02)]) == {
        "QQQ": "TRADE", "SPY": "POSITION_OPEN",
    }  # fmt: skip


def test_sessions_are_independent_and_other_statuses_are_left_alone() -> None:
    other = {**row("IWM", 30, EXIT, 0.001), "status": "PREMIUM_OVER_CAP"}
    rows = [
        row("QQQ", 30, EXIT, 0.05), other, row("SPY", 60, EXIT, 0.02, d=date(2024, 3, 6)),
    ]  # fmt: skip
    assert statuses(rows) == {"QQQ": "TRADE", "IWM": "PREMIUM_OVER_CAP", "SPY": "TRADE"}


# config -------------------------------------------------------------------------------------
def test_a3_parameters_and_owner_rulings_are_in_the_config() -> None:
    assert NA.lookback_sessions == 14
    assert (NA.first_check, NA.last_entry_check, NA.last_exit_check) == (
        time(10, 0), time(15, 0), time(15, 30),
    )  # fmt: skip
    assert NA.check_interval_minutes == 30
    assert NA.last_entry_check == CFG.schedule.last_new_entry
    assert NA.exit_time == CFG.trade.forced_exit_time == time(15, 50)
    assert (NA.open_offset_minutes, NA.prev_close_offset_minutes) == (1, 1)
    assert CFG.study_options_day.split_sessions == {"NVDA": [date(2024, 6, 10)]}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("last_entry_check", "15:30"),  # after schedule.last_new_entry
        ("last_exit_check", "15:45"),  # off the half-hour grid
        ("exit_time", "15:55"),  # after trade.forced_exit_time
        ("lookback_sessions", 0),
        ("first_check", "15:10"),  # after the last entry check
    ],
)
def test_contradictory_noise_area_values_are_refused(key: str, value: object) -> None:
    raw = yaml.safe_load(Path("configs/phase1.yaml").read_text("utf-8"))
    bad = copy.deepcopy(raw)
    bad["study_options_day"]["noise_area"][key] = value
    with pytest.raises(ValidationError):
        Phase1Config.model_validate(bad)
