"""ADR-0021 amendment A1, setup S1: the direction of the underlying's first candle
(Zarattini & Aziz). Pure functions on prices the caller has already read point-in-time.

The underlying is measured at the mid of 1-minute quotes (A1), so the candle's high and low are
the highest and lowest of the mids sampled once a minute over the candle (owner, 2026-11-15):
extremes inside a minute are not seen.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class OrbSignal:
    side: str  # "C" (candle up) or "P" (candle down)
    entry: float  # the candle's close: the underlying at the entry time
    stop: float  # the candle's low (call) or high (put)
    target: float  # entry +/- r_multiple x stop distance

    @property
    def stop_distance(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def direction(self) -> int:
        return 1 if self.side == "C" else -1


def orb_signal(candle: Sequence[float], r_multiple: float) -> OrbSignal | None:
    """`candle` = the mids over the candle in time order: first = its open, last = its close.
    None when the candle is flat (NO_TRADE, FLAT_FIRST_CANDLE)."""
    if len(candle) < 2:  # noqa: PLR2004 (an open and a close)
        raise ValueError("a candle needs at least its open and its close")
    open_, close = candle[0], candle[-1]
    if close == open_:
        return None
    if close > open_:
        stop = min(candle)
        return OrbSignal("C", close, stop, close + r_multiple * (close - stop))
    stop = max(candle)
    return OrbSignal("P", close, stop, close - r_multiple * (stop - close))


def orb_exit(
    signal: OrbSignal, path: Sequence[tuple[datetime, float]]
) -> tuple[datetime, str, float] | None:
    """The first (time, reason, price) on `path` (time-ordered mids after the entry) at which
    the underlying is at or beyond the stop ("STOP") or the target ("TARGET"); None if never."""
    d = signal.direction
    for t, m in path:
        if d * (m - signal.stop) <= 0:
            return t, "STOP", m
        if d * (m - signal.target) >= 0:
            return t, "TARGET", m
    return None
