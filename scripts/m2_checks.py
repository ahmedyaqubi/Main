"""Pure, vendor-agnostic checks for the M2 one-week sample (DATA_REQUIREMENTS.md §5).

Throwaway-grade M2 tooling, not the M3/M4 ingestion or validation modules. Inputs are plain
Python objects so any vendor's data can be adapted to them. Stdlib only.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt

ET = ZoneInfo("America/New_York")
RTH_OPEN = time(9, 30)
FIRST_BAR_END = time(9, 31)

BarConvention = Literal["start", "end", "unknown"]


@dataclass(frozen=True)
class Quote:
    ts: datetime
    bid: float
    ask: float


def _require_aware(ts: datetime) -> None:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(f"naive timestamp not allowed: {ts!r}")


def _session_date(ts: datetime) -> date:
    _require_aware(ts)
    return ts.astimezone(ET).date()


# C2 -------------------------------------------------------------------------
def bar_counts_by_session(bar_ts: Iterable[datetime]) -> dict[date, int]:
    """Number of bars per ET session date."""
    return dict(Counter(_session_date(ts) for ts in bar_ts))


def infer_bar_convention(bar_ts: Iterable[datetime]) -> BarConvention:
    """'start' if each session's first RTH bar is labelled 09:30, 'end' if 09:31."""
    first_by_session: dict[date, time] = {}
    for ts in bar_ts:
        local = ts.astimezone(ET) if ts.tzinfo else None
        if local is None:
            raise ValueError(f"naive timestamp not allowed: {ts!r}")
        t = local.timetz().replace(tzinfo=None)
        d = local.date()
        if d not in first_by_session or t < first_by_session[d]:
            first_by_session[d] = t
    firsts = set(first_by_session.values())
    if firsts == {RTH_OPEN}:
        return "start"
    if firsts == {FIRST_BAR_END}:
        return "end"
    return "unknown"


def bar_convention_by_alignment(
    closes: Mapping[datetime, float], mids: Mapping[datetime, float], bar: timedelta
) -> dict[str, float]:
    """Mean |close - quote mid| under each labelling hypothesis.

    'start': a bar labelled t covers [t, t+bar), so its close should match the mid at t+bar.
    'end':   a bar labelled t covers [t-bar, t), so its close should match the mid at t.
    The hypothesis with the clearly smaller error is the vendor's convention.
    """
    err_start: list[float] = []
    err_end: list[float] = []
    for t, close in closes.items():
        if t + bar in mids and t in mids:
            err_start.append(abs(close - mids[t + bar]))
            err_end.append(abs(close - mids[t]))
    if not err_start:
        return {"start": float("nan"), "end": float("nan"), "n": 0.0}
    return {
        "start": sum(err_start) / len(err_start),
        "end": sum(err_end) / len(err_end),
        "n": float(len(err_start)),
    }


# C3 -------------------------------------------------------------------------
def interval_quote_semantics(
    ticks: Sequence[Quote], buckets: Sequence[Quote], bucket: timedelta
) -> dict[str, int]:
    """Classify each bucketed quote at time t against the tick stream.

    at_or_before:       equals the last tick with ts <= t (point-in-time safe)
    within_next_bucket: equals the last tick with ts < t + bucket (leaks up to one bucket)
    ambiguous:          both interpretations give the same quote
    neither:            matches neither
    """
    ordered = sorted(ticks, key=lambda q: q.ts)
    times = [q.ts for q in ordered]
    counts = {"at_or_before": 0, "within_next_bucket": 0, "ambiguous": 0, "neither": 0}
    for b in buckets:
        i_pit = bisect_right(times, b.ts) - 1
        i_next = bisect_left(times, b.ts + bucket) - 1
        pit = ordered[i_pit] if i_pit >= 0 else None
        nxt = ordered[i_next] if i_next >= 0 else None
        m_pit = pit is not None and (pit.bid, pit.ask) == (b.bid, b.ask)
        m_next = nxt is not None and (nxt.bid, nxt.ask) == (b.bid, b.ask)
        if m_pit and m_next:
            counts["ambiguous"] += 1
        elif m_pit:
            counts["at_or_before"] += 1
        elif m_next:
            counts["within_next_bucket"] += 1
        else:
            counts["neither"] += 1
    return counts


