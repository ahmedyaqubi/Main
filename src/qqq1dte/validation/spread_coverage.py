"""M19T Step 0 (ADR-0013 D1.a / D1.c): can the stored data resolve the credit-fraction rule?

Pure helpers for the data-coverage report. Pick rule (D1.a), per T_e: among adjacent $width
pairs whose legs both have a usable quote in force at T_e, the conservative credit is
short bid - long ask; the short strike is the furthest out-of-the-money one with credit >=
X * width (puts: lowest strike, long = short - width; calls: highest, long = short + width).
No spot price is used.

`AT_BAND_EDGE`: the qualifying pair's long leg is the outermost stored strike, so a pair further
out (outside the downloaded band) cannot be ruled out. This reports data coverage only. No P&L is
computed here.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from qqq1dte.execution_sim.spreads import (  # noqa: F401 (re-exported for the Step-0 report)
    AT_BAND_EDGE,
    NO_QUALIFYING,
    OK,
    CreditPick,
    LegQuote,
    credit_pick,
)


def grid_holes(strikes: Sequence[float], width: float = 1.0) -> list[float]:
    """Whole-step grid points missing between the lowest and highest listed strike."""
    if not strikes:
        return []
    have = {round(s, 9) for s in strikes}
    lo, hi = min(have), max(have)
    n = round((hi - lo) / width)
    return [g for i in range(n + 1) if (g := round(lo + i * width, 9)) not in have]


def longest_gap_minutes(usable_at: Sequence[datetime], start: datetime, end: datetime) -> float:
    """Longest time within [start, end] since the last usable record (the quote in force at
    `start` may be older and its age counts). No usable record at or before `start` makes
    `start` the reference."""
    times = sorted(usable_at)
    before = [t for t in times if t <= start]
    prev = before[-1] if before else start
    worst = 0.0
    for t in (t for t in times if start < t <= end):
        worst = max(worst, (t - prev).total_seconds() / 60)
        prev = t
    return max(worst, (end - prev).total_seconds() / 60)
