"""M30 (ADR-0021 D6, setup S2): the first-half-hour rule and its screen. Synthetic cases with
exactly known answers; no market data is read.

Owner rulings of 2026-11-15 ("Approve all") tested here:
1. the previous close is the quote in force one minute before the previous session's close;
2. the 10:00 price is the quote in force at 10:00:00;
3. up only if the 10:00 bid is above the previous-close ask, down only if the 10:00 ask is
   below the previous-close bid, otherwise NO_TRADE (FLAT_MOVE);
4. no previous close -> NO_PREV_CLOSE;  5. a split session -> CORPORATE_ACTION;
6. Step A = signed mid(15:50) / mid(15:30) - 1 on every ticker-session with a direction.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from qqq1dte.backtesting.half_hour_screen import S2Candidate, session_decision
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import BrokerFees, load_config
from qqq1dte.execution_sim.selection import Contract, Quote
from qqq1dte.strategies.half_hour import half_hour_signal

CFG = load_config()
CAL = TradingCalendar(CFG)
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
SIGNAL, ENTRY, EXIT = 30, 360, 380  # minutes after the open: 10:00, 15:30, 15:50


def at(minutes: float) -> datetime:
    return OPEN + timedelta(minutes=minutes)


def uq(t: datetime, mid: float, half: float = 0.005) -> Quote:
    return Quote(mid - half, mid + half, 100, 100, t)


def und(prev: float | None, mids: dict[float, float]) -> list[Quote]:
    """Previous-close quote stamped 15:59 of PREV, then the session's quotes by minute."""
    out = [] if prev is None else [uq(PREV_CLOSE - timedelta(minutes=1), prev)]
    return out + [uq(at(i), m) for i, m in sorted(mids.items())]


def chain() -> list[Contract]:
    return [
        Contract(f"X{k}{r}", float(k), r, EXP, LISTED) for k in (99, 100, 101, 102) for r in "CP"
    ]


def opt(symbol: str, quotes: list[tuple[float, float, float]]) -> dict[str, list[Quote]]:
    return {symbol: [Quote(b, a, 10, 10, at(m)) for m, b, a in quotes]}


def decide(underlying: list[Quote], quotes: dict[str, list[Quote]], **kw: object) -> S2Candidate:
    args = {"prev_session": PREV, **kw}
    return session_decision(
        "QQQ", D, underlying, chain(), lambda sym: quotes.get(sym, []), CFG, CAL, FLAT,
        **args,  # type: ignore[arg-type]
    )  # fmt: skip


UP = {SIGNAL: 100.5, ENTRY: 100.6, EXIT: 100.9}
GOOD_CALL = opt("X101C", [(ENTRY, 1.00, 1.04), (EXIT, 1.50, 1.54)])


# the rule (strategies.half_hour) ------------------------------------------------------------
def test_direction_needs_the_two_quotes_not_to_overlap() -> None:
    assert half_hour_signal(99.99, 100.01, 100.02, 100.04) == "C"
    assert half_hour_signal(99.99, 100.01, 99.95, 99.98) == "P"
    assert half_hour_signal(99.99, 100.01, 100.00, 100.03) is None  # overlap
    assert half_hour_signal(99.99, 100.01, 100.01, 100.03) is None  # bid touches the old ask
    assert half_hour_signal(99.99, 100.01, 99.97, 99.99) is None  # ask touches the old bid


def test_a_wide_quote_gives_no_direction() -> None:
    assert half_hour_signal(99.99, 100.01, 99.0, 103.0) is None
    assert half_hour_signal(98.0, 104.0, 100.4, 100.42) is None


def test_crossed_or_missing_inputs_are_refused() -> None:
    with pytest.raises(ValueError):
        half_hour_signal(100.01, 99.99, 100.4, 100.5)
    with pytest.raises(ValueError):
        half_hour_signal(99.99, 100.01, 0.0, 100.5)


