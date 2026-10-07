"""M9: Model 2 (LightGBM) over the chronological walk-forward; write reports/models/.

Per fold and target: every pre-declared grid point is fit on train with early stopping on the
calibration block; the lowest calibration log loss is kept and scores the test block. Compared
with Model 0 (refit, train only) and Model 1 (saved artifacts of the reference M8 run, sha256
checked) by Brier skill with session-block bootstrap CIs. Scores are UNCALIBRATED (rule 6).

Gate-4 canary (T-LEAK-13, ADR-0008): the selected grid point refit on row-permuted training and
calibration labels, repeated over `canary_n_permutations` seeds; the mean over permutations of
the mean per-fold OOS AUC (true test labels) must be within 0.50 +/- tolerance.

Registry (spec §10): one `validation_runs` row per grid point, one for the OOS run and one for
the canary, all registered before any evaluation. Fitted models -> `model_versions` CANDIDATE.

    uv run python scripts/m9_gbm.py
"""

from __future__ import annotations

import itertools
import os
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text

from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import (
    TARGETS,
    block_rows,
    code_commit,
    dataset_id,
    load_data,
    score,
    skill,
    slug,
    target_name,
)
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
from qqq1dte.models import logistic
from qqq1dte.models.baseline import fit_baseline
from qqq1dte.models.design import KEYS
from qqq1dte.models.gbm import (
    GbmFit,
    canary_permutation,
    canary_statistic,
    fit_gbm,
    gain_importance,
    grid_points,
    save,
    select_params,
)
from qqq1dte.models.metrics import auc, n_effective

ROOT = Path(__file__).resolve().parents[1]
END = date(2026, 10, 2)  # last research session on disk (M4 history)
REPORT = ROOT / "reports" / "models" / "gbm_m2.md"
Arr = np.ndarray


def _key(point: dict[str, Any]) -> str:
    return f"leaves={point['num_leaves']},min_leaf={point['min_data_in_leaf']}"


def m1_models(engine: Engine, run_id: str) -> dict[tuple[int, str], logistic.LogisticModel]:
    """Saved Model 1 artifacts of the reference run, keyed by (fold, target); sha256 checked."""
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT model_version_id, target_label, artifact_uri, artifact_sha256 "
                "FROM model_versions WHERE model_version_id LIKE :p"
            ),
            {"p": f"m1-{run_id}-f%"},
        ).all()
    out = {}
    for mid, tgt, uri, sha in rows:
        fold = int(mid.removeprefix(f"m1-{run_id}-f").split("-")[0])
        out[(fold, tgt)], _ = logistic.load(ROOT / uri, expected_sha256=sha)
    if len(out) != len(TARGETS) * 7:
        raise RuntimeError(f"expected 70 Model 1 artifacts for {run_id}, found {len(out)}")
    return out


