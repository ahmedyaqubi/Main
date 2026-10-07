"""XNYS trading calendar, prediction schedule, forced-exit times and 1DTE resolution (spec §1-2)."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

import exchange_calendars as xcals
import pandas as pd

from qqq1dte.core.config import Phase1Config
from qqq1dte.core.timeutil import ET, ensure_utc

REGULAR_CLOSE_MINUTES = 390


class TradingCalendar:
    """Session logic for the configured exchange calendar (XNYS)."""

    def __init__(self, cfg: Phase1Config) -> None:
        self.cfg = cfg
        self._cal = xcals.get_calendar(cfg.session.calendar)

    # sessions ------------------------------------------------------------------------
    def is_session(self, d: date) -> bool:
        return bool(self._cal.is_session(pd.Timestamp(d)))

    def sessions(self, start: date, end: date) -> list[date]:
        return [
            ts.date() for ts in self._cal.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))
        ]

    def _require_session(self, d: date) -> None:
        if not self.is_session(d):
            raise ValueError(f"{d} is not a {self.cfg.session.calendar} session")

    def next_session(self, d: date) -> date:
        self._require_session(d)
        return self._cal.next_session(pd.Timestamp(d)).date()  # type: ignore[no-any-return]

    def open_close(self, d: date) -> tuple[datetime, datetime]:
        """Session open and close as UTC datetimes."""
        self._require_session(d)
        ts = pd.Timestamp(d)
        open_ = self._cal.session_open(ts).to_pydatetime()
        close = self._cal.session_close(ts).to_pydatetime()
        return ensure_utc(open_), ensure_utc(close)

    def is_early_close(self, d: date) -> bool:
        open_, close = self.open_close(d)
        return (close - open_) < timedelta(minutes=REGULAR_CLOSE_MINUTES)

    def exclusion_reason(self, d: date) -> str | None:
        """ADR-backed exclusion (history.excluded_sessions), or None."""
        for e in self.cfg.history.excluded_sessions:
            if e.date == d:
                return f"{e.adr}: {e.reason}"
        return None

    def in_research_window(self, d: date) -> bool:
        """Spec §1.3 / ADR-0003: on/after history.option_era_start and not ADR-excluded."""
        return d >= self.cfg.history.option_era_start and self.exclusion_reason(d) is None

    def final_holdout_start(self, last_session: date) -> date:
        """Spec §8: sessions strictly after this date (the last session minus
        validation.final_holdout_months calendar months, day clamped to month end) are the final
        holdout. It is locked until M19: nothing may be tuned or chosen by looking at it."""
        months = self.cfg.validation.final_holdout_months
        y, m = divmod(last_session.year * 12 + last_session.month - 1 - months, 12)
        m += 1
        last_day = calendar.monthrange(y, m)[1]
        return date(y, m, min(last_session.day, last_day))

    def research_sessions(self, start: date, end: date) -> list[date]:
        return [d for d in self.sessions(start, end) if self.in_research_window(d)]

    # schedule ------------------------------------------------------------------------
    def last_new_entry(self, d: date) -> datetime:
        _, close = self.open_close(d)
        if self.is_early_close(d):
            offset = self.cfg.schedule.early_close_last_entry_offset_min
            return close - timedelta(minutes=offset)
        local = datetime.combine(d, self.cfg.schedule.last_new_entry, tzinfo=ET)
        return ensure_utc(local)

    def forced_exit_time(self, d: date) -> datetime:
        _, close = self.open_close(d)
        if self.is_early_close(d):
            offset = self.cfg.trade.early_close_forced_exit_offset_min
            return close - timedelta(minutes=offset)
        return ensure_utc(datetime.combine(d, self.cfg.trade.forced_exit_time, tzinfo=ET))

    def prediction_timestamps(self, d: date) -> list[datetime]:
        """UTC prediction times for session d (spec §2); empty for non-sessions."""
        if not self.is_session(d):
            return []
        step = timedelta(minutes=self.cfg.schedule.cadence_minutes)
        t = ensure_utc(datetime.combine(d, self.cfg.schedule.first, tzinfo=ET))
        last = self.last_new_entry(d)
        out: list[datetime] = []
        while t <= last:
            out.append(t)
            t += step
        return out

    # 1DTE ----------------------------------------------------------------------------
    def resolve_1dte(self, d: date, listed_expirations: set[date]) -> date | None:
        """Spec §1.2: the expiration on the next session after d, if listed at T; else None.

        None means NO_1DTE_EXPIRY; the caller logs it. Listing must come from the
        point-in-time chain, never from the calendar alone.
        """
        nxt = self.next_session(d)
        return nxt if nxt in listed_expirations else None
