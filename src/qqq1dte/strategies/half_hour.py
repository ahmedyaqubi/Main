"""ADR-0021 D3, setup S2: the direction of the underlying's move from the previous close to
10:00 (Gao, Han, Li & Zhou, 2018). A pure function on quotes the caller has already read
point-in-time.

The underlying is read from 1-minute quotes, not trades, so the move has a direction only when
the two quotes do not overlap (owner, 2026-11-15, M30 ruling 3): up when the later bid is above
the earlier ask, down when the later ask is below the earlier bid. Otherwise the data does not
say which way the price moved, and the session is NO_TRADE (FLAT_MOVE). A wide quote therefore
disqualifies itself; no spread limit is needed.
"""

from __future__ import annotations


def half_hour_signal(prev_bid: float, prev_ask: float, bid: float, ask: float) -> str | None:
    """Returns "C" (up), "P" (down) or None (flat). Quotes must be two-sided, not crossed."""
    if min(prev_bid, prev_ask, bid, ask) <= 0 or prev_bid > prev_ask or bid > ask:
        raise ValueError("half_hour_signal needs two-sided, uncrossed quotes")
    if bid > prev_ask:
        return "C"
    if ask < prev_bid:
        return "P"
    return None
