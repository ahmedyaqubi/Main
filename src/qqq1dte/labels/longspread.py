"""ADR-0014 (M23 Step 1): SPX longer-dated defined-risk credit-spread labels. Pure functions.

Entry at T_e (D2, R1, R10, R11):
- Contracts must be known at T_e (definition available_at <= T_e).
- On a shared strike, SPXW is preferred over SPX (`study_2a.root_preference`, R11).
- A leg is usable if its latest record is not rejected and is no older than
  `liquidity.max_quote_age_s`.
- The frozen credit rule (`execution_sim.spreads.credit_pick`) picks the pair. A pick at the
  stored band's edge is NO_TRADE `AT_BAND_EDGE`. A condor needs both sides.
- Gates act after selection, with no fallback: the §4.9 gates, except that the spread check is
  replaced by R10 (spread <= `max_spread_pct` x mid), and min-bid applies to short legs only.

Exit at the session before expiry (D2, R9): every leg is closed at the quote in force at t_x.
- A missing ask, a rejected record, a leg not stored, or an exit quote older than
  `labels.option.max_path_gap_minutes` gives UNRESOLVED_DATA. There is no path check during the
  hold (R9).
- A missing bid counts as 0, and that side is still charged costs (conservative).

Costs (R3) are per contract per side at the fill price: the IBKR commission tier by premium, plus
the Cboe SPX fee by premium, plus allowances. Max risk = (W - conservative credit) x 100 +
conservative costs. Only one side of a condor can finish in the money.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from qqq1dte.core.config import Phase1Config, Study2a
from qqq1dte.execution_sim.fills import Conservative, FillModel, Moderate, Optimistic
from qqq1dte.execution_sim.selection import Contract, Quote, liquidity_failures
from qqq1dte.execution_sim.spreads import AT_BAND_EDGE, LegQuote, credit_pick
from qqq1dte.labels.spread import NoTrade, OpenLeg

OK = "OK"
UNRESOLVED_DATA = "UNRESOLVED_DATA"
NO_QUALIFYING = "NO_QUALIFYING"
CONDOR_SIDE_MISSING = "CONDOR_SIDE_MISSING"
LEG_ILLIQUID = "LEG_ILLIQUID"
EXIT_NO_ASK = "EXIT_NO_ASK"
EXIT_STALE = "EXIT_STALE"
SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
MULTIPLIER = 100
SIDES = {"put": ("P",), "condor": ("P", "C")}
_EPS = 1e-9

__all__ = [
    "AT_BAND_EDGE", "CONDOR_SIDE_MISSING", "EXIT_NO_ASK", "EXIT_STALE", "LEG_ILLIQUID",
    "NO_QUALIFYING", "OK", "UNRESOLVED_DATA", "LongOpened", "LongOutcome", "NoTrade",
    "close_long_spread", "open_long_spread", "spread_gate_r10", "spx_leg_cost",
]  # fmt: skip


@dataclass(frozen=True)
class LongOpened:
    legs: tuple[OpenLeg, ...]
    credit: dict[str, float]  # per fill model, index points
    entry_fill: dict[str, tuple[float, ...]]  # per fill model, per leg (for costs)
    width: float


@dataclass(frozen=True)
class LongOutcome:
    status: str
    reason: str | None
    net: dict[str, float]  # $ per position
    costs: dict[str, float]  # $ per position (open + close)
    max_risk: float


def _models(cfg: Phase1Config) -> dict[str, FillModel]:
    return {
        "conservative": Conservative(cfg),
        "moderate": Moderate(cfg, cfg.fills.moderate_alpha),
        "mid": Optimistic(cfg),
    }


def spx_leg_cost(price: float, s: Study2a) -> float:
    commission = s.commission_default
    for below, fee in s.commission_tiers:
        if price < below - _EPS:
            commission = fee
            break
    cboe = s.cboe_fee_below if price < s.cboe_fee_threshold - _EPS else s.cboe_fee
    return round(commission + cboe + s.regulatory_allowance + s.surcharge_allowance, 9)


def spread_gate_r10(q: Quote, max_pct: float) -> list[str]:
    if q.bid is None or q.ask is None:
        return []  # two-sidedness is checked by the §4.9 gates
    mid = (q.bid + q.ask) / 2
    return [SPREAD_TOO_WIDE] if round(q.ask - q.bid, 9) > max_pct * mid + _EPS else []


def _leg_failures(q: Quote, t_e: datetime, cfg: Phase1Config, short: bool) -> list[str]:
    base = [f for f in liquidity_failures(q, t_e, cfg, check_min_bid=short) if f != SPREAD_TOO_WIDE]
    if base:
        return base  # stale / rejected / one-sided: the spread check does not apply
    return spread_gate_r10(q, cfg.study_2a.max_spread_pct)


def _root(symbol: str) -> str:
    return symbol[:6].strip()


def open_long_spread(
    chain: Sequence[Contract],
    quotes: Mapping[str, Quote],
    t_e: datetime,
    structure: str,
    x: float,
    width: float,
    cfg: Phase1Config,
) -> LongOpened | NoTrade:
    pref = {r: i for i, r in enumerate(cfg.study_2a.root_preference)}
    max_age = timedelta(seconds=cfg.liquidity.max_quote_age_s)
    picked: list[OpenLeg] = []
    missing: list[str] = []
    edge: list[str] = []
    for right in SIDES[structure]:
        known: dict[float, Contract] = {}
        for c in sorted(
            (c for c in chain if c.right == right and c.available_at <= t_e),
            key=lambda c: pref.get(_root(c.symbol), len(pref)),
        ):
            known.setdefault(c.strike, c)  # the preferred root wins a shared strike (R11)
        book = {}
        for k, c in known.items():
            q = quotes.get(c.symbol)
            if q is None:
                continue
            usable = not q.rejected and t_e - q.available_at <= max_age
            book[k] = LegQuote(k, q.bid, q.ask, usable)
        p = credit_pick(book, right, x, width)
        if p.short is None or p.long is None:
            missing.append(right)
            continue
        if p.status == AT_BAND_EDGE:
            edge.append(right)
        for role, k in (("short", p.short), ("long", p.long)):
            picked.append(OpenLeg(known[k], role, quotes[known[k].symbol]))
    if missing:
        if len(missing) == len(SIDES[structure]):
            return NoTrade(NO_QUALIFYING)
        return NoTrade(CONDOR_SIDE_MISSING, tuple(missing))
    if edge:
        return NoTrade(AT_BAND_EDGE, tuple(edge))
    fails = tuple(
        (f"{lg.role}:{f}" if structure == "put" else f"{lg.role}{lg.contract.right}:{f}")
        for lg in picked
        for f in _leg_failures(lg.quote, t_e, cfg, lg.role == "short")
    )
    if fails:
        return NoTrade(LEG_ILLIQUID, fails)
    fills: dict[str, tuple[float, ...]] = {}
    credit: dict[str, float] = {}
    for name, m in _models(cfg).items():
        px = tuple(m.sell(lg.quote) if lg.role == "short" else m.buy(lg.quote) for lg in picked)
        fills[name] = px
        credit[name] = round(
            sum(p if lg.role == "short" else -p for lg, p in zip(picked, px, strict=True)), 9
        )
    return LongOpened(tuple(picked), credit, fills, width)


def close_long_spread(
    opened: LongOpened,
    exit_quotes: Mapping[str, Quote | None],
    t_x: datetime,
    cfg: Phase1Config,
) -> LongOutcome:
    s = cfg.study_2a
    max_gap = timedelta(minutes=cfg.labels.option.max_path_gap_minutes)
    size = cfg.trade.contracts * MULTIPLIER
    qs: list[Quote] = []
    reason = None
    for lg in opened.legs:
        q = exit_quotes.get(lg.contract.symbol)
        if q is None or q.rejected or q.ask is None or q.ask <= 0:
            reason = reason or EXIT_NO_ASK
            continue
        if t_x - q.available_at > max_gap:
            reason = reason or EXIT_STALE
            continue
        qs.append(q if q.bid is not None else Quote(0.0, q.ask, q.bid_sz, q.ask_sz, q.available_at))
    open_cost = {
        n: sum(spx_leg_cost(p, s) for p in px) * cfg.trade.contracts
        for n, px in opened.entry_fill.items()
    }
    if reason is not None:
        cons = open_cost["conservative"]
        risk = (opened.width - opened.credit["conservative"]) * MULTIPLIER + 2 * cons
        return LongOutcome(UNRESOLVED_DATA, reason, {}, {}, risk)
    net: dict[str, float] = {}
    costs: dict[str, float] = {}
    for name, m in _models(cfg).items():
        px = [
            m.buy(q) if lg.role == "short" else m.sell(q)
            for lg, q in zip(opened.legs, qs, strict=True)
        ]
        debit = sum(p if lg.role == "short" else -p for lg, p in zip(opened.legs, px, strict=True))
        costs[name] = round(
            open_cost[name] + sum(spx_leg_cost(p, s) for p in px) * cfg.trade.contracts, 9
        )
        net[name] = round((opened.credit[name] - debit) * size - costs[name], 9)
    max_risk = (opened.width - opened.credit["conservative"]) * MULTIPLIER + costs["conservative"]
    return LongOutcome(OK, None, net, costs, round(max_risk, 9))
