"""Monotonic simulation clock (ARCHITECTURE §4, mechanism 3)."""

from __future__ import annotations

from datetime import datetime

from qqq1dte.core.timeutil import ensure_utc


class ClockError(RuntimeError):
    """An attempt to move the simulation clock backwards."""


class SimClock:
    def __init__(self, start: datetime) -> None:
        self._now = ensure_utc(start)

    @property
    def now(self) -> datetime:
        return self._now

    def advance_to(self, t: datetime) -> None:
        t = ensure_utc(t)
        if t < self._now:
            raise ClockError(
                f"clock cannot move backwards: {t.isoformat()} < {self._now.isoformat()}"
            )
        self._now = t
