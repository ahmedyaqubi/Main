"""M13: calibrate Model 1 and Model 2 scores; evaluate gate 12 on held-out test blocks.

Per family (saved artifacts of the reference runs, sha256-checked; no refit), fold and target:
score the fold's calibration and test blocks with the fold's model; choose a calibration method
on a chronological inner split of the calibration block and refit it on the whole block
(`calibration.fit`, which refuses training/test rows, T-CAL-03); apply it to the test block.
Results: `calibration_results` rows (one per model version), calibrator JSON artifacts, one
`validation_runs` row per family (run_kind "calibration"), reports/models/calibration_m13.md.

The test blocks are never used to fit or choose anything. Gate 12 is reported as "would
pass/fail"; the formal verdict is M19.

    uv run python scripts/m13_calibration.py
"""

from __future__ import annotations

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
    slug,
    target_name,
)
from qqq1dte.backtesting.registry import complete_run, fail_run, register_run
from qqq1dte.backtesting.splits import Fold, walk_forward_folds
from qqq1dte.calibration.fit import fit_calibration
from qqq1dte.calibration.methods import save
from qqq1dte.calibration.metrics import calibration_slope, gate12, reliability
from qqq1dte.calibration.store import CalibrationRecord, record_calibration
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config, load_config
from qqq1dte.models import gbm, logistic
from qqq1dte.models.design import KEYS
from qqq1dte.models.metrics import brier, ece, log_loss

ROOT = Path(__file__).resolve().parents[1]
END = date(2026, 10, 2)
REPORT = ROOT / "reports" / "models" / "calibration_m13.md"
PREFIX = {"logistic_m1": "m1", "gbm_m2": "m2"}
Scorer = Callable[[pl.DataFrame], np.ndarray]


def scorers(engine: Engine, family: str, run_id: str) -> dict[tuple[int, str], tuple[str, Scorer]]:
    """(fold, target) -> (model_version_id, scoring function) from the saved artifacts."""
    p = f"{PREFIX[family]}-{run_id}-f"
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT model_version_id, target_label, artifact_uri, artifact_sha256 "
                "FROM model_versions WHERE model_version_id LIKE :p"
            ),
            {"p": p + "%"},
        ).all()
    out: dict[tuple[int, str], tuple[str, Scorer]] = {}
    for mid, tgt, uri, sha in rows:
        fold = int(mid.removeprefix(p).split("-")[0])
        if family == "logistic_m1":
            m, _ = logistic.load(ROOT / uri, expected_sha256=sha)
            out[(fold, tgt)] = (mid, m.score)
        else:
            b, _ = gbm.load(ROOT / uri, expected_sha256=sha)

            def _score(df: pl.DataFrame, b: Any = b) -> np.ndarray:
                feats = [c for c in df.columns if c not in (*KEYS, "y")]
                return np.asarray(b.predict(df.select(feats).to_numpy().astype(np.float64)))

            out[(fold, tgt)] = (mid, _score)
    if len(out) != len(TARGETS) * 7:
        raise RuntimeError(f"expected 70 {family} artifacts for {run_id}, found {len(out)}")
    return out


