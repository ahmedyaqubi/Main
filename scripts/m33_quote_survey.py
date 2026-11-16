"""M33 (ADR-0021 amendment A3, setup S3), for the plan: are the underlying quotes that S3 would
read present, and how wide are they?

Counts timestamps and measures bid-ask spreads only. No return, direction, boundary or signal is
computed, and no price level is reported. Development sessions only (study_options_day.dev_end);
early-close sessions are left out (S3 does not trade them and they are not history).

For each ticker and session, at 09:30, at the open plus `noise_area.open_offset_minutes`, at
every half-hour check and at the forced exit, it finds the latest cleaned record with
available_at <= that time and reports whether it is usable (at most max_quote_age_s old,
two-sided, not crossed) and its spread as a share of its mid.

    uv run python scripts/m33_quote_survey.py
"""

from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from m28_cost_map import M28_CLEAN, QQQ_CLEAN
from qqq1dte.backtesting.noise_area_screen import check_times
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import ET, ensure_utc
from qqq1dte.validation.options_day_data import ticker_config

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "research" / "m33_quote_survey.md"
TICKERS = ["QQQ", "SPY", "IWM", "NVDA", "TSLA"]
WIDE = 0.002  # spread / mid line counted in the report


def _at(d: date, t: time) -> datetime:
    return ensure_utc(datetime.combine(d, t, tzinfo=ET))


def survey(ticker: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cfg0 = load_config()
    s = cfg0.study_options_day
    na = s.noise_area
    cfg = ticker_config(cfg0, ticker)
    cal = TradingCalendar(cfg)
    f = (
        QQQ_CLEAN / "cleaned_market_data" / "bbo-1m" / "QQQ.parquet"
        if ticker == "QQQ"
        else M28_CLEAN / ticker / "underlying" / "cleaned.parquet"
    )
    u = (
        pl.scan_parquet(f)
        .filter(pl.col("session_date") <= s.dev_end[ticker])
        .select("session_date", "available_at", "bid", "ask")
        .collect()
        .sort("available_at")
        .with_columns(
            spread=(pl.col("ask") - pl.col("bid")) / ((pl.col("ask") + pl.col("bid")) / 2),
            two_sided=(pl.col("bid") > 0) & (pl.col("ask") > 0) & (pl.col("bid") <= pl.col("ask")),
            rec_at=pl.col("available_at"),
        )
    )
    assert u["session_date"].max() <= s.dev_end[ticker]  # type: ignore[operator]
    days = [d for d in sorted(u["session_date"].unique().to_list()) if not cal.is_early_close(d)]
    checks = check_times(na.first_check, na.last_exit_check, na.check_interval_minutes)
    open_offset = timedelta(minutes=na.open_offset_minutes)
    points: dict[str, dict[date, datetime]] = {
        "09:30 (the open itself)": {d: cal.open_close(d)[0] for d in days},
        "open as read": {d: cal.open_close(d)[0] + open_offset for d in days},
        **{f"check {t:%H:%M}": {d: _at(d, t) for d in days} for t in checks},
        f"exit {na.exit_time:%H:%M}": {d: _at(d, na.exit_time) for d in days},
    }
    out = []
    complete: set[date] = set(days)
    for name, when in points.items():
        want = pl.DataFrame(
            {"session_date": list(when), "t": list(when.values())},
            schema={"session_date": pl.Date, "t": u.schema["available_at"]},
        ).sort("t")
        j = want.join_asof(u.drop("session_date"), left_on="t", right_on="available_at")
        j = j.with_columns(age_s=(pl.col("t") - pl.col("rec_at")).dt.total_seconds())
        ok = j.filter(
            pl.col("age_s").is_not_null()
            & (pl.col("age_s") <= cfg.liquidity.max_quote_age_s)
            & pl.col("two_sided")
        )
        sp = ok["spread"]
        out.append({
            "ticker": ticker, "point": name, "sessions": j.height,
            "exact_stamp": j.filter(pl.col("age_s") == 0).height, "usable": ok.height,
            "median": sp.median(), "p99": sp.quantile(0.99), "max": sp.max(),
            "wide": ok.filter(pl.col("spread") > WIDE).height,
        })  # fmt: skip
        if name == "open as read" or name.startswith("check"):
            complete &= set(ok["session_date"].to_list())
    extra = {
        "ticker": ticker,
        "sessions": len(days),
        "complete": len(complete),
        "incomplete": sorted(str(d) for d in set(days) - complete),
    }
    return out, extra


def pc(x: float | None) -> str:
    return "-" if x is None else f"{x:.3%}"


def main() -> int:
    rows, extras = [], []
    for t in TICKERS:
        found, e = survey(t)
        rows += found
        extras.append(e)
        print(t, "done", flush=True)
    na = load_config().study_options_day.noise_area
    out = [
        "# M33: underlying quotes that S3 would read (survey for the plan; no signal)",
        "",
        f"Generated {datetime.now().astimezone():%Y-%m-%d %H:%M %Z} by "
        "`scripts/m33_quote_survey.py`. Development sessions only, early closes left out. "
        "Timestamps are counted and bid-ask spreads measured; no return, direction, boundary or "
        "price level is computed.",
        "",
        "For each time, the record read is the latest cleaned one with `available_at` at or "
        "before it. *usable* = at most 60 seconds old, two-sided, not crossed. Spread is a share "
        f'of the mid, over usable records. "open as read" is the open plus '
        f"{na.open_offset_minutes} minute(s) (`noise_area.open_offset_minutes`).",
        "",
        "| ticker | time | sessions | stamped exactly | usable | median | 99th | largest | "
        f"over {WIDE:.1%} |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        out.append(
            f"| {r['ticker']} | {r['point']} | {r['sessions']} | {r['exact_stamp']} | "
            f"{r['usable']} | {pc(r['median'])} | {pc(r['p99'])} | {pc(r['max'])} | {r['wide']} |"
        )
    out += ["", "## Sessions with every quote S3 needs as history", ""]
    for e in extras:
        out.append(
            f"- {e['ticker']}: {e['sessions']} sessions; a usable quote at the open as read and "
            f"at every check on {e['complete']}; not on: {', '.join(e['incomplete']) or 'none'}"
        )
    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
