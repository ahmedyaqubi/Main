"""M25 (ADR-0016 D2 amendment A1): ETF data-quality checks. Exact synthetic cases."""

from __future__ import annotations

from datetime import date

import polars as pl

from qqq1dte.validation.etf_checks import (
    adjustment_violations,
    completeness,
    dividend_counts,
    jump_scan,
    open_gaps,
    open_ratio_violations,
    shiller_violations,
)

D = [date(2005, 1, 3), date(2005, 1, 4), date(2005, 1, 5), date(2005, 1, 6)]


def frame(
    close: list[float], adj: list[float], div: list[float], split: list[float]
) -> pl.DataFrame:
    cols = {"close": close, "adj_close": adj, "div_cash": div, "split_factor": split}
    return pl.DataFrame({"date": D, **{k: [float(x) for x in v] for k, v in cols.items()}})


def test_completeness() -> None:
    missing, extra = completeness([D[0], D[2], date(2005, 1, 8)], D[:3])
    assert missing == [D[1]] and extra == [date(2005, 1, 8)]


def test_adjustment_consistency() -> None:
    # dividend 1.0 on day 3 with previous close 100: back-adjustment factor 0.99 before it
    ok = frame([100, 100, 99, 99], [99, 99, 99, 99], [0, 0, 1.0, 0], [1, 1, 1, 1])
    assert adjustment_violations(ok, tol=0.0005) == []
    # ratio changes on day 2 with no dividend or split -> violation
    bad = frame([100, 100, 99, 99], [99, 98, 99, 99], [0, 0, 1.0, 0], [1, 1, 1, 1])
    assert [v[0] for v in adjustment_violations(bad, tol=0.0005)] == [D[1], D[2]]
    # a split explains a ratio change
    split = frame([100, 50, 50, 50], [50, 50, 50, 50], [0, 0, 0, 0], [1, 2, 1, 1])
    assert adjustment_violations(split, tol=0.0005) == []


def test_jump_scan_flags_large_moves_and_splits() -> None:
    df = frame([100, 120, 60, 61], [1, 1, 1, 1], [0, 0, 0, 0], [1, 1, 2, 1])
    j = jump_scan(df, 0.15)
    assert [(r["date"], r["split"]) for r in j] == [(D[1], False), (D[2], True)]


def test_dividend_counts() -> None:
    df = pl.DataFrame({"date": [date(2005, 3, 18), date(2005, 6, 17), date(2006, 3, 17)],
                       "div_cash": [0.5, 0.5, 0.6]})  # fmt: skip
    assert dividend_counts(df) == {2005: 2, 2006: 1}


def test_shiller_ratio_and_dividends() -> None:
    months = ["2005-01", "2005-02", "2005-03"]
    spy_avg = {"2005-01": 120.0, "2005-02": 121.0, "2005-03": 119.0}
    shiller_p = {"2005-01": 1200.0, "2005-02": 1210.0, "2005-03": 1250.0}  # March is 5% off
    v = shiller_violations(months, spy_avg, shiller_p, scale=10.0, tol=0.01)
    assert [m for m, _ in v] == ["2005-03"]


def test_open_checks() -> None:
    df = pl.DataFrame({
        "date": D,
        "open": [100.0, 101.0, 80.0, 50.0], "close": [100.0, 100.0, 100.0, 100.0],
        "adj_open": [99.0, 99.99, 79.2, 60.0], "adj_close": [99.0, 99.0, 99.0, 99.0],
    })  # fmt: skip
    # ratios: day 4 adj_open/open = 1.2 vs adj_close/close = 0.99 -> violation
    assert [v[0] for v in open_ratio_violations(df, tol=0.0005)] == [D[3]]
    # gaps: day 3 opens at 80 after a close of 100 (-20%); day 4 at 50 (-50%)
    assert [g[0] for g in open_gaps(df, 0.15)] == [D[2], D[3]]
