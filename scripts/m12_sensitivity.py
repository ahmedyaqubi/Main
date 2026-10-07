"""M12: execution-assumption sensitivity of the mechanical diagnostic baseline. NOT a strategy.

The M11 mechanical signal (CALL at every prediction timestamp, separately PUT) is re-simulated
in full for every fill assumption, because target/stop levels follow each model's own entry fill
(owner Q2). Grid (owner Q4, pre-declared in configs/phase1.yaml -> sensitivity): moderate
alpha x latency x cost multiplier; plus the three named models (conservative, moderate at the
configured alpha, optimistic) at the configured latency and costs x1. Pre-holdout research
sessions only. One `validation_runs` row (run_kind "sensitivity", the whole grid is one
configuration; owner Q5). Every P&L figure goes through the gate-9 net-only helpers.

    uv run python scripts/m12_sensitivity.py [--workers 7]
"""

from __future__ import annotations

import argparse
import dataclasses
import itertools
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
from dotenv import load_dotenv
from sqlalchemy import create_engine

from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import code_commit, dataset_id
from qqq1dte.backtesting.registry import complete_run, fail_run, register_run
from qqq1dte.backtesting.reporting import NetSummary, net_from_frame, summarize_net
from qqq1dte.backtesting.session_data import session_inputs
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config, load_config
from qqq1dte.execution_sim.engine import Signal, Trade, run_session
from qqq1dte.execution_sim.fills import (
    Conservative,
    FillModel,
    Moderate,
    Optimistic,
    scaled_costs,
)

ROOT = Path(__file__).resolve().parents[1]
END = date(2026, 10, 2)
REPORT = ROOT / "reports" / "backtest" / "m12_sensitivity.md"
CFG = load_config()
DT = pl.Datetime("us", "UTC")
TRADE_SCHEMA: dict[str, pl.DataType] = {
    f.name: (
        DT
        if f.name.endswith("_ts") or f.name == "t_end"
        else pl.List(pl.String())
        if f.name == "flags"
        else pl.Int64()
        if f.name == "holding_seconds"
        else pl.String()
        if f.name in ("side", "symbol", "fill_model", "outcome", "exit_reason")
        else pl.Float64()
    )
    for f in dataclasses.fields(Trade)
}


@dataclasses.dataclass(frozen=True)
class Point:
    label: str  # "named" or "grid"
    model: str  # CONSERVATIVE / MODERATE / OPTIMISTIC
    alpha: float | None
    latency_s: int
    cost_mult: float


def points(cfg: Phase1Config) -> list[Point]:
    s = cfg.sensitivity
    named = [
        Point("named", "CONSERVATIVE", None, cfg.fills.latency_s, 1.0),
        Point("named", "MODERATE", cfg.fills.moderate_alpha, cfg.fills.latency_s, 1.0),
        Point("named", "OPTIMISTIC", None, cfg.fills.latency_s, 1.0),
    ]
    grid = [
        Point("grid", "MODERATE", a, lat, c)
        for a, lat, c in itertools.product(s.alphas, s.latencies_s, s.cost_multipliers)
    ]
    return named + grid


def _setup(p: Point, cfg: Phase1Config) -> tuple[Phase1Config, FillModel]:
    c = scaled_costs(cfg, p.cost_mult)
    c = c.model_copy(update={"fills": c.fills.model_copy(update={"latency_s": p.latency_s})})
    fill: FillModel = (
        Conservative(c)
        if p.model == "CONSERVATIVE"
        else Optimistic(c)
        if p.model == "OPTIMISTIC"
        else Moderate(c, p.alpha if p.alpha is not None else c.fills.moderate_alpha)
    )
    return c, fill


def session_job(args: tuple[date, dict[str, pl.DataFrame]]) -> pl.DataFrame:
    d, t = args
    cfg = load_config()
    cal = TradingCalendar(cfg)
    frames = []
    for i, p in enumerate(points(cfg)):
        c, fill = _setup(p, cfg)
        for side in ("C", "P"):
            sig = [Signal(ts, side) for ts in cal.prediction_timestamps(d)]
            res = run_session(d, sig, t["und"], t["chain"], t["records"], cal, c, fill)
            rows = [
                {
                    k: list(v) if isinstance(v, tuple) else v
                    for k, v in dataclasses.asdict(tr).items()
                }
                for tr in res.trades
            ]
            frames.append(
                pl.DataFrame(rows, schema=TRADE_SCHEMA).with_columns(
                    session_date=pl.lit(d), point=pl.lit(i)
                )
            )
    return pl.concat(frames)


