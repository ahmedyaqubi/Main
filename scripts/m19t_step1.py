"""M19T Step 1 (ADR-0013 D3-D4): the one registered, model-free screen of cells S1-S6 on
development sessions (2020-01-02 -> 2026-04-02). It is a trial: it is registered BEFORE any
statistic is computed, and n_trials is recorded before and after. The holdout is never read.

Inputs: data/labels/<study_1c.labels_dir> (scripts/m19t_build_labels.py, registered dataset).
Output: reports/research/m19t_step1_screen.md and a COMPLETED `screen_1c` run.

    uv run python scripts/m19t_step1.py
    uv run python scripts/m19t_step1.py --dry-run-labels DIR --dry-run-report FILE  # debug
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
import polars as pl
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine

from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import code_commit, dataset_id
from qqq1dte.backtesting.premium_screen import (
    FILLS,
    CellResult,
    breakeven_loss_freq,
    cell_outcome,
    draw_weights,
    era_driven,
    family_outcome,
    guards,
    max_consecutive_losses,
    session_means,
    weighted_means,
)
from qqq1dte.backtesting.registry import complete_run, fail_run, n_trials, register_run
from qqq1dte.backtesting.screen import max_drawdown
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config, config_hash, load_config

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "research" / "m19t_step1_screen.md"
WD = ["Mon", "Tue", "Wed", "Thu", "Fri"]
WORST_SHARE = 0.05
FRIDAY = 4
WEEKEND_GAP_DAYS = 3  # Friday entry, Monday expiry


def dirty() -> bool:
    out = subprocess.run(
        ["git", "status", "--porcelain", "src", "scripts", "configs"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return bool(out.strip())


def load_labels(labels_dir: Path) -> pl.DataFrame:
    frames = [pl.read_parquet(p) for p in sorted(labels_dir.glob("*/session=*.parquet"))]
    return pl.concat(frames, how="diagonal_relaxed")


def era_of(d: date, starts: dict[str, date]) -> str:
    if d < starts["mwf"]:
        return "1 Friday-only"
    return "2 Mon/Wed/Fri" if d < starts["daily"] else "3 daily"


def fmt(x: float | None, nd: int = 2) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def pct(a: float, b: float) -> str:
    return f"{a / b:.1%}" if b else "-"


def describe(sm: pl.DataFrame, trades: pl.DataFrame) -> dict[str, Any]:
    """Point statistics of one row set (no bootstrap)."""
    cons = sm["conservative"].to_numpy()
    ok = trades.filter(pl.col("status") == "OK")
    tnet = ok["net_conservative"].to_numpy()
    k = max(1, math.ceil(WORST_SHARE * len(cons))) if len(cons) else 0
    dd = max_drawdown(cons) if len(cons) else math.nan
    risk = float(sm["max_risk"].mean()) if sm.height else math.nan  # type: ignore[arg-type]
    return {
        "sessions": sm.height,
        "trades": ok.height,
        **{f"mean_{f}": float(sm[f].mean()) if sm.height else math.nan for f in FILLS},  # type: ignore[arg-type]
        "median": float(np.median(cons)) if len(cons) else math.nan,
        "loss_share": float((tnet < 0).mean()) if len(tnet) else math.nan,
        "breakeven": breakeven_loss_freq(tnet) if len(tnet) else math.nan,
        "worst5": float(np.sort(cons)[:k].mean()) if k else math.nan,
        "max_consec": max_consecutive_losses(cons),
        "dd": dd,
        "dd_risk": dd / risk if risk else math.nan,
        "per_risk": float(cons.mean()) / risk if len(cons) and risk else math.nan,
    }


def register(
    engine: Engine, cfg: Phase1Config, window: tuple[date, date], uri: str
) -> tuple[int, str, int]:
    """Register the trial BEFORE any statistic is computed; n_trials before and after."""
    s = cfg.study_1c
    n_before = n_trials(engine, *window)
    run_id = register_run(
        engine,
        run_kind="screen_1c",
        config={
            "study_1c": s.model_dump(mode="json"),
            "phase1_config_hash": config_hash(cfg.model_dump(mode="json")),
            "adr": "ADR-0013 D3",
        },
        data_window=window,
        dataset_id=dataset_id(engine, uri),
        code_commit=code_commit(ROOT),
        folds=[],
    )
    n_after = n_trials(engine, *window)
    print(f"registered {run_id}; n_trials {n_before} -> {n_after}", flush=True)
    return n_before, run_id, n_after


def main() -> int:  # noqa: PLR0912, PLR0915 (linear pipeline)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run-labels", type=Path, default=None)
    ap.add_argument("--dry-run-report", type=Path, default=None)
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    cal = TradingCalendar(cfg)
    s = cfg.study_1c
    window = (s.ext_start, s.dev_end)
    uri = f"data/labels/{s.labels_dir}"
    dry = args.dry_run_labels is not None
    if dry and args.dry_run_labels.resolve() == (ROOT / uri).resolve():
        print("--dry-run-labels must not point at the real labels")
        return 1
    if not dry and dirty():
        print("the screen is a registered trial: commit src/scripts/configs first")
        return 1
    report: Path = args.dry_run_report if dry else REPORT
    if dry and args.dry_run_report is None:
        print("--dry-run-labels needs --dry-run-report")
        return 1
    engine: Engine | None = None
    run_id, n_before, n_after = "dry-run", -1, -1
    if not dry:
        engine = create_engine(os.environ["DATABASE_URL"])
        n_before, run_id, n_after = register(engine, cfg, window, uri)
    try:
        labels = load_labels(args.dry_run_labels if dry else ROOT / uri)
        HoldoutGuard(s.dev_end, None).check(
            labels["session_date"].to_list()
            + labels.filter(pl.col("status") != "EXCLUDED")["expiry"].to_list()
        )
        sessions = [d for d in cal.sessions(*window) if not cal.exclusion_reason(d)]
        pos = {d: i for i, d in enumerate(sessions)}
        weights = draw_weights(len(sessions), cfg.validation.bootstrap_reps,
                               cfg.models.metrics.bootstrap_seed)  # fmt: skip
        degraded = set(s.degraded_days)
        lo_q = 1 - s.lower_bound_level
        hi_q = 1 - (1 - s.kill_level) / 2
        results: list[CellResult] = []
        rows: dict[str, dict[str, Any]] = {}
        sub_rows: list[str] = []
        for name in s.cells:
            t = labels.filter(pl.col("cell") == name).with_columns(
                era=pl.col("session_date").map_elements(
                    lambda d: era_of(d, s.era_starts), return_dtype=pl.String
                ),
                weekday=pl.col("session_date").dt.weekday() - 1,
                gap_days=(pl.col("expiry") - pl.col("session_date")).dt.total_days(),
            )
            sm = (
                session_means(t)
                .join(
                    t.select("session_date", "era", "weekday", "gap_days").unique("session_date"),
                    on="session_date",
                )
                .sort("session_date")
            )
            idx = np.array([pos[d] for d in sm["session_date"].to_list()])
            boot = {f: weighted_means(sm[f].to_numpy(), weights[:, idx]) for f in FILLS}
            n_recent = sm.filter(pl.col("session_date") >= s.recent_from).height
            stats = describe(sm, t)
            barred = guards(stats["trades"], stats["sessions"], n_recent, cfg)
            lb = float(np.nanquantile(boot["conservative"], lo_q))
            ub = float(np.nanquantile(boot["mid"], hi_q))
            flag = era_driven(sm["conservative"].to_numpy(), sm["era"].to_numpy())
            verdict = cell_outcome(lb, ub, barred)
            results.append(
                CellResult(name, verdict, lb, ub, stats["trades"], stats["sessions"], n_recent,
                           barred, flag)
            )  # fmt: skip
            entries = t.height
            by = dict(t.group_by("status").agg(n=pl.len()).iter_rows())
            illiquid = t.filter(pl.col("reason") == "LEG_ILLIQUID").height
            excl = dict(
                t.filter(pl.col("status") == "EXCLUDED").group_by("reason").agg(n=pl.len())
                .iter_rows()
            )  # fmt: skip
            ci = {
                f: (float(np.nanquantile(boot[f], (1 - 0.95) / 2)),
                    float(np.nanquantile(boot[f], 1 - (1 - 0.95) / 2)))
                for f in FILLS
            }  # fmt: skip
            rows[name] = {
                **stats, "lb": lb, "ub": ub, "ci": ci, "outcome": verdict, "barred": barred,
                "era_flag": flag, "recent": n_recent, "entries": entries,
                "no_trade": by.get("NO_TRADE", 0), "unresolved": by.get("UNRESOLVED_DATA", 0),
                "illiquid": illiquid, "excluded": excl,
            }  # fmt: skip
            cell = s.cells[name]
            groups: list[tuple[str, pl.Expr]] = [
                *[(f"era {e}", pl.col("era") == e) for e in sorted(set(sm["era"].to_list()))],
                *[(f"weekday {WD[w]}", pl.col("weekday") == w) for w in range(5)],
                ("without VENDOR_DEGRADED days (R4)",
                 ~pl.col("session_date").is_in(list(degraded))),
            ]  # fmt: skip
            if cell.tenor == "1dte":
                fri_mon = (pl.col("weekday") == FRIDAY) & (pl.col("gap_days") == WEEKEND_GAP_DAYS)
                groups += [
                    ("descriptive: Fri->Mon", fri_mon),
                    ("descriptive: pre-holiday",
                     (pl.col("gap_days") > 1) & ~fri_mon),
                ]  # fmt: skip
            for label, cond in groups:
                g_sm = sm.filter(cond)
                g_t = t.filter(pl.col("session_date").is_in(g_sm["session_date"].to_list()))
                g = describe(g_sm, g_t)
                sub_rows.append(
                    f"| {name} | {label} | {g['sessions']} | {g['trades']} "
                    f"| {fmt(g['mean_conservative'])} | {fmt(g['mean_moderate'])} "
                    f"| {fmt(g['mean_mid'])} | {fmt(g['loss_share'], 3)} "
                    f"| {fmt(g['breakeven'], 3)} |"
                )
        family, advanced = family_outcome(results, cfg)
        metrics = {
            "family_outcome": family,
            "advanced": advanced,
            "n_trials_before": n_before,
            "n_trials_after": n_after,
            "cells": {
                r.cell: {"outcome": r.outcome, "lb_conservative": r.lb_conservative,
                         "ub_mid": r.ub_mid, "n_trades": r.n_trades, "n_sessions": r.n_sessions,
                         "n_recent": r.n_recent, "barred": r.barred, "era_flag": r.era_flag}
                for r in results
            },
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
        "# M19T Step 1: model-free screen of the defined-risk short-premium family (ADR-0013)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m19t_step1.py`, code "
        f"{code_commit(ROOT)[:12]}. Registered run `{run_id}` (n_trials {n_before} → {n_after}). "
        f"Development sessions {window[0]} → {window[1]} only; the holdout was not read.",
        "",
        f"## Family outcome: **{family}**" + (f" (advance: {', '.join(advanced)})" if advanced
                                               else ""),
        "",
        "Rules (D3):",
        f"- **ADVANCE**: one-sided {s.lower_bound_level:.0%} lower bound of the mean net P&L per "
        "session at the conservative fill > 0, and no D4 guard applies.",
        f"- **KILL**: two-sided {s.kill_level:.0%} upper bound at the mid fill < 0.",
        "- **AMBIGUOUS** otherwise. The family is KILL only if every cell is KILL. AMBIGUOUS means "
        f"one pre-registered re-screen after ≥ {s.rescreen_min_new_sessions} new development "
        "sessions, then PARKED.",
        f"- Session-block bootstrap: {cfg.validation.bootstrap_reps} reps, seed "
        f"{cfg.models.metrics.bootstrap_seed}, one shared draw set over all sessions.",
        "",
        "These are development-data results with their uncertainty. They are not a claim of "
        "profitability, and nothing here is out-of-sample.",
        "",
        "## Decision table",
        "",
        "| cell | tenor | structure | X | sessions | from 2023 | trades | mean net/session "
        "(cons) | lower bound (cons) | mean (mid) | upper bound (mid) | guards | era-driven "
        "| outcome |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]  # fmt: skip
    for r in results:
        c, row = s.cells[r.cell], rows[r.cell]
        out.append(
            f"| {r.cell} | {c.tenor} | {c.structure} | {c.x:.2f} | {r.n_sessions} | {r.n_recent} "
            f"| {r.n_trades} | {fmt(row['mean_conservative'])} | {fmt(r.lb_conservative)} "
            f"| {fmt(row['mean_mid'])} | {fmt(r.ub_mid)} | {', '.join(r.barred) or '-'} "
            f"| {'yes' if r.era_flag else 'no'} | **{r.outcome}** |"
        )
    out += [
        "",
        "## D4 columns (pooled, per cell)",
        "",
        "Dollars per 1-lot position. *Mean net*: mean over sessions of each session's mean "
        "trade, with a 95% bootstrap CI. *Loss share*: losing trades at the conservative fill. "
        "*Break-even loss share*: mean win ÷ (mean win + mean loss) on the same trades. *DD*: "
        "maximum drawdown of cumulative session means, in $ and in units of mean max risk.",
        "",
        "| cell | conservative [95% CI] | moderate [95% CI] | mid [95% CI] | median | loss "
        "share | break-even loss share | X | worst 5% | max losing run | DD $ | DD / max risk "
        "| net per $ risk | NO_TRADE | §4.9 rejected | UNRESOLVED | EXCLUDED |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]  # fmt: skip
    for name, row in rows.items():
        ci = row["ci"]
        n_e = row["entries"]
        out.append(
            f"| {name} | "
            + " | ".join(
                f"{fmt(row[f'mean_{f}'])} [{fmt(ci[f][0])}, {fmt(ci[f][1])}]" for f in FILLS
            )
            + f" | {fmt(row['median'])} | {fmt(row['loss_share'], 3)} "
            f"| {fmt(row['breakeven'], 3)} | {s.cells[name].x:.2f} | {fmt(row['worst5'])} "
            f"| {row['max_consec']} | {fmt(row['dd'])} | {fmt(row['dd_risk'])} "
            f"| {fmt(row['per_risk'], 4)} | {pct(row['no_trade'], n_e)} "
            f"| {pct(row['illiquid'], n_e)} | {pct(row['unresolved'], n_e)} "
            f"| {', '.join(f'{k} {v}' for k, v in sorted(row['excluded'].items())) or '-'} |"
        )
    out += [
        "",
        "## Rows by era, weekday and descriptive groups (point estimates; never decisions)",
        "",
        "| cell | rows | sessions | trades | mean cons | mean moderate | mean mid | loss share "
        "| break-even loss share |",
        "|---|---|---|---|---|---|---|---|---|",
        *sub_rows,
        "",
    ]  # fmt: skip
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"family outcome {family} {advanced}; wrote {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
