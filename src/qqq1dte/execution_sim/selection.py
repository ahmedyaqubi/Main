"""Frozen option-selection rule (spec §5) with the §4.9 liquidity gates. Pure: same inputs give
the same output; it sees only the contracts known at T_e and the quote in force at T_e.

Used by the C labels (M6) and the backtester (M11). Adjusted and standard strikes are treated
alike (owner, M6 Q1; ADR-0005).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from qqq1dte.core.config import Phase1Config

SELECTED_CONTRACT_ILLIQUID = "SELECTED_CONTRACT_ILLIQUID"
NO_CONTRACT = "NO_CONTRACT"
NO_OFFSET_STRIKE = "NO_OFFSET_STRIKE"  # ADR-0012 T3: the offset strike is not listed


@dataclass(frozen=True, order=True)
class Contract:
    symbol: str
    strike: float
    right: str  # "C" or "P"
    expiration: date
    available_at: datetime  # when the definition became known


@dataclass(frozen=True)
class Quote:
    bid: float | None
    ask: float | None
    bid_sz: int | None
    ask_sz: int | None
    available_at: datetime
    rejected: bool = False  # the latest record failed data-quality checks (M4)


@dataclass(frozen=True)
class Selected:
    contract: Contract
    quote: Quote


@dataclass(frozen=True)
class NoTrade:
    reason: str
    details: tuple[str, ...] = ()


def choose_contract(
    chain: Sequence[Contract], spot: float, side: str, t_e: datetime, strike_offset: int = 0
) -> Contract | None:
    """Steps 1-3: among contracts known at t_e, CALL = lowest strike >= spot, PUT = highest
    strike <= spot. The caller passes the 1DTE expiry's chain.

    strike_offset > 0 (ADR-0012 T3, study only) then moves that many listed strikes of the same
    right in the money (CALL: lower, PUT: higher); None when that strike is not listed."""
    known = [c for c in chain if c.right == side and c.available_at <= t_e]
    if side == "C":
        eligible = [c for c in known if c.strike >= spot]
        base = min(eligible, key=lambda c: (c.strike, c.symbol)) if eligible else None
    else:
        eligible = [c for c in known if c.strike <= spot]
        base = max(eligible, key=lambda c: (c.strike, c.symbol)) if eligible else None
    if base is None or strike_offset == 0:
        return base
    strikes = sorted({c.strike for c in known})
    j = strikes.index(base.strike) + (-strike_offset if side == "C" else strike_offset)
    if not 0 <= j < len(strikes):
        return None
    return min((c for c in known if c.strike == strikes[j]), key=lambda c: c.symbol)


def liquidity_failures(
    quote: Quote | None, t_e: datetime, cfg: Phase1Config, *, check_min_bid: bool = True
) -> list[str]:
    """§4.9 gates on the quote in force at t_e; empty list = tradable. `check_min_bid=False`
    skips only the min-bid gate (ADR-0013 R1: the bought leg of a credit spread)."""
    liq = cfg.liquidity
    if quote is None:
        return ["NO_QUOTE"]
    if quote.rejected:
        return ["REJECTED_QUOTE"]
    if t_e - quote.available_at > timedelta(seconds=liq.max_quote_age_s):
        return ["STALE_QUOTE"]
    bid, ask = quote.bid, quote.ask
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return ["NOT_TWO_SIDED"]
    if bid > ask:
        return ["CROSSED"]
    out = []
    mid = (bid + ask) / 2
    if round(ask - bid, 9) > max(liq.max_spread_abs, liq.max_spread_pct * mid) + 1e-12:
        out.append("SPREAD_TOO_WIDE")
    if check_min_bid and bid < liq.min_bid:
        out.append("BID_BELOW_MIN")
    if liq.require_size and quote.ask_sz is not None and quote.ask_sz < cfg.trade.contracts:
        out.append("SIZE_BELOW_CONTRACTS")
    return out


def select_contract(
    chain: Sequence[Contract],
    spot: float,
    side: str,
    quotes: Mapping[str, Quote],
    t_e: datetime,
    cfg: Phase1Config,
    strike_offset: int = 0,
) -> Selected | NoTrade:
    """Spec §5: pick the contract, then gate it. No fallback to another strike."""
    contract = choose_contract(chain, spot, side, t_e, strike_offset)
    if contract is None:
        if strike_offset and choose_contract(chain, spot, side, t_e) is not None:
            return NoTrade(NO_OFFSET_STRIKE)
        return NoTrade(NO_CONTRACT)
    quote = quotes.get(contract.symbol)
    failures = liquidity_failures(quote, t_e, cfg)
    if failures or quote is None:
        return NoTrade(SELECTED_CONTRACT_ILLIQUID, tuple(failures))
    return Selected(contract, quote)
