"""T-TIME-01…08: timestamps, timezones, calendar, schedule, 1DTE (docs/TEST_PLAN.md)."""

from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import ET, NaiveDatetimeError, bar_available_at, ensure_utc, to_et

CFG = load_config()
CAL = TradingCalendar(CFG)


# T-TIME-01 -------------------------------------------------------------------------
def test_time_01_naive_rejected() -> None:
    with pytest.raises(NaiveDatetimeError):
        ensure_utc(datetime(2025, 3, 10, 9, 30))  # noqa: DTZ001


def test_time_01_aware_converted_to_utc() -> None:
    t = ensure_utc(datetime(2025, 3, 10, 9, 30, tzinfo=ET))
    assert t.tzinfo == UTC
    assert t == datetime(2025, 3, 10, 13, 30, tzinfo=UTC)
    assert to_et(t) == datetime(2025, 3, 10, 9, 30, tzinfo=ET)


# T-TIME-02 -------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("d", "open_utc_hour"),
    [
        (date(2025, 3, 7), 14),  # EST, Friday before spring-forward
        (date(2025, 3, 10), 13),  # EDT, first session after spring-forward
        (date(2024, 11, 1), 13),  # EDT, Friday before fall-back
        (date(2024, 11, 4), 14),  # EST, first session after fall-back
    ],
)
def test_time_02_open_in_utc_across_dst(d: date, open_utc_hour: int) -> None:
    open_, close = CAL.open_close(d)
    assert open_ == datetime(d.year, d.month, d.day, open_utc_hour, 30, tzinfo=UTC)
    assert (close - open_) == timedelta(minutes=390)


# T-TIME-03 -------------------------------------------------------------------------
@pytest.mark.parametrize("d", [date(2023, 11, 24), date(2024, 7, 3)])
def test_time_03_early_close(d: date) -> None:
    open_, close = CAL.open_close(d)
    assert CAL.is_early_close(d)
    assert to_et(close).time() == time(13, 0)
    assert (close - open_) == timedelta(minutes=210)
    stamps = CAL.prediction_timestamps(d)
    assert to_et(stamps[0]).time() == time(9, 45)
    assert to_et(stamps[-1]).time() == time(12, 0)  # close - 60 min
    assert to_et(CAL.forced_exit_time(d)).time() == time(12, 50)  # close - 10 min


# T-TIME-04 -------------------------------------------------------------------------
def test_time_04_holiday_has_no_session_or_timestamps() -> None:
    good_friday = date(2023, 4, 7)
    assert not CAL.is_session(good_friday)
    assert CAL.prediction_timestamps(good_friday) == []


# T-TIME-05 -------------------------------------------------------------------------
def test_time_05_normal_day_schedule() -> None:
    d = date(2025, 3, 10)
    stamps = CAL.prediction_timestamps(d)
    assert len(stamps) == 64
    assert to_et(stamps[0]).time() == time(9, 45)
    assert to_et(stamps[-1]).time() == time(15, 0)
    assert all(b - a == timedelta(minutes=5) for a, b in pairwise(stamps))
    assert to_et(CAL.forced_exit_time(d)).time() == time(15, 50)


SESSIONS = CAL.sessions(date(2023, 3, 28), date(2026, 10, 2))


@settings(max_examples=100, deadline=None)
@given(st.sampled_from(SESSIONS))
def test_time_05_schedule_properties(d: date) -> None:
    open_, close = CAL.open_close(d)
    stamps = CAL.prediction_timestamps(d)
    assert stamps, d
    for t in stamps:
        assert t.tzinfo == UTC
        assert open_ <= t < close
        assert to_et(t).minute % 5 == 0 and t.second == 0 and t.microsecond == 0
    if not CAL.is_early_close(d):
        assert len(stamps) == 64


# T-TIME-06 -------------------------------------------------------------------------
def test_time_06_bar_convention() -> None:
    label = datetime(2025, 3, 10, 14, 0, tzinfo=UTC)
    one_min = timedelta(minutes=1)
    assert bar_available_at(label, "start", one_min) == label + one_min
    assert bar_available_at(label, "end", one_min) == label
    with pytest.raises(ValueError, match="convention"):
        bar_available_at(label, "middle", one_min)  # type: ignore[arg-type]


# T-TIME-07 -------------------------------------------------------------------------
def test_time_07_friday_resolves_to_monday() -> None:
    fri, mon = date(2023, 3, 10), date(2023, 3, 13)
    assert CAL.next_session(fri) == mon
    assert CAL.resolve_1dte(fri, {mon, date(2023, 3, 17)}) == mon


def test_time_07_before_good_friday_resolves_to_monday() -> None:
    thu, mon = date(2023, 4, 6), date(2023, 4, 10)
    assert CAL.next_session(thu) == mon
    assert CAL.resolve_1dte(thu, {mon}) == mon


def test_time_07_unlisted_next_session_expiry_is_none() -> None:
    wed = date(2025, 3, 12)
    assert CAL.resolve_1dte(wed, {date(2025, 3, 14)}) is None  # Thursday not listed


# T-TIME-08 -------------------------------------------------------------------------
def test_time_08_research_window_start_from_config() -> None:
    assert CFG.history.option_era_start == date(2023, 3, 28)
    assert not CAL.in_research_window(date(2023, 3, 27))
    assert CAL.in_research_window(date(2023, 3, 28))
