"""M23 Step 1 (ADR-0014 D2, R3, R9-R11): SPX longer-dated credit-spread labels.

Synthetic chains with exactly known fills and costs. Per SPX contract per side (R3, IBKR + Cboe):
commission $0.25 / $0.50 / $0.65 (premium < 0.05 / < 0.10 / otherwise), plus the Cboe fee $0.36
(premium < $1) or $0.45, plus a $0.05 regulatory allowance.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from qqq1dte.core.config import load_config
from qqq1dte.execution_sim.selection import Contract, Quote
from qqq1dte.labels.longspread import (
    AT_BAND_EDGE,
    CONDOR_SIDE_MISSING,
    EXIT_NO_ASK,
    EXIT_STALE,
    LEG_ILLIQUID,
    NO_QUALIFYING,
    OK,
    UNRESOLVED_DATA,
    LongOpened,
    NoTrade,
    close_long_spread,
    open_long_spread,
    spread_gate_r10,
    spx_leg_cost,
)

CFG = load_config()
TE = datetime(2024, 6, 3, 14, 0, 5, tzinfo=UTC)
TX = datetime(2024, 6, 27, 19, 45, 5, tzinfo=UTC)
EXP = date(2024, 6, 28)
KNOWN = TE - timedelta(hours=8)
W = 10.0

PUTS = {  # strike: (bid, ask)
    4000.0: (30.0, 30.6),
    3990.0: (24.0, 24.5),
    3980.0: (19.0, 19.4),
    3970.0: (15.0, 15.3),
    3960.0: (12.0, 12.3),
    3950.0: (9.5, 9.8),
    3940.0: (7.6, 7.8),
}
CALLS = {
    4000.0: (30.0, 30.6),
    4010.0: (24.0, 24.5),
    4020.0: (19.0, 19.4),
    4030.0: (15.0, 15.3),
    4040.0: (12.0, 12.3),
    4050.0: (9.5, 9.8),
    4060.0: (7.6, 7.8),
}


def sym(root: str, right: str, k: float) -> str:
    return f"{root:<6}240628{right}{round(k * 1000):08d}"


def build(
    puts: dict[float, tuple[float | None, float | None]],
    calls: dict[float, tuple[float | None, float | None]] | None = None,
    root: str = "SPXW",
    known: datetime = KNOWN,
) -> tuple[list[Contract], dict[str, Quote]]:
    chain, quotes = [], {}
    for right, book in (("P", puts), ("C", calls or {})):
        for k, (b, a) in book.items():
            s = sym(root, right, k)
            chain.append(Contract(s, k, right, EXP, known))
            quotes[s] = Quote(b, a, 10, 10, TE - timedelta(seconds=5))
    return chain, quotes


def opened_put() -> LongOpened:
    chain, q = build(PUTS)
    o = open_long_spread(chain, q, TE, "put", 0.20, W, CFG)
    assert isinstance(o, LongOpened)
    return o


# costs and gate -----------------------------------------------------------------------------------
def test_leg_cost_tiers() -> None:
    s = CFG.study_2a
    assert spx_leg_cost(0.04, s) == pytest.approx(0.25 + 0.36 + 0.05)
    assert spx_leg_cost(0.07, s) == pytest.approx(0.50 + 0.36 + 0.05)
    assert spx_leg_cost(0.50, s) == pytest.approx(0.65 + 0.36 + 0.05)
    assert spx_leg_cost(1.00, s) == pytest.approx(0.65 + 0.45 + 0.05)


def test_r10_spread_gate_boundary() -> None:
    q = Quote(0.925, 1.075, 1, 1, TE)  # spread 0.15 = 15% of mid 1.00: passes
    assert spread_gate_r10(q, 0.15) == []
    assert spread_gate_r10(Quote(0.92, 1.08, 1, 1, TE), 0.15) == ["SPREAD_TOO_WIDE"]


# entry --------------------------------------------------------------------------------------------
def test_put_pick_credits_and_spxw() -> None:
    o = opened_put()
    # credits: 4000/3990 5.5, 3990/3980 4.6, 3980/3970 3.7, 3970/3960 2.7, 3960/3950 2.2,
    # 3950/3940 1.7 -> furthest pair reaching 2.0 is 3960/3950
    assert [(lg.role, lg.contract.strike) for lg in o.legs] == [("short", 3960.0), ("long", 3950.0)]
    # moderate: sell 12.15 - 0.075 -> 12.07; buy 9.65 + 0.075 -> 9.73
    assert o.credit == pytest.approx({"conservative": 2.20, "moderate": 2.34, "mid": 2.50})
    assert o.legs[0].contract.symbol.startswith("SPXW")


def test_spxw_preferred_on_shared_strike() -> None:
    chain, q = build(PUTS, root="SPXW")
    c2, q2 = build({k: (b - 1.0, a - 1.0) for k, (b, a) in PUTS.items()}, root="SPX")
    o = open_long_spread(chain + c2, {**q, **q2}, TE, "put", 0.20, W, CFG)
    assert isinstance(o, LongOpened)
    assert all(lg.contract.symbol.startswith("SPXW") for lg in o.legs)


def test_band_edge_no_qualifying_and_condor_rule() -> None:
    chain, q = build({k: v for k, v in PUTS.items() if k >= 3950.0})
    assert open_long_spread(chain, q, TE, "put", 0.20, W, CFG) == NoTrade(AT_BAND_EDGE, ("P",))
    chain, q = build(PUTS)
    assert open_long_spread(chain, q, TE, "put", 0.80, W, CFG) == NoTrade(NO_QUALIFYING)
    chain, q = build(PUTS, {4000.0: (0.5, 0.6), 4010.0: (0.4, 0.5)})
    res = open_long_spread(chain, q, TE, "condor", 0.20, W, CFG)
    assert res == NoTrade(CONDOR_SIDE_MISSING, ("C",))
    chain, q = build(PUTS, CALLS)
    o = open_long_spread(chain, q, TE, "condor", 0.20, W, CFG)
    assert isinstance(o, LongOpened)
    assert [(lg.contract.right, lg.contract.strike) for lg in o.legs] == [
        ("P", 3960.0), ("P", 3950.0), ("C", 4040.0), ("C", 4050.0)
    ]  # fmt: skip


def test_r10_gate_after_selection_no_fallback() -> None:
    puts = dict(PUTS)
    puts[3960.0] = (12.0, 14.0)  # spread 2.0 = 15.4% of mid 13.0: fails R10, pick unchanged
    chain, q = build(puts)
    res = open_long_spread(chain, q, TE, "put", 0.20, W, CFG)
    assert res == NoTrade(LEG_ILLIQUID, ("short:SPREAD_TOO_WIDE",))


def test_contract_must_be_known_at_t_e() -> None:
    chain, q = build(PUTS)
    late = [Contract(c.symbol, c.strike, c.right, c.expiration, TE + timedelta(seconds=1))
            if c.strike == 3950.0 else c for c in chain]  # fmt: skip
    o = open_long_spread(late, q, TE, "put", 0.20, W, CFG)
    # 3960/3950 is no longer a pair; 3970/3960 (2.7) is the furthest pair whose legs are known
    assert isinstance(o, LongOpened) and o.legs[0].contract.strike == 3970.0


# exit ---------------------------------------------------------------------------------------------
EXIT = {sym("SPXW", "P", 3960.0): (6.0, 6.2), sym("SPXW", "P", 3950.0): (4.4, 4.6)}


def exit_quotes(book: dict[str, tuple[float | None, float | None]]) -> dict[str, Quote | None]:
    return {s: Quote(b, a, 1, 1, TX - timedelta(seconds=30)) for s, (b, a) in book.items()}


def test_exit_net_costs_and_max_risk() -> None:
    out = close_long_spread(opened_put(), exit_quotes(EXIT), TX, CFG)
    assert out.status == OK
    # every leg price >= $1 -> $1.15 per contract per side; 4 sides -> $4.60
    assert out.costs["conservative"] == pytest.approx(4.60)
    assert out.net["conservative"] == pytest.approx((2.20 - (6.2 - 4.4)) * 100 - 4.60)
    assert out.net["mid"] == pytest.approx((2.50 - (6.1 - 4.5)) * 100 - 4.60)
    assert out.max_risk == pytest.approx((W - 2.20) * 100 + 4.60)


def test_exit_missing_bid_counts_as_zero_and_is_charged() -> None:
    book = dict(EXIT)
    book[sym("SPXW", "P", 3950.0)] = (None, 0.05)
    out = close_long_spread(opened_put(), exit_quotes(book), TX, CFG)
    assert out.status == OK
    # long leg sold at 0: cost 0.25 + 0.36 + 0.05 = 0.66; other three sides 1.15 each
    assert out.costs["conservative"] == pytest.approx(3 * 1.15 + 0.66)
    assert out.net["conservative"] == pytest.approx((2.20 - 6.2) * 100 - (3 * 1.15 + 0.66))


def test_exit_unresolved_cases() -> None:
    o = opened_put()
    book = dict(EXIT)
    book[sym("SPXW", "P", 3960.0)] = (6.0, None)
    assert close_long_spread(o, exit_quotes(book), TX, CFG).reason == EXIT_NO_ASK
    q = exit_quotes(EXIT)
    q[sym("SPXW", "P", 3950.0)] = Quote(4.4, 4.6, 1, 1, TX - timedelta(minutes=6))
    out = close_long_spread(o, q, TX, CFG)
    assert (out.status, out.reason) == (UNRESOLVED_DATA, EXIT_STALE)
    q = exit_quotes(EXIT)
    q[sym("SPXW", "P", 3960.0)] = None  # not stored
    assert close_long_spread(o, q, TX, CFG).reason == EXIT_NO_ASK