# one ticker-session -------------------------------------------------------------------------
def test_up_move_buys_the_call_at_1530_and_sells_at_1550() -> None:
    c = decide(und(100.0, UP), GOOD_CALL)
    assert (c.status, c.side, c.symbol) == ("CANDIDATE", "C", "X101C")
    assert (c.prev_bid, c.prev_ask) == pytest.approx((99.995, 100.005))
    assert (c.sig_bid, c.sig_ask) == pytest.approx((100.495, 100.505))
    assert c.und_entry == pytest.approx(100.6)
    assert c.und_return == pytest.approx(100.9 / 100.6 - 1)  # Step A: 15:30 -> 15:50
    assert (c.und_exit_reason, c.exit_reason, c.exit_time) == ("TIME", "TIME", at(EXIT))
    assert (c.entry_fill, c.exit_fill) == (1.04, 1.50)
    assert c.ret == pytest.approx((46.0 - 2.0) / 104.0)
    assert (c.entry_mid, c.exit_mid) == (1.02, 1.52)
    assert c.ret_mid == pytest.approx((50.0 - 2.0) / 102.0)
    assert c.cost_share == pytest.approx((4.0 + 2.0) / 105.0)
    assert c.exit_delay_minutes == 0


def test_down_move_buys_the_put_and_signs_the_underlying_return() -> None:
    u = und(100.0, {SIGNAL: 99.5, ENTRY: 100.5, EXIT: 100.2})
    c = decide(u, opt("X100P", [(ENTRY, 0.80, 0.84), (EXIT, 0.90, 0.94)]))
    assert (c.status, c.side, c.symbol) == ("CANDIDATE", "P", "X100P")
    assert c.und_return == pytest.approx(-(100.2 / 100.5 - 1))


def test_previous_close_is_read_one_minute_before_the_close_not_at_it() -> None:
    u = und(100.0, UP)
    u.insert(1, uq(PREV_CLOSE, 101.0))  # the 16:00:00 record: would turn the move down
    c = decide(u, GOOD_CALL)
    assert c.side == "C" and c.prev_ask == pytest.approx(100.005)


def test_the_signal_reads_nothing_after_1000() -> None:
    u = und(100.0, {**UP, SIGNAL + 0.5: 99.0, SIGNAL + 1: 99.0})  # falls right after 10:00
    assert decide(u, GOOD_CALL).side == "C"


def test_no_previous_close() -> None:
    assert decide(und(100.0, UP), GOOD_CALL, prev_session=None).status == "NO_PREV_CLOSE"
    assert decide(und(None, UP), GOOD_CALL).status == "NO_PREV_CLOSE"
    stale = [uq(PREV_CLOSE - timedelta(minutes=5), 100.0), *und(None, UP)]
    assert decide(stale, GOOD_CALL).status == "NO_PREV_CLOSE"  # 4 minutes old at 15:59
    one_sided = [Quote(0.0, 100.0, 100, 100, PREV_CLOSE - timedelta(minutes=1)), *und(None, UP)]
    assert decide(one_sided, GOOD_CALL).status == "NO_PREV_CLOSE"


def test_previous_close_after_an_early_close_is_read_at_1259() -> None:
    d, prev = date(2024, 7, 5), date(2024, 7, 3)  # 2024-07-03 closed at 13:00 ET = 17:00 UTC
    o = datetime(2024, 7, 5, 13, 30, tzinfo=UTC)
    u = [
        uq(datetime(2024, 7, 3, 16, 59, tzinfo=UTC), 100.0),
        *[uq(o + timedelta(minutes=i), m) for i, m in sorted(UP.items())],
    ]
    ch = [Contract("X101C", 101.0, "C", date(2024, 7, 8), LISTED)]
    quotes = {
        "X101C": [
            Quote(b, a, 10, 10, o + timedelta(minutes=m))
            for m, b, a in ((ENTRY, 1.0, 1.04), (EXIT, 1.5, 1.54))
        ]
    }
    c = session_decision(
        "QQQ", d, u, ch, lambda s: quotes.get(s, []), CFG, CAL, FLAT, prev_session=prev
    )
    assert (c.status, c.side, c.exit_fill) == ("CANDIDATE", "C", 1.5)


def test_no_trade_reasons_before_any_price_is_read() -> None:
    u = und(100.0, UP)
    assert decide(u, GOOD_CALL, excluded=True).status == "EARNINGS_WINDOW"
    assert decide(u, GOOD_CALL, split=True).status == "CORPORATE_ACTION"
    early = session_decision(
        "QQQ", date(2024, 7, 3), u, chain(), lambda s: [], CFG, CAL, FLAT,
        prev_session=date(2024, 7, 2),
    )  # fmt: skip
    assert early.status == "EARLY_CLOSE"  # 15:30 is after that session's forced exit


