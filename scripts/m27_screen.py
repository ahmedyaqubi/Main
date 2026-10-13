"""M27 (ADR-0018 D5): the one registered development screen of the Connors RSI(2) pullback rule on
SPY. It is a trial (1 of ADR-0015's 10 tests): registered BEFORE any statistic is computed, with
n_trials recorded before and after. Only development rows are read (`dev_only`, `HoldoutGuard`).

Unit: one trade (signals at the close; buy and sell at the next open) on a fixed $5,000.
Statistic: the mean net excess return per trade, with a circular moving-block bootstrap over
trades in time order.
- ADVANCE: one-sided lower bound > 0, with at least `min_trades` trades.
- KILL: two-sided upper bound < 0.
- AMBIGUOUS otherwise.

    uv run python scripts/m27_screen.py
    uv run python scripts/m27_screen.py --dry-run-report FILE   # synthetic prices, no database
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine

from m26_screen import calendar, daily_compare, dirty, real_inputs, synthetic_inputs
from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import code_commit
from qqq1dte.backtesting.premium_screen import moving_block_weights, weighted_means
from qqq1dte.backtesting.registry import complete_run, fail_run, n_trials, register_run
from qqq1dte.core.config import Phase1Config, config_hash, load_config
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.strategies.pullback import signals, trade_indices
from qqq1dte.strategies.tom import TomTrade, tom_trade
from qqq1dte.strategies.trend import tbill_growth

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "research" / "m27_dev_screen.md"


def register(
    engine: Engine, cfg: Phase1Config, files: list[Path], rows: int
) -> tuple[int, str, int]:
    """Register the raw data (the M26 files) and the trial BEFORE any statistic is computed."""
    s = cfg.study_pullback
    h = hashlib.sha256()
    for f in files:
        h.update(f.read_bytes())
    ds_id = f"raw_tom_{h.hexdigest()[:16]}"
    record_dataset(
        engine,
        DatasetVersion(
            dataset_id=ds_id, kind="raw_etf", source="tiingo+fred", coverage_start=s.data_start,
            coverage_end=s.holdout_end, row_count=rows, storage_uri=s.raw_dir,
            code_commit=code_commit(ROOT),
            config_hash=config_hash(cfg.study_tom.model_dump(mode="json")),
        ),
    )  # fmt: skip
    window = (s.data_start, s.dev_end)
    n_before = n_trials(engine, *window)
    run_id = register_run(
        engine,
        run_kind="screen_pullback",
        config={
            "study_pullback": s.model_dump(mode="json"),
            "bootstrap_reps": cfg.validation.bootstrap_reps,
            "bootstrap_seed": cfg.models.metrics.bootstrap_seed,
            "phase1_config_hash": config_hash(cfg.model_dump(mode="json")),
            "adr": "ADR-0018 D5",
        },
        data_window=window,
        dataset_id=ds_id,
        code_commit=code_commit(ROOT),
        folds=[],
    )
    n_after = n_trials(engine, *window)
    print(f"registered {run_id}; n_trials {n_before} -> {n_after}", flush=True)
    return n_before, run_id, n_after


def main() -> int:  # noqa: PLR0915 (linear pipeline)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run-report", type=Path, default=None)
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    s = cfg.study_pullback
    if (s.data_start, s.dev_end, s.raw_dir) != (
        cfg.study_tom.data_start,
        cfg.study_tom.dev_end,
        cfg.study_tom.raw_dir,
    ):
        print("study_pullback must use the M26 SPY data and split (ADR-0018 D2-D3)")
        return 1
    dry = args.dry_run_report is not None
    if dry and args.dry_run_report.resolve() == REPORT.resolve():
        print("--dry-run-report must not overwrite the real report")
        return 1
    if not dry and dirty():
        print("the screen is a registered trial: commit src/scripts/configs first")
        return 1
    sessions = calendar(s.dev_end)
    engine: Engine | None = None
    run_id, n_before, n_after = "dry-run", -1, -1
    if dry:
        df, rates = synthetic_inputs(cfg, sessions)
    else:
        df, rates, files = real_inputs(cfg)
        engine = create_engine(os.environ["DATABASE_URL"])
        n_before, run_id, n_after = register(engine, cfg, files, df.height)
    try:
        df = df.sort("date")
        dates: list[date] = df["date"].to_list()
        HoldoutGuard(s.dev_end, None).check([*dates, *rates])
        if dates != [d for d in sessions if d >= s.data_start]:
            raise ValueError("SPY dates differ from the XNYS sessions")
        adj_c, adj_o = df["adj_close"].to_list(), df["adj_open"].to_list()
        opn, cls = df["open"].to_list(), df["close"].to_list()
        entry, exit_ = signals(adj_c, s.rsi_period, s.rsi_entry, s.sma_trend, s.sma_exit)
        idx = trade_indices(entry, exit_)

        def run(mult: float, at_close: bool = False) -> list[TomTrade]:
            out = []
            for i, j in idx:
                if at_close:  # published timing: signal closes (descriptive only)
                    a, b, price, path = i, j, cls[i], adj_c[i : j + 1]
                else:
                    a, b = i + 1, j + 1
                    price, path = opn[a], [adj_o[a], *adj_c[a : j + 1], adj_o[b]]
                out.append(
                    tom_trade(
                        s.account_usd, price, path, tbill_growth(rates, dates[a], dates[b]),
                        s.commission_per_share, s.commission_min, s.commission_max_pct,
                        s.slippage_bps, cost_mult=mult,
                    )
                )  # fmt: skip
            return out

        tr, tr2, trc = run(1.0), run(s.cost_sensitivity), run(1.0, at_close=True)
        windows = [(dates[i + 1], dates[j + 1]) for i, j in idx]
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
        early = np.array([e < s.era_split for e, _ in windows])
        gross = np.array([t.gross_excess for t in tr])
        net2 = np.array([t.net_excess for t in tr2])
        netc = np.array([t.net_excess for t in trc])
        worst_days = np.array([t.worst_day for t in tr])
        hold = np.array([j - i for i, j in idx])  # sessions from buy open to sell open
        cmp_ = daily_compare(df, rates, windows, tr, s.account_usd)
        metrics: dict[str, Any] = {
            "outcome": outcome, "mean_net_excess": float(net.mean()), "lower_bound": lb,
            "upper_bound": ub, "trades": n, "few_trades": few,
            "mean_gross_excess": float(gross.mean()), "mean_net_2x": float(net2.mean()),
            "mean_net_at_signal_close": float(netc.mean()),
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
    span_years = (windows[-1][1] - windows[0][0]).days / 365.25
    out = [
        "# M27: development screen of the RSI(2) pullback rule on SPY (ADR-0018)"
        + (" — DRY RUN, SYNTHETIC PRICES" if dry else ""),
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m27_screen.py`, code "
        f"{code_commit(ROOT)[:12]}. Registered run `{run_id}` (n_trials {n_before} → {n_after}). "
        f"{n} development trades, first buy {windows[0][0]}, last sale {windows[-1][1]}; the "
        "holdout was not read (a position still open at the end of 2015 is excluded).",
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
        "is out-of-sample. The published tests of this rule overlap this period.",
        "",
        "## Descriptive (never decisions)",
        "",
        f"- **Same signals at the signal closes (published timing; not tradable for the owner):** "
        f"mean net {p(netc.mean())}. Next-open execution changes it by "
        f"{p(net.mean() - netc.mean())}.",
        f"- Mean gross excess per trade: {p(gross.mean())}; mean costs per trade: "
        f"${costs.mean():.2f} ({p(costs.mean() / s.account_usd)} of ${s.account_usd:,.0f})",
        f"- Mean net at {s.cost_sensitivity:g}x costs: {p(net2.mean())}",
        f"- Mean net without {s.excluded_year}: {p(float(net[years != s.excluded_year].mean()))}",
        f"- Before {s.era_split}: {p(float(net[early].mean()))} ({int(early.sum())} trades); "
        f"from {s.era_split}: {p(float(net[~early].mean()))} ({int((~early).sum())} trades)",
        f"- Winning trades: {float((net > 0).mean()):.1%}; worst trade {p(float(net.min()))}; "
        f"best {p(float(net.max()))}",
        f"- Holding (sessions, buy open → sell open): median {float(np.median(hold)):.0f}, max "
        f"{int(hold.max())}; trades per year {n / span_years:.1f}",
        f"- Loss limit (ADR-0015 D3): **{int((worst_days < -s.loss_day_limit).sum())}** trades "
        f"contain a day below -{s.loss_day_limit:.0%} of the account; worst day "
        f"{p(float(worst_days.min()))}",
        "",
        "Versus SPY buy-and-hold, same dates (approximate: close-to-close days, fractional, costs "
        "on entry/exit days):",
        "",
        "| | pullback + T-bills | SPY buy-and-hold |",
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
        "| signal close | buy open | exit signal close | sell open | shares | costs $ "
        "| net excess | net at signal closes | worst day |",
        "|---|---|---|---|---|---|---|---|---|",
        *[
            f"| {dates[i]} | {dates[i + 1]} | {dates[j]} | {dates[j + 1]} | {t.shares} "
            f"| {t.costs:.2f} | {p(t.net_excess, 4)} | {p(c.net_excess, 4)} "
            f"| {p(t.worst_day, 2)} |"
            for (i, j), t, c in zip(idx, tr, trc, strict=True)
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
