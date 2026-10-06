"""Record-level data-quality checks: T-DQ-01/02/03/05/06/07/08 and cleaned-layer PIT stamps."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from dq_fixtures import (
    INGESTED,
    NS,
    D,
    concat_quotes,
    et_ns,
    raw_bars,
    raw_definitions,
    raw_quotes,
    rth_bars,
)
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.validation.records import (
    build_definitions,
    clean_bars,
    clean_option_quotes,
    clean_quotes,
)

CFG = load_config()
CAL = TradingCalendar(CFG)
T10 = et_ns(D, 10, 0)
SYM = "QQQ   250311C00480000"


def reasons(rejected: pl.DataFrame) -> list[list[str]]:
    return rejected["dq_reasons"].to_list()


def defs_for(*rows: dict[str, object]) -> pl.DataFrame:
    return build_definitions(raw_definitions(list(rows)), CAL)  # type: ignore[arg-type]


STD_DEF = {"instrument_id": 1001, "raw_symbol": SYM, "expiration": date(2025, 3, 11),
           "strike": 480.0, "right": "C"}  # fmt: skip


# T-DQ-08 conservation (checked in every test via this helper) ------------------------
def assert_conserved(raw: pl.DataFrame, cleaned: pl.DataFrame, rejected: pl.DataFrame) -> None:
    assert cleaned.height + rejected.height == raw.height


# T-DQ-01 -------------------------------------------------------------------------------
def test_dq_01_crossed_quote_rejected_with_reason() -> None:
    raw = raw_quotes([(T10, T10, 1.05, 1.00), (T10 + 60 * NS, T10 + 60 * NS, 1.00, 1.02)])
    res = clean_quotes(raw, CAL, CFG)
    assert_conserved(raw, res.cleaned, res.rejected)
    assert reasons(res.rejected) == [["BID_GT_ASK"]]
    assert res.cleaned.height == 1


# T-DQ-02 (revised, owner decision 2: one-sided books flagged, not rejected) --------------
def test_dq_02_invalid_prices_rejected_one_sided_flagged() -> None:
    raw = raw_quotes(
        [
            (T10, T10, -0.01, 1.00),  # negative bid -> reject
            (T10 + 1 * NS, T10 + 1 * NS, 0.50, 0.0),  # ask 0 -> reject
            (T10 + 2 * NS, T10 + 2 * NS, None, 1.00),  # no bid -> flag
            (T10 + 3 * NS, T10 + 3 * NS, 1.00, None),  # no ask -> flag
            (T10 + 4 * NS, T10 + 4 * NS, None, None),  # empty book -> flag
            (T10 + 5 * NS, T10 + 5 * NS, 0.0, 0.05),  # zero bid -> flag
        ]
    )
    res = clean_quotes(raw, CAL, CFG)
    assert_conserved(raw, res.cleaned, res.rejected)
    assert sorted(r[0] for r in reasons(res.rejected)) == ["NONPOSITIVE_PRICE"] * 2
    flags = res.cleaned.sort("ts")["dq_flags"].to_list()
    assert flags == [["NO_BID"], ["NO_ASK"], ["EMPTY_BOOK"], ["ZERO_BID"]]
    assert res.cleaned["dq_status"].unique().to_list() == ["FLAGGED"]
    # undefined sides become null in the cleaned layer, never a number
    assert res.cleaned.sort("ts")["bid"].to_list()[:3] == [None, 1.0, None]


def test_dq_02_bar_nonpositive_or_inconsistent_rejected() -> None:
    t = et_ns(D, 10, 0)
    raw = raw_bars(
        [
            (t, 480.0, 480.2, 479.9, 480.1),  # ok
            (t + 60 * NS, 0.0, 480.2, 479.9, 480.1),  # open 0
            (t + 120 * NS, 480.0, None, 479.9, 480.1),  # high undefined
            (t + 180 * NS, 480.0, 479.0, 479.9, 480.1),  # high < close
        ]
    )
    res = clean_bars(raw, CAL, CFG)
    assert_conserved(raw, res.cleaned, res.rejected)
    assert reasons(res.rejected) == [["PRICE_NONPOSITIVE"], ["PRICE_NONPOSITIVE"],
                                     ["OHLC_INCONSISTENT"]]  # fmt: skip


# T-DQ-03 -------------------------------------------------------------------------------
def test_dq_03_duplicates_counted_never_silently_deduped() -> None:
    a = (T10, T10, 1.00, 1.02)
    b = (T10 + 60 * NS, T10 + 60 * NS, 1.01, 1.03)
    b_conflict = (T10 + 60 * NS, T10 + 60 * NS, 1.02, 1.03)
    raw = raw_quotes([a, a, a, b, b_conflict])
    res = clean_quotes(raw, CAL, CFG)
    assert_conserved(raw, res.cleaned, res.rejected)
    got = sorted(r[0] for r in reasons(res.rejected))
    assert got == ["DUP_CONFLICT", "DUP_CONFLICT", "DUP_EXACT", "DUP_EXACT"]
    assert res.cleaned.height == 1  # one copy of `a`; both conflicting `b` rows rejected


# T-DQ-05 -------------------------------------------------------------------------------
def test_dq_05_outside_rth_and_non_session_flagged_with_early_close() -> None:
    early = date(2024, 7, 3)  # 13:00 close
    holiday = date(2024, 7, 4)
    raw = raw_bars(
        [
            (et_ns(D, 9, 29), 480, 480.1, 479.9, 480),  # pre-open bar
            (et_ns(D, 9, 30), 480, 480.1, 479.9, 480),  # RTH
            (et_ns(D, 15, 59), 480, 480.1, 479.9, 480),  # last RTH bar
            (et_ns(D, 16, 0), 480, 480.1, 479.9, 480),  # post-close
            (et_ns(early, 12, 59), 480, 480.1, 479.9, 480),  # RTH on early close
            (et_ns(early, 13, 0), 480, 480.1, 479.9, 480),  # after early close
            (et_ns(holiday, 10, 0), 480, 480.1, 479.9, 480),  # holiday
        ]
    )
    res = clean_bars(raw, CAL, CFG)
    assert_conserved(raw, res.cleaned, res.rejected)
    got = res.cleaned["dq_flags"].to_list()  # cleaned rows keep input order
    assert got == [["OUTSIDE_RTH"], [], [], ["OUTSIDE_RTH"], [], ["OUTSIDE_RTH"], ["NON_SESSION"]]
    assert res.cleaned["is_rth"].to_list() == [False, True, True, False, True, False,
                                                          False]  # fmt: skip


# T-DQ-06 / T-DQ-07 ----------------------------------------------------------------------
UNDEF_MULT = 2147483647  # Databento OPRA definitions never fill the multiplier (ADR-0005)


def test_dq_06_invalid_contracts_rejected() -> None:
    defs = defs_for(
        STD_DEF,
        {"instrument_id": 1002, "raw_symbol": "QQQ   250311C00409330",
         "expiration": date(2025, 3, 11), "strike": 409.33, "right": "C"},
        {"instrument_id": 1003, "raw_symbol": "QQQ   250311C00481000",
         "expiration": date(2025, 3, 11), "strike": 481.0, "right": "C", "multiplier": 50},
        {"instrument_id": 1004, "raw_symbol": "QQQ   250312C00480000",
         "expiration": date(2025, 3, 11), "strike": 480.0, "right": "C"},
        {"instrument_id": 1005, "raw_symbol": "QQQ   250315C00480000",
         "expiration": date(2025, 3, 15), "strike": 480.0, "right": "C"},
        {"instrument_id": 1006, "raw_symbol": "QQQ1  250311C00480000",
         "expiration": date(2025, 3, 11), "strike": 480.0, "right": "C"},
    )  # fmt: skip
    q = [(T10, T10, 1.0, 1.02)]
    raw = concat_quotes(
        raw_quotes(q, instrument_id=1001, symbol=SYM),
        raw_quotes(q, instrument_id=1002, symbol="QQQ   250311C00409330"),
        raw_quotes(q, instrument_id=1003, symbol="QQQ   250311C00481000"),
        raw_quotes(q, instrument_id=1004, symbol="QQQ   250312C00480000"),
        raw_quotes(q, instrument_id=1005, symbol="QQQ   250315C00480000"),
        raw_quotes(q, instrument_id=1006, symbol="QQQ1  250311C00480000"),
        raw_quotes(q, instrument_id=9999, symbol="QQQ   250311C00999000"),
    )
    res = clean_option_quotes(raw, defs, CAL, CFG)
    assert_conserved(raw, res.cleaned, res.rejected)
    by_id = {r["instrument_id"]: r["dq_reasons"] for r in res.rejected.to_dicts()}
    assert by_id == {
        1002: ["NONSTANDARD_STRIKE"],  # off grid and not explained by any OCC adjustment
        1003: ["INVALID_MULTIPLIER"],  # a *known* multiplier other than 100
        1004: ["EXPIRATION_MISMATCH"],
        1005: ["EXPIRATION_NOT_SESSION"],  # 2025-03-15 is a Saturday
        1006: ["NONSTANDARD_ROOT"],  # adjusted-deliverable series get a new root
        9999: ["CONTRACT_UNKNOWN"],
    }
    kept = res.cleaned.row(0, named=True)
    assert (kept["raw_symbol"], kept["strike"], kept["right"], kept["expiration"]) == (
        SYM,
        480.0,
        "C",
        date(2025, 3, 11),
    )


def test_undefined_multiplier_kept_and_flagged() -> None:
    defs = defs_for({**STD_DEF, "multiplier": UNDEF_MULT})
    raw = raw_quotes([(T10, T10, 1.0, 1.02)], instrument_id=1001, symbol=SYM)
    res = clean_option_quotes(raw, defs, CAL, CFG)
    assert res.rejected.height == 0
    assert res.cleaned["dq_flags"].to_list() == [["MULTIPLIER_UNKNOWN"]]


def test_occ_adjusted_strike_accepted_only_on_or_after_ex_date() -> None:
    """OCC #53847: strikes reduced by 0.21584 (rounded) from 2023-12-27, symbol stays QQQ."""
    adj = {"instrument_id": 7, "raw_symbol": "QQQ   231229C00409780",
           "expiration": date(2023, 12, 29), "strike": 409.78, "right": "C"}  # fmt: skip
    before, after = date(2023, 12, 26), date(2023, 12, 28)
    defs = defs_for({**adj, "day": before}, {**adj, "day": after})
    raw = concat_quotes(
        raw_quotes([(et_ns(before, 10, 0), et_ns(before, 10, 0), 1.0, 1.02)], instrument_id=7,
                   symbol=adj["raw_symbol"]),  # type: ignore[arg-type]
        raw_quotes([(et_ns(after, 10, 0), et_ns(after, 10, 0), 1.0, 1.02)], instrument_id=7,
                   symbol=adj["raw_symbol"]),  # type: ignore[arg-type]
    )  # fmt: skip
    res = clean_option_quotes(raw, defs, CAL, CFG)
    assert_conserved(raw, res.cleaned, res.rejected)
    assert res.rejected["session_date"].to_list() == [before]
    assert reasons(res.rejected) == [["NONSTANDARD_STRIKE"]]
    assert res.cleaned["session_date"].to_list() == [after]
    assert res.cleaned["dq_flags"].to_list() == [["ADJUSTED_STRIKE"]]


