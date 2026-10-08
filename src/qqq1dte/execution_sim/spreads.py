"""ADR-0013 D1.a (frozen, model-free): the credit-fraction strike rule for $width credit spreads.

Per T_e, among adjacent $width pairs whose legs both have a usable quote in force at T_e, the
conservative credit is short bid - long ask. The short strike is the furthest out-of-the-money one
with credit >= X * width (puts: lowest strike, long = short - width; calls: highest, long = short +
width). No spot price is used. A pair whose long strike is not listed is ineligible (R2).
`AT_BAND_EDGE` marks a pick whose long leg is the outermost stored strike (Step-0 coverage).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

OK = "OK"
NO_QUALIFYING = "NO_QUALIFYING"  # D1.a NO_TRADE
AT_BAND_EDGE = "AT_BAND_EDGE"
_EPS = 1e-9


@dataclass(frozen=True)
class LegQuote:
    strike: float
    bid: float | None
    ask: float | None
    usable: bool  # latest record at T_e not rejected and no older than liquidity.max_quote_age_s


@dataclass(frozen=True)
class CreditPick:
    status: str
    short: float | None
    long: float | None
    credit: float | None
    pairs: int  # adjacent pairs with both legs usable and the needed sides defined
    beyond: int  # stored strikes further out of the money than the long leg


def credit_pick(
    chain: Mapping[float, LegQuote], right: str, x: float, width: float = 1.0
) -> CreditPick:
    step = -width if right == "P" else width
    target = round(x * width, 9)
    qualifying: list[tuple[float, float, float]] = []
    pairs = 0
    for k, short in chain.items():
        long = chain.get(round(k + step, 9))
        if long is None or not (short.usable and long.usable):
            continue
        if short.bid is None or long.ask is None or long.ask <= 0:
            continue
        pairs += 1
        credit = round(short.bid - long.ask, 9)
        if credit >= target - _EPS:
            qualifying.append((k, long.strike, credit))
    if not qualifying:
        return CreditPick(NO_QUALIFYING, None, None, None, pairs, 0)
    pick = min(qualifying) if right == "P" else max(qualifying)
    k, lk, credit = pick
    beyond = sum(1 for s in chain if (s < lk if right == "P" else s > lk))
    status = OK if beyond else AT_BAND_EDGE
    return CreditPick(status, k, lk, credit, pairs, beyond)
