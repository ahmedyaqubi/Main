"""Synthetic tests for the M2 sample-week checks (DATA_REQUIREMENTS.md §5)."""

import random
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from m2_checks import (
    Quote,
    bar_convention_by_alignment,
    bar_counts_by_session,
    infer_bar_convention,
    interval_quote_semantics,
    interval_quote_semantics_np,
    listing_lead_sessions,
    missing_one_dte_sessions,
    nbbo_agreement,
    quote_validity,
)

ET = ZoneInfo("America/New_York")


def et(d: date, hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=ET)


D = date(2025, 3, 10)  # Monday, first session after the 2025-03-09 DST change


# C2 -------------------------------------------------------------------------
def test_c2_start_labelled_bars() -> None:
    bars = [et(D, 9, 30) + timedelta(minutes=i) for i in range(390)]
    assert infer_bar_convention(bars) == "start"


def test_c2_end_labelled_bars() -> None:
    bars = [et(D, 9, 31) + timedelta(minutes=i) for i in range(390)]
    assert infer_bar_convention(bars) == "end"


def test_c2_ambiguous_bars_are_unknown() -> None:
    assert infer_bar_convention([et(D, 9, 45)]) == "unknown"


def test_c2_bar_counts_by_session_uses_et_date() -> None:
    # 390 bars stored in UTC must still count toward the ET session date.
    bars = [(et(D, 9, 30) + timedelta(minutes=i)).astimezone(UTC) for i in range(390)]
    bars.pop(100)
    assert bar_counts_by_session(bars) == {D: 389}


def test_c2_naive_timestamp_rejected() -> None:
    with pytest.raises(ValueError, match="naive"):
        bar_counts_by_session([datetime(2025, 3, 10, 9, 30)])  # noqa: DTZ001


# C3 -------------------------------------------------------------------------
def test_c3_bucket_equals_last_tick_at_or_before() -> None:
    ticks = [
        Quote(et(D, 10, 0, 10), 1.00, 1.02),
        Quote(et(D, 10, 0, 50), 1.01, 1.03),  # last tick <= 10:01:00
        Quote(et(D, 10, 1, 20), 1.05, 1.07),  # inside the following minute
    ]
    buckets = [Quote(et(D, 10, 1), 1.01, 1.03)]
    result = interval_quote_semantics(ticks, buckets, bucket=timedelta(minutes=1))
    assert result == {"at_or_before": 1, "within_next_bucket": 0, "ambiguous": 0, "neither": 0}


def test_c3_bucket_that_leaks_future_is_detected() -> None:
    ticks = [
        Quote(et(D, 10, 0, 50), 1.01, 1.03),
        Quote(et(D, 10, 1, 20), 1.05, 1.07),
    ]
    buckets = [Quote(et(D, 10, 1), 1.05, 1.07)]  # vendor used the quote from 10:01:20
    result = interval_quote_semantics(ticks, buckets, bucket=timedelta(minutes=1))
    assert result == {"at_or_before": 0, "within_next_bucket": 1, "ambiguous": 0, "neither": 0}


def test_c3_unchanged_quote_is_ambiguous() -> None:
    # No tick inside the next minute: both interpretations give the same quote.
    ticks = [Quote(et(D, 10, 0, 50), 1.01, 1.03)]
    buckets = [Quote(et(D, 10, 1), 1.01, 1.03)]
    result = interval_quote_semantics(ticks, buckets, bucket=timedelta(minutes=1))
    assert result == {"at_or_before": 0, "within_next_bucket": 0, "ambiguous": 1, "neither": 0}


# C4 / C5 ----------------------------------------------------------------------
SESSIONS = [date(2025, 3, d) for d in (10, 11, 12, 13, 14, 17)]


def test_c4_all_sessions_have_one_dte() -> None:
    listed = {s: {SESSIONS[i + 1]} for i, s in enumerate(SESSIONS[:-1])}
    assert missing_one_dte_sessions(SESSIONS[:-1], SESSIONS, listed) == []


def test_c4_missing_next_session_expiry_reported() -> None:
    listed = {s: {SESSIONS[i + 1]} for i, s in enumerate(SESSIONS[:-1])}
    listed[date(2025, 3, 12)] = {date(2025, 3, 14)}  # Thursday expiry absent on Wednesday
    assert missing_one_dte_sessions(SESSIONS[:-1], SESSIONS, listed) == [date(2025, 3, 12)]


