"""M19T Step 1 (ADR-0013 D1, R1-R2, condor rule): defined-risk credit-spread labels.

Synthetic chains with exactly known fills. Costs per leg per side = commission 0.65 + fees 0.05,
so a spread round trip costs 4 x 0.70 = $2.80 and a condor $5.60 (1 contract).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from qqq1dte.core.config import load_config
from qqq1dte.core.dividends import ExDividend
from qqq1dte.execution_sim.selection import Contract, Quote, liquidity_failures
from qqq1dte.labels.spread import (
    AT_BAND_EDGE,
    CONDOR_SIDE_MISSING,
    EXIT_NO_ASK,
    EXIT_STALE,
    LEG_ILLIQUID,
    NO_QUALIFYING,
    OK,
    PATH_GAP,
    UNRESOLVED_DATA,
    NoTrade,
    Opened,
    close_spread,
    ex_div_span,
    open_spread,
    quote_at,
)

CFG = load_config()
TE = datetime(2024, 6, 12, 14, 0, 5, tzinfo=UTC)
TX = datetime(2024, 6, 12, 19, 50, 5, tzinfo=UTC)
EXP = date(2024, 6, 12)
KNOWN = TE - timedelta(hours=6)

PUTS = {  # strike: (bid, ask)
    100.0: (1.48, 1.52),
    99.0: (0.88, 0.92),
    98.0: (0.48, 0.52),
    97.0: (0.23, 0.27),
    96.0: (0.10, 0.12),
    95.0: (0.03, 0.05),
}
CALLS = {
    100.0: (1.48, 1.52),
    101.0: (0.88, 0.92),
    102.0: (0.48, 0.52),
    103.0: (0.23, 0.27),
    104.0: (0.10, 0.12),
}


def sym(right: str, k: float) -> str:
    return f"QQQ   240612{right}{round(k * 1000):08d}"


def build(
    puts: dict[float, tuple[float | None, float | None]],
    calls: dict[float, tuple[float | None, float | None]] | None = None,
    at: datetime = TE - timedelta(seconds=5),
) -> tuple[list[Contract], dict[str, Quote]]:
    chain, quotes = [], {}
    for right, book in (("P", puts), ("C", calls or {})):
        for k, (b, a) in book.items():
            s = sym(right, k)
            chain.append(Contract(s, k, right, EXP, KNOWN))
            quotes[s] = Quote(b, a, 10, 10, at)
    return chain, quotes


def exit_quotes(book: dict[str, tuple[float | None, float | None]]) -> dict[str, Quote]:
    return {s: Quote(b, a, 10, 10, TX - timedelta(seconds=30)) for s, (b, a) in book.items()}


def opened_put(x: float = 0.20) -> Opened:
    chain, q = build(PUTS)
    o = open_spread(chain, q, TE, "put", x, 1.0, CFG)
    assert isinstance(o, Opened)
    return o


# selection ---------------------------------------------------------------------------------------
def test_put_spread_pick_and_entry_credits() -> None:
    o = opened_put()
    assert [(leg.role, leg.contract.strike) for leg in o.legs] == [("short", 98.0), ("long", 97.0)]
    # credits (short sell - long buy): conservative .48-.27, moderate .49-.26, mid .50-.25
    assert o.credit == pytest.approx({"conservative": 0.21, "moderate": 0.23, "mid": 0.25})
    o33 = opened_put(0.33)
    assert [leg.contract.strike for leg in o33.legs] == [99.0, 98.0]


def test_r1_gate_after_selection_no_fallback() -> None:
    puts = dict(PUTS)
    puts[98.0] = (0.48, 0.60)  # short leg spread .12 > max(.05, 5% of mid): fails, credit same
    chain, q = build(puts)
    res = open_spread(chain, q, TE, "put", 0.20, 1.0, CFG)
    assert res == NoTrade(LEG_ILLIQUID, ("short:SPREAD_TOO_WIDE",))


def test_r1_long_leg_exempt_from_min_bid() -> None:
    puts = {100.0: (1.48, 1.52), 99.0: (0.40, 0.44), 98.0: (0.10, 0.14), 97.0: (0.02, 0.04)}
    chain, q = build(puts)
    long_q = q[sym("P", 98.0)]
    assert "BID_BELOW_MIN" in liquidity_failures(long_q, TE, CFG)  # Phase 1 gate unchanged
    o = open_spread(chain, q, TE, "put", 0.20, 1.0, CFG)
    assert isinstance(o, Opened)
    assert [leg.contract.strike for leg in o.legs] == [99.0, 98.0]


def test_r2_missing_long_strike_makes_pair_ineligible() -> None:
    chain, q = build({k: v for k, v in PUTS.items() if k != 97.0})
    o = open_spread(chain, q, TE, "put", 0.20, 1.0, CFG)
    assert isinstance(o, Opened)
    assert [leg.contract.strike for leg in o.legs] == [99.0, 98.0]


def test_no_qualifying_pair() -> None:
    chain, q = build(PUTS)
    assert open_spread(chain, q, TE, "put", 0.60, 1.0, CFG) == NoTrade(NO_QUALIFYING)


def test_contracts_not_yet_known_or_stale_quotes_are_not_candidates() -> None:
    chain, q = build(PUTS)
    chain = [
        Contract(c.symbol, c.strike, c.right, c.expiration, TE + timedelta(seconds=1))
        if c.strike == 97.0
        else c
        for c in chain
    ]
    o = open_spread(chain, q, TE, "put", 0.20, 1.0, CFG)
    assert isinstance(o, Opened) and o.legs[0].contract.strike == 99.0
    chain, q = build(PUTS)
    q[sym("P", 97.0)] = Quote(0.23, 0.27, 10, 10, TE - timedelta(seconds=61))  # too old
    o = open_spread(chain, q, TE, "put", 0.20, 1.0, CFG)
    assert isinstance(o, Opened) and o.legs[0].contract.strike == 99.0


def test_condor_needs_both_sides() -> None:
    chain, q = build(PUTS, CALLS)
    o = open_spread(chain, q, TE, "condor", 0.20, 1.0, CFG)
    assert isinstance(o, Opened)
    assert [(leg.role, leg.contract.right, leg.contract.strike) for leg in o.legs] == [
        ("short", "P", 98.0),
        ("long", "P", 97.0),
        ("short", "C", 102.0),
        ("long", "C", 103.0),
    ]
    assert o.credit["conservative"] == pytest.approx(0.21 + 0.21)
    # call credits: 101/102 .05-.03 = .02, 102/103 .01-.01 = 0: no call pair reaches .20
    chain, q = build(PUTS, {101.0: (0.05, 0.07), 102.0: (0.01, 0.03), 103.0: (0.00, 0.01)})
    res = open_spread(chain, q, TE, "condor", 0.20, 1.0, CFG)
    assert res == NoTrade(CONDOR_SIDE_MISSING, ("C",))


# exit --------------------------------------------------------------------------------------------
EXIT_BOOK = {sym("P", 98.0): (0.08, 0.12), sym("P", 97.0): (0.01, 0.05)}


def test_exit_fills_costs_and_max_risk() -> None:
    o = opened_put()
    out = close_spread(o, exit_quotes(EXIT_BOOK), TX, {}, CFG)
    assert out.status == OK
    assert out.costs == pytest.approx(2.80)
    # debits (short buy - long sell): conservative .12-.01, moderate .11-.02, mid .10-.03
    assert out.net == pytest.approx({"conservative": 7.20, "moderate": 11.20, "mid": 15.20})
    assert out.max_risk == pytest.approx((1.0 - 0.21) * 100 + 2.80)


def test_missing_bid_counts_as_zero() -> None:
    o = opened_put()
    book = dict(EXIT_BOOK)
    book[sym("P", 97.0)] = (None, 0.05)
    out = close_spread(o, exit_quotes(book), TX, {}, CFG)
    assert out.status == OK
    assert out.net["conservative"] == pytest.approx((0.21 - 0.12) * 100 - 2.80)
    # mid of (0, .05) = .025 -> sold at .02 (tick floor); short bought at mid .10
    assert out.net["mid"] == pytest.approx((0.25 - 0.08) * 100 - 2.80)


def test_missing_ask_or_stale_or_gap_is_unresolved() -> None:
    o = opened_put()
    book = dict(EXIT_BOOK)
    book[sym("P", 98.0)] = (0.08, None)
    out = close_spread(o, exit_quotes(book), TX, {}, CFG)
    assert (out.status, out.reason) == (UNRESOLVED_DATA, EXIT_NO_ASK)
    q = exit_quotes(EXIT_BOOK)
    q[sym("P", 97.0)] = Quote(0.01, 0.05, 10, 10, TX - timedelta(minutes=6))
    out = close_spread(o, q, TX, {}, CFG)
    assert (out.status, out.reason) == (UNRESOLVED_DATA, EXIT_STALE)
    q = exit_quotes(EXIT_BOOK)
    q[sym("P", 98.0)] = Quote(None, None, None, None, TX - timedelta(seconds=30), rejected=True)
    out = close_spread(o, q, TX, {}, CFG)
    assert (out.status, out.reason) == (UNRESOLVED_DATA, EXIT_NO_ASK)
    out = close_spread(o, exit_quotes(EXIT_BOOK), TX, {sym("P", 98.0): 6.0}, CFG)
    assert (out.status, out.reason) == (UNRESOLVED_DATA, PATH_GAP)
    out = close_spread(o, exit_quotes(EXIT_BOOK), TX, {sym("P", 98.0): 5.0}, CFG)
    assert out.status == OK  # exactly max_path_gap_minutes is allowed


def test_condor_costs_and_max_risk() -> None:
    chain, q = build(PUTS, CALLS)
    o = open_spread(chain, q, TE, "condor", 0.20, 1.0, CFG)
    assert isinstance(o, Opened)
    book = {**EXIT_BOOK, sym("C", 102.0): (0.00, 0.02), sym("C", 103.0): (0.00, 0.01)}
    out = close_spread(o, exit_quotes(book), TX, {}, CFG)
    assert out.costs == pytest.approx(5.60)
    # conservative: credit .42; debit (.12-.01) + (.02-0) = .13
    assert out.net["conservative"] == pytest.approx((0.42 - 0.13) * 100 - 5.60)
    assert out.max_risk == pytest.approx((1.0 - 0.42) * 100 + 5.60)


# point in time -----------------------------------------------------------------------------------
def test_quote_at_ignores_later_records() -> None:
    recs = pl.DataFrame(
        {
            "symbol": ["A", "A", "A"],
            "available_at": [TX - timedelta(minutes=2), TX, TX + timedelta(seconds=1)],
            "bid": [0.10, 0.20, 9.99],
            "ask": [0.12, 0.22, 9.99],
            "bid_sz": [1, 1, 1],
            "ask_sz": [1, 1, 1],
            "rejected": [False, False, False],
        },
        schema_overrides={"available_at": pl.Datetime("ns", "UTC")},
    )
    q = quote_at(recs, TX)
    assert q["A"].bid == 0.20 and q["A"].available_at == TX
    recs2 = recs.with_columns(rejected=pl.Series([False, True, False]))
    q2 = quote_at(recs2, TX)
    assert q2["A"].rejected  # a rejected latest record never lets an older quote stand in


SESSIONS = [date(2024, 3, 14), date(2024, 3, 15), date(2024, 3, 18), date(2024, 3, 19)]
EXDIV = [ExDividend(date(2024, 3, 18), "regular", 0.57, date(2023, 12, 19), "rule")]


def test_ex_div_span() -> None:
    # 1DTE entered Fri 03-15, flat Mon 03-18 (the ex-date): holds over the close before it
    assert ex_div_span(date(2024, 3, 15), date(2024, 3, 18), True, EXDIV, SESSIONS)
    assert not ex_div_span(date(2024, 3, 15), date(2024, 3, 18), False, EXDIV, SESSIONS)
    assert not ex_div_span(date(2024, 3, 15), date(2024, 3, 15), True, EXDIV, SESSIONS)  # 0DTE
    assert not ex_div_span(date(2024, 3, 18), date(2024, 3, 19), True, EXDIV, SESSIONS)
    late = [ExDividend(date(2024, 3, 18), "special", 0.2, date(2024, 3, 16), "declared")]
    assert not ex_div_span(date(2024, 3, 15), date(2024, 3, 18), True, late, SESSIONS)


def test_band_edge_pick_is_not_traded() -> None:
    # 98/97 qualifies and 97 is the lowest stored strike: a further pair cannot be ruled out,
    # and the stored band was chosen with the session's full-day range (storage scope only)
    chain, q = build({k: v for k, v in PUTS.items() if k >= 97.0})
    assert open_spread(chain, q, TE, "put", 0.20, 1.0, CFG) == NoTrade(AT_BAND_EDGE, ("P",))


def test_quote_at_tie_prefers_rejected_copy_deterministically() -> None:
    # an exact duplicate: the kept copy and the rejected DUP_EXACT copy share a timestamp
    recs = pl.DataFrame(
        {
            "symbol": ["A", "A"],
            "available_at": [TX, TX],
            "bid": [0.20, None],
            "ask": [0.22, None],
            "bid_sz": [1, None],
            "ask_sz": [1, None],
            "rejected": [False, True],
        },
        schema_overrides={"available_at": pl.Datetime("ns", "UTC")},
    )
    for frame in (recs, recs.reverse()):
        for _ in range(20):
            assert quote_at(frame, TX)["A"].rejected  # conservative and order-independent
