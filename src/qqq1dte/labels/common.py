"""Shared label types and the label window (spec §3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config

INVALID = "INVALID"
UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class LabelRow:
    label_id: str  # A_up, A_dn, B_up, B_dn, D_call, D_put, C_call, C_put
    variant: str  # e.g. "m=0.0025"; "" when the label has a single variant
    value: int | None  # 1 / 0; None for INVALID / UNRESOLVED
    outcome_class: str
    t_end: datetime
    reason: str | None = None
    ambiguous_bar: bool = False
    flags: tuple[str, ...] = field(default_factory=tuple)


def label_t_end(t: datetime, session: date, cal: TradingCalendar, cfg: Phase1Config) -> datetime:
    """T_end = min(T + H, forced flat time) (spec §3, §2)."""
    return min(t + timedelta(minutes=cfg.labels.horizon_minutes), cal.forced_exit_time(session))
