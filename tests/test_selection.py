"""Frozen option-selection rule, spec §5 (T-SEL-01...05) and §4.9 liquidity gates."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from qqq1dte.core.config import load_config
from qqq1dte.execution_sim.selection import Contract, NoTrade, Quote, Selected, select_contract

CFG = load_config()
TE = datetime(2025, 3, 11, 15, 0, 5, tzinfo=UTC)
EXP = date(2025, 3, 12)
KNOWN = TE - timedelta(hours=8)


def chain(strikes: list[float], known: datetime = KNOWN) -> list[Contract]:
    return [
        Contract(f"QQQ   250312{r}{int(k * 1000):08d}", k, r, EXP, known)
        for k in strikes
        for r in "CP"
    ]


def good(symbol_chain: list[Contract], bid: float = 1.00, ask: float = 1.02) -> dict[str, Quote]:
    return {c.symbol: Quote(bid, ask, 10, 10, TE - timedelta(seconds=5)) for c in symbol_chain}


def pick(spot: float, side: str, strikes: list[float]) -> Selected | NoTrade:
    ch = chain(strikes)
    return select_contract(ch, spot, side, good(ch), TE, CFG)


def test_sel_01_atm_first_otm() -> None:
    call, put = pick(512.40, "C", [511, 512, 513]), pick(512.40, "P", [511, 512, 513])
    assert isinstance(call, Selected) and call.contract.strike == 513
    assert isinstance(put, Selected) and put.contract.strike == 512


def test_sel_02_exactly_at_strike() -> None:
    call, put = pick(512.0, "C", [511, 512, 513]), pick(512.0, "P", [511, 512, 513])
    assert isinstance(call, Selected) and call.contract.strike == 512
    assert isinstance(put, Selected) and put.contract.strike == 512


def test_sel_03_only_point_in_time_chain() -> None:
    ch = chain([511, 513]) + chain([512.5], known=TE + timedelta(seconds=1))  # listed after T_e
    res = select_contract(ch, 512.40, "C", good(ch), TE, CFG)
    assert isinstance(res, Selected) and res.contract.strike == 513


def test_sel_04_no_fallback_when_selected_is_illiquid() -> None:
    ch = chain([512, 513, 514])
    quotes = good(ch)
    sym513 = next(c.symbol for c in ch if c.strike == 513 and c.right == "C")
    quotes[sym513] = Quote(1.00, 1.40, 10, 10, TE)  # spread 0.40 > max(0.05, 5% of 1.20)
    res = select_contract(ch, 512.40, "C", quotes, TE, CFG)
    assert res == NoTrade("SELECTED_CONTRACT_ILLIQUID", ("SPREAD_TOO_WIDE",))


@settings(max_examples=300, deadline=None)
@given(
    strikes=st.lists(st.integers(400, 600), min_size=1, max_size=40, unique=True),
    spot=st.floats(390, 610, allow_nan=False),
    side=st.sampled_from(["C", "P"]),
)
def test_sel_05_deterministic_and_matches_the_rule(
    strikes: list[int], spot: float, side: str
) -> None:
    ks = [float(k) for k in strikes]
    a, b = pick(spot, side, ks), pick(spot, side, list(reversed(ks)))
    assert a == b  # same inputs (any order) -> same output
    eligible = [k for k in ks if (k >= spot if side == "C" else k <= spot)]
    if not eligible:
        assert a == NoTrade("NO_CONTRACT")
    else:
        want = min(eligible) if side == "C" else max(eligible)
        assert isinstance(a, Selected) and a.contract.strike == want


def test_gates_each_reason() -> None:
    ch = chain([513])
    sym = next(c.symbol for c in ch if c.right == "C")
    cases = {
        "NO_QUOTE": None,
        "REJECTED_QUOTE": Quote(None, None, None, None, TE, rejected=True),
        "STALE_QUOTE": Quote(1.00, 1.02, 10, 10, TE - timedelta(seconds=61)),
        "NOT_TWO_SIDED": Quote(None, 1.02, 0, 10, TE),
        "CROSSED": Quote(1.03, 1.02, 10, 10, TE),
        "BID_BELOW_MIN": Quote(0.15, 0.16, 10, 10, TE),
        "SIZE_BELOW_CONTRACTS": Quote(1.00, 1.02, 10, 0, TE),
    }
    for reason, q in cases.items():
        quotes = {} if q is None else {sym: q}
        res = select_contract(ch, 512.40, "C", quotes, TE, CFG)
        assert isinstance(res, NoTrade) and res.reason == "SELECTED_CONTRACT_ILLIQUID", reason
        assert reason in res.details, (reason, res.details)


def test_spread_gate_uses_max_of_abs_and_pct() -> None:
    ch = chain([513])
    sym = next(c.symbol for c in ch if c.right == "C")
    # mid 4.00: 5% = 0.20 > 0.05 -> a 0.19 spread passes; mid 0.40: 0.05 floor -> 0.05 passes
    assert isinstance(
        select_contract(ch, 512.4, "C", {sym: Quote(3.905, 4.095, 9, 9, TE)}, TE, CFG), Selected
    )
    assert isinstance(
        select_contract(ch, 512.4, "C", {sym: Quote(0.375, 0.425, 9, 9, TE)}, TE, CFG), Selected
    )
    assert isinstance(
        select_contract(ch, 512.4, "C", {sym: Quote(0.37, 0.43, 9, 9, TE)}, TE, CFG), NoTrade
    )
