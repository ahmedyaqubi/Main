"""M25 (ADR-0016 D2, amendment A1): data-quality checks on the Tiingo ETF series, development
period only (data_start -> dev_end; the holdout lock applies). Downloads Shiller's free S&P 500
monthly data (Yale `ie_data.xls`) once, stored unchanged with its source URL.

Checks (thresholds fixed in A1 before any data was examined; any failure = STOP):
  (a) completeness vs the XNYS calendar
  (b) adjustment consistency (dividend days within 0.05 pp; no unexplained ratio changes)
  (c) jumps over 15% listed; unexplained ones fail (splits are explained)
  (d) dividends per full year: SPY/QQQ 4, TLT 12-13, GLD 0
  (e) SPY vs Shiller: P / (10 x SPY monthly-average close) within +-1% of its median every month;
      SPY trailing-12-month dividends x 10 within +-10% of Shiller D

    uv run python scripts/m25_verify_data.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import exchange_calendars as xcals
import pandas as pd
import polars as pl
import requests

from qqq1dte.core.config import load_config
from qqq1dte.ingestion.etf_data import dev_only, parse_tiingo
from qqq1dte.validation.etf_checks import (
    adjustment_violations,
    completeness,
    dividend_counts,
    jump_scan,
    shiller_violations,
)

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "research" / "m25_data_check.md"
SHILLER_URL = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
ADJ_TOL = 0.0005
JUMP = 0.15
SHILLER_TOL, DIV_TOL = 0.01, 0.10
EXPECTED_DIVS = {"SPY": {4}, "QQQ": {4}, "TLT": {12, 13}, "GLD": {0}}
# ADR-0016 exception E1 (decided after seeing the result, disclosed): exact (ticker, year, count)
# confirmed against official records. Any other off-pattern year still fails.
EXPLAINED_DIVS = {
    ("QQQ", 2005, 2): "SEC N-30B-2 FY2005 $0.41 and FY2006 $0.18 per share match Tiingo",
    ("QQQ", 2014, 5): "Nasdaq record: extra payment $0.37313, ex-date 2014-02-27",
}


def shiller_monthly(path: Path) -> pl.DataFrame:
    raw = pd.read_excel(path, sheet_name="Data", header=7)
    raw = raw[pd.to_numeric(raw["Date"], errors="coerce").notna()]
    months = [f"{float(x):.2f}".replace(".", "-") for x in raw["Date"]]
    div = pd.to_numeric(raw["D"], errors="coerce").astype(float).to_list()
    return pl.DataFrame({"month": months, "P": raw["P"].astype(float).to_list(), "D": div})


def main() -> int:  # noqa: PLR0915 (linear report)
    s = load_config().study_etf_trend
    raw = ROOT / s.raw_dir
    shiller = raw / "shiller" / "ie_data.xls"
    if not shiller.exists():
        r = requests.get(SHILLER_URL, timeout=120)
        r.raise_for_status()
        shiller.parent.mkdir(parents=True, exist_ok=True)
        shiller.write_bytes(r.content)
        meta = {"source_url": SHILLER_URL, "fetched_at": datetime.now(UTC).isoformat(),
                "bytes": len(r.content)}  # fmt: skip
        shiller.with_suffix(".xls.meta.json").write_text(json.dumps(meta, indent=1), "utf-8")
    cal = xcals.get_calendar("XNYS", start="2004-01-01", end="2016-12-31")
    sessions = [
        ts.date()
        for ts in cal.sessions_in_range(pd.Timestamp(s.data_start), pd.Timestamp(s.dev_end))
    ]
    failures: list[str] = []
    explained: list[str] = []
    lines = [
        "# M25 data check: Tiingo ETF series (ADR-0016 D2, amendment A1)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m25_verify_data.py`. "
        f"Development period only, {s.data_start} → {s.dev_end}; the holdout was not read. "
        "Data quality only: no strategy computation.",
        "",
        "| ticker | rows | missing sessions | extra dates | adjustment violations | jumps > 15% "
        "(unexplained) | dividends per full year |",
        "|---|---|---|---|---|---|---|",
    ]
    frames = {}
    for t in s.tickers:
        rows = json.loads((raw / "tiingo" / f"{t}.json").read_text("utf-8"))
        df = dev_only(parse_tiingo(rows, t), s.dev_end)
        frames[t] = df
        missing, extra = completeness(df["date"].to_list(), sessions)
        adj = adjustment_violations(df, ADJ_TOL)
        jumps = jump_scan(df, JUMP)
        unexplained = [j for j in jumps if not j["split"]]
        divs = dividend_counts(df)
        full_years = {y: n for y, n in divs.items() if 2005 <= y <= 2015}  # noqa: PLR2004
        years_all = {y: full_years.get(y, 0) for y in range(2005, 2016)}
        off = {y: n for y, n in years_all.items() if n not in EXPECTED_DIVS[t]}
        bad_div = {y: n for y, n in off.items() if (t, y, n) not in EXPLAINED_DIVS}
        explained += [f"{t} {y}: {n} dividends ({EXPLAINED_DIVS[(t, y, n)]})"
                      for y, n in off.items() if (t, y, n) in EXPLAINED_DIVS]  # fmt: skip
        if missing or extra:
            failures.append(f"{t}: {len(missing)} missing / {len(extra)} extra dates")
        if adj:
            failures.append(f"{t}: {len(adj)} adjustment violations, first {adj[:3]}")
        if unexplained:
            failures.append(
                f"{t}: unexplained jumps {[(j['date'], round(j['move'], 3)) for j in unexplained]}"
            )
        if bad_div:
            failures.append(f"{t}: dividend counts off-pattern {bad_div}")
        lines.append(
            f"| {t} | {df.height:,} | {len(missing)} | {len(extra)} | {len(adj)} "
            f"| {len(jumps)} ({len(unexplained)}) | "
            + ", ".join(f"{y}: {n}" for y, n in years_all.items()) + " |"
        )  # fmt: skip
    # (e) SPY vs Shiller
    spy = frames["SPY"].with_columns(month=pl.col("date").dt.strftime("%Y-%m"))
    spy_avg = dict(spy.group_by("month").agg(pl.col("close").mean()).iter_rows())
    sh = shiller_monthly(shiller)
    months = sorted(m for m in spy_avg if "2005-01" <= m <= s.dev_end.strftime("%Y-%m"))
    p = dict(zip(sh["month"].to_list(), sh["P"].to_list(), strict=True))
    dd = dict(zip(sh["month"].to_list(), sh["D"].to_list(), strict=True))
    pv = shiller_violations(months, spy_avg, p, scale=10.0, tol=SHILLER_TOL)
    spy_div = spy.group_by("month").agg(pl.col("div_cash").sum()).sort("month")
    div_m = dict(spy_div.iter_rows())
    allm = sorted(div_m)
    dv = []
    for i, m in enumerate(allm):
        if i < 11 or m not in months or dd.get(m) is None:  # noqa: PLR2004
            continue
        t12 = sum(div_m[x] for x in allm[i - 11 : i + 1]) * 10
        if abs(t12 / dd[m] - 1) > DIV_TOL:
            dv.append((m, round(t12 / dd[m] - 1, 3)))
    if pv:
        failures.append(f"SPY vs Shiller price: {len(pv)} months outside ±1%, e.g. {pv[:5]}")
    if dv:
        failures.append(f"SPY vs Shiller dividends: {len(dv)} months outside ±10%, e.g. {dv[:5]}")
    note = ", with the explained exceptions below." if explained else "."
    lines += [
        "",
        f"(e) SPY vs Shiller S&P 500 (Yale `ie_data.xls`), {len(months)} months: "
        "price-ratio months "
        f"outside ±{SHILLER_TOL:.0%} of the median: **{len(pv)}**. Trailing-12-month dividend "
        f"months outside ±{DIV_TOL:.0%}: **{len(dv)}**.",
        "",
        f"## Verdict: **{'PASS' if not failures else 'STOP'}**",
        "",
        *([f"- {f}" for f in failures] or [f"- All A1 checks passed{note}"]),
        "",
        *(["Explained exceptions (ADR-0016 E1, decided after seeing the result, disclosed):", "",
           *[f"- {e}" for e in explained], ""] if explained else []),
        "Limit (A1): QQQ, TLT and GLD have internal checks only; SPY also has the independent "
        "Shiller check.",
        "",
    ]  # fmt: skip
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"verdict {'PASS' if not failures else 'STOP'}; wrote {REPORT.relative_to(ROOT)}")
    for f in failures:
        print(" -", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
