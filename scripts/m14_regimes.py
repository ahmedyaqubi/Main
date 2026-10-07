"""M14: regime labels R1 (spec §9) and per-regime calibration / baseline expectancy.

Per fold, thresholds (VIX terciles, efficiency-ratio median) are fit on the fold's training
sessions only (T-LEAK-12) and applied to its test block. Labels for every test-block prediction
timestamp go to `regime_labels` (version R1, `thresholds_fit_run` = this run). Then, on the test
blocks only:
- calibration by regime: M13 calibrated probabilities (saved model + calibrator artifacts,
  sha256-checked) of Models 1 and 2, all targets by single-axis bucket, C targets by full cell;
- baseline expectancy by regime: the M12 mechanical baseline trades (conservative, moderate),
  NOT a strategy, net of costs (gate 9);
- OD-9: does the trend axis separate outcomes? Pre-declared (owner Q4): stratified TREND - CHOP
  differences within volatility x event for C_call WIN, C_put WIN, baseline net CALL and PUT
  (conservative); keep the axis if any 95% session-bootstrap CI excludes 0, else propose an ADR.

    uv run python scripts/m14_regimes.py
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
from dotenv import load_dotenv
from sqlalchemy import create_engine

from qqq1dte.backtesting.artifacts import calibrators, model_scorers
from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import (
    TARGETS,
    block_rows,
    code_commit,
    dataset_id,
    load_data,
    target_name,
)
from qqq1dte.backtesting.registry import complete_run, fail_run, register_run
from qqq1dte.backtesting.reporting import net_from_frame
from qqq1dte.backtesting.splits import Fold, walk_forward_folds
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.features.inputs import daily_stats, macro_table, vix_table
from qqq1dte.models.metrics import ece
from qqq1dte.regimes.analysis import stratified_difference, summarize
from qqq1dte.regimes.engine import AXES, RegimeInputs, assign, fit_thresholds, session_state
from qqq1dte.regimes.store import RegimeLabel, write_regime_labels

ROOT = Path(__file__).resolve().parents[1]
END = date(2026, 10, 2)
REPORT = ROOT / "reports" / "regimes" / "regimes_r1.md"
CFG = load_config()
DT = pl.Datetime("us", "UTC")
CELL = ["volatility", "trend", "event"]


def regime_frame(
    inp: RegimeInputs, folds: list[Fold], cal: TradingCalendar
) -> tuple[pl.DataFrame, list[RegimeLabel], list[dict[str, Any]]]:
    """Per test-block prediction timestamp: fold and the three axis values (fold thresholds)."""
    rows, labels, ths = [], [], []
    for f in folds:
        train = [session_state(inp, d, cal.prediction_timestamps(d)[0], cal, CFG) for d in f.train]
        th = fit_thresholds(train, CFG)
        ths.append(
            {
                "fold": f.index,
                "vix_cuts": list(th.vix_cuts),
                "er_median": th.er_median,
                "n_train_sessions": th.n_train_sessions,
                "n_extreme": th.n_extreme,
                "er_unknown_train": sum(s.er is None for s in train),
            }
        )
        for d in f.test:
            for t in cal.prediction_timestamps(d):
                a = assign(session_state(inp, d, t, cal, CFG), th)
                rows.append(
                    {
                        "session_date": d,
                        "prediction_ts": t,
                        "fold": f.index,
                        **{ax: a[ax][0] for ax in AXES},
                    }
                )
                labels += [RegimeLabel(t, ax, v, at) for ax, (v, at) in a.items()]
        print(
            f"regimes fold {f.index}: cuts {th.vix_cuts}, ER median {th.er_median:.3f}", flush=True
        )
    df = pl.DataFrame(rows).with_columns(pl.col("prediction_ts").cast(DT))
    return df, labels, ths


def calibrated_predictions(
    engine: Any, wide: pl.DataFrame, labels: pl.DataFrame, folds: list[Fold]
) -> pl.DataFrame:
    parts = []
    for fam, model_run in CFG.calibration.reference_runs.items():
        scorers = model_scorers(engine, ROOT, fam, model_run)
        cals = calibrators(engine, ROOT, CFG.regimes.calibration_runs[fam])
        for f in folds:
            for lid, var in TARGETS:
                name = target_name(lid, var)
                mid, scorer = scorers[(f.index, name)]
                _, calib = cals[mid]
                t = labels.filter((pl.col("label_id") == lid) & (pl.col("variant") == var))
                te = block_rows(wide, t, f.test)
                parts.append(
                    te.select("session_date", "prediction_ts", "y").with_columns(
                        family=pl.lit(fam),
                        target=pl.lit(name),
                        p=pl.Series(calib.apply(scorer(te))),
                    )
                )
    return pl.concat(parts).with_columns(
        pl.col("prediction_ts").cast(DT), pl.col("y").cast(pl.Float64)
    )


def calibration_tables(pred: pl.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"bucket": [], "cell": []}
    pred = pred.with_columns(sq=(pl.col("p") - pl.col("y")) ** 2)
    keys = [("bucket", [ax]) for ax in AXES] + [("cell", CELL)]
    for (fam, tgt), g in pred.group_by("family", "target", maintain_order=True):
        for kind, by in keys:
            if kind == "cell" and not str(tgt).startswith("C_"):
                continue
            for r in summarize(g, by, "sq", CFG):
                m = g.filter(pl.all_horizontal([pl.col(c) == r[c] for c in by]))
                out[kind].append(
                    {
                        "family": fam,
                        "target": tgt,
                        "axis": "+".join(by),
                        "bucket": "/".join(str(r[c]) for c in by),
                        "n": r["n"],
                        "sessions": r["sessions"],
                        "brier": r["mean"],
                        "brier_ci": r["ci"],
                        "mean_pred": float(m["p"].to_numpy().mean()),
                        "observed": float(m["y"].to_numpy().mean()),
                        "ece": ece(
                            m["y"].to_numpy(), m["p"].to_numpy(), CFG.models.metrics.ece_bins
                        ),
                        "low_support": r["low_support"],
                    }
                )
    return out


def baseline_trades(test_sessions: set[date]) -> pl.DataFrame:
    path = (
        ROOT / "data" / "backtest" / "m12_sensitivity" / CFG.regimes.baseline_run / "trades.parquet"
    )
    t = pl.read_parquet(path).filter(
        pl.col("point").is_in([0, 1])  # named CONSERVATIVE (0) and MODERATE (1) at defaults
        & pl.col("net_pnl").is_not_null()
        & pl.col("session_date").is_in(list(test_sessions))
    )
    nets = net_from_frame(t)  # gate 9: rebuilt from gross and costs, checked against net_pnl
    return t.with_columns(
        net=pl.Series([float(n) for n in nets]), prediction_ts=pl.col("prediction_ts").cast(DT)
    )


def expectancy_tables(trades: pl.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"bucket": [], "cell": []}
    for (model, side), g in trades.group_by("fill_model", "side", maintain_order=True):
        for kind, by in [("bucket", [ax]) for ax in AXES] + [("cell", CELL)]:
            for r in summarize(g, by, "net", CFG, trades=True):
                out[kind].append(
                    {
                        "fill_model": model,
                        "side": side,
                        "axis": "+".join(by),
                        "bucket": "/".join(str(r[c]) for c in by),
                        "trades": r["n"],
                        "sessions": r["sessions"],
                        "mean_net": r["mean"],
                        "ci": r["ci"],
                        "low_support": r["low_support"],
                    }
                )
    return out


def od9(c_labels: pl.DataFrame, trades: pl.DataFrame) -> dict[str, Any]:
    strata = ["volatility", "event"]
    res = {}
    for side, lid in (("C", "C_call"), ("P", "C_put")):
        res[f"{lid} WIN rate"] = stratified_difference(
            c_labels.filter(pl.col("label_id") == lid), "y", strata, CFG
        )
        res[f"baseline net {'CALL' if side == 'C' else 'PUT'} (conservative)"] = (
            stratified_difference(
                trades.filter((pl.col("side") == side) & (pl.col("fill_model") == "CONSERVATIVE")),
                "net",
                strata,
                CFG,
            )
        )
    keep = any(r["ci"][0] > 0 or r["ci"][1] < 0 for r in res.values())
    return {"tests": res, "keep_trend_axis": keep}


def _support(low: bool) -> str:
    return "LOW_SUPPORT" if low else "ok"


def _ci(lo_hi: list[float], fmt: str = "+.4f") -> str:
    return f"[{format(lo_hi[0], fmt)}, {format(lo_hi[1], fmt)}]"


def write_report(meta: dict[str, Any], res: dict[str, Any]) -> None:
    rc = CFG.regimes
    lines = [
        f"# Regime analysis {rc.version} (spec §9)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {meta['commit'][:12]}, run "
        f"`{meta['run_id']}`. Test blocks {meta['first']} → {meta['last']} "
        f"({meta['n_sessions']} sessions); final holdout (after {meta['hold']}) not opened.",
        "",
        "**Definitions.** Volatility: prior-session VIX close vs tercile cuts of the fold's "
        "training sessions (EXTREME merged into HIGH; training sessions with VIX ≥ "
        f"{rc.extreme_vix:g} counted). Trend: efficiency ratio of the last "
        f"{rc.er_window_sessions} daily moves to the prior close, TREND above the training "
        f"median else CHOP. Event: MACRO if {', '.join(rc.macro_events)} is scheduled on the "
        "session and known by T. LOW_SUPPORT: fewer than "
        f"{rc.low_support_sessions} sessions (or {rc.low_support_trades} trades for trade "
        "tables); such cells are reported but never used to gate decisions. CIs: session-block "
        f"bootstrap, {CFG.validation.bootstrap_reps} reps, {CFG.models.metrics.ci_level:.0%}.",
        "",
        "## Thresholds per fold (fit on training sessions only, T-LEAK-12)",
        "",
        "| fold | VIX cuts | ER median | training sessions | training VIX ≥ extreme "
        "| training ER unknown |",
        "|---|---|---|---|---|---|",
        *[
            f"| {t['fold']} | {t['vix_cuts'][0]:.2f} / {t['vix_cuts'][1]:.2f} "
            f"| {t['er_median']:.3f} | {t['n_train_sessions']} | {t['n_extreme']} "
            f"| {t['er_unknown_train']} |"
            for t in res["thresholds"]
        ],
        "",
        "## Sessions per regime cell (test blocks)",
        "",
        "| cell | " + " | ".join(f"fold {k}" for k in meta["folds"]) + " | pooled | support |",
        "|---|" + "---|" * (len(meta["folds"]) + 2),
        *[
            f"| {c['cell']} | "
            + " | ".join(str(c["per_fold"].get(k, 0)) for k in meta["folds"])
            + f" | {c['pooled']} | {_support(c['pooled'] < rc.low_support_sessions)} |"
            for c in res["cell_counts"]
        ],
    ]
    o = res["od9"]
    lines += [
        "",
        "## OD-9: does the trend axis separate outcomes?",
        "",
        "Pre-declared test (owner, M14 Q4): stratified TREND - CHOP difference within "
        "volatility x event cells; keep the axis if any 95% CI excludes 0.",
        "",
        "| quantity | TREND - CHOP | 95% CI | strata |",
        "|---|---|---|---|",
        *[
            f"| {k} | {r['difference']:+.4f} | {_ci(r['ci'])} | {r['strata']} |"
            for k, r in o["tests"].items()
        ],
        "",
        "**Result: "
        + (
            "keep the trend axis (12 cells)"
            if o["keep_trend_axis"]
            else "no separation: propose an ADR to collapse to 6 cells (volatility x event)"
        )
        + ".**",
    ]
    for kind, title in (("bucket", "single-axis buckets"), ("cell", "full cells")):
        rows = res["expectancy"][kind]
        lines += [
            "",
            f"## Baseline expectancy by {title} (mechanical baseline, NOT a strategy; net $)",
            "",
            "| fill | side | axis | bucket | trades | sessions | mean net $ [CI] | support |",
            "|---|---|---|---|---|---|---|---|",
            *[
                f"| {r['fill_model']} | {r['side']} | {r['axis']} | {r['bucket']} "
                f"| {r['trades']:,} "
                f"| {r['sessions']} | {r['mean_net']:+.2f} {_ci(r['ci'], '+.2f')} "
                f"| {'LOW_SUPPORT' if r['low_support'] else 'ok'} |"
                for r in rows
            ],
        ]
    for kind, title in (("bucket", "single-axis buckets"), ("cell", "full cells, C targets")):
        rows = res["calibration"][kind]
        lines += [
            "",
            f"## Calibrated probabilities by {title} (test blocks)",
            "",
            "| model | target | axis | bucket | n | sessions | mean predicted | observed "
            "| obs - pred | Brier [CI] | ECE | support |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
            *[
                f"| {r['family']} | {r['target']} | {r['axis']} | {r['bucket']} | {r['n']:,} "
                f"| {r['sessions']} | {r['mean_pred']:.3f} | {r['observed']:.3f} "
                f"| {r['observed'] - r['mean_pred']:+.3f} | {r['brier']:.4f} {_ci(r['brier_ci'])} "
                f"| {r['ece']:.4f} | {'LOW_SUPPORT' if r['low_support'] else 'ok'} |"
                for r in rows
            ],
        ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    load_dotenv(ROOT / ".env")
    cal = TradingCalendar(CFG)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set: every run must be registered in validation_runs")
        return 2
    engine = create_engine(url)
    hold = cal.final_holdout_start(END)
    sessions = cal.research_sessions(CFG.history.option_era_start, hold)
    HoldoutGuard(hold, engine).check(sessions)
    folds = walk_forward_folds(sessions, hold, CFG)
    test_sessions = {d for f in folds for d in f.test}
    commit = code_commit(ROOT)
    window = (folds[0].train[0], folds[-1].test[-1])
    run_id = register_run(
        engine,
        run_kind="regime",
        config={
            "model": "regimes",
            "regimes": CFG.regimes.model_dump(mode="json"),
            "validation": CFG.validation.model_dump(mode="json"),
        },
        data_window=window,
        dataset_id=dataset_id(engine, f"data/features/{CFG.features.version}"),
        code_commit=commit,
        folds=[
            {
                "fold": f.index,
                "train": [str(f.train[0]), str(f.train[-1])],
                "test": [str(f.test[0]), str(f.test[-1])],
            }
            for f in folds
        ],
    )
    print(f"registered run {run_id}")
    try:
        bars = pl.read_parquet(
            ROOT / "data" / "clean" / "cleaned" / "cleaned_market_data" / "ohlcv-1m" / "QQQ.parquet"
        )
        inp = RegimeInputs(
            daily_stats(bars).select("session_date", "close", "available_at"),
            vix_table(ROOT / "data" / "raw" / "cboe" / "VIX_History.csv", CFG),
            macro_table(ROOT / "configs" / "reference" / "macro_calendar.csv"),
        )
        reg, rlabels, ths = regime_frame(inp, folds, cal)
        n_new = write_regime_labels(engine, rlabels, run_id, CFG.regimes.version)
        sess = reg.unique(["session_date"]).with_columns(
            cell=pl.concat_str([pl.col(c) for c in CELL], separator="/")
        )
        counts = []
        for (cell_v,), g in sess.group_by("cell", maintain_order=True):
            pf = {r["fold"]: r["len"] for r in g.group_by("fold").len().to_dicts()}
            counts.append({"cell": cell_v, "per_fold": pf, "pooled": g.height})
        counts.sort(key=lambda c: c["cell"])
        wide, labels = load_data(ROOT, CFG, sorted(test_sessions))
        pred = calibrated_predictions(engine, wide, labels, folds).join(
            reg, on=["session_date", "prediction_ts"], how="inner"
        )
        trades = baseline_trades(test_sessions).join(
            reg, on=["session_date", "prediction_ts"], how="inner"
        )
        c_lab = (
            labels.filter(pl.col("label_id").is_in(["C_call", "C_put"]) & pl.col("y").is_not_null())
            .with_columns(pl.col("prediction_ts").cast(DT), pl.col("y").cast(pl.Float64))
            .join(reg, on=["session_date", "prediction_ts"], how="inner")
        )
        res: dict[str, Any] = {
            "thresholds": ths,
            "cell_counts": counts,
            "calibration": calibration_tables(pred),
            "expectancy": expectancy_tables(trades),
            "od9": od9(c_lab, trades),
            "labels": {"total": len(rlabels), "inserted": n_new},
        }
    except Exception as e:
        fail_run(engine, run_id, repr(e))
        raise
    keep = bool(res["od9"]["keep_trend_axis"])
    complete_run(engine, run_id, res)
    write_report(
        {
            "commit": commit,
            "run_id": run_id,
            "first": min(test_sessions),
            "last": max(test_sessions),
            "n_sessions": len(test_sessions),
            "hold": hold,
            "folds": [f.index for f in folds],
        },
        res,
    )
    engine.dispose()
    print(f"completed run {run_id}; report {REPORT.relative_to(ROOT)}; keep trend axis: {keep}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
