"""Timezone helpers. Storage is UTC; market logic is America/New_York (CLAUDE.md, Stack)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

BarConvention = Literal["start", "end"]


class NaiveDatetimeError(ValueError):
    """A timezone-naive datetime crossed a boundary that requires an aware one."""


def ensure_utc(ts: datetime) -> datetime:
    """Return `ts` converted to UTC; reject naive datetimes instead of guessing a zone."""
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise NaiveDatetimeError(f"naive datetime not allowed: {ts!r}")
    return ts.astimezone(UTC)


def to_et(ts: datetime) -> datetime:
    """Convert an aware datetime to America/New_York."""
    return ensure_utc(ts).astimezone(ET)


def bar_available_at(label: datetime, convention: BarConvention, interval: timedelta) -> datetime:
    """When a bar labelled `label` becomes knowable.

    A start-labelled bar covers [label, label + interval) and is complete at its end; an
    end-labelled bar is complete at its label. Databento OHLCV bars are start-labelled (M2, C2).
    """
    label = ensure_utc(label)
    if convention == "start":
        return label + interval
    if convention == "end":
        return label
    raise ValueError(f"unknown bar convention: {convention!r}")
