"""M19R Stage 2: pre-declared experiments E1-E4 (owner option a; 4 of a 6-trial budget).

  E1  f3 (f2 + extras) + Model 2 (LightGBM grid, selection on calibration blocks), C_call / C_put
  E2  E1 + the D1 implied inputs (x1 at m = primary magnitude, x2, x3) as features
  E3  f3 + Model 1 (L2 logistic, C chosen on calibration blocks), C_call / C_put
  E4  f3 + Model 2, C_put only

Per fold and target: fit on train, select on the calibration block, score the test block;
calibrate with the M13 recipe on the calibration block (`fit_calibration`), apply to the test
block. Reported per experiment x target: gate 6 (raw-score BSS vs conditional Model 0, CI and
fold share), gate 12 (calibrated test probabilities, ADR-0009), and lift of the top 10% / 2% / 1%
vs the median breakeven. Each experiment is one registered run (a trial). Holdout locked
(ADR-0011): pre-holdout sessions only.

    uv run python scripts/m19r_experiments.py [--only E1,E3]
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from dotenv import load_dotenv
from sqlalchemy import create_engine

from qqq1dte.backtesting.bootstrap import session_bootstrap_ci
from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import block_rows, code_commit, dataset_id
from qqq1dte.backtesting.registry import complete_run, fail_run, register_run
from qqq1dte.backtesting.reporting import net_from_frame, summarize_net
from qqq1dte.backtesting.splits import Fold, walk_forward_folds
from qqq1dte.calibration.fit import fit_calibration
from qqq1dte.calibration.metrics import gate12, wilson_ci
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.execution_sim.fills import round_trip_costs
from qqq1dte.features.engine import FEATURE_NAMES
from qqq1dte.models.baseline import fit_baseline
from qqq1dte.models.design import KEYS, fit_design, transform, wide_features
from qqq1dte.models.gbm import select_params
from qqq1dte.models.implied import implied_inputs
from qqq1dte.models.lift import lift_table
from qqq1dte.models.logistic import fit_logistic, select_c
from qqq1dte.models.metrics import brier

ROOT = Path(__file__).resolve().parents[1]
END = date(2026, 10, 2)
REPORT = ROOT / "reports" / "research" / "m19r_experiments.md"
REPORT_2B = ROOT / "reports" / "research" / "m19r_tail_rule.md"
CFG = load_config()
F3 = [*FEATURE_NAMES, *CFG.features_f3.extra_features]
EXPERIMENTS: dict[str, dict[str, Any]] = {
    "E1": {"family": "gbm", "implied": False, "targets": ["C_call", "C_put"]},
    "E2": {"family": "gbm", "implied": True, "targets": ["C_call", "C_put"]},
    "E3": {"family": "logistic", "implied": False, "targets": ["C_call", "C_put"]},
    "E4": {"family": "gbm", "implied": False, "targets": ["C_put"]},
    # Stage 2b (declared before running): E2's C_put model + a score-tail trade rule
    "E5": {"family": "gbm", "implied": True, "targets": ["C_put"], "tail_q": 0.98},
    "E6": {"family": "gbm", "implied": True, "targets": ["C_put"], "tail_q": 0.99},
}
IMPLIED = ["imp_x1", "imp_x2", "imp_x3"]


def load(sessions: list[date], cal: TradingCalendar) -> tuple[pl.DataFrame, pl.DataFrame]:
    fdir = ROOT / "data" / "features"
    wide = pl.concat(
        [
            wide_features(
                pl.concat(
                    [
                        pl.read_parquet(fdir / CFG.features.version / f"session={d}.parquet"),
                        pl.read_parquet(fdir / CFG.features_f3.extras_dir / f"session={d}.parquet"),
                    ]
                ),
                F3,
            )
            for d in sessions
        ]
    )
    x = implied_inputs(wide, CFG.labels.magnitude.thresholds[0], cal, CFG)
    wide = wide.with_columns(**{n: pl.Series(x[:, i]) for i, n in enumerate(IMPLIED)})
    ldir = ROOT / "data" / "labels" / CFG.labels.version
    labels = pl.concat(
        [
            pl.read_parquet(ldir / f"session={d}.parquet").select(
                *KEYS, "label_id", "variant", pl.col("value").alias("y")
            )
            for d in sessions
        ]
    )
    return wide, labels


def _fit_score(
    exp: dict[str, Any], tr: pl.DataFrame, ca: pl.DataFrame, te: pl.DataFrame, feats: list[str]
) -> tuple[np.ndarray, np.ndarray, str]:
    y_tr, y_ca = (d["y"].cast(pl.Float64).to_numpy() for d in (tr, ca))
    if exp["family"] == "gbm":
        xt, xc, xs = (d.select(feats).to_numpy().astype(np.float64) for d in (tr, ca, te))
        best, _ = select_params(xt, y_tr, xc, y_ca, CFG.models.gbm, feats)
        return best.predict(xc), best.predict(xs), f"{best.params} trees {best.best_iteration}"
    design = fit_design(tr.select(*KEYS, *feats), CFG.models.logistic.z_clip)
    x_tr, _ = transform(design, tr)
    x_ca, _ = transform(design, ca)
    x_te, _ = transform(design, te)
    c, _ = select_c(x_tr, y_tr, x_ca, y_ca, CFG.models.logistic)
    coef, b = fit_logistic(x_tr, y_tr, c, CFG.models.logistic)

    def score(x: np.ndarray) -> np.ndarray:
        return np.asarray(1 / (1 + np.exp(-(x @ coef + b))))

    return score(x_ca), score(x_te), f"C={c:g}"


def tail_trades(rows: pl.DataFrame, tgt: str) -> dict[str, Any]:
    """Every tail timestamp as one trade with the C label's conservative-fill outcome."""
    side = {"C_call": "C", "C_put": "P"}[tgt]
    odir = ROOT / "data" / "labels" / f"{CFG.labels.version}_option"
    days = rows["session_date"].unique().to_list()
    det = (
        pl.concat([pl.read_parquet(odir / f"session={d}.parquet") for d in days])
        .filter(pl.col("side") == side)
        .select("prediction_ts", "entry_price", "exit_price", "net_pnl")
    )
    t = rows.join(det, on="prediction_ts", how="inner").drop_nulls("net_pnl")
    size = CFG.trade.contracts * 100
    comm, fees = round_trip_costs(CFG)
    t = t.with_columns(
        gross_pnl=(pl.col("exit_price") - pl.col("entry_price")) * size,
        commissions=pl.lit(comm),
        fees=pl.lit(fees),
    )
    net = summarize_net(net_from_frame(t), t["session_date"].to_list(), CFG)  # gate 9
    wins = float(t["y"].cast(pl.Float64).mean() or 0.0)  # type: ignore[arg-type]
    lo, hi = wilson_ci(wins, t.height, CFG.models.metrics.ci_level) if t.height else (0.0, 0.0)
    return {
        "trades": t.height,
        "sessions": t["session_date"].n_unique(),
        "win_rate": wins,
        "win_ci": [lo, hi],
        "mean_net": net.mean,
        "net_ci": list(net.ci),
        "median_net": net.median,
    }


