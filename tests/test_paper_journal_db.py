"""M32 (ADR-0022 P6): the paper journal tables. PostgreSQL; skipped without TEST_DATABASE_URL."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from qqq1dte.journal.paper_store import (
    read_fills,
    read_signals,
    write_event,
    write_fill,
    write_signal,
)
from qqq1dte.monitoring.paper_review import FillRecord
from qqq1dte.strategies.pullback_live import Instruction

D0, D1 = date(2026, 11, 16), date(2026, 11, 17)
RUN = datetime(2026, 11, 16, 23, 30, tzinfo=UTC)
AVAIL = datetime(2026, 11, 16, 23, 10, tzinfo=UTC)


def _ins(action: str = "BUY", shares: int = 3) -> Instruction:
    return Instruction(
        data_date=D0,
        action=action,
        shares=shares,
        close=700.0,
        adj_close=700.0,
        rsi=5.0,
        sma_trend=650.0,
        sma_exit=710.0,
        entry_signal=action == "BUY",
        exit_signal=False,
        position_before=0,
        halted=False,
    )


def _write(engine: Engine, ins: Instruction, avail: datetime = AVAIL) -> None:
    with engine.begin() as c:
        write_signal(
            c,
            ins,
            next_session=D1,
            ticker="SPY",
            instruction="BUY 3 SPY market-on-open",
            run_at=RUN,
            available_at=avail,
            code_commit="abc",
            data_sha256="sha",
            config_hash="h",
        )


def test_signal_and_fill_round_trip(migrated_engine: Engine) -> None:
    _write(migrated_engine, _ins())
    f = FillRecord(D0, "FILLED", 701.0, 3, 1.0, datetime(2026, 11, 17, 14, 30, tzinfo=UTC), None)
    with migrated_engine.begin() as c:
        write_fill(c, f)
        write_event(c, "DATA_READ", D0, {"rows": 10})
    with migrated_engine.connect() as c:
        (s,) = read_signals(c)
        assert (s.data_date, s.next_session, s.action, s.shares) == (D0, D1, "BUY", 3)
        assert read_fills(c) == [f]


def test_available_at_after_run_is_refused(migrated_engine: Engine) -> None:
    with pytest.raises(DBAPIError):
        _write(migrated_engine, _ins(), avail=datetime(2026, 11, 16, 23, 31, tzinfo=UTC))


def test_available_at_before_the_close_is_refused(migrated_engine: Engine) -> None:
    with pytest.raises(DBAPIError):
        _write(migrated_engine, _ins(), avail=datetime(2026, 11, 16, 20, 59, tzinfo=UTC))


def test_one_signal_per_date_and_append_only(migrated_engine: Engine) -> None:
    _write(migrated_engine, _ins())
    with pytest.raises(DBAPIError):
        _write(migrated_engine, _ins())
    for sql in (
        "UPDATE paper_signals SET shares = 4",
        "DELETE FROM paper_signals",
        "TRUNCATE paper_signals",
    ):
        with pytest.raises(DBAPIError), migrated_engine.begin() as c:
            c.execute(text(sql))


def test_no_fill_for_a_no_action_evening(migrated_engine: Engine) -> None:
    _write(migrated_engine, _ins("NO_ACTION", 0))
    f = FillRecord(D0, "MISSED", None, None, None, None, "no order")
    with pytest.raises(DBAPIError), migrated_engine.begin() as c:
        write_fill(c, f)


def test_filled_row_needs_price_and_missed_row_needs_reason(migrated_engine: Engine) -> None:
    _write(migrated_engine, _ins())
    for f in (
        FillRecord(D0, "FILLED", None, 3, 1.0, RUN, None),
        FillRecord(D0, "MISSED", None, None, None, None, None),
    ):
        with pytest.raises(DBAPIError), migrated_engine.begin() as c:
            write_fill(c, f)
