"""ADR-0013 (M19T Step 1): defined-risk credit-spread labels. Pure functions.

Entry (D1.a-b, R1-R2), at T_e:
- Contracts known at T_e (definition available_at <= T_e). A leg is usable if its latest record
  at T_e is not rejected and is no older than `liquidity.max_quote_age_s`.
- The frozen credit rule picks each side's pair (`execution_sim.spreads.credit_pick`).
- A condor needs both sides (owner, M19T Step 1): a missing side is NO_TRADE
  `CONDOR_SIDE_MISSING`.
- A pick whose long leg is the outermost stored strike is NO_TRADE `AT_BAND_EDGE`: the stored
  band was chosen with the session's full-day range, so a further pair cannot be ruled out
  point-in-time (leakage review, M19T Step 1).
- §4.9 gates act after selection, with no fallback (R1). Every leg gets them, except that the
  min-bid gate applies to short legs only.
- Credits are given for three fill models: conservative (sell at the bid, buy at the ask),
  moderate (`fills.moderate_alpha`) and mid.

Exit (D1.c), at the expiry session's forced exit + latency:
- Every leg is closed: short legs are bought, long legs sold. A missing bid counts as 0.
- These give UNRESOLVED_DATA (never filled):
  - a missing ask or a rejected latest record on any leg;
  - an exit quote older than `labels.option.max_path_gap_minutes`;
  - an RTH quote gap during the hold longer than that.
- Costs (§4.8): commission and fees per leg, on open and on close.
- Max risk = (width - conservative credit) x 100 + costs. Only one side of a condor can lose.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import polars as pl

from qqq1dte.core.config import Phase1Config
from qqq1dte.core.dividends import ExDividend
from qqq1dte.execution_sim.fills import Conservative, FillModel, Moderate, Optimistic
from qqq1dte.execution_sim.selection import Contract, Quote, liquidity_failures
from qqq1dte.execution_sim.spreads import AT_BAND_EDGE, LegQuote, credit_pick

OK = "OK"
NO_TRADE = "NO_TRADE"
UNRESOLVED_DATA = "UNRESOLVED_DATA"
NO_QUALIFYING = "NO_QUALIFYING"
CONDOR_SIDE_MISSING = "CONDOR_SIDE_MISSING"
LEG_ILLIQUID = "LEG_ILLIQUID"
EXIT_NO_ASK = "EXIT_NO_ASK"
EXIT_STALE = "EXIT_STALE"
PATH_GAP = "PATH_GAP"
MULTIPLIER = 100
FILLS = ("conservative", "moderate", "mid")
SIDES = {"put": ("P",), "condor": ("P", "C")}


@dataclass(frozen=True)
class NoTrade:
    reason: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class OpenLeg:
    contract: Contract
    role: str  # "short" | "long"
    quote: Quote


@dataclass(frozen=True)
class Opened:
    legs: tuple[OpenLeg, ...]
    credit: dict[str, float]  # per fill model, per share
    width: float

    @property
    def has_short_call(self) -> bool:
        return any(leg.role == "short" and leg.contract.right == "C" for leg in self.legs)


@dataclass(frozen=True)
class SpreadOutcome:
    status: str  # OK | UNRESOLVED_DATA
    reason: str | None
    net: dict[str, float]  # per fill model, dollars per position
    costs: float
    max_risk: float


def _models(cfg: Phase1Config) -> dict[str, FillModel]:
    return {
        "conservative": Conservative(cfg),
        "moderate": Moderate(cfg, cfg.fills.moderate_alpha),
        "mid": Optimistic(cfg),
    }


def _usable(q: Quote | None, t_e: datetime, cfg: Phase1Config) -> bool:
    return (
        q is not None
        and not q.rejected
        and t_e - q.available_at <= timedelta(seconds=cfg.liquidity.max_quote_age_s)
    )


def _zero_bid(q: Quote) -> Quote:
    """D1.c: a missing bid counts as 0."""
    return q if q.bid is not None else Quote(0.0, q.ask, q.bid_sz, q.ask_sz, q.available_at)


def open_spread(
    chain: Sequence[Contract],
    quotes: Mapping[str, Quote],
    t_e: datetime,
    structure: str,
    x: float,
    width: float,
    cfg: Phase1Config,
) -> Opened | NoTrade:
    picked: list[OpenLeg] = []
    missing: list[str] = []
    edge: list[str] = []
    for right in SIDES[structure]:
        known = {c.strike: c for c in chain if c.right == right and c.available_at <= t_e}
        legq = {
            k: LegQuote(k, q.bid, q.ask, _usable(q, t_e, cfg))
            for k, c in known.items()
            if (q := quotes.get(c.symbol)) is not None
        }
        p = credit_pick(legq, right, x, width)
        if p.short is None or p.long is None:
            missing.append(right)
            continue
        if p.status == AT_BAND_EDGE:
            edge.append(right)  # the stored band (full-day range) may hide the furthest pair
        for role, k in (("short", p.short), ("long", p.long)):
            c = known[k]
            picked.append(OpenLeg(c, role, quotes[c.symbol]))
    if missing:
        if len(missing) == len(SIDES[structure]):
            return NoTrade(NO_QUALIFYING)
        return NoTrade(CONDOR_SIDE_MISSING, tuple(missing))
    if edge:
        return NoTrade(AT_BAND_EDGE, tuple(edge))
    fails = tuple(
        f"{leg.role}:{f}" if structure == "put" else f"{leg.role}{leg.contract.right}:{f}"
        for leg in picked
        for f in liquidity_failures(leg.quote, t_e, cfg, check_min_bid=leg.role == "short")
    )
    if fails:
        return NoTrade(LEG_ILLIQUID, fails)
    models = _models(cfg)
    credit = {
        name: round(
            sum(m.sell(leg.quote) if leg.role == "short" else -m.buy(leg.quote) for leg in picked),
            9,
        )
        for name, m in models.items()
    }
    return Opened(tuple(picked), credit, width)


def close_spread(
    opened: Opened,
    exit_quotes: Mapping[str, Quote | None],
    t_x: datetime,
    hold_gaps: Mapping[str, float],
    cfg: Phase1Config,
) -> SpreadOutcome:
    """`exit_quotes`: quote in force at t_x per leg symbol (None: no record); `hold_gaps`: the
    longest RTH stretch (minutes) without a usable record per leg during the hold."""
    max_gap = cfg.labels.option.max_path_gap_minutes
    n_legs = len(opened.legs)
    costs = (
        n_legs
        * 2
        * cfg.trade.contracts
        * (cfg.costs.commission_per_contract + cfg.costs.fees_per_contract)
    )
    # one width at risk: a condor's two sides cannot both finish in the money
    max_risk = (opened.width - opened.credit["conservative"]) * MULTIPLIER + costs
    size = cfg.trade.contracts * MULTIPLIER

    def unresolved(reason: str) -> SpreadOutcome:
        return SpreadOutcome(UNRESOLVED_DATA, reason, {}, costs, max_risk)

    qs = []
    for leg in opened.legs:
        q = exit_quotes.get(leg.contract.symbol)
        if q is None or q.rejected or q.ask is None or q.ask <= 0:
            return unresolved(EXIT_NO_ASK)
        if t_x - q.available_at > timedelta(minutes=max_gap):
            return unresolved(EXIT_STALE)
        if hold_gaps.get(leg.contract.symbol, 0.0) > max_gap:
            return unresolved(PATH_GAP)
        qs.append(_zero_bid(q))
    net = {}
    for name, m in _models(cfg).items():
        debit = sum(
            m.buy(q) if leg.role == "short" else -m.sell(q)
            for leg, q in zip(opened.legs, qs, strict=True)
        )
        net[name] = round((opened.credit[name] - debit) * size - costs, 9)
    return SpreadOutcome(OK, None, net, costs, max_risk)


def quote_at(records: pl.DataFrame, t: datetime) -> dict[str, Quote]:
    """Latest record per symbol with available_at <= t (cleaned + rejected records, as
    `labels.option.option_records`). A rejected latest record stays rejected."""
    last = (
        records.filter(pl.col("available_at") <= t)
        .sort("available_at", "rejected")  # a tie (DUP_EXACT copy) resolves to the rejected one
        .group_by("symbol", maintain_order=True)
        .last()
    )
    return {
        r["symbol"]: Quote(
            r["bid"], r["ask"], r["bid_sz"], r["ask_sz"], r["available_at"], r["rejected"]
        )
        for r in last.iter_rows(named=True)
    }


def ex_div_span(
    entry: date,
    exit_: date,
    has_short_call: bool,
    exdivs: Sequence[ExDividend],
    sessions: Sequence[date],
) -> bool:
    """D1.d: a short call held over the close of the session before an ex-date known at entry."""
    if not has_short_call:
        return False
    for e in exdivs:
        if e.known_from > entry:
            continue
        before = [s for s in sessions if s < e.ex_date]
        if before and entry <= before[-1] < exit_:
            return True
    return False
