"""M23 Step 1 (ADR-0014 D5): the one registered, model-free screen of SPX cells L1-L4 on
development sessions (`study_2a.start` -> `study_2a.dev_end`). It is a trial: registered BEFORE
any statistic is computed, with n_trials recorded before and after. The holdout is never read.

Unit: one entry per session per cell; the statistic is the mean net P&L per entered trade.
Uncertainty: a circular moving-block bootstrap over sessions, with block = `block_multiple` x the
cell's median hold (sessions), because 7- and 30-day positions overlap.

Outcomes:
- ADVANCE: the one-sided lower bound at the conservative fill is > 0 and the D5 guards are met.
- KILL: the two-sided upper bound at the mid fill is < 0.
- AMBIGUOUS otherwise.
- Family: at most `max_advance` cell advances.

    uv run python scripts/m23_step1.py
    uv run python scripts/m23_step1.py --dry-run-labels DIR --dry-run-report FILE  # debug
"""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import polars as pl
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine

from m23_build_data import spx_config
from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import code_commit, dataset_id
from qqq1dte.backtesting.premium_screen import (
    CellResult,
    breakeven_loss_freq,
    cell_outcome,
    family_outcome,
    guards_2a,
    independent_periods,
    max_consecutive_losses,
    moving_block_weights,
    weighted_means,
)
from qqq1dte.backtesting.registry import complete_run, fail_run, n_trials, register_run
from qqq1dte.backtesting.screen import max_drawdown
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config, config_hash, load_config
from qqq1dte.execution_sim.longdated import mde_upper_bound

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "research" / "m23_step1_screen.md"
FILLS = ("conservative", "moderate", "mid")
WORST_SHARE = 0.05
Arr = npt.NDArray[np.float64]


