"""M8: Model 1 (L2 logistic regression) over the chronological walk-forward; write reports/models/.

Per fold and target: design (standardisation, fills, indicators) fit on train only; C chosen
from the configured grid by calibration-block log loss (fit on train); the chosen model scores
the test block. Compared with Model 0 (refit here identically, fit on train) via Brier skill with
session-block bootstrap CIs. Scores are UNCALIBRATED (rule 6).

Registry (spec §10): one `validation_runs` row per grid point (evaluated on the calibration
blocks) plus one for the out-of-sample run, all registered before any evaluation. Each fitted
model is saved as JSON and recorded in `model_versions` as CANDIDATE.

    uv run python scripts/m8_logistic.py
"""

from __future__ import annotations

import os
import re
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
from qqq1dte.backtesting.registry import (
    ModelVersion,
    complete_run,
    fail_run,
    n_trials,
    record_model_version,
    register_run,
)
from qqq1dte.backtesting.splits import Fold, walk_forward_folds
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config, load_config
from qqq1dte.features.engine import FEATURE_NAMES
from qqq1dte.models.baseline import fit_baseline
from qqq1dte.models.design import KEYS, fit_design, transform, wide_features
from qqq1dte.models.logistic import LogisticModel, fit_logistic, save, select_c
from qqq1dte.models.metrics import brier, ece, log_loss, n_effective

ROOT = Path(__file__).resolve().parents[1]
END = date(2026, 10, 2)  # last research session on disk (M4 history)
REPORT = ROOT / "reports" / "models" / "logistic_m1.md"
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


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "_", name).strip("_")


def load_data(cfg: Phase1Config, sessions: list[date]) -> tuple[pl.DataFrame, pl.DataFrame]:
    fdir = ROOT / "data" / "features" / cfg.features.version
    ldir = ROOT / "data" / "labels" / cfg.labels.version
    wide = pl.concat(
        [
            wide_features(pl.read_parquet(fdir / f"session={d}.parquet"), FEATURE_NAMES)
            for d in sessions
        ]
    )
    labels = pl.concat(
        [
            pl.read_parquet(ldir / f"session={d}.parquet").select(
                *KEYS, "label_id", "variant", pl.col("value").alias("y")
            )
            for d in sessions
        ]
    )
    return wide, labels


def _ci(sid: npt.NDArray[Any], fn: Callable[[Arr], float], cfg: Phase1Config) -> list[float]:
    m = cfg.models.metrics
    lo, hi = session_bootstrap_ci(
        sid, fn, cfg.validation.bootstrap_reps, m.bootstrap_seed, m.ci_level
    )
    return [lo, hi]


def _bss(y: Arr, p: Arr, ref: Arr) -> Callable[[Arr], float]:
    return lambda w: 1 - brier(y, p, w) / brier(y, ref, w)


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


