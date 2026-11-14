"""ADR-0021 D5 / M28 step 4: data-presence checks on the quotes the cost map will read. Synthetic
cases with exactly known answers."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from qqq1dte.core.config import load_config
from qqq1dte.execution_sim.selection import Quote
from qqq1dte.validation.options_day_data import (
    bar_coverage,
    data_present,
    dev_partitions,
    held_coverage,
    minute_grid,
    quote_at,
    ticker_config,
)

CFG = load_config()
T0 = datetime(2024, 5, 1, 13, 35, tzinfo=UTC)  # 09:35 ET


def _q(
    minute: int,
    bid: float | None = 1.0,
    ask: float | None = 1.1,
    *,
    rejected: bool = False,
    seconds: int = 0,
) -> Quote:
    at = T0 + timedelta(minutes=minute, seconds=seconds)
    return Quote(bid, ask, 10, 10, at, rejected)


def test_minute_grid_is_inclusive_and_one_minute_apart() -> None:
    g = minute_grid(T0, T0 + timedelta(minutes=3))
    assert g == [T0 + timedelta(minutes=i) for i in range(4)]
    assert minute_grid(T0, T0) == [T0]
    assert minute_grid(T0, T0 - timedelta(minutes=1)) == []


def test_quote_at_takes_the_latest_record_known_at_t_never_a_later_one() -> None:
    recs = [_q(0), _q(1, 2.0, 2.1), _q(3, 3.0, 3.1)]
    assert quote_at(recs, T0 + timedelta(minutes=2)) == recs[1]
    assert quote_at(recs, T0 + timedelta(minutes=3)) == recs[2]
    assert quote_at(recs, T0 - timedelta(seconds=1)) is None


def test_data_present_ignores_liquidity_but_not_missing_stale_rejected_or_crossed() -> None:
    t = T0
    assert data_present(_q(0), t, CFG)
    # a wide spread and a low bid are liquidity failures, not missing data
    assert data_present(_q(0, 0.05, 0.90), t, CFG)
    assert not data_present(None, t, CFG)
    assert not data_present(_q(0, rejected=True), t, CFG)
    assert not data_present(_q(-2), t, CFG)  # 120 s old > max_quote_age_s 60
    assert data_present(_q(-1), t, CFG)  # exactly 60 s: still in force
    assert not data_present(_q(0, 0.0, 1.0), t, CFG)  # not two-sided
    assert not data_present(_q(0, 1.2, 1.1), t, CFG)  # crossed


def test_held_coverage_counts_minutes_with_a_present_quote() -> None:
    # quotes at minutes 0, 1, 2 and a rejected record at 3; window 0..4 (5 minutes)
    recs = [_q(0), _q(1), _q(2), _q(3, rejected=True)]
    # minutes 0, 1, 2 present; 3 rejected; 4: latest record (3) rejected -> absent
    assert held_coverage(recs, T0, T0 + timedelta(minutes=4), CFG) == pytest.approx(3 / 5)
    # a gap: last quote at minute 0 stays in force through minute 1 only (60 s)
    assert held_coverage([_q(0)], T0, T0 + timedelta(minutes=3), CFG) == pytest.approx(2 / 4)
    assert held_coverage([], T0, T0 + timedelta(minutes=1), CFG) == 0.0


def test_bar_coverage_against_the_expected_minutes() -> None:
    open_ = T0
    close = T0 + timedelta(minutes=10)  # expected minutes 0..9
    present = {T0 + timedelta(minutes=i) for i in (0, 1, 2, 3, 4, 5, 6, 7, 8)}
    assert bar_coverage(present, open_, close) == pytest.approx(0.9)
    # minutes outside the session do not count
    assert bar_coverage(present | {close, close + timedelta(minutes=1)}, open_, close) == (
        pytest.approx(0.9)
    )


def test_dev_partitions_never_return_a_holdout_date() -> None:
    names = ["date=2026-04-01", "date=2026-04-02", "date=2026-04-03", "date=2026-10-02"]
    assert dev_partitions(names, date(2026, 4, 2)) == ["date=2026-04-01", "date=2026-04-02"]
    files = ["2026-04-02.parquet", "2026-04-03.parquet", "notes.txt"]
    assert dev_partitions(files, date(2026, 4, 2)) == ["2026-04-02.parquet"]


def test_ticker_config_follows_the_m23_precedent_for_other_roots() -> None:
    q = ticker_config(CFG, "QQQ")
    assert q is CFG  # QQQ keeps its own ADR-backed settings unchanged
    s = ticker_config(CFG, "NVDA")
    assert s.dq.option_root == "NVDA"
    assert s.dq.strike_adjustments == []  # the ADR-0005 memo is QQQ-only
    assert s.history.excluded_sessions == []  # ADR-0006 exclusions are QQQ-only
    assert s.dq.strike_increment == CFG.dq.strike_increment
    assert CFG.dq.option_root == "QQQ"  # the base config is not modified