def evaluate(
    family: str,
    run_id: str,
    wide: pl.DataFrame,
    labels: pl.DataFrame,
    folds: list[Fold],
    models: dict[tuple[int, str], tuple[str, Scorer]],
    engine: Engine,
    cfg: Phase1Config,
) -> dict[str, Any]:
    out: dict[str, Any] = {"per_fold": [], "pooled": {}}
    pooled: dict[str, list[pl.DataFrame]] = {}
    adir = ROOT / "data" / "calibration" / run_id / family
    for f in folds:
        for lid, var in TARGETS:
            name = target_name(lid, var)
            mid, scorer = models[(f.index, name)]
            t = labels.filter((pl.col("label_id") == lid) & (pl.col("variant") == var))
            ca, te = block_rows(wide, t, f.calib), block_rows(wide, t, f.test)
            raw_ca, raw_te = scorer(ca), scorer(te)
            y_ca, y_te = (d["y"].cast(pl.Float64).to_numpy() for d in (ca, te))
            fit = fit_calibration(
                raw_ca, y_ca, ca["session_date"].to_list(), f.train[-1], f.test[0], cfg
            )
            p_te = fit.calibrator.apply(raw_te)
            vid = f"cal-{run_id}-f{f.index}-{slug(name)}"
            path = adir / f"fold{f.index}_{slug(name)}.json"
            sha = save(fit.calibrator, path)
            slope, intercept = calibration_slope(y_te, p_te)
            bins = reliability(y_te, p_te, cfg)
            record_calibration(
                engine,
                CalibrationRecord(
                    vid,
                    mid,
                    fit.method,
                    f.calib[0],
                    f.calib[-1],
                    f.test[0],
                    f.test[-1],
                    len(y_ca),
                    len(y_te),
                    brier(y_te, p_te),
                    log_loss(y_te, p_te),
                    ece(y_te, p_te, cfg.models.metrics.ece_bins),
                    slope,
                    intercept,
                    bins,
                    path.relative_to(ROOT).as_posix(),
                    sha,
                ),
            )
            g_cal, g_raw = gate12(y_te, p_te, cfg), gate12(y_te, raw_te, cfg)
            out["per_fold"].append(
                {
                    "fold": f.index,
                    "target": name,
                    "model_version_id": mid,
                    "calibration_version_id": vid,
                    "method": fit.method,
                    "inner_log_loss": fit.inner_log_loss,
                    "n_calib": len(y_ca),
                    "n_test": len(y_te),
                    "raw": {
                        "brier": brier(y_te, raw_te),
                        "log_loss": log_loss(y_te, raw_te),
                        **g_raw,
                    },
                    "cal": {"brier": brier(y_te, p_te), "log_loss": log_loss(y_te, p_te), **g_cal},
                }
            )
            pooled.setdefault(name, []).append(
                te.select("session_date", "y").with_columns(
                    raw=pl.Series(raw_te), cal=pl.Series(p_te)
                )
            )
            print(f"{family} fold {f.index} {name}: {fit.method}", flush=True)
    for name, parts in pooled.items():
        s = pl.concat(parts)
        y = s["y"].cast(pl.Float64).to_numpy()
        raw, cal = s["raw"].to_numpy(), s["cal"].to_numpy()
        sid = s["session_date"].to_numpy()
        out["pooled"][name] = {
            "n": s.height,
            "n_sessions": s["session_date"].n_unique(),
            "raw": {"brier": brier(y, raw), "log_loss": log_loss(y, raw), **gate12(y, raw, cfg)},
            "cal": {**score(y, cal, sid, cfg), **gate12(y, cal, cfg)},
            "reliability": reliability(y, cal, cfg),
        }
        print(f"{family} pooled {name}", flush=True)
    return out


def _ci(d: dict[str, Any], k: str) -> str:
    lo, hi = d[f"{k}_ci"]
    return f"{d[k]:.4f} [{lo:.4f}, {hi:.4f}]"


