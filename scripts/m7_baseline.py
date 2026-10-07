"""M7: Model 0 (base rates) over the chronological walk-forward; write reports/models/.

For each of the 7 folds and 10 targets: fit unconditional and conditional (time-of-day bucket x
VIX tercile, shrunk) rates on the training sessions only, score the test block, and report
Brier, log loss and ECE with session-block bootstrap CIs. The run is registered in
`validation_runs` BEFORE any evaluation and completed with its metrics afterwards.

Only pre-holdout session files are opened; the HoldoutGuard is checked on the session list.

    uv run python scripts/m7_baseline.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import polars as pl
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text

from qqq1dte.backtesting.bootstrap import session_bootstrap_ci
from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.registry import complete_run, fail_run, n_trials, register_run
from qqq1dte.backtesting.splits import Fold, walk_forward_folds
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config, load_config
from qqq1dte.models.baseline import fit_baseline
from qqq1dte.models.metrics import brier, ece, log_loss, n_effective

ROOT = Path(__file__).resolve().parents[1]
END = date(2026, 10, 2)  # last research session on disk (M4 history)
REPORT = ROOT / "reports" / "models" / "baseline_m0.md"
TARGETS = [
    ("A_up", ""),
    ("A_dn", ""),
    ("B_up", "m=0.0025"),
    ("B_dn", "m=0.0025"),
    ("B_up", "m=0.005"),
    ("B_dn", "m=0.005"),
    ("C_call", ""),
    ("C_put", ""),
    ("D_call", ""),
    ("D_put", ""),
]
Arr = npt.NDArray[np.float64]


def _name(label_id: str, variant: str) -> str:
    return f"{label_id}[{variant}]" if variant else label_id


def load_rows(cfg: Phase1Config, sessions: list[date]) -> pl.DataFrame:
    """One row per (session, prediction_ts, target): y = label value (null = unresolved)."""
    fdir = ROOT / "data" / "features" / cfg.features.version
    ldir = ROOT / "data" / "labels" / cfg.labels.version
    vix = pl.concat(
        [
            pl.read_parquet(fdir / f"session={d}.parquet")
            .filter(pl.col("feature_name") == "vix_prev_close")
            .select("session_date", "prediction_ts", pl.col("value").alias("vix"))
            for d in sessions
        ]
    )
    labels = pl.concat(
        [
            pl.read_parquet(ldir / f"session={d}.parquet").select(
                "session_date", "prediction_ts", "label_id", "variant", pl.col("value").alias("y")
            )
            for d in sessions
        ]
    )
    return labels.join(vix, on=["session_date", "prediction_ts"], how="left", validate="m:1")


def _ci(sid: npt.NDArray[Any], fn: Callable[[Arr], float], cfg: Phase1Config) -> list[float]:
    m = cfg.models.metrics
    lo, hi = session_bootstrap_ci(
        sid, fn, cfg.validation.bootstrap_reps, m.bootstrap_seed, m.ci_level
    )
    return [lo, hi]


def score(y: Arr, p: Arr, sid: npt.NDArray[Any], cfg: Phase1Config) -> dict[str, Any]:
    bins = cfg.models.metrics.ece_bins
    return {
        "brier": brier(y, p),
        "brier_ci": _ci(sid, lambda w: brier(y, p, w), cfg),
        "log_loss": log_loss(y, p),
        "log_loss_ci": _ci(sid, lambda w: log_loss(y, p, w), cfg),
        "ece": ece(y, p, bins),
        "ece_ci": _ci(sid, lambda w: ece(y, p, bins, w), cfg),
    }


def _bss(y: Arr, pu: Arr, pc: Arr) -> Callable[[Arr], float]:
    return lambda w: 1 - brier(y, pc, w) / brier(y, pu, w)


def evaluate(
    rows: pl.DataFrame, folds: list[Fold], cfg: Phase1Config, window_minutes: int
) -> dict[str, Any]:
    horizon = cfg.labels.horizon_minutes
    out: dict[str, Any] = {"per_fold": [], "pooled": {}}
    pooled: dict[str, list[pl.DataFrame]] = {}
    for f in folds:
        for lid, var in TARGETS:
            t = rows.filter((pl.col("label_id") == lid) & (pl.col("variant") == var))
            train = t.filter(pl.col("session_date").is_in(list(f.train)))
            test = t.filter(pl.col("session_date").is_in(list(f.test)))
            model = fit_baseline(train, cfg.models.baseline)
            resolved = test.filter(pl.col("y").is_not_null())
            scored = resolved.with_columns(
                p_uncond=pl.Series(model.predict_unconditional(resolved)),
                p_cond=pl.Series(model.predict(resolved)),
            )
            pooled.setdefault(_name(lid, var), []).append(scored)
            y = scored["y"].cast(pl.Float64).to_numpy()
            sid = scored["session_date"].to_numpy()
            n_sess = scored["session_date"].n_unique()
            out["per_fold"].append(
                {
                    "fold": f.index,
                    "target": _name(lid, var),
                    "train_rate": model.p0,
                    "n_train": model.n_train,
                    "vix_cuts": list(model.vix_cuts),
                    "test_rate": float(y.mean()),
                    "n_predictions": scored.height,
                    "n_unresolved": test.height - scored.height,
                    "n_sessions": n_sess,
                    "n_effective": n_effective(n_sess, window_minutes, horizon),
                    "uncond": score(y, scored["p_uncond"].to_numpy(), sid, cfg),
                    "cond": score(y, scored["p_cond"].to_numpy(), sid, cfg),
                }
            )
            print(f"fold {f.index} {_name(lid, var)}: n={scored.height}", flush=True)
    for name, parts in pooled.items():
        s = pl.concat(parts)
        y = s["y"].cast(pl.Float64).to_numpy()
        pu, pc = s["p_uncond"].to_numpy(), s["p_cond"].to_numpy()
        sid = s["session_date"].to_numpy()
        n_sess = s["session_date"].n_unique()
        out["pooled"][name] = {
            "test_rate": float(y.mean()),
            "n_predictions": s.height,
            "n_sessions": n_sess,
            "n_effective": n_effective(n_sess, window_minutes, horizon),
            "uncond": score(y, pu, sid, cfg),
            "cond": score(y, pc, sid, cfg),
            # Brier skill of conditional over unconditional (positive = conditional better)
            "bss_cond_vs_uncond": 1 - brier(y, pc) / brier(y, pu),
            "bss_ci": _ci(sid, _bss(y, pu, pc), cfg),
        }
        print(f"pooled {name}", flush=True)
    return out


def _f(x: float) -> str:
    return f"{x:.4f}"


def _m(d: dict[str, Any], k: str) -> str:
    lo, hi = d[f"{k}_ci"]
    return f"{_f(d[k])} [{_f(lo)}, {_f(hi)}]"


def write_report(res: dict[str, Any], meta: dict[str, Any]) -> None:
    lines = [
        "# Model 0 (base rates): out-of-sample walk-forward results",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {meta['commit'][:12]}, "
        f"run `{meta['run_id']}` (config hash {meta['config_hash'][:12]}), "
        f"n_trials on this data window = {meta['n_trials']}.",
        "",
        f"Features {meta['features']} (dataset {meta['features_id'][:16]}), labels "
        f"{meta['labels']} (dataset {meta['labels_id'][:16]}). {len(meta['folds'])} folds: "
        f"expanding train from {meta['folds'][0]['train'][0]}, 1-session embargo, 2-month "
        f"calibration block (unused by Model 0), 3-month test blocks "
        f"{meta['folds'][0]['test'][0]} → {meta['folds'][-1]['test'][1]}. Final holdout "
        f"(sessions after {meta['holdout_after']}) was not opened.",
        "",
        "**These are raw base rates, not calibrated probabilities from a model.** Model 0 is "
        "the benchmark later models must beat. CIs: session-block bootstrap, "
        f"{meta['reps']} reps, {meta['level']:.0%}. Predictions within a session overlap "
        f"(5-minute cadence, {meta['horizon']}-minute horizon), so the honest sample size is "
        "n_effective = sessions x floor(315 / 90) = sessions x 3, not n_predictions.",
        "",
        "Unconditional = training base rate. Conditional = rate per (time-of-day bucket "
        f"{meta['tod']} x VIX tercile of `vix_prev_close`, cut points from training sessions), "
        f"shrunk towards the base rate with n0 = {meta['n0']}. D targets are evaluated on "
        "resolved predictions only (an unresolved D label is excluded, and counted). C targets "
        "exclude predictions without a valid contract.",
        "",
        "## Pooled out-of-sample (all test blocks)",
        "",
        "| target | test rate | n pred | sessions | n_eff | Brier uncond | Brier cond "
        "| BSS cond vs uncond | log loss cond | ECE uncond | ECE cond |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, r in res["pooled"].items():
        lo, hi = r["bss_ci"]
        lines.append(
            f"| {name} | {r['test_rate']:.3f} | {r['n_predictions']:,} | {r['n_sessions']} "
            f"| {r['n_effective']:,} | {_m(r['uncond'], 'brier')} | {_m(r['cond'], 'brier')} "
            f"| {r['bss_cond_vs_uncond']:+.4f} [{lo:+.4f}, {hi:+.4f}] "
            f"| {_m(r['cond'], 'log_loss')} | {_m(r['uncond'], 'ece')} | {_m(r['cond'], 'ece')} |"
        )
    lines += [
        "",
        "## Per fold",
        "",
        "| fold | target | train rate | test rate | n pred | unresolved | sessions | n_eff "
        "| Brier uncond | Brier cond | log loss uncond | log loss cond | ECE uncond | ECE cond |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in res["per_fold"]:
        u, c = r["uncond"], r["cond"]
        lines.append(
            f"| {r['fold']} | {r['target']} | {r['train_rate']:.3f} | {r['test_rate']:.3f} "
            f"| {r['n_predictions']:,} | {r['n_unresolved']} | {r['n_sessions']} "
            f"| {r['n_effective']} | {_m(u, 'brier')} | {_m(c, 'brier')} "
            f"| {_m(u, 'log_loss')} | {_m(c, 'log_loss')} | {_m(u, 'ece')} | {_m(c, 'ece')} |"
        )
    lines += [
        "",
        "## Folds",
        "",
        "| fold | train | embargo | calibration | test |",
        "|---|---|---|---|---|",
    ]
    for f in meta["folds"]:
        lines.append(
            f"| {f['fold']} | {f['train'][0]} → {f['train'][1]} ({f['n_train']}) "
            f"| {f['embargo']} | {f['calib'][0]} → {f['calib'][1]} "
            f"| {f['test'][0]} → {f['test'][1]} ({f['n_test']}) |"
        )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _dataset_id(engine: Engine, uri: str) -> str:
    with engine.connect() as c:
        return str(
            c.execute(
                text("SELECT dataset_id FROM dataset_versions WHERE storage_uri = :u"), {"u": uri}
            ).scalar_one()
        )


def main() -> int:
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    cal = TradingCalendar(cfg)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set: every run must be registered in validation_runs")
        return 2
    engine = create_engine(url)
    hold = cal.final_holdout_start(END)
    sessions = cal.research_sessions(cfg.history.option_era_start, hold)
    HoldoutGuard(hold, engine).check(sessions)  # pre-holdout only: raises otherwise
    folds = walk_forward_folds(sessions, hold, cfg)
    used = sorted({d for f in folds for d in (*f.train, *f.test)})
    first_ts = cal.prediction_timestamps(used[0])
    window_minutes = int((first_ts[-1] - first_ts[0]).total_seconds() // 60)
    fold_meta = [
        {
            "fold": f.index,
            "train": [str(f.train[0]), str(f.train[-1])],
            "n_train": len(f.train),
            "embargo": ", ".join(map(str, f.embargo)),
            "calib": [str(f.calib[0]), str(f.calib[-1])],
            "test": [str(f.test[0]), str(f.test[-1])],
            "n_test": len(f.test),
        }
        for f in folds
    ]
    features_id = _dataset_id(engine, f"data/features/{cfg.features.version}")
    labels_id = _dataset_id(engine, f"data/labels/{cfg.labels.version}")
    commit = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
        or "unknown"
    )
    run_cfg = {
        "model": "baseline_m0",
        "baseline": cfg.models.baseline.model_dump(mode="json"),
        "metrics": cfg.models.metrics.model_dump(mode="json"),
        "validation": cfg.validation.model_dump(mode="json"),
        "features": {"version": cfg.features.version, "dataset_id": features_id},
        "labels": {"version": cfg.labels.version, "dataset_id": labels_id},
        "targets": [_name(lid, v) for lid, v in TARGETS],
    }
    window = (folds[0].train[0], folds[-1].test[-1])
    run_id = register_run(
        engine,
        run_kind="walk_forward",
        config=run_cfg,
        data_window=window,
        dataset_id=features_id,
        code_commit=commit,
        folds=fold_meta,
    )
    print(f"registered run {run_id}")
    try:
        rows = load_rows(cfg, used)
        res = evaluate(rows, folds, cfg, window_minutes)
    except Exception as e:
        fail_run(engine, run_id, repr(e))
        raise
    complete_run(engine, run_id, res)
    with engine.connect() as c:
        h = c.execute(
            text("SELECT config_hash FROM validation_runs WHERE run_id = :r"), {"r": run_id}
        ).scalar_one()
    meta = {
        "commit": commit,
        "run_id": run_id,
        "config_hash": h,
        "n_trials": n_trials(engine, *window),
        "features": cfg.features.version,
        "features_id": features_id,
        "labels": cfg.labels.version,
        "labels_id": labels_id,
        "folds": fold_meta,
        "holdout_after": hold,
        "reps": cfg.validation.bootstrap_reps,
        "level": cfg.models.metrics.ci_level,
        "horizon": cfg.labels.horizon_minutes,
        "tod": ", ".join(t.strftime("%H:%M") for t in cfg.models.baseline.tod_bucket_starts),
        "n0": cfg.models.baseline.shrinkage_prior_n,
    }
    write_report(res, meta)
    engine.dispose()
    print(f"completed run {run_id}; report {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
