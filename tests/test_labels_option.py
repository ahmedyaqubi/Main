"""Option-outcome labels C (spec §3, §4.6, §5, §6 conservative fills; M6 Q2/Q3): T-LBL-03 et al.

Fixture: D = 2025-03-11, T = 11:00 ET, T_e = 11:00:05, T_end = 12:30. QQQ mid 500.40 -> call
501, put 500 (D+1 = 2025-03-12). Entry quote (stamped 11:00) bid 1.00 / ask 1.02 -> entry 1.02;
target bid >= 1.326, stop bid <= 0.816; round-trip costs $1.40/contract; breakeven band
2% of $102 = $2.04.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import polars as pl
import pytest

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import ET
from qqq1dte.labels.option import option_label

CFG = load_config()
CAL = TradingCalendar(CFG)
D, NEXT = date(2025, 3, 11), date(2025, 3, 12)
CALL = "QQQ   250312C00501000"
DT = pl.Datetime("ns", "UTC")


def et(hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime.combine(D, time(hh, mm, ss), tzinfo=ET).astimezone(UTC)


T = et(11, 0)
T_END = et(12, 30)


def und() -> pl.DataFrame:
    rows = [{"available_at": et(9, 31) + timedelta(minutes=k), "bid": 500.39, "ask": 500.41}
            for k in range(390)]  # fmt: skip
    return pl.DataFrame(rows, schema={"available_at": DT, "bid": pl.Float64, "ask": pl.Float64})


def chain() -> pl.DataFrame:
    rows = [{"session_date": D, "raw_symbol": f"QQQ   250312{r}{k * 1000:08d}", "expiration": NEXT,
             "strike": float(k), "right": r, "available_at": et(6, 30)}
            for k in (499, 500, 501, 502) for r in "CP"]  # fmt: skip
    return pl.DataFrame(rows, schema={"session_date": pl.Date, "raw_symbol": pl.String,
                                      "expiration": pl.Date, "strike": pl.Float64,
                                      "right": pl.String, "available_at": DT})  # fmt: skip


def records(path: dict[datetime, tuple[float | None, float | None, bool]] | None = None,
            flat_bid: float = 1.00, end: datetime = T_END,
            entry: tuple[float, float] = (1.00, 1.02)) -> pl.DataFrame:  # fmt: skip
    """Call quotes every minute from 10:58 to `end`; path[ts] = (bid, ask, rejected)."""
    path = path or {}
    rows = []
    ts = et(10, 58)
    while ts <= end:
        if ts == T:
            bid, ask, rej = entry[0], entry[1], False
        else:
            bid, ask, rej = path.get(ts, (flat_bid, flat_bid + 0.02, False))
        rows.append({"symbol": CALL, "available_at": ts, "bid": bid, "ask": ask, "bid_sz": 10,
                     "ask_sz": 10, "rejected": rej})  # fmt: skip
        ts += timedelta(minutes=1)
    return pl.DataFrame(rows, schema={"symbol": pl.String, "available_at": DT, "bid": pl.Float64,
                                      "ask": pl.Float64, "bid_sz": pl.Int64, "ask_sz": pl.Int64,
                                      "rejected": pl.Boolean})  # fmt: skip


def label(recs: pl.DataFrame):  # type: ignore[no-untyped-def]
    return option_label("C", T, D, und(), chain(), recs, CAL, CFG)


def test_lbl_03_target_first_on_the_bid() -> None:
    row, oc = label(records({et(11, 20): (1.40, 1.45, False), et(11, 30): (0.50, 0.55, False)}))
    assert (row.label_id, row.value, row.outcome_class) == ("C_call", 1, "WIN")
    assert (oc.contract, oc.entry_price, oc.exit_price, oc.exit_ts) == (
        CALL,
        1.02,
        1.40,
        et(11, 20),
    )
    assert oc.net_pnl == pytest.approx((1.40 - 1.02) * 100 - 1.40)


def test_lbl_03_stop_first_on_the_bid() -> None:
    row, oc = label(records({et(11, 10): (0.80, 0.85, False), et(11, 20): (1.40, 1.45, False)}))
    assert (row.value, row.outcome_class, oc.exit_price) == (0, "LOSS", 0.80)


def test_mid_touching_target_does_not_trigger() -> None:
    # ask 1.40 puts the mid at 1.33 >= 1.326, but the bid (1.26) never reaches the target
    row, _ = label(records({et(11, 20): (1.26, 1.40, False)}))
    assert row.outcome_class != "WIN"


@pytest.mark.parametrize(
    ("flat", "cls"),
    [(1.10, "TIME_EXIT_PROFIT"), (0.95, "TIME_EXIT_LOSS"), (1.03, "BREAKEVEN")],  # cent prices
)
def test_time_exit_classes(flat: float, cls: str) -> None:
    row, oc = label(records(flat_bid=flat))
    assert (row.value, row.outcome_class) == (0, cls)
    assert oc.exit_ts == T_END and oc.exit_price == flat
    assert oc.net_pnl == pytest.approx((flat - 1.02) * 100 - 1.40)


def test_no_bid_counts_as_zero_and_stops() -> None:
    row, oc = label(records({et(11, 10): (None, 1.05, False)}))
    assert (row.outcome_class, oc.exit_price) == ("LOSS", 0.0)
    assert "NO_BID_AS_ZERO" in row.flags


def test_rejected_record_is_skipped_and_flagged() -> None:
    row, _ = label(records({et(11, 10): (0.10, 0.05, True), et(11, 20): (1.40, 1.45, False)}))
    assert row.outcome_class == "WIN"  # the rejected 0.10 bid never triggers the stop
    assert "PATH_GAP" in row.flags


def test_long_gap_is_unresolved() -> None:
    gap = {et(11, m): (None, None, True) for m in range(10, 17)}  # 7 minutes without a usable quote
    row, _ = label(records(gap))
    assert (row.value, row.outcome_class, row.reason) == (
        None,
        "UNRESOLVED_DATA",
        "PATH_GAP_TOO_LONG",
    )


def test_missing_exit_quote_is_unresolved() -> None:
    row, _ = label(records(end=et(12, 28)))  # newest quote 2 min old at T_end (> 60 s)
    assert (row.outcome_class, row.reason) == ("UNRESOLVED_DATA", "NO_EXIT_QUOTE")


def test_illiquid_selected_contract_is_invalid() -> None:
    row, oc = label(records(entry=(1.00, 1.40)))
    assert (row.value, row.outcome_class, row.reason) == (
        None,
        "INVALID",
        "SELECTED_CONTRACT_ILLIQUID",
    )
    assert "SPREAD_TOO_WIDE" in row.flags and oc.contract == CALL


def test_entry_uses_quote_in_force_at_t_e_only() -> None:
    recs = pl.concat(
        [
            records(),
            pl.DataFrame(
                [
                    {
                        "symbol": CALL,
                        "available_at": et(11, 0, 30),
                        "bid": 5.0,
                        "ask": 0.01,
                        "bid_sz": 1,
                        "ask_sz": 1,
                        "rejected": False,
                    }
                ],
                schema=records().schema,
            ),
        ]
    ).sort("available_at")
    _, oc = label(recs)
    assert oc.entry_price == 1.02  # the 11:00:30 quote is after T_e = 11:00:05


def test_label_ignores_everything_after_t_end() -> None:
    base_row, base_oc = label(records(flat_bid=1.10))
    after = records(flat_bid=1.10, end=et(15, 0)).with_columns(
        bid=pl.when(pl.col("available_at") > T_END).then(9.99).otherwise(pl.col("bid"))
    )
    row, oc = label(after)
    assert (row, oc) == (base_row, base_oc)


def test_put_side_selects_highest_strike_at_or_below_spot() -> None:
    put = "QQQ   250312P00500000"
    recs = records().with_columns(symbol=pl.lit(put))
    row, oc = option_label("P", T, D, und(), chain(), recs, CAL, CFG)
    assert (row.label_id, oc.contract) == ("C_put", put)


def test_outcome_schema_covers_every_field() -> None:
    import dataclasses  # noqa: PLC0415

    from qqq1dte.labels.option import OUTCOME_SCHEMA, OptionOutcome  # noqa: PLC0415

    assert [f.name for f in dataclasses.fields(OptionOutcome)] == list(OUTCOME_SCHEMA)
    # a frame whose first rows have reason None and a later row has a string must build
    _, ok = label(records(flat_bid=1.10))
    _, bad = label(records(entry=(1.00, 1.40)))
    rows = [dataclasses.asdict(ok)] * 150 + [dataclasses.asdict(bad)]
    df = pl.DataFrame(rows, schema=OUTCOME_SCHEMA)
    assert df["reason"].to_list()[-1] == "SELECTED_CONTRACT_ILLIQUID"