def dirty() -> bool:
    out = subprocess.run(
        ["git", "status", "--porcelain", "src", "scripts", "configs"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return bool(out.strip())


def register(
    engine: Engine, cfg: Phase1Config, window: tuple[date, date], uri: str
) -> tuple[int, str, int]:
    """Register the trial BEFORE any statistic is computed; n_trials before and after."""
    n_before = n_trials(engine, *window)
    run_id = register_run(
        engine,
        run_kind="screen_2a",
        config={
            "study_2a": cfg.study_2a.model_dump(mode="json"),
            "phase1_config_hash": config_hash(cfg.model_dump(mode="json")),
            "adr": "ADR-0014 D5",
        },
        data_window=window,
        dataset_id=dataset_id(engine, uri),
        code_commit=code_commit(ROOT),
        folds=[],
    )
    n_after = n_trials(engine, *window)
    print(f"registered {run_id}; n_trials {n_before} -> {n_after}", flush=True)
    return n_before, run_id, n_after


def fmt(x: float | None, nd: int = 2) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:,.{nd}f}"


def pct(a: float, b: float) -> str:
    return f"{a / b:.1%}" if b else "-"


def describe(t: pl.DataFrame) -> dict[str, Any]:
    """Point statistics of OK trades in entry order (1 lot per entry)."""
    cons = t["net_conservative"].to_numpy()
    n = len(cons)
    k = max(1, math.ceil(WORST_SHARE * n)) if n else 0
    risk = float(t["max_risk"].mean()) if n else math.nan  # type: ignore[arg-type]
    dd = max_drawdown(cons) if n else math.nan
    return {
        "trades": n,
        **{f"mean_{f}": float(t[f"net_{f}"].mean()) if n else math.nan for f in FILLS},  # type: ignore[arg-type]
        "median": float(np.median(cons)) if n else math.nan,
        "loss_share": float((cons < 0).mean()) if n else math.nan,
        "breakeven": breakeven_loss_freq(cons) if n else math.nan,
        "worst5": float(np.sort(cons)[:k].mean()) if k else math.nan,
        "worst1": float(cons.min()) if n else math.nan,
        "max_consec": max_consecutive_losses(cons),
        "dd": dd,
        "dd_risk": dd / risk if risk else math.nan,
        "per_risk": float(cons.mean()) / risk if n and risk else math.nan,
        "risk": risk,
        "cost_15": float(np.mean(cons - 0.5 * t["costs_conservative"].to_numpy()))
        if n
        else math.nan,
    }


def main() -> int:  # noqa: PLR0912, PLR0915 (linear pipeline)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run-labels", type=Path, default=None)
    ap.add_argument("--dry-run-report", type=Path, default=None)
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    base = load_config()
    cfg = spx_config(base, "SPXW")
    s = base.study_2a
    cal = TradingCalendar(cfg)
    window = (s.start, s.dev_end)
    uri = f"data/labels/{s.labels_dir}"
    dry = args.dry_run_labels is not None
    if dry and args.dry_run_labels.resolve() == (ROOT / uri).resolve():
        print("--dry-run-labels must not point at the real labels")
        return 1
    if dry and args.dry_run_report is None:
        print("--dry-run-labels needs --dry-run-report")
        return 1
    if not dry and dirty():
        print("the screen is a registered trial: commit src/scripts/configs first")
        return 1
    report: Path = args.dry_run_report if dry else REPORT
    engine: Engine | None = None
    run_id, n_before, n_after = "dry-run", -1, -1
    if not dry:
        engine = create_engine(os.environ["DATABASE_URL"])
        n_before, run_id, n_after = register(engine, base, window, uri)
    try:
        src = args.dry_run_labels if dry else ROOT / uri
        labels = pl.concat(
            [pl.read_parquet(p) for p in sorted(src.glob("*/session=*.parquet"))],
            how="diagonal_relaxed",
        )
        HoldoutGuard(s.dev_end, None).check(
            labels["session_date"].to_list()
            + labels.filter(pl.col("status").is_in(["OK", "UNRESOLVED_DATA"]))[
                "exit_session"
            ].to_list()
        )
        sessions = cal.sessions(*window)
        pos = {d: i for i, d in enumerate(sessions)}
        weights_cache: dict[int, npt.NDArray[np.int64]] = {}
        results: list[CellResult] = []
        rows: dict[str, dict[str, Any]] = {}
        sub_rows: list[str] = []
        lo_q = 1 - s.lower_bound_level
        hi_q = 1 - (1 - s.kill_level) / 2
        for name, cell in s.cells.items():
            t_all = labels.filter(pl.col("cell") == name)
            t = t_all.filter(pl.col("status") == "OK").sort("session_date")
            hold = int(t["hold"].median()) if t.height else 1  # type: ignore[arg-type]
            block = max(1, math.ceil(s.block_multiple * hold))
            if block not in weights_cache:
                weights_cache[block] = moving_block_weights(
                    len(sessions), block, base.validation.bootstrap_reps,
                    base.models.metrics.bootstrap_seed,
                )  # fmt: skip
            w = weights_cache[block]
            idx = np.array([pos[d] for d in t["session_date"].to_list()], dtype=np.int64)
            boot = {f: weighted_means(t[f"net_{f}"].to_numpy(), w[:, idx]) for f in FILLS}
            lb = float(np.nanquantile(boot["conservative"], lo_q))
            ub = float(np.nanquantile(boot["mid"], hi_q))
            ci = {f: (float(np.nanquantile(boot[f], 0.025)), float(np.nanquantile(boot[f], 0.975)))
                  for f in FILLS}  # fmt: skip
            n_ind = independent_periods(idx, hold)
            dates = t["session_date"].to_list()
            years = (max(dates) - min(dates)).days / 365.25 if dates else 0.0
            barred = guards_2a(t.height, n_ind, years, base)
            verdict = cell_outcome(lb, ub, barred)
            results.append(
                CellResult(name, verdict, lb, ub, t.height, t.height,
                           t.filter(pl.col("session_date") >= date(2023, 1, 1)).height,
                           barred, False)
            )  # fmt: skip
            st = describe(t)
            by = dict(t_all.group_by("status").agg(n=pl.len()).iter_rows())
            illiquid = t_all.filter(pl.col("reason") == "LEG_ILLIQUID").height
            excl = dict(
                t_all.filter(pl.col("status") == "EXCLUDED").group_by("reason").agg(n=pl.len())
                .iter_rows()
            )  # fmt: skip
            w_med = float(t["W"].median()) if t.height else math.nan  # type: ignore[arg-type]
            mde = mde_upper_bound(w_med * 100, len(sessions) / hold if hold else 0.0)
            rows[name] = {
                **st, "lb": lb, "ub": ub, "ci": ci, "verdict": verdict, "barred": barred,
                "hold": hold, "block": block, "n_ind": n_ind, "years": years,
                "entries": t_all.height, "no_trade": by.get("NO_TRADE", 0),
                "unresolved": by.get("UNRESOLVED_DATA", 0), "illiquid": illiquid,
                "excluded": excl, "mde": mde, "cell": cell,
            }  # fmt: skip
            for y, g in t.group_by(pl.col("session_date").dt.year().alias("y")):
                gs = describe(g)
                sub_rows.append(
                    f"| {name} | {y[0]} | {gs['trades']} | {fmt(gs['mean_conservative'])} "
                    f"| {fmt(gs['mean_mid'])} | {fmt(gs['loss_share'], 3)} "
                    f"| {fmt(gs['breakeven'], 3)} | {fmt(gs['worst1'])} |"
                )
        family, advanced = family_outcome(results, base, s.max_advance)
        metrics = {
            "family_outcome": family, "advanced": advanced,
            "n_trials_before": n_before, "n_trials_after": n_after,
            "cells": {r.cell: {"outcome": r.outcome, "lb_conservative": r.lb_conservative,
                               "ub_mid": r.ub_mid, "n_trades": r.n_trades, "barred": r.barred}
                      for r in results},
        }  # fmt: skip
        if engine is not None:
            complete_run(engine, run_id, metrics)
    except Exception as e:
        if engine is not None:
            fail_run(engine, run_id, repr(e))
        raise
    if engine is not None:
        engine.dispose()

    out = [
        "# M23 Step 1: model-free screen of SPX longer-dated defined-risk premium (ADR-0014)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m23_step1.py`, code "
        f"{code_commit(ROOT)[:12]}. Registered run `{run_id}` (n_trials {n_before} → {n_after}; "
        f"the window overlaps Phase 1's, whose count was 39). Development sessions {window[0]} → "
        f"{window[1]}; the holdout was not read.",
        "",
        f"## Family outcome: **{family}**" + (f" (advance: {', '.join(advanced)})" if advanced
                                               else ""),
        "",
        "Rules (D5):",
        f"- **ADVANCE**: one-sided {s.lower_bound_level:.0%} lower bound of the mean net P&L per "
        "trade at the conservative fill > 0, with the guards met.",
        f"- **KILL**: two-sided {s.kill_level:.0%} upper bound at the mid fill < 0.",
        "- **AMBIGUOUS** otherwise. That allows one pre-registered re-screen after ≥ "
        f"{s.rescreen_min_new_sessions} new development sessions, then PARKED.",
        f"- Circular moving-block bootstrap: {base.validation.bootstrap_reps} reps, seed "
        f"{base.models.metrics.bootstrap_seed}, block = {s.block_multiple:g} x the median hold.",
        "- Costs: IBKR commission by premium, Cboe SPX fee and regulatory allowance (R3). SPX "
        "surcharges are not included (retail applicability unverified, disclosed).",
        "",
        "These are development-data results with their uncertainty. They are not a claim of "
        "profitability, and nothing here is out-of-sample.",
        "",
        "## Decision table",
        "",
        "| cell | DTE | structure | X | trades | independent periods | years | mean $/trade "
        "(cons) | lower bound (cons) | mean (mid) | upper bound (mid) | guards | outcome |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]  # fmt: skip
    for r in results:
        row = rows[r.cell]
        c = row["cell"]
        out.append(
            f"| {r.cell} | {c.target_dte} | {c.structure} | {c.x:.2f} | {r.n_trades} "
            f"| {row['n_ind']} | {row['years']:.1f} | {fmt(row['mean_conservative'])} "
            f"| {fmt(r.lb_conservative)} | {fmt(row['mean_mid'])} | {fmt(r.ub_mid)} "
            f"| {', '.join(r.barred) or '-'} | **{r.outcome}** |"
        )
    out += [
        "",
        "## Precision vs the Step-0 MDE (R12)",
        "",
        "| cell | median hold | block | realised 95% CI width, conservative ($) | Step-0 MDE "
        "upper bound ($) |",
        "|---|---|---|---|---|",
        *[
            f"| {k} | {v['hold']} | {v['block']} "
            f"| {fmt(v['ci']['conservative'][1] - v['ci']['conservative'][0])} "
            f"| {fmt(v['mde'], 0)} |"
            for k, v in rows.items()
        ],
        "",
        "## D4 columns (pooled, per cell; $ per 1-lot position)",
        "",
        "| cell | conservative [95% CI] | moderate [95% CI] | mid [95% CI] | median | loss share "
        "| break-even loss share | worst 5% | worst trade | max losing run | DD $ | DD / mean "
        "max risk | net per $ risk | mean at 1.5x costs | NO_TRADE | §4.9/R10 rejected "
        "| UNRESOLVED | EXCLUDED |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]  # fmt: skip
    for k, v in rows.items():
        ci = v["ci"]
        n_e = v["entries"]
        out.append(
            f"| {k} | "
            + " | ".join(f"{fmt(v[f'mean_{f}'])} [{fmt(ci[f][0])}, {fmt(ci[f][1])}]" for f in FILLS)
            + f" | {fmt(v['median'])} | {fmt(v['loss_share'], 3)} | {fmt(v['breakeven'], 3)} "
            f"| {fmt(v['worst5'])} | {fmt(v['worst1'])} | {v['max_consec']} | {fmt(v['dd'])} "
            f"| {fmt(v['dd_risk'])} | {fmt(v['per_risk'], 4)} | {fmt(v['cost_15'])} "
            f"| {pct(v['no_trade'], n_e)} | {pct(v['illiquid'], n_e)} "
            f"| {pct(v['unresolved'], n_e)} "
            f"| {', '.join(f'{a} {b}' for a, b in sorted(v['excluded'].items())) or '-'} |"
        )
    out += [
        "",
        "DD is the drawdown of the cumulative P&L of one lot entered every session (overlapping "
        "positions), so it scales with the number of open positions, not with one trade.",
        "",
        "## Per-year rows (point estimates; never decisions)",
        "",
        "| cell | year | trades | mean cons | mean mid | loss share | break-even loss share "
        "| worst trade |",
        "|---|---|---|---|---|---|---|---|",
        *sorted(sub_rows),
        "",
    ]  # fmt: skip
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"family outcome {family} {advanced}; wrote {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