def test_dq_07_quote_before_first_listing_rejected() -> None:
    # No 03-10 definition for the contract; it first appears in the 03-11 definitions.
    defs = defs_for({**STD_DEF, "day": date(2025, 3, 11)})
    raw = raw_quotes([(T10, T10, 1.0, 1.02)], instrument_id=1001, symbol=SYM)
    res = clean_option_quotes(raw, defs, CAL, CFG)
    assert_conserved(raw, res.cleaned, res.rejected)
    assert reasons(res.rejected) == [["NOT_YET_LISTED"]]


def test_symbol_mapping_disagreeing_with_definition_rejected() -> None:
    defs = defs_for({**STD_DEF, "raw_symbol": "QQQ   250311P00470000", "strike": 470.0,
                     "right": "P"})  # fmt: skip
    raw = raw_quotes([(T10, T10, 1.0, 1.02)], instrument_id=1001, symbol=SYM)
    res = clean_option_quotes(raw, defs, CAL, CFG)
    assert reasons(res.rejected) == [["SYMBOL_MISMATCH"]]


# timestamps / leakage --------------------------------------------------------------------
def test_ts_after_ingest_rejected_as_future_information() -> None:
    late = int((INGESTED + timedelta(seconds=1)).timestamp()) * NS
    raw = raw_quotes([(late, late, 1.0, 1.02)])
    res = clean_quotes(raw, CAL, CFG)
    assert reasons(res.rejected) == [["TS_AFTER_INGEST"]]