QuoteArrays = tuple[npt.NDArray[np.int64], npt.NDArray[np.float64], npt.NDArray[np.float64]]


def interval_quote_semantics_np(
    ticks: QuoteArrays, buckets: QuoteArrays, bucket_ns: int
) -> dict[str, int]:
    """Vectorised `interval_quote_semantics` for one contract.

    Each argument is (ts_ns, bid, ask) arrays; ticks sorted by ts. Same classification as the
    reference implementation (NaN never matches, as in the reference).
    """
    tick_ts, tick_bid, tick_ask = ticks
    bucket_ts, bucket_bid, bucket_ask = buckets
    i_pit = np.searchsorted(tick_ts, bucket_ts, side="right") - 1
    i_next = np.searchsorted(tick_ts, bucket_ts + bucket_ns, side="left") - 1

    def matches(idx: npt.NDArray[np.intp]) -> npt.NDArray[np.bool_]:
        ok = idx >= 0
        safe = np.where(ok, idx, 0)
        same = (tick_bid[safe] == bucket_bid) & (tick_ask[safe] == bucket_ask)
        result: npt.NDArray[np.bool_] = np.logical_and(ok, same)
        return result

    m_pit, m_next = matches(i_pit), matches(i_next)
    return {
        "at_or_before": int(np.sum(m_pit & ~m_next)),
        "within_next_bucket": int(np.sum(m_next & ~m_pit)),
        "ambiguous": int(np.sum(m_pit & m_next)),
        "neither": int(np.sum(~m_pit & ~m_next)),
    }


# C4 / C5 ----------------------------------------------------------------------
def missing_one_dte_sessions(
    sessions_to_check: Sequence[date],
    calendar_sessions: Sequence[date],
    listed_expirations: Mapping[date, set[date]],
) -> list[date]:
    """Sessions whose next-session expiration is not in that session's listed chain."""
    cal = sorted(calendar_sessions)
    missing = []
    for s in sessions_to_check:
        idx = cal.index(s)
        if idx + 1 >= len(cal):
            raise ValueError(f"calendar has no session after {s}")
        if cal[idx + 1] not in listed_expirations.get(s, set()):
            missing.append(s)
    return missing


def listing_lead_sessions(
    first_quote: date, expiration: date, calendar_sessions: Sequence[date]
) -> int:
    """Number of trading sessions from first quote up to (not including) expiration."""
    return sum(1 for s in calendar_sessions if first_quote <= s < expiration)


# C6 -------------------------------------------------------------------------
@dataclass
class QuoteValidity:
    total: int = 0
    missing: int = 0
    nonpositive: int = 0
    crossed: int = 0
    valid: int = 0
    spreads: list[float] = field(default_factory=list)


def quote_validity(quotes: Iterable[Quote]) -> QuoteValidity:
    """Counts of invalid quotes. Nothing is dropped silently: every quote is classified."""
    v = QuoteValidity()
    for q in quotes:
        v.total += 1
        if math.isnan(q.bid) or math.isnan(q.ask):
            v.missing += 1  # one side of the book empty (vendor NaN)
        elif q.bid <= 0 or q.ask <= 0:
            v.nonpositive += 1
        elif q.bid > q.ask:
            v.crossed += 1
        else:
            v.valid += 1
            v.spreads.append(q.ask - q.bid)
    return v


# C8 -------------------------------------------------------------------------
@dataclass(frozen=True)
class Agreement:
    common: int
    identical: int

    @property
    def share(self) -> float:
        return self.identical / self.common if self.common else float("nan")


def nbbo_agreement(
    a: Mapping[tuple[datetime, str], tuple[float, float]],
    b: Mapping[tuple[datetime, str], tuple[float, float]],
    decimals: int = 4,
) -> Agreement:
    """Share of common (minute, contract) keys whose bid/ask are identical in both sources."""
    common = a.keys() & b.keys()
    identical = sum(
        1
        for k in common
        if tuple(round(x, decimals) for x in a[k]) == tuple(round(x, decimals) for x in b[k])
    )
    return Agreement(common=len(common), identical=identical)