def skill(
    y: Arr, p: Arr, refs: dict[str, Arr], sid: npt.NDArray[Any], cfg: Phase1Config
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, ref in refs.items():
        out[f"bss_vs_{k}"] = 1 - brier(y, p) / brier(y, ref)
        out[f"bss_vs_{k}_ci"] = _ci(sid, _bss(y, p, ref), cfg)
    return out


def _xy(wide: pl.DataFrame, t: pl.DataFrame, block: tuple[date, ...]) -> pl.DataFrame:
    rows = t.filter(pl.col("session_date").is_in(list(block)) & pl.col("y").is_not_null())
    return wide.join(rows.select(*KEYS, "y"), on=KEYS, how="inner", validate="1:1").sort(KEYS)


def _vix(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(vix=pl.col("vix_prev_close"))


def evaluate(
    wide: pl.DataFrame,
    labels: pl.DataFrame,
    folds: list[Fold],
    cfg: Phase1Config,
    window_minutes: int,
    save_model: Callable[[Fold, str, LogisticModel, dict[str, Any]], None],
) -> dict[str, Any]:
    lcfg = cfg.models.logistic
    horizon = cfg.labels.horizon_minutes
    out: dict[str, Any] = {"per_fold": [], "pooled": {}}
    pooled: dict[str, list[pl.DataFrame]] = {}
    for f in folds:
        for lid, var in TARGETS:
            name = _name(lid, var)
            t = labels.filter((pl.col("label_id") == lid) & (pl.col("variant") == var))
            tr, ca, te = _xy(wide, t, f.train), _xy(wide, t, f.calib), _xy(wide, t, f.test)
            design = fit_design(tr.drop("y"), lcfg.z_clip)
            x_tr, fill_tr = transform(design, tr)
            x_ca, _ = transform(design, ca)
            x_te, fill_te = transform(design, te)
            y_tr, y_ca = tr["y"].cast(pl.Float64).to_numpy(), ca["y"].cast(pl.Float64).to_numpy()
            c, calib_losses = select_c(x_tr, y_tr, x_ca, y_ca, lcfg)
            coef, b = fit_logistic(x_tr, y_tr, c, lcfg)
            model = LogisticModel(design, tuple(float(v) for v in coef), b, c)
            m0 = fit_baseline(_vix(tr), cfg.models.baseline)
            scored = te.select(*KEYS, "y").with_columns(
                p_m1=pl.Series(model.score_matrix(x_te)),
                p_m0c=pl.Series(m0.predict(_vix(te))),
                p_m0u=pl.Series(m0.predict_unconditional(te)),
            )
            pooled.setdefault(name, []).append(scored)
            y = scored["y"].cast(pl.Float64).to_numpy()
            sid = scored["session_date"].to_numpy()
            p1 = scored["p_m1"].to_numpy()
            refs = {"m0_cond": scored["p_m0c"].to_numpy(), "m0_uncond": scored["p_m0u"].to_numpy()}
            n_sess = scored["session_date"].n_unique()
            rec = {
                "fold": f.index,
                "target": name,
                "c": c,
                "calib_log_loss": {str(k): v for k, v in calib_losses.items()},
                "n_train": len(y_tr),
                "n_calib": len(y_ca),
                "n_predictions": len(y),
                "n_sessions": n_sess,
                "n_effective": n_effective(n_sess, window_minutes, horizon),
                "test_rate": float(y.mean()),
                "coef": dict(zip(design.out_columns, model.coef, strict=True)),
                "train_fills": fill_tr,
                "test_fills": fill_te,
                "m1": score(y, p1, sid, cfg),
                **skill(y, p1, refs, sid, cfg),
            }
            save_model(f, name, model, rec)
            out["per_fold"].append(rec)
            print(f"fold {f.index} {name}: C={c} n={len(y)}", flush=True)
    for name, parts in pooled.items():
        s = pl.concat(parts)
        y = s["y"].cast(pl.Float64).to_numpy()
        sid = s["session_date"].to_numpy()
        p1 = s["p_m1"].to_numpy()
        refs = {"m0_cond": s["p_m0c"].to_numpy(), "m0_uncond": s["p_m0u"].to_numpy()}
        n_sess = s["session_date"].n_unique()
        folds_better = sum(r["bss_vs_m0_cond"] > 0 for r in out["per_fold"] if r["target"] == name)
        out["pooled"][name] = {
            "test_rate": float(y.mean()),
            "n_predictions": s.height,
            "n_sessions": n_sess,
            "n_effective": n_effective(n_sess, window_minutes, horizon),
            "m1": score(y, p1, sid, cfg),
            **skill(y, p1, refs, sid, cfg),
            "folds_better_than_m0_cond": folds_better,
            "n_folds": len(folds),
        }
        print(f"pooled {name}", flush=True)
    return out


def _m(d: dict[str, Any], k: str) -> str:
    lo, hi = d[f"{k}_ci"]
    return f"{d[k]:.4f} [{lo:.4f}, {hi:.4f}]"


def _s(d: dict[str, Any], k: str) -> str:
    lo, hi = d[f"{k}_ci"]
    return f"{d[k]:+.4f} [{lo:+.4f}, {hi:+.4f}]"


def coef_tables(res: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for name in res["pooled"]:
        rows = [r for r in res["per_fold"] if r["target"] == name]
        feats = list(rows[0]["coef"])
        for r in rows[1:]:
            feats += [k for k in r["coef"] if k not in feats]
        lines += [
            f"### {name}",
            "",
            "C per fold: " + ", ".join(f"{r['fold']}: {r['c']:g}" for r in rows),
            "",
            "| term | " + " | ".join(f"fold {r['fold']}" for r in rows) + " | same sign |",
            "|---|" + "---|" * len(rows) + "---|",
        ]
        for k in feats:
            vals = [r["coef"].get(k) for r in rows]
            present = [v for v in vals if v is not None]
            med = float(np.median(present))
            same = sum(np.sign(v) == np.sign(med) for v in present)
            cells = " | ".join("—" if v is None else f"{v:+.3f}" for v in vals)
            lines.append(f"| {k} | {cells} | {same}/{len(present)} |")
        lines.append("")
    return lines


def write_report(res: dict[str, Any], meta: dict[str, Any]) -> None:
    lines = [
        "# Model 1 (L2 logistic regression): out-of-sample walk-forward results",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {meta['commit'][:12]}, "
        f"run `{meta['run_id']}` (config hash {meta['config_hash'][:12]}); C-grid runs "
        f"{', '.join(f'`{r}`' for r in meta['grid_runs'])}. n_trials on the test window = "
        f"{meta['n_trials']}.",
        "",
        f"Features {meta['features']} ({len(FEATURE_NAMES)} features; day_of_week one-hot), "
        f"labels {meta['labels']}. Same {meta['n_folds']} folds as Model 0 "
        "(`reports/models/baseline_m0.md`). Final holdout (sessions after "
        f"{meta['holdout_after']}) was not opened.",
        "",
        "**Scores are uncalibrated model outputs, not probabilities** (calibration is M13). "
        "Design per fold: training mean / population std, missing values set to the training "
        f"mean with a `missing_<feature>` indicator, z clipped at ±{meta['z_clip']:g}. C from "
        f"{meta['c_grid']} by calibration-block log loss (model fit on train only); the "
        "calibration block is never used for fitting and test blocks never for selection.",
        "",
        "BSS = Brier skill score, 1 - Brier(M1) / Brier(reference); positive = Model 1 better. "
        "References refit identically per fold: Model 0 conditional (time-of-day x VIX "
        "tercile, shrunk) and unconditional. Gate 6 reference: pooled BSS vs Model 0 with CI "
        "lower bound > 0 and better in >= 70% of folds (reported here, judged at M19). CIs: "
        f"session-block bootstrap, {meta['reps']} reps, {meta['level']:.0%}.",
        "",
        "## Pooled out-of-sample",
        "",
        "| target | test rate | n pred | sessions | n_eff | Brier M1 | log loss M1 | ECE M1 "
        "| BSS vs M0 cond | BSS vs M0 uncond | folds better than M0 cond |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, r in res["pooled"].items():
        lines.append(
            f"| {name} | {r['test_rate']:.3f} | {r['n_predictions']:,} | {r['n_sessions']} "
            f"| {r['n_effective']:,} | {_m(r['m1'], 'brier')} | {_m(r['m1'], 'log_loss')} "
            f"| {_m(r['m1'], 'ece')} | {_s(r, 'bss_vs_m0_cond')} | {_s(r, 'bss_vs_m0_uncond')} "
            f"| {r['folds_better_than_m0_cond']}/{r['n_folds']} |"
        )
    lines += [
        "",
        "## Per fold",
        "",
        "| fold | target | C | n train | n test | sessions | n_eff | Brier M1 | log loss M1 "
        "| ECE M1 | BSS vs M0 cond | BSS vs M0 uncond |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in res["per_fold"]:
        lines.append(
            f"| {r['fold']} | {r['target']} | {r['c']:g} | {r['n_train']:,} "
            f"| {r['n_predictions']:,} | {r['n_sessions']} | {r['n_effective']} "
            f"| {_m(r['m1'], 'brier')} | {_m(r['m1'], 'log_loss')} | {_m(r['m1'], 'ece')} "
            f"| {_s(r, 'bss_vs_m0_cond')} | {_s(r, 'bss_vs_m0_uncond')} |"
        )
    fills: dict[str, list[int]] = {}
    for r in res["per_fold"]:
        if r["target"] == "A_up":
            for k, v in r["test_fills"].items():
                fills.setdefault(k, [0] * meta["n_folds"])[r["fold"] - 1] = v
    n_test = {r["fold"]: r["n_predictions"] for r in res["per_fold"] if r["target"] == "A_up"}
    lines += [
        "",
        "## Missing-value fills (test blocks, target A_up rows)",
        "",
        "Values set to the training mean (z = 0); share of the block's rows in brackets.",
        "",
        "| feature | " + " | ".join(f"fold {k}" for k in sorted(n_test)) + " |",
        "|---|" + "---|" * len(n_test),
        *[
            f"| {k} | "
            + " | ".join(f"{v} ({v / n_test[i + 1]:.1%})" for i, v in enumerate(vs))
            + " |"
            for k, vs in sorted(fills.items())
        ],
        "",
        "## Standardised coefficients per fold (stability)",
        "",
        "Coefficient per standard deviation of the training feature; `same sign` = folds whose "
        "sign matches the median's. Missing-indicator terms exist only in folds whose training "
        "data had missing values.",
        "",
        *coef_tables(res),
    ]
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
    HoldoutGuard(hold, engine).check(sessions)
    folds = walk_forward_folds(sessions, hold, cfg)
    used = sorted({d for f in folds for d in (*f.train, *f.calib, *f.test)})
    ts = cal.prediction_timestamps(used[0])
    window_minutes = int((ts[-1] - ts[0]).total_seconds() // 60)
    features_id = _dataset_id(engine, f"data/features/{cfg.features.version}")
    labels_id = _dataset_id(engine, f"data/labels/{cfg.labels.version}")
    commit = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
        or "unknown"
    )
    fold_meta = [
        {
            "fold": f.index,
            "train": [str(f.train[0]), str(f.train[-1])],
            "calib": [str(f.calib[0]), str(f.calib[-1])],
            "test": [str(f.test[0]), str(f.test[-1])],
        }
        for f in folds
    ]
    base = {
        "model": "logistic_m1",
        "logistic": cfg.models.logistic.model_dump(mode="json"),
        "baseline_reference": cfg.models.baseline.model_dump(mode="json"),
        "metrics": cfg.models.metrics.model_dump(mode="json"),
        "validation": cfg.validation.model_dump(mode="json"),
        "features": {"version": cfg.features.version, "dataset_id": features_id},
        "labels": {"version": cfg.labels.version, "dataset_id": labels_id},
        "targets": [_name(lid, v) for lid, v in TARGETS],
    }
    # Register every run before any evaluation: one per grid point (calibration blocks) + OOS.
    calib_window = (folds[0].train[0], folds[-1].calib[-1])
    grid_runs = {
        c: register_run(
            engine,
            run_kind="hyperparam_search",
            config={**base, "evaluation": "calibration_block", "C": c},
            data_window=calib_window,
            dataset_id=features_id,
            code_commit=commit,
            folds=fold_meta,
        )
        for c in cfg.models.logistic.c_grid
    }
    final_cfg = {**base, "evaluation": "test_block", "selection": "min calibration log loss"}
    window = (folds[0].train[0], folds[-1].test[-1])
    run_id = register_run(
        engine,
        run_kind="walk_forward",
        config=final_cfg,
        data_window=window,
        dataset_id=features_id,
        code_commit=commit,
        folds=fold_meta,
    )
    with engine.connect() as c:
        h = c.execute(
            text("SELECT config_hash FROM validation_runs WHERE run_id = :r"), {"r": run_id}
        ).scalar_one()
    print(f"registered run {run_id} and {len(grid_runs)} grid runs")
    art_dir = ROOT / "data" / "models" / "m1" / run_id

    def save_model(f: Fold, name: str, model: LogisticModel, rec: dict[str, Any]) -> None:
        path = art_dir / f"fold{f.index}_{_slug(name)}.json"
        sha = save(model, path)
        rec["artifact"] = {"uri": path.relative_to(ROOT).as_posix(), "sha256": sha}
        record_model_version(
            engine,
            ModelVersion(
                model_version_id=f"m1-{run_id}-f{f.index}-{_slug(name)}",
                model_family="logistic_l2",
                target_label=name,
                train_start=f.train[0],
                train_end=f.train[-1],
                dataset_id=features_id,
                feature_version=cfg.features.version,
                label_version=cfg.labels.version,
                hyperparameters={
                    "C": model.c,
                    "z_clip": model.design.z_clip,
                    "solver": cfg.models.logistic.solver,
                },
                artifact_uri=rec["artifact"]["uri"],
                artifact_sha256=sha,
                code_commit=commit,
                config_hash=h,
            ),
        )

    try:
        wide, labels = load_data(cfg, used)
        res = evaluate(wide, labels, folds, cfg, window_minutes, save_model)
    except Exception as e:
        for r in [*grid_runs.values(), run_id]:
            fail_run(engine, r, repr(e))
        raise
    for cv, rid in grid_runs.items():
        complete_run(
            engine,
            rid,
            {
                "calib_log_loss": [
                    {
                        "fold": r["fold"],
                        "target": r["target"],
                        "log_loss": r["calib_log_loss"][str(cv)],
                    }
                    for r in res["per_fold"]
                ]
            },
        )
    complete_run(engine, run_id, res)
    meta = {
        "commit": commit,
        "run_id": run_id,
        "config_hash": h,
        "grid_runs": list(grid_runs.values()),
        "n_trials": n_trials(engine, *window),
        "features": cfg.features.version,
        "labels": cfg.labels.version,
        "n_folds": len(folds),
        "holdout_after": hold,
        "z_clip": cfg.models.logistic.z_clip,
        "c_grid": cfg.models.logistic.c_grid,
        "reps": cfg.validation.bootstrap_reps,
        "level": cfg.models.metrics.ci_level,
    }
    write_report(res, meta)
    engine.dispose()
    print(f"completed run {run_id}; report {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