def _summ(t: pl.DataFrame) -> NetSummary:
    done = t.filter(pl.col("net_pnl").is_not_null())
    return summarize_net(net_from_frame(done), done["session_date"].to_list(), CFG)  # gate 9


def evaluate(trades: pl.DataFrame, pts: list[Point]) -> dict[str, Any]:
    out: dict[str, Any] = {"named": [], "grid": []}
    for i, p in enumerate(pts):
        for side in ("C", "P"):
            t = trades.filter((pl.col("point") == i) & (pl.col("side") == side))
            done = t.filter(pl.col("net_pnl").is_not_null())
            s = _summ(t)
            oc = {r["outcome"]: r["len"] for r in t.group_by("outcome").len().to_dicts()}
            rec = {
                **dataclasses.asdict(p),
                "side": side,
                "trades": t.height,
                "outcomes": oc,
                "mean_net": s.mean,
                "ci": list(s.ci),
                "median_net": s.median,
                "n_net": s.n,
                "mean_r": done["r_multiple"].mean(),
                "mean_spread_cost": done["spread_cost"].mean(),
                "mean_slippage": done["slippage"].mean(),
                "slippage_known": int(done["slippage"].is_not_null().sum()),
            }
            out[p.label].append(rec)
    return out


def _f(x: object, fmt: str) -> str:
    return format(float(x), fmt) if isinstance(x, int | float) else "—"