def test_flat_move_and_missing_underlying_quotes() -> None:
    flat = decide(und(100.0, {**UP, SIGNAL: 100.005}), GOOD_CALL)
    assert flat.status == "FLAT_MOVE" and flat.und_return is None
    wide = und(100.0, {ENTRY: 100.6, EXIT: 100.9})
    wide.insert(1, Quote(99.0, 103.0, 100, 100, at(SIGNAL)))
    assert decide(wide, GOOD_CALL).status == "FLAT_MOVE"
    no_signal = decide(und(100.0, {ENTRY: 100.6, EXIT: 100.9}), GOOD_CALL)
    assert (no_signal.status, no_signal.detail) == ("NO_UNDERLYING_QUOTE", "signal")
    no_entry = decide(und(100.0, {SIGNAL: 100.5, EXIT: 100.9}), GOOD_CALL)
    assert (no_entry.status, no_entry.detail) == ("NO_UNDERLYING_QUOTE", "entry")
    assert no_entry.side == "C" and no_entry.und_return is None


def test_step_a_is_measured_whatever_the_option_does() -> None:
    u = und(100.0, UP)
    r = 100.9 / 100.6 - 1
    none = decide(u, {})
    assert none.status == "NO_OPTION_QUOTE" and none.und_return == pytest.approx(r)
    wide = decide(u, opt("X101C", [(ENTRY, 1.00, 1.20)]))
    assert wide.status == "SELECTED_CONTRACT_ILLIQUID" and "SPREAD_TOO_WIDE" in wide.detail
    dear = decide(u, opt("X101C", [(ENTRY, 4.95, 5.00), (EXIT, 5.0, 5.1)]))
    assert dear.status == "PREMIUM_OVER_CAP"  # $500 + $1 of fees is over the $500 ceiling
    assert wide.und_return == dear.und_return == pytest.approx(r)


def test_no_underlying_quote_at_1550_leaves_step_a_out_but_prices_the_option() -> None:
    c = decide(und(100.0, {SIGNAL: 100.5, ENTRY: 100.6}), GOOD_CALL)
    assert (c.status, c.und_exit_reason, c.und_return) == ("CANDIDATE", "NO_EXIT_QUOTE", None)
    assert c.ret == pytest.approx((46.0 - 2.0) / 104.0)


def test_entry_quote_must_be_known_by_1530_plus_latency() -> None:
    late = opt("X101C", [(ENTRY + 0.5, 1.00, 1.04), (EXIT, 1.50, 1.54)])
    assert decide(und(100.0, UP), late).status == "NO_OPTION_QUOTE"


def test_a_contract_listed_after_the_entry_cannot_be_chosen() -> None:
    quotes = {**GOOD_CALL, **opt("X100.8C", [(ENTRY, 1.2, 1.24), (EXIT, 1.7, 1.74)])}
    newer = [*chain(), Contract("X100.8C", 100.8, "C", EXP, at(ENTRY + 1))]
    c = session_decision(
        "QQQ", D, und(100.0, UP), newer, lambda s: quotes.get(s, []), CFG, CAL, FLAT,
        prev_session=PREV,
    )  # fmt: skip
    assert c.symbol == "X101C"


def test_no_usable_option_quote_at_1550_is_unresolved_with_no_later_minute() -> None:
    quotes = opt("X101C", [(ENTRY, 1.00, 1.04), (EXIT + 1, 1.50, 1.54)])  # arrives at 15:51
    c = decide(und(100.0, UP), quotes)
    assert (c.status, c.exit_reason, c.ret) == ("CANDIDATE", "UNRESOLVED_DATA", None)


def test_exit_with_no_bid_sells_at_zero() -> None:
    c = decide(und(100.0, UP), opt("X101C", [(ENTRY, 1.00, 1.04), (EXIT, 0.0, 0.05)]))
    assert c.exit_no_bid is True and c.exit_fill == 0.0
    assert c.ret == pytest.approx((-104.0 - 2.0) / 104.0)


# config -------------------------------------------------------------------------------------
def test_owner_rulings_are_in_the_config() -> None:
    s = CFG.study_options_day
    assert s.half_hour.prev_close_offset_minutes == 1
    assert s.split_sessions == {"NVDA": [date(2024, 6, 10)]}