def evaluate(
    wide: pl.DataFrame,
    labels: pl.DataFrame,
    folds: list[Fold],
    cfg: Phase1Config,
    window_minutes: int,
    m1: dict[tuple[int, str], logistic.LogisticModel],
    save_model: Callable[[Fold, str, GbmFit, dict[str, Any]], None],
) -> dict[str, Any]:
    gcfg = cfg.models.gbm
    horizon = cfg.labels.horizon_minutes
    feats = [c for c in wide.columns if c not in KEYS]
    out: dict[str, Any] = {"per_fold": [], "pooled": {}, "canary": {}}
    pooled: dict[str, list[pl.DataFrame]] = {}
    for f in folds:
        for lid, var in TARGETS:
            name = target_name(lid, var)
            t = labels.filter((pl.col("label_id") == lid) & (pl.col("variant") == var))
            tr, ca, te = (block_rows(wide, t, b) for b in (f.train, f.calib, f.test))
            x_tr, x_ca, x_te = (d.select(feats).to_numpy().astype(np.float64) for d in (tr, ca, te))
            y_tr, y_ca, y_te = (d["y"].cast(pl.Float64).to_numpy() for d in (tr, ca, te))
            best, fits = select_params(x_tr, y_tr, x_ca, y_ca, gcfg, feats)
            canary_aucs, canary_iters = [], []
            for k in range(gcfg.canary_n_permutations):  # ADR-0008
                seed = gcfg.canary_seed + 100_000 * k + 1000 * f.index + TARGETS.index((lid, var))
                canary = fit_gbm(
                    x_tr,
                    canary_permutation(y_tr, seed),
                    x_ca,
                    canary_permutation(y_ca, seed + 1),
                    best.params,
                    gcfg,
                    feats,
                )
                canary_aucs.append(auc(y_te, canary.predict(x_te)))
                canary_iters.append(canary.best_iteration)
            m0 = fit_baseline(tr.with_columns(vix=pl.col("vix_prev_close")), cfg.models.baseline)
            scored = te.select(*KEYS, "y").with_columns(
                p_m2=pl.Series(best.predict(x_te)),
                p_m1=pl.Series(m1[(f.index, name)].score(te)),
                p_m0c=pl.Series(m0.predict(te.with_columns(vix=pl.col("vix_prev_close")))),
                p_m0u=pl.Series(m0.predict_unconditional(te)),
            )
            pooled.setdefault(name, []).append(scored)
            sid = scored["session_date"].to_numpy()
            p2 = scored["p_m2"].to_numpy()
            refs = {k: scored[f"p_{k}"].to_numpy() for k in ("m0c", "m0u", "m1")}
            n_sess = scored["session_date"].n_unique()
            rec = {
                "fold": f.index,
                "target": name,
                "params": _key(best.params),
                "best_iteration": best.best_iteration,
                "calib_log_loss": {_key(g.params): g.calib_log_loss for g in fits},
                "calib_best_iteration": {_key(g.params): g.best_iteration for g in fits},
                "n_train": len(y_tr),
                "n_calib": len(y_ca),
                "n_predictions": len(y_te),
                "n_sessions": n_sess,
                "n_effective": n_effective(n_sess, window_minutes, horizon),
                "test_rate": float(y_te.mean()),
                "importance": gain_importance(best.booster),
                "auc_m2": auc(y_te, p2),
                "auc_m1": auc(y_te, refs["m1"]),
                "canary_aucs": canary_aucs,
                "canary_best_iterations": canary_iters,
                "m2": score(y_te, p2, sid, cfg),
                **skill(y_te, p2, refs, sid, cfg),
            }
            save_model(f, name, best, rec)
            out["per_fold"].append(rec)
            print(
                f"fold {f.index} {name}: {rec['params']} it={best.best_iteration} "
                f"canary mean auc={np.mean(canary_aucs):.3f}",
                flush=True,
            )
    for name, parts in pooled.items():
        s = pl.concat(parts)
        y = s["y"].cast(pl.Float64).to_numpy()
        sid = s["session_date"].to_numpy()
        p2 = s["p_m2"].to_numpy()
        refs = {k: s[f"p_{k}"].to_numpy() for k in ("m0c", "m0u", "m1")}
        rows = [r for r in out["per_fold"] if r["target"] == name]
        n_sess = s["session_date"].n_unique()
        out["pooled"][name] = {
            "test_rate": float(y.mean()),
            "n_predictions": s.height,
            "n_sessions": n_sess,
            "n_effective": n_effective(n_sess, window_minutes, horizon),
            "m2": score(y, p2, sid, cfg),
            **skill(y, p2, refs, sid, cfg),
            "auc_m2": auc(y, p2),
            "auc_m1": auc(y, refs["m1"]),
            "folds_better": {k: sum(r[f"bss_vs_{k}"] > 0 for r in rows) for k in refs},
            "n_folds": len(rows),
        }
        # (n_permutations, n_folds) per-fold OOS AUCs -> ADR-0008 statistic
        fold_aucs = np.array([r["canary_aucs"] for r in rows]).T
        out["canary"][name] = canary_statistic(fold_aucs, gcfg.canary_auc_tolerance)
        print(f"pooled {name}", flush=True)
    return out