def write_report(res: dict[str, Any], meta: dict[str, Any]) -> None:
    s = CFG.sensitivity
    lines = [
        "# M12 execution sensitivity of the mechanical baseline (NOT a strategy)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {meta['commit'][:12]}, run "
        f"`{meta['run_id']}`. Sessions {meta['n_sessions']} ({meta['first']} → {meta['last']}, "
        f"pre-holdout research sessions; holdout after {meta['hold']} not opened).",
        "",
        "**What this is.** The M11 mechanical signal (CALL at every prediction timestamp; "
        "separately PUT; one open position, ≤ 3 entries per session) re-simulated in full under "
        "each execution assumption. Target and stop are set from each model's own entry fill and "
        "always trigger on the bid (§6). It measures how much the unconditional-entry baseline "
        "depends on execution assumptions. It is not evidence of an edge and makes no claim of "
        "profitability (rule 12).",
        "",
        "**Gate 9.** Every dollar figure is net of §4.8 commissions and fees and of the "
        "spread paid through the fill (`NetPnl` type; `backtesting/reporting.py`). Mean net "
        "P&L per trade, per contract, with session-block bootstrap "
        f"{CFG.validation.bootstrap_reps}-rep {CFG.models.metrics.ci_level:.0%} CIs. "
        "(+) = CI above 0, (-) = CI below 0.",
        "",
        "**Known limitations.** Fill probability is assumed to be 1 whenever the §4.9 gates pass "
        "(spec §6). Option quotes are 1-minute snapshots, so latencies of 0 s and 5 s see the "
        "same quote; only 60 s moves entry (and selection) to the next snapshot. Latency "
        "slippage = entry fill at T_e minus the same model's fill on the quote in force at T.",
        "",
        "## Three fill models side by side "
        f"(latency {CFG.fills.latency_s} s, costs x1, moderate alpha = {CFG.fills.moderate_alpha})",
        "",
        "| side | model | trades | WIN | LOSS | time exits (BE / +/ -) | unresolved "
        "| mean net $ [CI] | median net $ | mean R | mean spread cost $ |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(res["named"], key=lambda r: (r["side"], r["model"])):
        oc = r["outcomes"]
        lines.append(
            f"| {r['side']} | {r['model']} | {r['trades']:,} | {oc.get('WIN', 0):,} "
            f"| {oc.get('LOSS', 0):,} | {oc.get('BREAKEVEN', 0)} / "
            f"{oc.get('TIME_EXIT_PROFIT', 0)} / {oc.get('TIME_EXIT_LOSS', 0)} "
            f"| {oc.get('UNRESOLVED_DATA', 0)} "
            f"| {r['mean_net']:+.2f} [{r['ci'][0]:+.2f}, {r['ci'][1]:+.2f}] "
            f"| {r['median_net']:+.2f} | {_f(r['mean_r'], '+.3f')} "
            f"| {_f(r['mean_spread_cost'], '.2f')} |"
        )
    for side in ("C", "P"):
        grid = [r for r in res["grid"] if r["side"] == side]
        cols = list(itertools.product(s.latencies_s, s.cost_multipliers))
        lines += [
            "",
            f"## Grid: mean net $ per trade, {'CALL' if side == 'C' else 'PUT'} side "
            "(moderate alpha; alpha = 1 prices like conservative, alpha = 0 like optimistic)",
            "",
            "| alpha | " + " | ".join(f"latency {lat} s, costs x{c:g}" for lat, c in cols) + " |",
            "|---|" + "---|" * len(cols),
        ]
        for a in s.alphas:
            cells = []
            for lat, c in cols:
                (r,) = [
                    g
                    for g in grid
                    if g["alpha"] == a and g["latency_s"] == lat and g["cost_mult"] == c
                ]
                cells.append(f"{r['mean_net']:+.2f} [{r['ci'][0]:+.2f}, {r['ci'][1]:+.2f}]")
            lines.append(f"| {a:g} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Latency slippage and spread cost (grid, costs x1)",
        "",
        "| side | alpha | latency s | trades | mean latency slippage $ (n known) "
        "| mean spread cost $ |",
        "|---|---|---|---|---|---|",
    ]
    for r in res["grid"]:
        if r["cost_mult"] == 1.0:
            lines.append(
                f"| {r['side']} | {r['alpha']:g} | {r['latency_s']} | {r['trades']:,} "
                f"| {_f(r['mean_slippage'], '+.2f')} ({r['slippage_known']:,}) "
                f"| {_f(r['mean_spread_cost'], '.2f')} |"
            )
    pos = [r for r in res["grid"] + res["named"] if r["ci"][0] > 0]
    sign = sorted({r["mean_net"] > 0 for r in res["grid"] + res["named"]})
    lines += [
        "",
        "## Sign summary",
        "",
        f"- Configurations with mean net > 0: "
        f"{sum(r['mean_net'] > 0 for r in res['grid'] + res['named'])} of "
        f"{len(res['grid']) + len(res['named'])} (side x configuration).",
        f"- Configurations whose CI lies above 0: {len(pos)}.",
        f"- The sign of the mean {'depends' if len(sign) > 1 else 'does not depend'} on the "
        "execution assumptions in this grid.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    cfg = CFG
    cal = TradingCalendar(cfg)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set: every run must be registered in validation_runs")
        return 2
    engine = create_engine(url)
    hold = cal.final_holdout_start(END)
    sessions = cal.research_sessions(cfg.history.option_era_start, hold)
    HoldoutGuard(hold, engine).check(sessions)
    commit = code_commit(ROOT)
    pts = points(cfg)
    run_cfg = {
        "model": "mechanical_diagnostic_sensitivity",
        "signal": "every prediction timestamp, CALL and PUT run separately",
        "points": [dataclasses.asdict(p) for p in pts],
        "sensitivity": cfg.sensitivity.model_dump(mode="json"),
        "trade": cfg.trade.model_dump(mode="json"),
        "fills": cfg.fills.model_dump(mode="json"),
        "costs": cfg.costs.model_dump(mode="json"),
        "liquidity": cfg.liquidity.model_dump(mode="json"),
        "labels_option": cfg.labels.option.model_dump(mode="json"),
    }
    run_id = register_run(
        engine,
        run_kind="sensitivity",
        config=run_cfg,
        data_window=(sessions[0], sessions[-1]),
        dataset_id=dataset_id(engine, f"data/features/{cfg.features.version}"),
        code_commit=commit,
        folds=[],
    )
    print(f"registered run {run_id}; {len(pts)} points x 2 sides")
    try:
        parts = []
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            jobs = session_inputs(ROOT, sessions, cal, cfg)
            for i, df in enumerate(pool.map(session_job, jobs, chunksize=2), 1):
                parts.append(df)
                if i % 100 == 0:
                    print(f"sessions {i}/{len(sessions)}", flush=True)
        trades = pl.concat(parts)
        odir = ROOT / "data" / "backtest" / "m12_sensitivity" / run_id
        odir.mkdir(parents=True, exist_ok=True)
        trades.write_parquet(odir / "trades.parquet")
        res = evaluate(trades, pts)
    except Exception as e:
        fail_run(engine, run_id, repr(e))
        raise
    complete_run(engine, run_id, res)
    write_report(
        res,
        {
            "commit": commit,
            "run_id": run_id,
            "n_sessions": len(sessions),
            "first": sessions[0],
            "last": sessions[-1],
            "hold": hold,
        },
    )
    engine.dispose()
    print(f"completed run {run_id}; report {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