def _bss_fn(y: np.ndarray, p: np.ndarray, ref: np.ndarray) -> Any:
    return lambda w: 1 - brier(y, p, w) / brier(y, ref, w)


def run_experiment(
    name: str, wide: pl.DataFrame, labels: pl.DataFrame, folds: list[Fold], breakeven: float
) -> dict[str, Any]:
    exp = EXPERIMENTS[name]
    # the wide f3 columns (day_of_week one-hot) plus, for E2, the implied inputs
    feats = [c for c in wide.columns if c not in (*KEYS, *IMPLIED)] + (
        IMPLIED if exp["implied"] else []
    )
    out: dict[str, Any] = {}
    m = CFG.models.metrics
    for tgt in exp["targets"]:
        t = labels.filter((pl.col("label_id") == tgt) & (pl.col("variant") == ""))
        parts: list[pl.DataFrame] = []
        tail_parts: list[pl.DataFrame] = []
        per_fold: list[dict[str, Any]] = []
        for f in folds:
            tr, ca, te = (block_rows(wide, t, b) for b in (f.train, f.calib, f.test))
            raw_ca, raw_te, sel = _fit_score(exp, tr, ca, te, feats)
            cal = fit_calibration(
                raw_ca,
                ca["y"].cast(pl.Float64).to_numpy(),
                ca["session_date"].to_list(),
                f.train[-1],
                f.test[0],
                CFG,
            )
            m0 = fit_baseline(tr.with_columns(vix=pl.col("vix_prev_close")), CFG.models.baseline)
            y = te["y"].cast(pl.Float64).to_numpy()
            p0 = m0.predict(te.with_columns(vix=pl.col("vix_prev_close")))
            rank = pl.Series(raw_te).rank("average").to_numpy() / len(raw_te)
            if "tail_q" in exp:  # threshold from the calibration block's scores only
                thr = float(np.quantile(raw_ca, exp["tail_q"]))
                tail_parts.append(
                    te.filter(pl.Series(raw_te >= thr)).select("session_date", "prediction_ts", "y")
                )
            parts.append(
                pl.DataFrame(
                    {
                        "session_date": te["session_date"],
                        "y": y,
                        "raw": raw_te,
                        "cal": cal.calibrator.apply(raw_te),
                        "m0": p0,
                        "rank": rank,
                    }
                )
            )
            per_fold.append(
                {
                    "fold": f.index,
                    "selection": sel,
                    "calibration": cal.method,
                    "bss": 1 - brier(y, raw_te) / brier(y, p0),
                }
            )
            print(f"{name} {tgt} fold {f.index}: {sel}", flush=True)
        s = pl.concat(parts)
        y, raw, p0 = s["y"].to_numpy(), s["raw"].to_numpy(), s["m0"].to_numpy()
        lo, hi = session_bootstrap_ci(
            s["session_date"].to_numpy(),
            _bss_fn(y, raw, p0),
            CFG.validation.bootstrap_reps,
            m.bootstrap_seed,
            m.ci_level,
        )
        better = sum(r["bss"] > 0 for r in per_fold)
        g6 = lo > 0 and better / len(folds) >= CFG.validation_gates.min_folds_better_share
        g12 = gate12(y, s["cal"].to_numpy(), CFG)
        lift = lift_table(
            y,
            s["rank"].to_numpy(),
            deciles=False,
            top=CFG.research.lift_quantiles,
            level=m.ci_level,
        )
        tail = tail_trades(pl.concat(tail_parts), tgt) if tail_parts else None
        out[tgt] = {
            "tail": tail,
            "bss": 1 - brier(y, raw) / brier(y, p0),
            "bss_ci": [lo, hi],
            "folds_better": better,
            "gate6_pass": g6,
            "gate12": g12,
            "lift": lift,
            "breakeven": breakeven,
            "per_fold": per_fold,
            "n": s.height,
        }
    return out


