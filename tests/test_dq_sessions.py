"""Session-level checks, gates 1-2, events and the DQ report (T-DQ-04, T-DQ-09)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl
import pytest

from dq_fixtures import (
    NS,
    D,
    concat_quotes,
    et_ns,
    raw_definitions,
    raw_quotes,
    rth_bars,
)
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.validation.events import open_critical, record_events, session_events
from qqq1dte.validation.gates import gate1, gate2
from qqq1dte.validation.records import (
    build_definitions,
    clean_bars,
    clean_option_quotes,
    clean_quotes,
)
from qqq1dte.validation.report import DatasetCounts, render_report, summarize_dataset
from qqq1dte.validation.sessions import (
    bar_coverage,
    chain_coverage,
    invalid_quote_rate,
    one_dte_presence,
)

CFG = load_config()
CAL = TradingCalendar(CFG)
NEXT = date(2025, 3, 11)


# T-DQ-04 ---------------------------------------------------------------------------------
def test_dq_04_missing_bars_counted_with_timestamps() -> None:
    cleaned = clean_bars(rth_bars(skip=(0, 100, 389)), CAL, CFG).cleaned
    cov = bar_coverage(cleaned, CAL, [D]).row(0, named=True)
    assert (cov["expected"], cov["received"]) == (390, 387)
    assert cov["coverage"] == pytest.approx(387 / 390)
    assert cov["missing"] == [
        datetime(2025, 3, 10, 13, 30, tzinfo=UTC),
        datetime(2025, 3, 10, 15, 10, tzinfo=UTC),
        datetime(2025, 3, 10, 19, 59, tzinfo=UTC),
    ]


def test_bar_coverage_uses_early_close_length_and_counts_absent_sessions() -> None:
    early = date(2024, 7, 3)
    cleaned = clean_bars(rth_bars(d=early, minutes=210), CAL, CFG).cleaned
    cov = bar_coverage(cleaned, CAL, [early, date(2024, 7, 5)])
    rows = {r["session_date"]: r for r in cov.to_dicts()}
    assert (rows[early]["expected"], rows[early]["received"]) == (210, 210)
    assert (rows[date(2024, 7, 5)]["expected"], rows[date(2024, 7, 5)]["received"]) == (390, 0)


def test_one_dte_presence() -> None:
    defs = build_definitions(raw_definitions([
        {"instrument_id": 1, "raw_symbol": "QQQ   250311C00480000",
         "expiration": NEXT, "strike": 480.0, "right": "C"},
        {"instrument_id": 2, "raw_symbol": "QQQ   250313C00480000",
         "expiration": date(2025, 3, 13), "strike": 480.0, "right": "C",
         "day": date(2025, 3, 11)},
    ]), CAL)  # fmt: skip
    got = {
        r["session_date"]: r["listed"] for r in one_dte_presence(defs, CAL, [D, NEXT]).to_dicts()
    }
    assert got == {D: True, NEXT: False}  # on 03-11 the 03-12 expiry is missing


# chain coverage ------------------------------------------------------------------------
def _chain_fixture(put_gap_minutes: tuple[int, ...] = (), crossed_call_minute: int | None = None):  # type: ignore[no-untyped-def]
    """Spot 480.40 all day; ATM call 481 / put 480 quoted every minute 09:31..16:00."""
    und = clean_quotes(
        raw_quotes(
            [(et_ns(D, 9, 31) + k * 60 * NS, et_ns(D, 9, 31) + k * 60 * NS, 480.39, 480.41)
             for k in range(390)],
            schema="bbo-1m", dataset="EQUS.MINI", instrument_id=13340, symbol="QQQ",
        ),
        CAL, CFG,
    ).cleaned  # fmt: skip
    defs = build_definitions(raw_definitions([
        {"instrument_id": 11, "raw_symbol": "QQQ   250311C00480000", "expiration": NEXT,
         "strike": 480.0, "right": "C"},
        {"instrument_id": 12, "raw_symbol": "QQQ   250311C00481000", "expiration": NEXT,
         "strike": 481.0, "right": "C"},
        {"instrument_id": 21, "raw_symbol": "QQQ   250311P00480000", "expiration": NEXT,
         "strike": 480.0, "right": "P"},
        {"instrument_id": 22, "raw_symbol": "QQQ   250311P00481000", "expiration": NEXT,
         "strike": 481.0, "right": "P"},
    ]), CAL)  # fmt: skip
    t0 = et_ns(D, 9, 31)
    call_rows = []
    for k in range(390):
        t = t0 + k * 60 * NS
        bid, ask = (1.10, 1.00) if k == crossed_call_minute else (1.00, 1.02)
        call_rows.append((t, t, bid, ask))
    put_rows = [(t0 + k * 60 * NS, t0 + k * 60 * NS, 1.30, 1.32)
                for k in range(390) if k not in put_gap_minutes]  # fmt: skip
    raw = concat_quotes(
        raw_quotes(call_rows, instrument_id=12, symbol="QQQ   250311C00481000"),
        raw_quotes(put_rows, instrument_id=21, symbol="QQQ   250311P00480000"),
    )
    res = clean_option_quotes(raw, defs, CAL, CFG)
    return und, defs, res


def test_chain_coverage_full_day() -> None:
    und, defs, res = _chain_fixture()
    cov = chain_coverage(res.cleaned, res.rejected, und, defs, CAL, CFG, [D]).row(0, named=True)
    assert (cov["n_timestamps"], cov["n_valid"]) == (64, 64)


def test_chain_coverage_stale_and_rejected_quotes_are_invalid() -> None:
    # Put missing for 09:59..10:01 (minutes 28..30 after 09:31): at 10:00 the latest put quote is
    # 09:58, 2 minutes old -> stale. A crossed call at 10:30 (minute 59) must not fall back to the
    # 10:29 quote, even though it would be within 60 s.
    und, defs, res = _chain_fixture(put_gap_minutes=(28, 29, 30), crossed_call_minute=59)
    cov = chain_coverage(res.cleaned, res.rejected, und, defs, CAL, CFG, [D]).row(0, named=True)
    assert cov["n_valid"] == 62
    assert (cov["put_invalid"], cov["call_invalid"]) == (1, 1)


def test_invalid_quote_rate_atm_population() -> None:
    und, _defs, res = _chain_fixture(crossed_call_minute=59)
    rate = invalid_quote_rate(res.cleaned, res.rejected, und, CAL, CFG, [D]).row(0, named=True)
    # RTH stamps 09:31..16:00 = 390 per contract, 2 contracts in ATM +- 5, 1 rejected
    assert (rate["n_total"], rate["n_rejected"]) == (780, 1)
    assert rate["rate"] == pytest.approx(1 / 780)


# gates -----------------------------------------------------------------------------------
def test_gate1_pass_and_fail() -> None:
    bars = pl.DataFrame({"session_date": [D, NEXT], "coverage": [1.0, 0.99]})
    chain = pl.DataFrame({"session_date": [D, NEXT], "share": [1.0, 0.96]})
    assert gate1(bars, chain, CFG).passed
    bars_bad = pl.DataFrame({"session_date": [D, NEXT], "coverage": [1.0, 0.97]})
    g = gate1(bars_bad, chain, CFG)
    assert not g.passed
    assert g.numbers["sessions_below_bar_coverage"] == 1


def test_gate2_requires_no_open_critical_and_low_invalid_rate() -> None:
    assert gate2(open_critical_events=0, invalid_rate=0.019, cfg=CFG).passed
    assert not gate2(open_critical_events=1, invalid_rate=0.0, cfg=CFG).passed
    assert not gate2(open_critical_events=0, invalid_rate=0.021, cfg=CFG).passed


# events ----------------------------------------------------------------------------------
def test_events_aggregate_per_check_contract_session() -> None:
    _, _, res = _chain_fixture(crossed_call_minute=59)
    ev = record_events(res.cleaned, res.rejected, instrument="QQQ options")
    rej = [e for e in ev if e.check_name == "BID_GT_ASK"]
    assert len(rej) == 1
    assert (rej[0].count, rej[0].contract, rej[0].session_date) == (1, "QQQ   250311C00481000", D)
    assert rej[0].action == "REJECTED"


def test_session_events_critical_and_open_count() -> None:
    bars = pl.DataFrame({"session_date": [D], "expected": [390], "received": [380],
                         "coverage": [380 / 390],
                         "missing": [[datetime(2025, 3, 10, 14, 0, tzinfo=UTC)]]})  # fmt: skip
    one = pl.DataFrame({"session_date": [D], "next_session": [NEXT], "listed": [False]})
    chain = pl.DataFrame({"session_date": [D], "n_timestamps": [64], "n_valid": [60],
                          "share": [60 / 64]})  # fmt: skip
    ev = session_events(bars, one, chain, None, CFG)
    names = sorted(e.check_name for e in ev)
    assert names == ["BAR_COVERAGE_LOW", "CHAIN_COVERAGE_LOW", "MISSING_BAR", "NO_1DTE_EXPIRY"]
    assert open_critical(ev, resolved=set()) == 3
    assert open_critical(ev, resolved={("NO_1DTE_EXPIRY", D)}) == 2


# T-DQ-09 ---------------------------------------------------------------------------------
def test_dq_09_report_numbers_match_hand_counts() -> None:
    raw = raw_quotes(
        [
            (et_ns(D, 10, 0), et_ns(D, 10, 0), 1.0, 1.02),
            (et_ns(D, 10, 0), et_ns(D, 10, 0), 1.0, 1.02),  # exact duplicate
            (et_ns(D, 10, 1), et_ns(D, 10, 1), 1.05, 1.0),  # crossed
            (et_ns(D, 10, 2), et_ns(D, 10, 2), None, 1.0),  # no bid (flagged)
            (et_ns(D, 20, 0), et_ns(D, 20, 0), 1.0, 1.02),  # after close (flagged)
        ]
    )
    res = clean_quotes(raw, CAL, CFG)
    counts = summarize_dataset("test cbbo-1m", raw, res)
    assert counts == DatasetCounts(
        name="test cbbo-1m", raw=5, cleaned=3, rejected=2, flagged=2,
        rejected_by_reason={"BID_GT_ASK": 1, "DUP_EXACT": 1},
        flagged_by_flag={"NO_BID": 1, "OUTSIDE_RTH": 1},
        sessions=1, timestamp_errors=0,
    )  # fmt: skip
    md = render_report([counts], bar_cov=None, chain_cov=None, gates=[], title="t")
    assert "| test cbbo-1m | 5 | 3 | 2 | 2 |" in md
    assert "conservation OK" in md


def test_resolved_critical_from_config() -> None:
    from qqq1dte.validation.events import resolved_from_config  # noqa: PLC0415

    resolved = resolved_from_config(CFG)
    assert ("CHAIN_COVERAGE_LOW", date(2024, 2, 6)) in resolved
    assert ("CHAIN_COVERAGE_LOW", date(2023, 12, 27)) in resolved  # excluded session
    assert resolved[("CHAIN_COVERAGE_LOW", date(2024, 2, 6))] == "ADR-0006"
