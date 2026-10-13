"""M26 (ADR-0017 D5): the one registered development screen of the turn-of-month rule on SPY. It is
a trial (1 of ADR-0015's 10 tests): registered BEFORE any statistic is computed, with n_trials
recorded before and after. Only development rows are read (`dev_only`, `HoldoutGuard`).

Unit: one trade (buy at the close of day -2, sell at the close of day +3) on a fixed $5,000.
Statistic: the mean net excess return per trade, with a circular moving-block bootstrap over
trades in time order.
- ADVANCE: one-sided lower bound > 0, with at least `min_trades` trades.
- KILL: two-sided upper bound < 0.
- AMBIGUOUS otherwise.

    uv run python scripts/m26_screen.py
    uv run python scripts/m26_screen.py --dry-run-report FILE   # synthetic prices, no database
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
import polars as pl
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine

from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import code_commit
from qqq1dte.backtesting.premium_screen import moving_block_weights, weighted_means
from qqq1dte.backtesting.registry import complete_run, fail_run, n_trials, register_run
from qqq1dte.core.config import Phase1Config, config_hash, load_config
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.ingestion.etf_data import dev_only, parse_fred, parse_tiingo
from qqq1dte.strategies.tom import TomTrade, tom_trade, tom_windows
from qqq1dte.strategies.trend import max_drawdown_pct, tbill_growth

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "research" / "m26_dev_screen.md"
TRADING_DAYS = 252
Arr = npt.NDArray[np.float64]


def dirty() -> bool:
    out = subprocess.run(
        ["git", "status", "--porcelain", "src", "scripts", "configs"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return bool(out.strip())


def calendar(end: date) -> list[date]:
    cal = xcals.get_calendar("XNYS", start="1993-01-01", end=str(end + timedelta(days=400)))
    return [ts.date() for ts in cal.sessions if ts.date() <= end]


def real_inputs(cfg: Phase1Config) -> tuple[pl.DataFrame, dict[date, float | None], list[Path]]:
    s = cfg.study_tom
    raw = ROOT / s.raw_dir
    spy = raw / "tiingo" / f"{s.ticker}.json"
    fred = raw / "fred" / f"{s.fred_series}.csv"
    df = dev_only(parse_tiingo(json.loads(spy.read_text("utf-8")), s.ticker), s.dev_end)
    rates = dev_only(parse_fred(fred.read_text("utf-8"), s.fred_series), s.dev_end)
    return df, dict(rates.iter_rows()), [spy, fred]


def synthetic_inputs(
    cfg: Phase1Config, sessions: list[date]
) -> tuple[pl.DataFrame, dict[date, float | None]]:
    """A seeded random walk on the real calendar (dry run only: no real data is read)."""
    s = cfg.study_tom
    days = [d for d in sessions if d >= s.data_start]
    rng = np.random.default_rng(12345)
    close = 45.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, len(days))))
    df = pl.DataFrame({
        "date": days, "ticker": s.ticker, "open": close, "close": close, "adj_open": close,
        "adj_close": close, "div_cash": 0.0, "split_factor": 1.0,
    })  # fmt: skip
    rates: dict[date, float | None] = {}
    d = s.data_start
    while d <= s.dev_end:
        rates[d] = 2.0
        d += timedelta(days=1)
    return df, rates


def register(
    engine: Engine, cfg: Phase1Config, files: list[Path], rows: int
) -> tuple[int, str, int]:
    """Register the raw data and the trial BEFORE any statistic is computed."""
    s = cfg.study_tom
    h = hashlib.sha256()
    for f in files:
        h.update(f.read_bytes())
    ds_id = f"raw_tom_{h.hexdigest()[:16]}"
    record_dataset(
        engine,
        DatasetVersion(
            dataset_id=ds_id, kind="raw_etf", source="tiingo+fred", coverage_start=s.data_start,
            coverage_end=s.holdout_end, row_count=rows, storage_uri=s.raw_dir,
            code_commit=code_commit(ROOT), config_hash=config_hash(s.model_dump(mode="json")),
        ),
    )  # fmt: skip
    window = (s.data_start, s.dev_end)
    n_before = n_trials(engine, *window)
    run_id = register_run(
        engine,
        run_kind="screen_tom",
        config={
            "study_tom": s.model_dump(mode="json"),
            "bootstrap_reps": cfg.validation.bootstrap_reps,
            "bootstrap_seed": cfg.models.metrics.bootstrap_seed,
            "phase1_config_hash": config_hash(cfg.model_dump(mode="json")),
            "adr": "ADR-0017 D5",
        },
        data_window=window,
        dataset_id=ds_id,
        code_commit=code_commit(ROOT),
        folds=[],
    )
    n_after = n_trials(engine, *window)
    print(f"registered {run_id}; n_trials {n_before} -> {n_after}", flush=True)
    return n_before, run_id, n_after


def trades(
    cfg: Phase1Config, df: pl.DataFrame, rates: dict[date, float | None],
    windows: list[tuple[date, date]], mult: float,
) -> list[TomTrade]:  # fmt: skip
    s = cfg.study_tom
    close = dict(df.select("date", "close").iter_rows())
    adj = df.select("date", "adj_close").sort("date")
    out = []
    for entry, exit_ in windows:
        path = adj.filter(pl.col("date").is_between(entry, exit_))["adj_close"].to_list()
        out.append(
            tom_trade(
                s.account_usd, close[entry], path, tbill_growth(rates, entry, exit_),
                s.commission_per_share, s.commission_min, s.commission_max_pct, s.slippage_bps,
                cost_mult=mult,
            )
        )  # fmt: skip
    return out


def daily_compare(
    df: pl.DataFrame, rates: dict[date, float | None], windows: list[tuple[date, date]],
    trade_list: list[TomTrade], account: float,
) -> dict[str, dict[str, float]]:  # fmt: skip
    """Descriptive, approximate (fractional, costs as a share of the account on entry and exit
    days): the TOM + T-bills account vs SPY buy-and-hold, from the first entry to the last exit."""
    d = df.sort("date").filter(pl.col("date").is_between(windows[0][0], windows[-1][1]))
    dates, px = d["date"].to_list(), d["adj_close"].to_numpy()
    held: set[date] = set()
    cost_on: dict[date, float] = {}
    for (entry, exit_), t in zip(windows, trade_list, strict=True):
        held |= {dd for dd in dates if entry < dd <= exit_}
        half = t.costs / 2 / account
        cost_on[entry] = cost_on.get(entry, 0.0) + half
        cost_on[exit_] = cost_on.get(exit_, 0.0) + half
    spy, tom, tb = [], [], []
    for i in range(1, len(dates)):
        cash = tbill_growth(rates, dates[i - 1], dates[i]) - 1
        r = px[i] / px[i - 1] - 1
        spy.append(r)
        tb.append(cash)
        tom.append((r if dates[i] in held else cash) - cost_on.get(dates[i], 0.0))
    out = {}
    for name, x in (("tom", np.array(tom)), ("spy", np.array(spy))):
        ex = x - np.array(tb)
        out[name] = {
            "cagr": float(np.prod(1 + x) ** (TRADING_DAYS / len(x)) - 1),
            "sharpe": float(ex.mean() / ex.std(ddof=1) * math.sqrt(TRADING_DAYS)),
            "mdd": max_drawdown_pct(x),
        }
    inside = np.array([dd in held for dd in dates[1:]])
    out["spy_days"] = {
        "in_mean": float(np.array(spy)[inside].mean()),
        "out_mean": float(np.array(spy)[~inside].mean()),
    }
    return out


def main() -> int:  # noqa: PLR0915 (linear pipeline)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run-report", type=Path, default=None)
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    s = cfg.study_tom
    dry = args.dry_run_report is not None
    if dry and args.dry_run_report.resolve() == REPORT.resolve():
        print("--dry-run-report must not overwrite the real report")
        return 1
    if not dry and dirty():
        print("the screen is a registered trial: commit src/scripts/configs first")
        return 1
    sessions = calendar(s.dev_end)
    windows = [
        (e, x) for e, x in tom_windows(sessions, s.entry_from_end, s.exit_day)
        if e >= s.data_start and x <= s.dev_end
    ]  # fmt: skip
    engine: Engine | None = None
    run_id, n_before, n_after = "dry-run", -1, -1
    if dry:
        df, rates = synthetic_inputs(cfg, sessions)
    else:
        df, rates, files = real_inputs(cfg)
        engine = create_engine(os.environ["DATABASE_URL"])
        n_before, run_id, n_after = register(engine, cfg, files, df.height)
    try:
        guard = HoldoutGuard(s.dev_end, None)
        guard.check([*df["date"].to_list(), *rates, *(x for _, x in windows)])
        have = set(df["date"].to_list())
        if missing := [d for d in sessions if d >= s.data_start and d not in have]:
            raise ValueError(f"{len(missing)} sessions missing, first {missing[:3]}")
        tr = trades(cfg, df, rates, windows, 1.0)
        tr2 = trades(cfg, df, rates, windows, s.cost_sensitivity)
        net = np.array([t.net_excess for t in tr])
        n = len(net)
        w = moving_block_weights(n, s.block_trades, cfg.validation.bootstrap_reps,
                                 cfg.models.metrics.bootstrap_seed)  # fmt: skip
        boot = weighted_means(net, w)
        lb = float(np.nanquantile(boot, 1 - s.lower_bound_level))
        ub = float(np.nanquantile(boot, 1 - (1 - s.kill_level) / 2))
        lo95 = float(np.nanquantile(boot, (1 - s.kill_level) / 2))
        few = n < s.min_trades
        outcome = "KILL" if ub < 0 else "ADVANCE" if lb > 0 and not few else "AMBIGUOUS"
        years = np.array([e.year for e, _ in windows])
        gross = np.array([t.gross_excess for t in tr])
        net2 = np.array([t.net_excess for t in tr2])
        worst_days = np.array([t.worst_day for t in tr])
        early = np.array([e < s.era_split for e, _ in windows])
        cmp_ = daily_compare(df, rates, windows, tr, s.account_usd)
        metrics: dict[str, Any] = {
            "outcome": outcome, "mean_net_excess": float(net.mean()), "lower_bound": lb,
            "upper_bound": ub, "trades": n, "few_trades": few,
            "mean_gross_excess": float(gross.mean()), "mean_net_2x": float(net2.mean()),
            "mean_without_excluded_year": float(net[years != s.excluded_year].mean()),
            "mean_early": float(net[early].mean()), "mean_late": float(net[~early].mean()),
            "loss_limit_trades": int((worst_days < -s.loss_day_limit).sum()), "compare": cmp_,
            "n_trials_before": n_before, "n_trials_after": n_after,
        }  # fmt: skip
        if engine is not None:
            complete_run(engine, run_id, metrics)
    except Exception as e:
        if engine is not None:
            fail_run(engine, run_id, repr(e))
        raise
    if engine is not None:
        engine.dispose()

    def p(x: float, nd: int = 3) -> str:
        return "-" if math.isnan(x) else f"{x:.{nd}%}"

    costs = np.array([t.costs for t in tr])
    out = [
        "# M26: development screen of the turn-of-month rule on SPY (ADR-0017)"
        + (" — DRY RUN, SYNTHETIC PRICES" if dry else ""),
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m26_screen.py`, code "
        f"{code_commit(ROOT)[:12]}. Registered run `{run_id}` (n_trials {n_before} → {n_after}). "
        f"{n} development trades, first entry {windows[0][0]}, last exit {windows[-1][1]}; the "
        "holdout was not read (the December 2015 trade exits in January 2016 and is excluded).",
        "",
        f"## Outcome: **{outcome}**",
        "",
        f"- Mean net excess return per trade (after costs, above T-bills): **{p(net.mean())}**",
        f"- One-sided {s.lower_bound_level:.0%} lower bound: **{p(lb)}** (ADVANCE needs > 0)",
        f"- Two-sided {s.kill_level:.0%} interval: [{p(lo95)}, {p(ub)}] (KILL needs the upper "
        "bound < 0)",
        f"- Trades: {n} (guard ≥ {s.min_trades}{', NOT MET' if few else ', met'})",
        f"- Circular moving-block bootstrap over trades: block {s.block_trades}, "
        f"{cfg.validation.bootstrap_reps} reps, seed {cfg.models.metrics.bootstrap_seed}.",
        "",
        "Development-data result with its uncertainty. Not a claim of profitability; nothing here "
        "is out-of-sample. The published evidence for this effect overlaps this period.",
        "",
        "## Descriptive (never decisions)",
        "",
        f"- Mean gross excess per trade: {p(gross.mean())}; mean costs per trade: "
        f"${costs.mean():.2f} ({p(costs.mean() / s.account_usd)} of ${s.account_usd:,.0f})",
        f"- Mean net at {s.cost_sensitivity:g}x costs: {p(net2.mean())}",
        f"- Mean net without {s.excluded_year}: {p(float(net[years != s.excluded_year].mean()))}",
        f"- Before {s.era_split}: {p(float(net[early].mean()))} ({int(early.sum())} trades); "
        f"from {s.era_split}: {p(float(net[~early].mean()))} ({int((~early).sum())} trades)",
        f"- Winning trades: {float((net > 0).mean()):.1%}; worst trade {p(float(net.min()))}; "
        f"best {p(float(net.max()))}",
        f"- Loss limit (ADR-0015 D3): **{int((worst_days < -s.loss_day_limit).sum())}** trades "
        f"contain a day below -{s.loss_day_limit:.0%} of the account; worst day "
        f"{p(float(worst_days.min()))}",
        f"- SPY mean daily return on held days {p(cmp_['spy_days']['in_mean'], 4)} vs other days "
        f"{p(cmp_['spy_days']['out_mean'], 4)} (gross)",
        "",
        "Versus SPY buy-and-hold, same dates (approximate: fractional, costs on entry/exit days):",
        "",
        "| | TOM + T-bills | SPY buy-and-hold |",
        "|---|---|---|",
        f"| CAGR | {p(cmp_['tom']['cagr'], 1)} | {p(cmp_['spy']['cagr'], 1)} |",
        f"| Sharpe (daily excess, annualised) | {cmp_['tom']['sharpe']:.2f} "
        f"| {cmp_['spy']['sharpe']:.2f} |",
        f"| maximum drawdown | {p(cmp_['tom']['mdd'], 1)} | {p(cmp_['spy']['mdd'], 1)} |",
        "",
        "## Per year (point estimates)",
        "",
        "| year | trades | mean net excess | sum net excess | worst trade |",
        "|---|---|---|---|---|",
    ]  # fmt: skip
    for y in sorted(set(years.tolist())):
        m = years == y
        out.append(
            f"| {y} | {int(m.sum())} | {p(float(net[m].mean()))} | {p(float(net[m].sum()))} "
            f"| {p(float(net[m].min()))} |"
        )
    out += [
        "",
        "## Per trade (for hand checks)",
        "",
        "| entry | exit | shares | costs $ | gross excess | net excess | worst day |",
        "|---|---|---|---|---|---|---|",
        *[
            f"| {e} | {x} | {t.shares} | {t.costs:.2f} | {p(t.gross_excess, 4)} "
            f"| {p(t.net_excess, 4)} | {p(t.worst_day, 2)} |"
            for (e, x), t in zip(windows, tr, strict=True)
        ],
        "",
    ]  # fmt: skip
    report: Path = args.dry_run_report if dry else REPORT
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"outcome {outcome}; mean {net.mean():.5f} lower bound {lb:.5f}; wrote {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