def test_event_after_receipt_rejected() -> None:
    raw = raw_quotes([(T10, T10 + 2 * NS, 1.0, 1.02), (T10 + 60 * NS, T10 + 60 * NS + NS, 1, 1.1)])
    res = clean_quotes(raw, CAL, CFG)
    assert reasons(res.rejected) == [["TS_EVENT_AFTER_RECV"]]  # 1 s skew allowed, 2 s not


def test_bar_available_at_is_label_plus_one_minute() -> None:
    res = clean_bars(rth_bars(minutes=2), CAL, CFG)
    row = res.cleaned.sort("ts").row(0, named=True)
    assert row["ts"] == datetime(2025, 3, 10, 13, 30, tzinfo=UTC)
    assert row["available_at"] == datetime(2025, 3, 10, 13, 31, tzinfo=UTC)
    assert row["close"] == pytest.approx(480.05)
    assert res.cleaned.schema["available_at"] == pl.Datetime("ns", "UTC")


def test_quote_available_at_is_ts_recv() -> None:
    res = clean_quotes(raw_quotes([(T10, T10 - NS, 1.0, 1.02)]), CAL, CFG)
    row = res.cleaned.row(0, named=True)
    assert row["available_at"] == row["ts"] == datetime(2025, 3, 10, 14, 0, tzinfo=UTC)
    assert (row["bid"], row["ask"]) == (pytest.approx(1.0), pytest.approx(1.02))


