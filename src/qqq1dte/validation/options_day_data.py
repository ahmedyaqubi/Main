"""ADR-0021 D5 / M28 step 4: is the quote data the cost map will read present?

"Present" means a quote is in force at T: the latest record with `available_at <= T`, not
rejected, no older than `liquidity.max_quote_age_s`, two-sided and not crossed. Spread and
minimum-bid failures are liquidity (spec §4.9), not missing data: the cost map counts them.
No signal or return is computed here.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta

from qqq1dte.core.config import Phase1Config
from qqq1dte.execution_sim.selection import Quote, liquidity_failures

DATA_FAILURES = frozenset({"NO_QUOTE", "REJECTED_QUOTE", "STALE_QUOTE", "NOT_TWO_SIDED", "CROSSED"})
_MINUTE = timedelta(minutes=1)
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def minute_grid(start: datetime, end: datetime) -> list[datetime]:
    """Every minute from start to end, both included."""
    out: list[datetime] = []
    t = start
    while t <= end:
        out.append(t)
        t += _MINUTE
    return out


def quote_at(records: Sequence[Quote], t: datetime) -> Quote | None:
    """The latest record known at t (records sorted by available_at)."""
    i = bisect_right([r.available_at for r in records], t)
    return records[i - 1] if i else None


def data_present(quote: Quote | None, t: datetime, cfg: Phase1Config) -> bool:
    return not (set(liquidity_failures(quote, t, cfg)) & DATA_FAILURES)


def held_coverage(
    records: Sequence[Quote], start: datetime, end: datetime, cfg: Phase1Config
) -> float:
    """Share of the minutes start..end at which the contract has a present quote."""
    grid = minute_grid(start, end)
    if not grid:
        return 0.0
    times = [r.available_at for r in records]
    hits = 0
    for t in grid:
        i = bisect_right(times, t)
        if data_present(records[i - 1] if i else None, t, cfg):
            hits += 1
    return hits / len(grid)


def bar_coverage(present: Iterable[datetime], open_: datetime, close: datetime) -> float:
    """Share of the session's minute bars (open .. close - 1 minute) that are present."""
    expected = set(minute_grid(open_, close - _MINUTE))
    return len(expected & set(present)) / len(expected) if expected else 0.0


def dev_partitions(names: Iterable[str], dev_end: date) -> list[str]:
    """File or partition names dated on or before dev_end; undated names are left out.
    Used so that no holdout file is ever opened."""
    out = []
    for n in names:
        m = _DATE.search(n)
        if m and date.fromisoformat(m.group(1)) <= dev_end:
            out.append(n)
    return out


def ticker_config(cfg: Phase1Config, ticker: str) -> Phase1Config:
    """The cleaning settings for one ADR-0021 ticker. QQQ keeps its config unchanged. Any other
    ticker follows the M23 precedent (scripts/m23_build_data.py): its own option root, and none
    of QQQ's ADR-backed exceptions (the ADR-0005 strike adjustment and ADR-0006 excluded sessions
    are QQQ-only). Every other rule, the $0.50 strike grid included, is unchanged."""
    if ticker == cfg.dq.option_root:
        return cfg
    dq = cfg.dq.model_copy(update={"option_root": ticker, "strike_adjustments": []})
    hist = cfg.history.model_copy(update={"excluded_sessions": []})
    return cfg.model_copy(update={"dq": dq, "history": hist})
