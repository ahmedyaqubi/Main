"""ADR-0013 R5: build configs/reference/qqq_ex_dividends.csv (2020-01 -> 2026-12).

Sources:
- Rule: the QQQ Trust's regular ex-dividend date is "the first Business Day subsequent to the
  third Friday in each of March, June, September and December" (Form N-30B-2, SEC EDGAR).
- History: Nasdaq dividend history (api.nasdaq.com), with ex-date, amount and declaration date.

Every regular ex-date in the history must equal the rule date. Any mismatch stops the script, and
nothing is guessed. Rows that are neither rule dates nor declared are refused. Free public data:
no market-data purchase.

    uv run python scripts/m19t_ex_dividends.py
"""

from __future__ import annotations

import csv
import json
import sys
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.dividends import QUARTER_MONTHS, REFERENCE, qqq_regular_ex_date

ROOT = Path(__file__).resolve().parents[1]
URL = "https://api.nasdaq.com/api/quote/QQQ/dividends?assetclass=etf"
RULE_SRC = (
    "rule: QQQ Trust N-30B-2 (sec.gov/Archives/edgar/data/0001067839/000119312518355790); "
    "dates: api.nasdaq.com QQQ dividend history"
)
SPAN = (2020, 2026)
RULE_LEAD_DAYS = 90  # rule dates are public far earlier; 90 days is a conservative floor


def fetch() -> list[dict[str, str]]:
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0", "Accept": "json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        rows: list[dict[str, str]] = json.load(r)["data"]["dividends"]["rows"]
    return rows


def us(d: str) -> date | None:
    if d in ("", "N/A"):
        return None
    m, dd, y = (int(x) for x in d.split("/"))
    return date(y, m, dd)


def main() -> int:
    cal = TradingCalendar(load_config())
    rule = {
        qqq_regular_ex_date(y, m, cal): (y, m)
        for y in range(SPAN[0], SPAN[1] + 1)
        for m in QUARTER_MONTHS
    }
    out, problems = [], []
    seen_rule = set()
    for r in fetch():
        ex = us(r["exOrEffDate"])
        if ex is None or not SPAN[0] <= ex.year <= SPAN[1]:
            continue
        amount = float(r["amount"].replace("$", ""))
        declared = us(r["declarationDate"])
        if ex in rule:
            seen_rule.add(ex)
            out.append((ex, "regular", amount, ex - timedelta(days=RULE_LEAD_DAYS), RULE_SRC))
        elif declared is not None and declared < ex:
            src = f"declared {declared}; api.nasdaq.com QQQ dividend history; OCC memo #53847"
            out.append((ex, "special", amount, declared, src))
        else:
            problems.append(f"{ex}: not a rule date and no prior declaration ({r})")
    missing = [d for d in rule if d not in seen_rule and d <= datetime.now(UTC).date()]
    if missing:
        problems.append(f"rule dates absent from the history: {sorted(missing)}")
    if problems:
        print("STOP, nothing written:\n" + "\n".join(problems))
        return 1
    future = [d for d in rule if d not in seen_rule]  # scheduled by rule, amount unknown
    for d in future:
        out.append((d, "regular", float("nan"), d - timedelta(days=RULE_LEAD_DAYS), RULE_SRC))
    REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    with REFERENCE.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ex_date", "kind", "amount", "known_from", "source"])
        for row in sorted(out):
            w.writerow([row[0], row[1], "" if row[2] != row[2] else row[2], row[3], row[4]])
    print(f"wrote {REFERENCE.relative_to(ROOT)}: {len(out)} rows ({len(future)} scheduled only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