def test_session_date_uses_new_york_date() -> None:
    late_evening = et_ns(D, 20, 30)  # 00:30 UTC next day
    res = clean_bars(raw_bars([(late_evening, 480, 480.1, 479.9, 480)]), CAL, CFG)
    assert res.cleaned["session_date"].to_list() == [D]


def test_undefined_event_timestamp_kept_and_flagged() -> None:
    """Databento writes UNDEF_TIMESTAMP (2**64 - 1) as ts_event for interval records with no
    update in the interval (seen in QQQ bbo-1m, M4). A real state: keep it, flag it, and never
    treat it as an event after receipt."""
    undef_ts = 2**64 - 1
    raw = raw_quotes([(T10, undef_ts, 480.0, 480.02)], schema="bbo-1m", dataset="EQUS.MINI")
    res = clean_quotes(raw, CAL, CFG)
    assert_conserved(raw, res.cleaned, res.rejected)
    assert res.rejected.height == 0
    assert res.cleaned["dq_flags"].to_list() == [["NO_EVENT_TS"]]


def test_selection_chain_includes_adjusted_and_excludes_nonstandard() -> None:
    from qqq1dte.validation.records import standard_contract  # noqa: PLC0415

    after, exp = date(2023, 12, 28), date(2023, 12, 29)
    base = {"expiration": exp, "right": "C", "day": after}
    defs = defs_for(
        {**base, "instrument_id": 1, "raw_symbol": "QQQ   231229C00409780", "strike": 409.78,
         "multiplier": UNDEF_MULT},
        {**base, "instrument_id": 2, "raw_symbol": "QQQ   231229C00410000", "strike": 410.0,
         "multiplier": UNDEF_MULT},
        {**base, "instrument_id": 3, "raw_symbol": "QQQ1  231229C00410000", "strike": 410.0},
        {**base, "instrument_id": 4, "raw_symbol": "QQQ   231229C00409330", "strike": 409.33},
    )  # fmt: skip
    kept = sorted(defs.filter(standard_contract(CFG))["instrument_id"].to_list())
    assert kept == [1, 2]


def test_zero_bid_zero_ask_is_an_empty_market_flagged_not_rejected() -> None:
    """Real OPRA data shows 0/0 quotes (no market). Same treatment as an empty book (owner
    decision 2): flagged and kept. An ask of 0 with a positive bid is still rejected."""
    raw = raw_quotes([(T10, T10, 0.0, 0.0), (T10 + 60 * NS, T10 + 60 * NS, 0.05, 0.0)])
    res = clean_quotes(raw, CAL, CFG)
    assert_conserved(raw, res.cleaned, res.rejected)
    assert res.cleaned["dq_flags"].to_list() == [["ZERO_QUOTE"]]
    assert reasons(res.rejected) == [["NONPOSITIVE_PRICE", "BID_GT_ASK"]]
