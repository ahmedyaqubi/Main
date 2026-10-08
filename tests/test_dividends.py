"""ADR-0013 R5 / D1.d: QQQ regular ex-dividend dates follow the trust's published rule."""

from __future__ import annotations

from datetime import date

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.dividends import ex_dividend_dates, qqq_regular_ex_date

CAL = TradingCalendar(load_config())


def test_first_business_day_after_third_friday() -> None:
    assert qqq_regular_ex_date(2024, 3, CAL) == date(2024, 3, 18)  # 3rd Fri 03-15 -> Mon
    assert qqq_regular_ex_date(2025, 9, CAL) == date(2025, 9, 22)  # 3rd Fri 09-19 -> Mon


def test_skips_holidays() -> None:
    # 3rd Friday 2023-06-16; Monday 06-19 is Juneteenth (market closed) -> Tuesday 06-20
    assert qqq_regular_ex_date(2023, 6, CAL) == date(2023, 6, 20)


def test_only_quarter_end_months() -> None:
    try:
        qqq_regular_ex_date(2024, 4, CAL)
    except ValueError:
        return
    raise AssertionError("April is not a distribution month")


def test_reference_file_rows_known_before_use() -> None:
    rows = ex_dividend_dates()
    assert rows, "configs/reference/qqq_ex_dividends.csv is empty"
    for r in rows:
        assert r.known_from < r.ex_date
    special = [r for r in rows if r.kind == "special"]
    assert [(r.ex_date, r.known_from) for r in special] == [
        (date(2023, 12, 27), date(2023, 12, 26))
    ]