def _rank(v: Arr) -> Arr:
    return np.asarray(pl.Series(v).rank("average").to_numpy(), dtype=np.float64)


def importance_section(res: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for name in res["pooled"]:
        rows = [r for r in res["per_fold"] if r["target"] == name]
        feats = list(rows[0]["importance"])
        mat = np.array([[r["importance"][k] for k in feats] for r in rows])
        ranks = [_rank(m) for m in mat]
        rhos = [float(np.corrcoef(a, b)[0, 1]) for a, b in itertools.combinations(ranks, 2)]
        top10 = [set(np.array(feats)[np.argsort(-m)[:10]]) for m in mat]
        order = np.argsort(-mat.mean(axis=0))[:12]
        lines += [
            f"### {name}",
            "",
            f"Mean pairwise Spearman rank correlation of gain shares across folds: "
            f"{np.mean(rhos):.2f} (min {min(rhos):.2f}).",
            "",
            "| feature | mean share | "
            + " | ".join(f"fold {r['fold']}" for r in rows)
            + " | folds in top 10 |",
            "|---|---|" + "---|" * len(rows) + "---|",
        ]
        for j in order:
            k = feats[j]
            cells = " | ".join(f"{v:.3f}" for v in mat[:, j])
            lines.append(
                f"| {k} | {mat[:, j].mean():.3f} | {cells} "
                f"| {sum(k in s for s in top10)}/{len(rows)} |"
            )
        lines.append("")
    return lines


def _m(d: dict[str, Any], k: str) -> str:
    lo, hi = d[f"{k}_ci"]
    return f"{d[k]:.4f} [{lo:.4f}, {hi:.4f}]"


def _s(d: dict[str, Any], k: str) -> str:
    lo, hi = d[f"{k}_ci"]
    return f"{d[k]:+.4f} [{lo:+.4f}, {hi:+.4f}]"


def write_report(res: dict[str, Any], meta: dict[str, Any]) -> None:
    tol = meta["tol"]
    lines = [
        "# Model 2 (LightGBM): out-of-sample walk-forward results",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {meta['commit'][:12]}, "
        f"run `{meta['run_id']}` (config hash {meta['config_hash'][:12]}); grid runs "
        f"{', '.join(f'`{r}`' for r in meta['grid_runs'])}; canary run `{meta['canary_run']}`. "
        f"n_trials on the test window = {meta['n_trials']}.",
        "",
        f"Features {meta['features']} (raw values, LightGBM native missing handling, "
        f"day_of_week one-hot), labels {meta['labels']}. Same {meta['n_folds']} folds as "
        "Models 0 and 1. Final holdout (sessions after "
        f"{meta['holdout_after']}) was not opened. Model 1 = saved artifacts of "
        f"`{meta['m1_run']}` (sha256 verified), not refit.",
        "",
        "**Scores are uncalibrated model outputs, not probabilities** (calibration is M13). "
        f"Grid {meta['grid']} with fixed {meta['fixed']}; each grid point is fit on train with "
        f"early stopping ({meta['es']} rounds, max {meta['max_rounds']}) on calibration-block "
        "log loss and the lowest calibration log loss is kept. Test blocks are never used for "
        "selection.",
        "",
        "BSS = 1 - Brier(M2) / Brier(reference); positive = Model 2 better. M0c = Model 0 "
        "conditional, M0u = unconditional, M1 = logistic. CIs: session-block bootstrap, "
        f"{meta['reps']} reps, {meta['level']:.0%}.",
        "",
        "## Gate-4 canary (T-LEAK-13, ADR-0008): permuted training labels",
        "",
        f"Statistic = mean over {meta['n_perm']} label permutations of the mean per-fold OOS AUC "
        f"(true test labels, no pooling of scores across folds). Pass = within 0.50 ± {tol}. "
        "Spread = SD / min / max of the per-permutation means. The earlier single-permutation, "
        f"pooled-score canary `{meta['old_canary']}` failed for three B targets (below 0.5); see "
        "ADR-0008.",
        "",
        "| target | statistic | perm SD | perm min / max | per-fold AUC (mean over perms) "
        "| result |",
        "|---|---|---|---|---|---|",
        *[
            f"| {n} | {c['statistic']:.4f} | {c['perm_sd']:.4f} "
            f"| {c['perm_min']:.3f} / {c['perm_max']:.3f} | "
            + ", ".join(f"{a:.3f}" for a in c["fold_mean"])
            + f" | {'PASS' if c['pass'] else 'FAIL'} |"
            for n, c in res["canary"].items()
        ],
        "",
        "## Pooled out-of-sample",
        "",
        "| target | test rate | n pred | sessions | n_eff | Brier M2 | log loss M2 | ECE M2 "
        "| AUC M2 / M1 | BSS vs M0c | BSS vs M0u | BSS vs M1 | folds better (M0c / M1) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, r in res["pooled"].items():
        fb = r["folds_better"]
        lines.append(
            f"| {name} | {r['test_rate']:.3f} | {r['n_predictions']:,} | {r['n_sessions']} "
            f"| {r['n_effective']:,} | {_m(r['m2'], 'brier')} | {_m(r['m2'], 'log_loss')} "
            f"| {_m(r['m2'], 'ece')} | {r['auc_m2']:.3f} / {r['auc_m1']:.3f} "
            f"| {_s(r, 'bss_vs_m0c')} | {_s(r, 'bss_vs_m0u')} | {_s(r, 'bss_vs_m1')} "
            f"| {fb['m0c']}/{r['n_folds']} / {fb['m1']}/{r['n_folds']} |"
        )
    lines += [
        "",
        "## Per fold",
        "",
        "| fold | target | grid point | trees | n test | sessions | n_eff | Brier M2 | ECE M2 "
        "| AUC M2 | BSS vs M0c | BSS vs M1 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in res["per_fold"]:
        lines.append(
            f"| {r['fold']} | {r['target']} | {r['params']} | {r['best_iteration']} "
            f"| {r['n_predictions']:,} | {r['n_sessions']} | {r['n_effective']} "
            f"| {_m(r['m2'], 'brier')} | {_m(r['m2'], 'ece')} | {r['auc_m2']:.3f} "
            f"| {_s(r, 'bss_vs_m0c')} | {_s(r, 'bss_vs_m1')} |"
        )
    lines += [
        "",
        "## Feature importance stability (gain share per fold, top 12 by mean)",
        "",
        *importance_section(res),
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    gcfg = cfg.models.gbm
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
    features_id = dataset_id(engine, f"data/features/{cfg.features.version}")
    labels_id = dataset_id(engine, f"data/labels/{cfg.labels.version}")
    commit = code_commit(ROOT)
    m1 = m1_models(engine, gcfg.reference_m1_run)
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
        "model": "gbm_m2",
        # canary_n_permutations is canary-only (ADR-0008): grid/OOS configs stay unchanged
        "gbm": gcfg.model_dump(mode="json", exclude={"canary_n_permutations"}),
        "baseline_reference": cfg.models.baseline.model_dump(mode="json"),
        "metrics": cfg.models.metrics.model_dump(mode="json"),
        "validation": cfg.validation.model_dump(mode="json"),
        "features": {"version": cfg.features.version, "dataset_id": features_id},
        "labels": {"version": cfg.labels.version, "dataset_id": labels_id},
        "targets": [target_name(lid, v) for lid, v in TARGETS],
    }
    calib_window = (folds[0].train[0], folds[-1].calib[-1])
    window = (folds[0].train[0], folds[-1].test[-1])

    def reg(kind: str, config: dict[str, Any], win: tuple[date, date]) -> str:
        return register_run(
            engine,
            run_kind=kind,
            config=config,
            data_window=win,
            dataset_id=features_id,
            code_commit=commit,
            folds=fold_meta,
        )

    # Register every run before any evaluation: grid points, OOS run, canary.
    grid_runs = {
        _key(pt): reg(
            "hyperparam_search",
            {**base, "evaluation": "calibration_block", "grid_point": pt},
            calib_window,
        )
        for pt in grid_points(gcfg)
    }
    run_id = reg(
        "walk_forward",
        {**base, "evaluation": "test_block", "selection": "min calibration log loss"},
        window,
    )
    canary_run = reg(
        "canary",
        {
            **base,
            "evaluation": "permuted_label_canary",
            "adr": "ADR-0008",
            "canary_n_permutations": gcfg.canary_n_permutations,
            "statistic": "mean over permutations of mean per-fold OOS AUC",
        },
        window,
    )
    with engine.connect() as c:
        h = c.execute(
            text("SELECT config_hash FROM validation_runs WHERE run_id = :r"), {"r": run_id}
        ).scalar_one()
    print(f"registered run {run_id}, {len(grid_runs)} grid runs, canary {canary_run}")
    art_dir = ROOT / "data" / "models" / "m2" / run_id

    def save_model(f: Fold, name: str, fit: GbmFit, rec: dict[str, Any]) -> None:
        path = art_dir / f"fold{f.index}_{slug(name)}.txt"
        sha = save(fit, path)
        rec["artifact"] = {"uri": path.relative_to(ROOT).as_posix(), "sha256": sha}
        record_model_version(
            engine,
            ModelVersion(
                model_version_id=f"m2-{run_id}-f{f.index}-{slug(name)}",
                model_family="lightgbm",
                target_label=name,
                train_start=f.train[0],
                train_end=f.train[-1],
                dataset_id=features_id,
                feature_version=cfg.features.version,
                label_version=cfg.labels.version,
                hyperparameters={**gcfg.fixed, **fit.params, "num_iterations": fit.best_iteration},
                artifact_uri=rec["artifact"]["uri"],
                artifact_sha256=sha,
                code_commit=commit,
                config_hash=h,
            ),
        )

    all_runs = [*grid_runs.values(), run_id, canary_run]
    try:
        wide, labels = load_data(ROOT, cfg, used)
        res = evaluate(wide, labels, folds, cfg, window_minutes, m1, save_model)
    except Exception as e:
        for r in all_runs:
            fail_run(engine, r, repr(e))
        raise
    for key, rid in grid_runs.items():
        complete_run(
            engine,
            rid,
            {
                "calib_log_loss": [
                    {
                        "fold": r["fold"],
                        "target": r["target"],
                        "log_loss": r["calib_log_loss"][key],
                        "best_iteration": r["calib_best_iteration"][key],
                    }
                    for r in res["per_fold"]
                ]
            },
        )
    complete_run(engine, run_id, {k: v for k, v in res.items() if k != "canary"})
    complete_run(engine, canary_run, res["canary"])
    meta = {
        "commit": commit,
        "run_id": run_id,
        "config_hash": h,
        "grid_runs": list(grid_runs.values()),
        "canary_run": canary_run,
        "n_trials": n_trials(engine, *window),
        "features": cfg.features.version,
        "labels": cfg.labels.version,
        "n_folds": len(folds),
        "holdout_after": hold,
        "m1_run": gcfg.reference_m1_run,
        "grid": gcfg.grid.model_dump(),
        "fixed": {k: v for k, v in gcfg.fixed.items() if k not in ("verbosity",)},
        "es": gcfg.early_stopping_rounds,
        "max_rounds": gcfg.max_rounds,
        "tol": gcfg.canary_auc_tolerance,
        "n_perm": gcfg.canary_n_permutations,
        "old_canary": "canary-541beb1db5f4",
        "reps": cfg.validation.bootstrap_reps,
        "level": cfg.models.metrics.ci_level,
    }
    write_report(res, meta)
    engine.dispose()
    print(f"completed run {run_id}; report {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
