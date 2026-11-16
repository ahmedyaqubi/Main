"""ADR-0021 amendment A3, setup S3: the noise-area breakout (Zarattini, Aziz & Barbon, 2024).
Pure functions on prices the caller has already read point-in-time.

For a time of day, sigma is the average over the previous sessions of |price at that time /
that session's open - 1|. The noise area lies between
    upper = max(today's open, previous close) x (1 + sigma)
    lower = min(today's open, previous close) x (1 - sigma).

The underlying is read from 1-minute quotes, not trades. Boundaries use mids; a signal or an
exit needs the whole quote beyond the boundary (owner, 2026-11-16, M33 ruling 3), so a wide
quote disqualifies itself and no spread limit is needed.
"""

from __future__ import annotations

from collections.abc import Sequence


def sigma(moves: Sequence[float]) -> float:
    """Mean absolute move; `moves` = price / open - 1 at one time of day, one per session."""
    if not moves:
        raise ValueError("sigma needs at least one session")
    return sum(abs(m) for m in moves) / len(moves)


def boundaries(open_: float, prev_close: float, sig: float) -> tuple[float, float]:
    """(upper, lower) of the noise area."""
    if min(open_, prev_close) <= 0 or sig < 0:
        raise ValueError("boundaries need positive prices and a non-negative sigma")
    return max(open_, prev_close) * (1 + sig), min(open_, prev_close) * (1 - sig)


def _checked(bid: float, ask: float) -> None:
    if min(bid, ask) <= 0 or bid > ask:
        raise ValueError("the noise-area rule needs a two-sided, uncrossed quote")


def noise_signal(bid: float, ask: float, upper: float, lower: float) -> str | None:
    """ "C" when the bid is above the upper boundary, "P" when the ask is below the lower,
    otherwise None."""
    _checked(bid, ask)
    if bid > upper:
        return "C"
    if ask < lower:
        return "P"
    return None


def noise_exit(side: str, bid: float, ask: float, upper: float, lower: float) -> bool:
    """True when the quote is wholly beyond the boundary opposite to the position."""
    _checked(bid, ask)
    return ask < lower if side == "C" else bid > upper
