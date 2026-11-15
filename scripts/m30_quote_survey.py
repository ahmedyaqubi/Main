"""M30 (ADR-0021 D6, setup S2), before the plan is approved: are the underlying quotes that S2
would read present, and how wide are they?

Counts timestamps and measures bid-ask spreads only. No return, direction or signal is computed,
and no price level is reported. Development sessions only (study_options_day.dev_end).

For each ticker and each development session, at these times (the session's own close, one
and five minutes before it, 10:00, 15:30, 15:50) it finds the latest cleaned record with
available_at <= that time and reports its
age, whether it is a regular-hours record, and its spread as a share of its mid.

    uv run python scripts/m30_quote_survey.py
"""

from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from m28_cost_map import M28, M28_CLEAN, QQQ_REJECTED, load_ticker
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import ET, ensure_utc
from qqq1dte.validation.options_day_data import ticker_config

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "research" / "m30_quote_survey.md"
TICKERS = ["QQQ", "SPY", "IWM", "NVDA", "TSLA"]
WIDE = (0.0005, 0.001, 0.002)  # spread / mid lines counted in the report


def _at(d: date, t: time) -> datetime:
    return ensure_utc(datetime.combine(d, t, tzinfo=ET))


def survey(ticker: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cfg0 = load_config()
    s = cfg0.study_options_day
    cfg = ticker_config(cfg0, ticker)
    cal = TradingCalendar(cfg)
    start = cfg.history.option_era_start if ticker == "QQQ" else date.fromisoformat(M28["start"])
    all_sessions = cal.sessions(start, s.dev_end[ticker])
    research = set(cal.research_sessions(start, s.dev_end[ticker]))
    u, _ = load_ticker(ticker, cfg, s.dev_end[ticker])
    assert u["session_date"].max() <= s.dev_end[ticker]  # type: ignore[operator]
    u = u.sort("available_at").with_columns(
        spread=(pl.col("ask") - pl.col("bid")) / ((pl.col("ask") + pl.col("bid")) / 2),
        two_sided=(pl.col("bid") > 0) & (pl.col("ask") > 0) & (pl.col("bid") <= pl.col("ask")),
        rec_at=pl.col("available_at"),
    )
    half = s.half_hour
    points = {
        "close": {d: cal.open_close(d)[1] for d in all_sessions},
        "close-1m": {d: cal.open_close(d)[1] - timedelta(minutes=1) for d in all_sessions},
        "close-5m": {d: cal.open_close(d)[1] - timedelta(minutes=5) for d in all_sessions},
        "signal_10:00": {d: _at(d, half.signal_time) for d in all_sessions},
        "entry_15:30": {d: _at(d, half.entry_time) for d in all_sessions},
        "exit_15:50": {d: _at(d, half.exit_time) for d in all_sessions},
    }
    max_age = cfg.liquidity.max_quote_age_s
    out = []
    for name, when in points.items():
        want = pl.DataFrame(
            {"session_date": list(when), "t": list(when.values())},
            schema={"session_date": pl.Date, "t": u.schema["available_at"]},
        ).sort("t")
        j = want.join_asof(u.drop("session_date"), left_on="t", right_on="available_at")
        j = j.with_columns(age_s=(pl.col("t") - pl.col("rec_at")).dt.total_seconds())
        if not name.startswith("close"):  # S2 does not trade early closes (owner, 2026-11-14)
            j = j.filter(~pl.col("session_date").is_in([d for d in when if cal.is_early_close(d)]))
        ok = j.filter(pl.col("age_s").is_not_null() & (pl.col("age_s") <= max_age)
                      & pl.col("two_sided"))  # fmt: skip
        sp = ok["spread"]
        out.append({
            "ticker": ticker, "point": name, "sessions": j.height,
            "exact_stamp": j.filter(pl.col("age_s") == 0).height,
            "usable": ok.height,
            "none_or_stale": j.height - j.filter(pl.col("age_s") <= max_age).height,
            "not_two_sided": j.filter((pl.col("age_s") <= max_age) & ~pl.col("two_sided")).height,
            "not_rth": ok.filter(~pl.col("is_rth")).height,
            "median": sp.median(), "p90": sp.quantile(0.9), "p99": sp.quantile(0.99),
            "max": sp.max(),
            **{f"over_{w:.2%}": ok.filter(pl.col("spread") > w).height for w in WIDE},
        })  # fmt: skip
    # sessions whose previous calendar session is not a research session, or is before the data
    prev_missing = [
        d for i, d in enumerate(all_sessions)
        if d in research and (i == 0 or all_sessions[i - 1] not in research)
    ]  # fmt: skip
    rj = (
        QQQ_REJECTED / "cleaned_market_data" / "bbo-1m" / "QQQ.parquet"
        if ticker == "QQQ"
        else M28_CLEAN / ticker / "underlying" / "rejected.parquet"
    )
    n_rej = None
    if rj.exists():
        r = pl.scan_parquet(rj).filter(pl.col("session_date") <= s.dev_end[ticker])
        col = "available_at" if "available_at" in r.collect_schema() else "ts"
        stamps = {t for when in points.values() for t in when.values()}
        n_rej = r.select(col).collect().filter(pl.col(col).is_in(list(stamps))).height
    extra = {
        "ticker": ticker,
        "sessions": len(all_sessions),
        "research_sessions": len(research),
        "early_close": sum(cal.is_early_close(d) for d in all_sessions),
        "prev_session_unavailable": [str(d) for d in prev_missing],
        "rejected_at_these_stamps": n_rej,
    }
    return out, extra


def pc(x: float | None) -> str:
    return "-" if x is None else f"{x:.3%}"


def main() -> int:
    rows, extras = [], []
    for t in TICKERS:
        r, e = survey(t)
        rows += r
        extras.append(e)
        print(t, "done", flush=True)
    out = [
        "# M30: underlying quotes that S2 would read (survey before the plan; no signal)",
        "",
        f"Generated {datetime.now().astimezone():%Y-%m-%d %H:%M %Z} by "
        "`scripts/m30_quote_survey.py`. Development sessions only. Timestamps are counted and "
        "bid-ask spreads measured; no return, direction or price level is computed.",
        "",
        "For each time, the record read is the latest cleaned one with `available_at` at or "
        "before it. *usable* = at most 60 seconds old, two-sided, not crossed. Spread is a share "
        "of the mid, over usable records. The 10:00, 15:30 and 15:50 rows leave out early-close "
        "sessions (S2 is NO_TRADE there); the close rows use each session's own close (16:00, "
        "or 13:00 on an early close); close-1m and close-5m are one and five minutes before it.",
        "",
        "| ticker | time | sessions | stamped exactly | usable | none or stale | one-sided or "
        "crossed | usable but not regular-hours | median | 90th | 99th | largest | "
        + " | ".join(f"over {w:.2%}" for w in WIDE)
        + " |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        out.append(
            f"| {r['ticker']} | {r['point']} | {r['sessions']} | {r['exact_stamp']} | "
            f"{r['usable']} | {r['none_or_stale']} | {r['not_two_sided']} | {r['not_rth']} | "
            f"{pc(r['median'])} | {pc(r['p90'])} | {pc(r['p99'])} | {pc(r['max'])} | "
            + " | ".join(str(r[f"over_{w:.2%}"]) for w in WIDE) + " |"
        )  # fmt: skip
    out += ["", "## Sessions and gaps", ""]
    for e in extras:
        out.append(
            f"- {e['ticker']}: {e['sessions']} calendar sessions, {e['research_sessions']} "
            f"research sessions, {e['early_close']} early closes; rejected underlying records "
            f"stamped at one of these times: {e['rejected_at_these_stamps']}; research sessions "
            f"whose previous session is outside the data or excluded: "
            f"{', '.join(e['prev_session_unavailable']) or 'none'}"
        )
    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
