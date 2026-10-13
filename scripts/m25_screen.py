"""M25 (ADR-0016 D5): the one registered development screen of the frozen ETF trend rule. It is a
trial (1 of ADR-0015's 10 tests): registered BEFORE any statistic is computed, with n_trials
recorded before and after. Only development rows are read (`dev_only`, `HoldoutGuard`).

Each monthly period runs from the first open after month-end k to the first open after month-end
k+1. The December 2015 period would end at the 2016-01-04 open, which is in the holdout, so the
last development return is November 2015.

Statistic: Δ = Sharpe(strategy) - Sharpe(benchmark) on monthly net returns in excess of T-bills,
with a paired circular moving-block bootstrap over months.
- ADVANCE: one-sided lower bound > 0, with at least `min_months` months.
- KILL: two-sided upper bound < 0.
- AMBIGUOUS otherwise.

    uv run python scripts/m25_screen.py
    uv run python scripts/m25_screen.py --dry-run-report FILE   # synthetic prices, no database
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import exchange_calendars as xcals
import numpy as np
import numpy.typing as npt
import pandas as pd
import polars as pl
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine

from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import code_commit
from qqq1dte.backtesting.premium_screen import moving_block_weights
from qqq1dte.backtesting.registry import complete_run, fail_run, n_trials, register_run
from qqq1dte.core.config import Phase1Config, config_hash, load_config
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.ingestion.etf_data import dev_only, parse_fred, parse_tiingo
from qqq1dte.strategies.trend import (
    SimResult,
    SlotPeriod,
    cagr,
    max_drawdown_pct,
    month_end_signals,
    period_dates,
    sharpe,
    simulate,
    tbill_growth,
    weighted_sharpe_diff,
    worst_window,
)

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "research" / "m25_dev_screen.md"
EXCLUDED_YEAR = 2008  # D5 descriptive row: Δ without 2008
Arr = npt.NDArray[np.float64]


def dirty() -> bool:
    out = subprocess.run(
        ["git", "status", "--porcelain", "src", "scripts", "configs"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return bool(out.strip())


def sessions_between(start: date, end: date) -> list[date]:
    cal = xcals.get_calendar("XNYS", start="2004-01-01", end=str(end + timedelta(days=400)))
    return [ts.date() for ts in cal.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))]


def real_inputs(cfg: Phase1Config) -> tuple[pl.DataFrame, dict[date, float | None], list[Path]]:
    s = cfg.study_etf_trend
    raw = ROOT / s.raw_dir
    files = [raw / "tiingo" / f"{t}.json" for t in s.tickers]
    frames = [
        dev_only(parse_tiingo(json.loads(f.read_text("utf-8")), t), s.dev_end)
        for f, t in zip(files, s.tickers, strict=True)
    ]
    fred = raw / "fred" / f"{s.fred_series}.csv"
    rates = dev_only(parse_fred(fred.read_text("utf-8"), s.fred_series), s.dev_end)
    return pl.concat(frames), dict(rates.iter_rows()), [*files, fred]


def synthetic_inputs(
    cfg: Phase1Config, sessions: list[date]
) -> tuple[pl.DataFrame, dict[date, float | None]]:
    """Seeded random walks on the real calendar (dry run only: no real data is read)."""
    s = cfg.study_etf_trend
    rng = np.random.default_rng(12345)
    frames = []
    for i, t in enumerate(s.tickers):
        r = rng.normal(0.0003, 0.012, len(sessions))
        close = 50.0 * (i + 1) * np.exp(np.cumsum(r))
        opn = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, 0.002, len(sessions)))
        frames.append(
            pl.DataFrame({
                "date": sessions, "ticker": [t] * len(sessions), "open": opn, "close": close,
                "adj_open": opn, "adj_close": close, "div_cash": 0.0, "split_factor": 1.0,
            })
        )  # fmt: skip
    d = s.data_start
    rates: dict[date, float | None] = {}
    while d <= s.dev_end:
        rates[d] = 2.0
        d += timedelta(days=1)
    return pl.concat(frames), rates


def register_data(engine: Engine, cfg: Phase1Config, files: list[Path], rows: int) -> str:
    """The raw files as stored (holdout rows included but never read), by content hash."""
    s = cfg.study_etf_trend
    h = hashlib.sha256()
    for f in files:
        h.update(f.read_bytes())
    ds_id = f"raw_etf_{h.hexdigest()[:16]}"
    record_dataset(
        engine,
        DatasetVersion(
            dataset_id=ds_id, kind="raw_etf", source="tiingo+fred", coverage_start=s.data_start,
            coverage_end=s.holdout_end, row_count=rows, storage_uri=s.raw_dir,
            code_commit=code_commit(ROOT), config_hash=config_hash(s.model_dump(mode="json")),
        ),
    )  # fmt: skip
    return ds_id


def register(
    engine: Engine, cfg: Phase1Config, window: tuple[date, date], ds_id: str
) -> tuple[int, str, int]:
    """Register the trial BEFORE any statistic is computed; n_trials before and after."""
    n_before = n_trials(engine, *window)
    run_id = register_run(
        engine,
        run_kind="screen_etf_trend",
        config={
            "study_etf_trend": cfg.study_etf_trend.model_dump(mode="json"),
            "bootstrap_reps": cfg.validation.bootstrap_reps,
            "bootstrap_seed": cfg.models.metrics.bootstrap_seed,
            "phase1_config_hash": config_hash(cfg.model_dump(mode="json")),
            "adr": "ADR-0016 D5",
        },
        data_window=window,
        dataset_id=ds_id,
        code_commit=code_commit(ROOT),
        folds=[],
    )
    n_after = n_trials(engine, *window)
    print(f"registered {run_id}; n_trials {n_before} -> {n_after}", flush=True)
    return n_before, run_id, n_after


def build_periods(
    cfg: Phase1Config, daily: pl.DataFrame, rates: dict[date, float | None], sessions: list[date]
) -> tuple[list[tuple[date, date, date]], list[SlotPeriod]]:
    """(month-end, start open, end open) and the slot inputs for each development period."""
    s = cfg.study_etf_trend
    for t in s.tickers:
        have = set(daily.filter(pl.col("ticker") == t)["date"].to_list())
        if missing := [d for d in sessions if d not in have]:
            raise ValueError(f"{t}: {len(missing)} sessions missing, first {missing[:3]}")
    sig = month_end_signals(daily, s.lookback_months)
    signal = {(t, d): v for t, d, _, v in sig.iter_rows()}
    month_ends = sorted(set(sig["month_end"].to_list()))
    px = {(t, d): (o, ao) for d, t, o, ao in daily.select("date", "ticker", "open", "adj_open")
          .iter_rows()}  # fmt: skip
    dates, periods = [], []
    for a, (start, end) in zip(month_ends, period_dates(month_ends, sessions), strict=False):
        if start < s.dev_returns_start:
            continue
        flags = {t: signal[(t, a)] for t in s.tickers}
        if any(v is None for v in flags.values()):
            raise ValueError(f"no signal at {a}: {flags}")
        dates.append((a, start, end))
        periods.append(
            SlotPeriod(
                in_market={t: bool(flags[t]) for t in s.tickers},
                growth={t: px[(t, end)][1] / px[(t, start)][1] for t in s.tickers},
                open_price={t: px[(t, start)][0] for t in s.tickers},
                cash=tbill_growth(rates, start, end),
            )
        )
    return dates, periods


def run_sim(cfg: Phase1Config, periods: list[SlotPeriod], mult: float) -> SimResult:
    s = cfg.study_etf_trend
    return simulate(
        periods, s.tickers, s.weight, s.account_usd, s.commission_per_share, s.commission_min,
        s.commission_max_pct, s.spread_bps, cost_mult=mult,
    )  # fmt: skip


def cost_drag(res: SimResult, account: float) -> float:
    """Average yearly costs as a share of the starting value of each month."""
    v = account * np.concatenate([[1.0], np.cumprod(1 + np.array(res.returns))])[:-1]
    return float(np.sum(np.array(res.costs) / v) / (len(v) / 12))


def describe(res: SimResult, ex: Arr, account: float) -> dict[str, float]:
    r = np.array(res.returns)
    return {
        "sharpe": sharpe(ex), "cagr": cagr(r), "mdd": max_drawdown_pct(r),
        "worst12": worst_window(r, 12), "invested": float(np.mean(res.invested)),
        "orders_yr": sum(res.orders) / (len(r) / 12), "costs": float(sum(res.costs)),
        "drag": cost_drag(res, account),
    }  # fmt: skip


def main() -> int:  # noqa: PLR0915 (linear pipeline)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run-report", type=Path, default=None)
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    s = cfg.study_etf_trend
    dry = args.dry_run_report is not None
    if dry and args.dry_run_report.resolve() == REPORT.resolve():
        print("--dry-run-report must not overwrite the real report")
        return 1
    if not dry and dirty():
        print("the screen is a registered trial: commit src/scripts/configs first")
        return 1
    window = (s.data_start, s.dev_end)
    sessions = sessions_between(s.data_start, s.dev_end)
    engine: Engine | None = None
    run_id, n_before, n_after = "dry-run", -1, -1
    if dry:
        daily, rates = synthetic_inputs(cfg, sessions)
    else:
        daily, rates, files = real_inputs(cfg)
        engine = create_engine(os.environ["DATABASE_URL"])
        ds_id = register_data(engine, cfg, files, daily.height)
        n_before, run_id, n_after = register(engine, cfg, window, ds_id)
    try:
        HoldoutGuard(s.dev_end, None).check([*daily["date"].to_list(), *rates])
        dates, periods = build_periods(cfg, daily, rates, sessions)
        HoldoutGuard(s.dev_end, None).check(e for _, _, e in dates)
        bench_periods = [
            SlotPeriod(dict.fromkeys(s.tickers, True), p.growth, p.open_price, p.cash)
            for p in periods
        ]
        strat, bench = run_sim(cfg, periods, 1.0), run_sim(cfg, bench_periods, 1.0)
        strat2 = run_sim(cfg, periods, s.cost_sensitivity)
        bench2 = run_sim(cfg, bench_periods, s.cost_sensitivity)
        tb = np.array([p.cash - 1 for p in periods])
        ex_s, ex_b = np.array(strat.returns) - tb, np.array(bench.returns) - tb
        n = len(ex_s)
        delta = sharpe(ex_s) - sharpe(ex_b)
        w = moving_block_weights(n, s.block_months, cfg.validation.bootstrap_reps,
                                 cfg.models.metrics.bootstrap_seed)  # fmt: skip
        boot = weighted_sharpe_diff(ex_s, ex_b, w)
        lb = float(np.nanquantile(boot, 1 - s.lower_bound_level))
        ub = float(np.nanquantile(boot, 1 - (1 - s.kill_level) / 2))
        ci = (float(np.nanquantile(boot, 0.025)), ub)
        few = n < s.min_months
        outcome = "KILL" if ub < 0 else "ADVANCE" if lb > 0 and not few else "AMBIGUOUS"
        years = np.array([st.year for _, st, _ in dates])
        keep = years != EXCLUDED_YEAR
        delta_ex08 = sharpe(ex_s[keep]) - sharpe(ex_b[keep])
        delta_2x = sharpe(np.array(strat2.returns) - tb) - sharpe(np.array(bench2.returns) - tb)
        ds, db = describe(strat, ex_s, s.account_usd), describe(bench, ex_b, s.account_usd)
        metrics: dict[str, Any] = {
            "outcome": outcome, "delta": delta, "lower_bound": lb, "upper_bound": ub,
            "months": n, "few_months": few, "delta_ex_2008": delta_ex08, "delta_2x_costs": delta_2x,
            "strategy": ds, "benchmark": db, "n_trials_before": n_before,
            "n_trials_after": n_after,
        }  # fmt: skip
        if engine is not None:
            complete_run(engine, run_id, metrics)
    except Exception as e:
        if engine is not None:
            fail_run(engine, run_id, repr(e))
        raise
    if engine is not None:
        engine.dispose()

    def f(x: float, nd: int = 3) -> str:
        return "-" if math.isnan(x) else f"{x:.{nd}f}"

    def p(x: float) -> str:
        return "-" if math.isnan(x) else f"{x:.1%}"

    out = [
        "# M25: development screen of the ETF trend rule (ADR-0016)"
        + (" — DRY RUN, SYNTHETIC PRICES" if dry else ""),
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m25_screen.py`, code "
        f"{code_commit(ROOT)[:12]}. Registered run `{run_id}` (n_trials {n_before} → {n_after}). "
        f"Development returns {dates[0][1]} → {dates[-1][2]} ({n} months); the holdout was not "
        "read. The December 2015 period would end at the 2016-01-04 open (holdout), so it is "
        "excluded.",
        "",
        f"## Outcome: **{outcome}**",
        "",
        f"- Δ Sharpe (strategy - benchmark, monthly excess returns, annualised): **{f(delta)}**",
        f"- One-sided {s.lower_bound_level:.0%} lower bound: **{f(lb)}** (ADVANCE needs > 0)",
        f"- Two-sided {s.kill_level:.0%} interval: [{f(ci[0])}, {f(ci[1])}] (KILL needs the upper "
        "bound < 0)",
        f"- Months: {n} (guard ≥ {s.min_months}{', NOT MET' if few else ', met'})",
        f"- Paired circular moving-block bootstrap over months: block {s.block_months}, "
        f"{cfg.validation.bootstrap_reps} reps, seed {cfg.models.metrics.bootstrap_seed}.",
        "",
        "Development-data result with its uncertainty. Not a claim of profitability; nothing here "
        "is out-of-sample.",
        "",
        "## Descriptive (never decisions)",
        "",
        "| | strategy | benchmark (equal-weight, monthly rebalanced) |",
        "|---|---|---|",
        f"| Sharpe (excess) | {f(ds['sharpe'])} | {f(db['sharpe'])} |",
        f"| CAGR (net) | {p(ds['cagr'])} | {p(db['cagr'])} |",
        f"| maximum drawdown (month-end opens) | {p(ds['mdd'])} | {p(db['mdd'])} |",
        f"| worst 12 months | {p(ds['worst12'])} | {p(db['worst12'])} |",
        f"| average share in ETFs | {p(ds['invested'])} | {p(db['invested'])} |",
        f"| orders per year | {ds['orders_yr']:.1f} | {db['orders_yr']:.1f} |",
        f"| costs paid ($, ${s.account_usd:,.0f} start) | {ds['costs']:,.2f} "
        f"| {db['costs']:,.2f} |",
        f"| cost drag per year | {p(ds['drag'])} | {p(db['drag'])} |",
        "",
        f"- Δ without {EXCLUDED_YEAR}: {f(delta_ex08)}",
        f"- Δ at {s.cost_sensitivity:g}x costs: {f(delta_2x)}",
        "",
        "## Per year (point estimates)",
        "",
        "| year | months | strategy | benchmark | T-bills | share in ETFs |",
        "|---|---|---|---|---|---|",
    ]  # fmt: skip
    rs, rb = np.array(strat.returns), np.array(bench.returns)
    inv = np.array(strat.invested)
    for y in sorted(set(years.tolist())):
        m = years == y
        out.append(
            f"| {y} | {int(m.sum())} | {p(float(np.prod(1 + rs[m]) - 1))} "
            f"| {p(float(np.prod(1 + rb[m]) - 1))} | {p(float(np.prod(1 + tb[m]) - 1))} "
            f"| {p(float(inv[m].mean()))} |"
        )
    out += [
        "",
        "## Per month (for hand checks)",
        "",
        "| signal month-end | start open | end open | held | strategy | benchmark | T-bills "
        "| costs $ |",
        "|---|---|---|---|---|---|---|---|",
    ]  # fmt: skip
    for i, ((a, st, en), per) in enumerate(zip(dates, periods, strict=True)):
        held = " ".join(t for t in s.tickers if per.in_market[t]) or "cash"
        out.append(
            f"| {a} | {st} | {en} | {held} | {rs[i]:.4%} | {rb[i]:.4%} | {tb[i]:.4%} "
            f"| {strat.costs[i]:.2f} |"
        )
    report: Path = args.dry_run_report if dry else REPORT
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"outcome {outcome}; delta {delta:.3f} lower bound {lb:.3f}; wrote {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
