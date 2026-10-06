"""Point-in-time gate (ARCHITECTURE §4, mechanism 1).

`AsOfReader` is the only data access object handed to features/, regimes/ and
execution_sim/. Every query is filtered to `available_at <= cutoff`, and any request reaching
past the cutoff raises `LookAheadError`: it is never silently clipped.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

import polars as pl

from qqq1dte.core.timeutil import ensure_utc

AVAILABLE_AT = "available_at"


class LookAheadError(RuntimeError):
    """A caller asked for information that was not available at the cutoff time."""


class AsOfReader:
    def __init__(self, tables: Mapping[str, pl.DataFrame], cutoff: datetime) -> None:
        self._cutoff = ensure_utc(cutoff)
        for name, df in tables.items():
            if AVAILABLE_AT not in df.columns:
                raise ValueError(f"table {name!r} has no {AVAILABLE_AT!r} column")
            dtype = df.schema[AVAILABLE_AT]
            if not isinstance(dtype, pl.Datetime) or dtype.time_zone != "UTC":
                raise ValueError(
                    f"table {name!r}: {AVAILABLE_AT} must be Datetime in UTC, got {dtype}"
                )
        # Pre-filter once: rows after the cutoff are unreachable through this object.
        self._tables = {
            name: df.filter(pl.col(AVAILABLE_AT) <= self._cutoff) for name, df in tables.items()
        }

    @property
    def cutoff(self) -> datetime:
        return self._cutoff

    def _check(self, t: datetime, what: str) -> datetime:
        t = ensure_utc(t)
        if t > self._cutoff:
            raise LookAheadError(
                f"{what} {t.isoformat()} is after cutoff {self._cutoff.isoformat()}"
            )
        return t

    def get(self, name: str) -> pl.DataFrame:
        """All rows of `name` available at or before the cutoff."""
        return self._tables[name]

    def window(self, name: str, start: datetime, end: datetime) -> pl.DataFrame:
        """Rows with start < available_at <= end; `end` must not exceed the cutoff."""
        end = self._check(end, "window end")
        start = ensure_utc(start)
        col = pl.col(AVAILABLE_AT)
        return self._tables[name].filter((col > start) & (col <= end))

    def latest(self, name: str, at: datetime | None = None) -> pl.DataFrame:
        """Row(s) with the greatest available_at <= `at` (default: the cutoff)."""
        at = self._check(at, "latest at") if at is not None else self._cutoff
        df = self._tables[name].filter(pl.col(AVAILABLE_AT) <= at)
        if df.is_empty():
            return df
        return df.filter(pl.col(AVAILABLE_AT) == df[AVAILABLE_AT].max())
