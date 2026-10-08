"""QQQ ex-dividend dates (ADR-0013 D1.d / R5), point-in-time.

Regular dates follow the trust's published rule: "the first Business Day subsequent to the
third Friday in each of March, June, September and December" (QQQ Trust annual report, Form
N-30B-2). They are known in advance by rule. Special dividends are known from their declaration
date. The reference file (configs/reference/qqq_ex_dividends.csv) is built and cross-checked by
scripts/m19t_ex_dividends.py.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from qqq1dte.core.calendar import TradingCalendar

REFERENCE = Path(__file__).resolve().parents[3] / "configs" / "reference" / "qqq_ex_dividends.csv"
QUARTER_MONTHS = (3, 6, 9, 12)
FRIDAY = 4


@dataclass(frozen=True)
class ExDividend:
    ex_date: date
    kind: str  # "regular" | "special"
    amount: float
    known_from: date  # earliest date the ex-date is public (rule: prior quarter; special: declared)
    source: str


def qqq_regular_ex_date(year: int, month: int, cal: TradingCalendar) -> date:
    if month not in QUARTER_MONTHS:
        raise ValueError(f"QQQ pays regular dividends in {QUARTER_MONTHS}, not month {month}")
    first = date(year, month, 1)
    third_friday = first + timedelta(days=(FRIDAY - first.weekday()) % 7 + 14)
    d = third_friday + timedelta(days=1)
    while not cal.is_session(d):
        d += timedelta(days=1)
    return d


def ex_dividend_dates(path: Path = REFERENCE) -> list[ExDividend]:
    with path.open(encoding="utf-8") as f:
        return [
            ExDividend(
                ex_date=date.fromisoformat(r["ex_date"]),
                kind=r["kind"],
                amount=float(r["amount"]) if r["amount"] else float("nan"),  # nan: not yet paid
                known_from=date.fromisoformat(r["known_from"]),
                source=r["source"],
            )
            for r in csv.DictReader(f)
        ]