def write_report(results: dict[str, dict[str, Any]], meta: dict[str, Any]) -> None:
    g = CFG.calibration.gate12
    lines = [
        "# M13 probability calibration: Model 1 and Model 2",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {meta['commit'][:12]}; runs "
        + ", ".join(f"`{r}` ({f})" for f, r in meta["runs"].items())
        + f". Final holdout (sessions after {meta['hold']}) not opened.",
        "",
        "**Protocol.** Saved model artifacts of "
        + ", ".join(f"`{r}` ({f})" for f, r in CFG.calibration.reference_runs.items())
        + " (sha256-checked, not refit) score each fold's calibration and test blocks. "
        f"Candidates {CFG.calibration.methods}: each is fit on the first "
        f"{CFG.calibration.inner_split:.0%} of the calibration block's sessions and scored "
        "(log loss) on the rest; the best is refit on the whole calibration block and applied "
        "to the test block. Test blocks are never used to fit or choose. Probabilities below "
        "are calibrated on held-out data; raw scores are shown only for comparison.",
        "",
        f"**Gate 12** (spec §11), pooled test blocks: ECE ≤ {g.ece_max} (10 equal-count bins); "
        f"calibration slope in [{g.slope_min}, {g.slope_max}]; every bin with n ≥ {g.bin_min_n} "
        f"has its observed rate inside the {g.wilson_level:.0%} Wilson CI of its mean "
        "predicted value. Shown as would-pass / would-fail; the formal verdict is M19.",
        "",
        "**Caveats.** (1) M8/M9 used the calibration blocks to choose C / the LightGBM grid "
        "point and for early stopping, so the calibrator is fit on data that already informed "
        "model selection; the test-block evaluation is unaffected. (2) The bin rule as written "
        "fails about 40% of perfectly calibrated models with 10 bins "
        "(1 - 0.95^10; `tests/test_calibration.py::test_gate12_bin_rule_false_fail_rate_is_"
        "documented`). Bin-rule failures below should be read with that in mind; changing the "
        "rule needs an owner ADR.",
    ]
    for family, res in results.items():
        lines += [
            "",
            f"## {family}: pooled test blocks",
            "",
            "| target | n | sessions | ECE raw → cal | slope raw → cal | Brier raw → cal [CI] "
            "| log loss cal [CI] | bins failed / checked | gate 12 |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for name, r in res["pooled"].items():
            raw, cal = r["raw"], r["cal"]
            verdict = (
                "would PASS"
                if cal["pass"]
                else "would FAIL ("
                + ", ".join(
                    k
                    for k, ok in (
                        ("ECE", cal["ece_ok"]),
                        ("slope", cal["slope_ok"]),
                        ("bins", cal["bins_ok"]),
                    )
                    if not ok
                )
                + ")"
            )
            lines.append(
                f"| {name} | {r['n']:,} | {r['n_sessions']} | {raw['ece']:.4f} → "
                f"{cal['ece']:.4f} | {raw['slope']:.3f} → {cal['slope']:.3f} "
                f"| {raw['brier']:.4f} → {_ci(cal, 'brier')} | {_ci(cal, 'log_loss')} "
                f"| {cal['bins_failed']} / {cal['bins_checked']} | {verdict} |"
            )
        methods: dict[str, dict[str, int]] = {}
        for r in res["per_fold"]:
            methods.setdefault(r["target"], {}).setdefault(r["method"], 0)
            methods[r["target"]][r["method"]] += 1
        lines += [
            "",
            f"### {family}: chosen method per target (count of folds)",
            "",
            "| target | " + " | ".join(CFG.calibration.methods) + " |",
            "|---|" + "---|" * len(CFG.calibration.methods),
            *[
                f"| {t} | " + " | ".join(str(m.get(k, 0)) for k in CFG.calibration.methods) + " |"
                for t, m in methods.items()
            ],
            "",
            f"### {family}: per fold (calibrated, test block)",
            "",
            "| fold | target | method | n test | ECE | slope | bins failed / checked | gate 12 |",
            "|---|---|---|---|---|---|---|---|",
            *[
                f"| {r['fold']} | {r['target']} | {r['method']} | {r['n_test']:,} "
                f"| {r['cal']['ece']:.4f} | {r['cal']['slope']:.3f} "
                f"| {r['cal']['bins_failed']} / {r['cal']['bins_checked']} "
                f"| {'pass' if r['cal']['pass'] else 'fail'} |"
                for r in res["per_fold"]
            ],
        ]
        for name, r in res["pooled"].items():
            lines += [
                "",
                f"### {family} {name}: reliability (pooled test blocks, calibrated)",
                "",
                "| bin | n | mean predicted | observed | Wilson CI of mean predicted | inside |",
                "|---|---|---|---|---|---|",
                *[
                    f"| {b['bin']} | {b['n']:,} | {b['mean_pred']:.3f} | {b['observed']:.3f} "
                    f"| [{b['wilson_lo']:.3f}, {b['wilson_hi']:.3f}] "
                    f"| {'yes' if b['inside'] else 'NO'} |"
                    for b in r["reliability"]
                ],
            ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


CFG = load_config()


def main() -> int:
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
    folds = walk_forward_folds(sessions, hold, cfg)
    used = sorted({d for f in folds for d in (*f.calib, *f.test)})
    commit = code_commit(ROOT)
    features_id = dataset_id(engine, f"data/features/{cfg.features.version}")
    window = (folds[0].calib[0], folds[-1].test[-1])
    models = {fam: scorers(engine, fam, r) for fam, r in cfg.calibration.reference_runs.items()}
    runs = {
        fam: register_run(
            engine,
            run_kind="calibration",
            config={
                "model": f"calibration_{fam}",
                "reference_run": ref,
                "calibration": cfg.calibration.model_dump(mode="json"),
                "ece_bins": cfg.models.metrics.ece_bins,
                "features": cfg.features.version,
                "labels": cfg.labels.version,
            },
            data_window=window,
            dataset_id=features_id,
            code_commit=commit,
            folds=[
                {
                    "fold": f.index,
                    "calib": [str(f.calib[0]), str(f.calib[-1])],
                    "test": [str(f.test[0]), str(f.test[-1])],
                }
                for f in folds
            ],
        )
        for fam, ref in cfg.calibration.reference_runs.items()
    }
    print(f"registered {runs}")
    results: dict[str, dict[str, Any]] = {}
    try:
        wide, labels = load_data(ROOT, cfg, used)
        for fam, rid in runs.items():
            results[fam] = evaluate(fam, rid, wide, labels, folds, models[fam], engine, cfg)
    except Exception as e:
        for r in runs.values():
            fail_run(engine, r, repr(e))
        raise
    for fam, r in runs.items():
        complete_run(engine, r, results[fam])
    write_report(results, {"commit": commit, "runs": runs, "hold": hold})
    engine.dispose()
    print(f"report {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