def write_report(
    results: dict[str, dict[str, Any]], runs: dict[str, str], commit: str, path: Path
) -> None:
    lines = [
        f"# M19R Stage 2 experiments ({', '.join(results)})",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {commit[:12]}; runs "
        + ", ".join(f"{k} `{v}`" for k, v in runs.items())
        + ". Walk-forward folds 1-7 (test blocks 2024-05-28 → 2026-02-27); holdout locked "
        "(ADR-0011). f3 = f2 + 8 extra features (option mid momentum, put/call imbalance change, "
        "quote size imbalances, QQQ NBBO imbalance); OPRA open interest is not on disk for the "
        "history and was not used.",
        "",
        "Gate 6: raw-score BSS vs conditional Model 0, CI lower bound > 0 and better in ≥ 70% of "
        "folds. Gate 12: calibrated test probabilities (M13 recipe, ADR-0009). Lift: observed "
        "outcome rate in the top 10% / 2% / 1% of within-fold score ranks vs the median breakeven "
        "probability (0.412, M15).",
        "",
        "| experiment | target | BSS vs Model 0 [CI] | folds better | gate 6 | ECE | slope "
        "| bins failed | gate 12 | top 10% | top 2% | top 1% |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, res in results.items():
        for tgt, r in res.items():
            g = r["gate12"]
            lift = {x["bucket"]: x for x in r["lift"]}
            cells = " | ".join(
                f"{lift[b]['observed']:.3f} "
                f"[{lift[b]['wilson_lo']:.3f}, {lift[b]['wilson_hi']:.3f}]"
                for b in ("top 10%", "top 2%", "top 1%")
            )
            lines.append(
                f"| {name} | {tgt} | {r['bss']:+.4f} "
                f"[{r['bss_ci'][0]:+.4f}, {r['bss_ci'][1]:+.4f}] "
                f"| {r['folds_better']}/7 | {'PASS' if r['gate6_pass'] else 'FAIL'} "
                f"| {g['ece']:.4f} | {g['slope']:.3f} | {g['bins_failed']}/{g['bins_checked']} "
                f"| {'PASS' if g['pass'] else 'FAIL'} | {cells} |"
            )
    tails = [(n, t, r["tail"]) for n, res in results.items() for t, r in res.items() if r["tail"]]
    if tails:
        lines += [
            "",
            "## Stage 2b: score-tail trade rule (research test; bypasses the §4.1 rule)",
            "",
            "Trade whenever the raw test score >= the fold's calibration-block score quantile "
            "(E5 0.98, E6 0.99); each tail timestamp is one trade with the C label's "
            "conservative-fill outcome, net of §4.8 costs. Breakeven win rate about 0.412.",
            "",
            "| experiment | target | trades | sessions | win rate [Wilson CI] "
            "| mean net $ [CI] | median net $ |",
            "|---|---|---|---|---|---|---|",
        ]
        for n, t, x in tails:
            lines.append(
                f"| {n} | {t} | {x['trades']:,} | {x['sessions']} | {x['win_rate']:.3f} "
                f"[{x['win_ci'][0]:.3f}, {x['win_ci'][1]:.3f}] | {x['mean_net']:+.2f} "
                f"[{x['net_ci'][0]:+.2f}, {x['net_ci'][1]:+.2f}] | {x['median_net']:+.2f} |"
            )
    lines += [
        "",
        "Reference (f2, M9 / M13 / M19R D2): C_call BSS +0.0066 [-0.0008, +0.0138], 5/7 folds, "
        "top 10% 0.298, top 1% 0.288; C_put BSS +0.0046 [-0.0020, +0.0116], 5/7 folds, top 10% "
        "0.350, top 1% 0.374. Breakeven ≈ 0.41.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="E1,E2,E3,E4")
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    cal = TradingCalendar(CFG)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set")
        return 2
    engine = create_engine(url)
    hold = cal.final_holdout_start(END)
    sessions = cal.research_sessions(CFG.history.option_era_start, hold)
    HoldoutGuard(hold, engine).check(sessions)
    folds = walk_forward_folds(sessions, hold, CFG)
    commit = code_commit(ROOT)
    fid = dataset_id(engine, f"data/features/{CFG.features_f3.extras_dir}")
    names = [n for n in args.only.split(",") if n in EXPERIMENTS]
    runs = {
        n: register_run(
            engine,
            run_kind="experiment",
            config={
                "model": f"m19r_{n}",
                "experiment": EXPERIMENTS[n],
                "features": F3,
                "extras_dataset": fid,
                "gbm": CFG.models.gbm.model_dump(mode="json"),
                "logistic": CFG.models.logistic.model_dump(mode="json"),
                "calibration": CFG.calibration.model_dump(mode="json"),
            },
            data_window=(folds[0].train[0], folds[-1].test[-1]),
            dataset_id=fid,
            code_commit=commit,
            folds=[],
        )
        for n in names
    }
    print(f"registered {runs}")
    results: dict[str, dict[str, Any]] = {}
    try:
        wide, labels = load(sorted({d for f in folds for d in (*f.train, *f.calib, *f.test)}), cal)
        for n in names:
            results[n] = run_experiment(n, wide, labels, folds, 0.412)
            complete_run(engine, runs[n], results[n])
    except Exception as e:
        for n, r in runs.items():
            if n not in results:
                fail_run(engine, r, repr(e))
        raise
    # Stage 2b gets its own report so the Stage 2 (E1-E4) report is left as generated
    path = REPORT_2B if all("tail_q" in EXPERIMENTS[n] for n in names) else REPORT
    write_report(results, runs, commit, path)
    engine.dispose()
    print(f"report {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
