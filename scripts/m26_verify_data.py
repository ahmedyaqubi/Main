"""M26 (ADR-0017 D2): ADR-0016 A1 data checks (a)-(e), unchanged thresholds, on Tiingo SPY
1993-01-29 -> 2015-12-31 (development rows only; the holdout lock applies). Any failure = STOP.
Reuses the Shiller file downloaded by `m25_verify_data.py`.

    uv run python scripts/m26_verify_data.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import exchange_calendars as xcals
import pandas as pd
import polars as pl

from m25_verify_data import ADJ_TOL, DIV_TOL, JUMP, SHILLER_TOL, shiller_monthly
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
REPORT = ROOT / "reports" / "research" / "m26_data_check.md"
FIRST_FULL_YEAR = 1994
EXPECTED_DIVS = 4
# ADR-0017 exception E1 (decided after seeing the result, disclosed), from SPY's SEC annual
# reports (CIK 884394). Any other failure still stops the study.
EXPLAINED_DIV_YEARS = {2004: 5}  # N-30D 2005-12-01: special dividend (Microsoft), ex 2004-11-15
FEE_ERA_END, FEE_GAP_FLOOR = "2000-12", -0.15  # SPY below Shiller by its fee share (7-14%)
SPECIAL = ("2004-11", "2005-10")  # trailing 12 months containing the special dividend


def explained_gap(month: str, gap: float) -> bool:
    if month <= FEE_ERA_END:
        return FEE_GAP_FLOOR <= gap < 0
    return SPECIAL[0] <= month <= SPECIAL[1] and gap > 0


def main() -> int:  # noqa: PLR0915 (linear report)
    cfg = load_config()
    s = cfg.study_tom
    shiller = ROOT / cfg.study_etf_trend.raw_dir / "shiller" / "ie_data.xls"
    if not shiller.exists():
        print(f"{shiller} missing: run scripts/m25_verify_data.py first")
        return 1
    cal = xcals.get_calendar("XNYS", start="1993-01-01", end="2016-12-31")
    sessions = [
        ts.date()
        for ts in cal.sessions_in_range(pd.Timestamp(s.data_start), pd.Timestamp(s.dev_end))
    ]
    rows = json.loads((ROOT / s.raw_dir / "tiingo" / f"{s.ticker}.json").read_text("utf-8"))
    df = dev_only(parse_tiingo(rows, s.ticker), s.dev_end)
    failures: list[str] = []
    missing, extra = completeness(df["date"].to_list(), sessions)
    adj = adjustment_violations(df, ADJ_TOL)
    jumps = jump_scan(df, JUMP)
    unexplained = [j for j in jumps if not j["split"]]
    divs = dividend_counts(df)
    years = {y: divs.get(y, 0) for y in range(FIRST_FULL_YEAR, s.dev_end.year + 1)}
    off = {y: n for y, n in years.items() if n != EXPECTED_DIVS}
    bad_div = {y: n for y, n in off.items() if EXPLAINED_DIV_YEARS.get(y) != n}
    explained = [f"{y}: {n} dividends (special dividend, ex 2004-11-15; SPY N-30D filed "
                 "2005-12-01)" for y, n in off.items() if y not in bad_div]  # fmt: skip
    if missing or extra:
        failures.append(f"{len(missing)} missing {missing[:5]} / {len(extra)} extra {extra[:5]}")
    if adj:
        failures.append(f"{len(adj)} adjustment violations, first {adj[:3]}")
    if unexplained:
        bad = [(j["date"], round(j["move"], 3)) for j in unexplained]
        failures.append(f"unexplained jumps {bad}")
    if bad_div:
        failures.append(f"dividend counts off-pattern {bad_div}")
    spy = df.with_columns(month=pl.col("date").dt.strftime("%Y-%m"))
    spy_avg = dict(spy.group_by("month").agg(pl.col("close").mean()).iter_rows())
    sh = shiller_monthly(shiller)
    first_full_month = "1993-02"  # January 1993 has one SPY session
    months = sorted(m for m in spy_avg if first_full_month <= m <= s.dev_end.strftime("%Y-%m"))
    p = dict(zip(sh["month"].to_list(), sh["P"].to_list(), strict=True))
    dd = dict(zip(sh["month"].to_list(), sh["D"].to_list(), strict=True))
    pv = shiller_violations(months, spy_avg, p, scale=10.0, tol=SHILLER_TOL)
    div_m = dict(spy.group_by("month").agg(pl.col("div_cash").sum()).sort("month").iter_rows())
    allm = sorted(div_m)
    dv = []
    for i, m in enumerate(allm):
        if i < 11 or m not in months or dd.get(m) is None:  # noqa: PLR2004
            continue
        t12 = sum(div_m[x] for x in allm[i - 11 : i + 1]) * 10
        if abs(t12 / dd[m] - 1) > DIV_TOL:
            dv.append((m, round(t12 / dd[m] - 1, 3)))
    if pv:
        failures.append(f"Shiller price: {len(pv)} months outside ±1%, e.g. {pv[:5]}")
    dv_ok = [(m, g) for m, g in dv if explained_gap(m, g)]
    dv_bad = [(m, g) for m, g in dv if not explained_gap(m, g)]
    if dv_ok:
        explained.append(
            f"Shiller dividends: {len(dv_ok)} months outside ±10% explained by SPY's fees "
            f"(1993-{FEE_ERA_END}, SPY below Shiller by 0-15%: "
            f"{sum(m <= FEE_ERA_END for m, _ in dv_ok)} months) or by the 2004 special dividend "
            f"in the trailing 12 months ({sum(m > FEE_ERA_END for m, _ in dv_ok)} months); "
            f"largest gaps {sorted(dv_ok, key=lambda x: abs(x[1]))[-3:]}"
        )
    if dv_bad:
        failures.append(f"Shiller dividends: {len(dv_bad)} months outside ±10%, e.g. {dv_bad[:5]}")
    ex_dates = set(df.filter(pl.col("div_cash") > 0)["date"].to_list())
    held = {d for i in range(1, len(sessions)) if sessions[i].month != sessions[i - 1].month
            for d in sessions[i - 1 : i + 3]}  # fmt: skip
    ex_in = sorted(ex_dates & held)
    verdict = "PASS" if not failures else "STOP"
    note = ", with the explained exceptions below." if explained else "."
    lines = [
        "# M26 data check: Tiingo SPY from 1993 (ADR-0017 D2; ADR-0016 A1 checks)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m26_verify_data.py`. "
        f"Development rows only, {s.data_start} → {s.dev_end}; the holdout was not read. Data "
        "quality only: no strategy computation.",
        "",
        "| rows | missing sessions | extra dates | adjustment violations | jumps > 15% "
        "(unexplained) | dividends per full year |",
        "|---|---|---|---|---|---|",
        f"| {df.height:,} | {len(missing)} | {len(extra)} | {len(adj)} | {len(jumps)} "
        f"({len(unexplained)}) | " + ", ".join(f"{y}: {n}" for y, n in years.items()) + " |",
        "",
        f"(e) SPY vs Shiller S&P 500 (Yale `ie_data.xls`), {len(months)} months from "
        f"{first_full_month}: price-ratio months outside ±{SHILLER_TOL:.0%} of the median: "
        f"**{len(pv)}**. Trailing-12-month dividend months outside ±{DIV_TOL:.0%}: **{len(dv)}**.",
        "",
        f"## Verdict: **{verdict}**",
        "",
        *([f"- {f}" for f in failures] or [f"- All checks passed{note}"]),
        "",
        *(["Explained exceptions (ADR-0017 E1, decided after seeing the result, disclosed):", "",
           *[f"- {e}" for e in explained], "",
           f"SPY ex-dividend dates inside a turn-of-month holding day (-1, +1, +2, +3): "
           f"**{len(ex_in)}** of {len(ex_dates)}{' ' + str(ex_in) if ex_in else ''}. Dividends "
           "inside a window would only enter through the adjusted close.", ""]
          if explained else []),
    ]  # fmt: skip
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"verdict {verdict}; wrote {REPORT.relative_to(ROOT)}")
    for f in failures:
        print(" -", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