def test_c5_listing_lead_sessions() -> None:
    # A Tuesday expiry first quoted Monday has a lead of 1 session; Friday->Monday also 1.
    assert listing_lead_sessions(date(2025, 3, 10), date(2025, 3, 11), SESSIONS) == 1
    assert listing_lead_sessions(date(2025, 3, 14), date(2025, 3, 17), SESSIONS) == 1
    assert listing_lead_sessions(date(2025, 3, 10), date(2025, 3, 14), SESSIONS) == 4


# C6 -------------------------------------------------------------------------
def test_c6_quote_validity_counts() -> None:
    t = et(D, 10, 0)
    quotes = [
        Quote(t, 1.00, 1.02),  # valid, spread 0.02
        Quote(t, 1.05, 1.00),  # crossed
        Quote(t, 0.00, 0.05),  # zero bid
        Quote(t, -1.0, 0.05),  # negative bid (also counted as nonpositive)
        Quote(t, 2.00, 2.10),  # valid, spread 0.10
    ]
    v = quote_validity(quotes)
    assert v.total == 5
    assert v.crossed == 1
    assert v.nonpositive == 2
    assert v.valid == 2
    assert v.spreads == pytest.approx([0.02, 0.10])


# C8 -------------------------------------------------------------------------
def test_c8_nbbo_agreement_share() -> None:
    t0 = et(D, 10, 0)
    a = {(t0, "X"): (1.00, 1.02), (t0, "Y"): (2.00, 2.05), (t0, "Z"): (3.0, 3.1)}
    b = {(t0, "X"): (1.00, 1.02), (t0, "Y"): (2.00, 2.06)}
    agreement = nbbo_agreement(a, b)
    assert agreement.common == 2
    assert agreement.identical == 1
    assert agreement.share == pytest.approx(0.5)


def test_c2_alignment_start_labelled() -> None:
    # Bar labelled t covers [t, t+1m); its close equals the quote mid at t+1m.
    t0 = et(D, 10, 0)
    mids = {t0 + timedelta(minutes=i): 100.0 + i for i in range(10)}
    closes = {t0 + timedelta(minutes=i): 100.0 + i + 1 for i in range(9)}
    err = bar_convention_by_alignment(closes, mids, bar=timedelta(minutes=1))
    assert err["start"] == pytest.approx(0.0)
    assert err["end"] == pytest.approx(1.0)


def test_c2_alignment_end_labelled() -> None:
    t0 = et(D, 10, 0)
    mids = {t0 + timedelta(minutes=i): 100.0 + i for i in range(10)}
    closes = {t0 + timedelta(minutes=i): 100.0 + i for i in range(1, 10)}
    err = bar_convention_by_alignment(closes, mids, bar=timedelta(minutes=1))
    assert err["end"] == pytest.approx(0.0)
    assert err["start"] == pytest.approx(1.0)


def test_c6_missing_side_counted_as_missing() -> None:
    t = et(D, 10, 0)
    v = quote_validity([Quote(t, float("nan"), 1.0), Quote(t, 1.0, float("nan")), Quote(t, 1, 1.1)])
    assert v.missing == 2
    assert v.valid == 1
    assert v.nonpositive == 0


# C3 vectorised version must agree exactly with the reference implementation -----------


@settings(max_examples=200, deadline=None)
@given(
    tick_secs=st.lists(st.integers(0, 600), min_size=1, max_size=60),
    bucket_mins=st.lists(st.integers(0, 10), min_size=1, max_size=10, unique=True),
    seed=st.integers(0, 10_000),
)
def test_c3_vectorised_matches_reference(
    tick_secs: list[int], bucket_mins: list[int], seed: int
) -> None:
    rng = random.Random(seed)
    t0 = et(D, 10, 0)
    tick_secs = sorted(tick_secs)
    ticks = [
        Quote(t0 + timedelta(seconds=s), float(rng.randint(1, 3)), float(rng.randint(4, 5)))
        for s in tick_secs
    ]
    buckets = [
        Quote(t0 + timedelta(minutes=m), float(rng.randint(1, 3)), float(rng.randint(4, 5)))
        for m in sorted(bucket_mins)
    ]
    ref = interval_quote_semantics(ticks, buckets, bucket=timedelta(minutes=1))
    ns = 1_000_000_000

    def arrays(
        qs: list[Quote],
    ) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        return (
            np.array([int(q.ts.timestamp()) * ns for q in qs], dtype=np.int64),
            np.array([q.bid for q in qs]),
            np.array([q.ask for q in qs]),
        )

    got = interval_quote_semantics_np(arrays(ticks), arrays(buckets), bucket_ns=60 * ns)
    assert got == ref
