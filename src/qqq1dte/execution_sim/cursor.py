"""Quote cursor for one contract (T-BT-05). Records are released strictly in time order as the
shared simulation clock advances; the cursor never moves backward and never releases a record
stamped later than the clock."""

from __future__ import annotations

from datetime import datetime

import polars as pl

from qqq1dte.core.clock import SimClock
from qqq1dte.execution_sim.selection import Quote


class QuoteCursor:
    def __init__(self, records: pl.DataFrame, clock: SimClock) -> None:
        if records["symbol"].n_unique() > 1:
            raise ValueError("a cursor holds one symbol's records")
        ts = records["available_at"]
        if records.height > 1 and not ts.is_sorted():
            raise ValueError("records must be in available_at order")
        self._rows = [
            Quote(r["bid"], r["ask"], r["bid_sz"], r["ask_sz"], r["available_at"], r["rejected"])
            for r in records.iter_rows(named=True)
        ]
        self._clock = clock
        self._next = 0
        self.latest: Quote | None = None  # most recent released record (may be rejected)

    def advance_to(self, t: datetime) -> list[Quote]:
        """Move the clock to t; return the records released in (previous position, t]."""
        self._clock.advance_to(t)
        out: list[Quote] = []
        while self._next < len(self._rows) and self._rows[self._next].available_at <= t:
            out.append(self._rows[self._next])
            self._next += 1
        if out:
            self.latest = out[-1]
        return out
