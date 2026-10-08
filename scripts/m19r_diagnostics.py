"""M19R Stage 1 diagnostics (research iteration 1; holdout locked, ADR-0011).

D1  B targets: Model 2 (saved M9 artifacts) vs the implied-move benchmark (`models.implied`, fit
    on train) and vs conditional Model 0, test blocks, Brier skill with session-bootstrap CIs.
D2  Lift: within-fold score percentile of Model 2 for C_call, C_put, A_up, A_dn; observed rate by
    decile and top 10% / 2% / 1% with Wilson CIs, vs the median breakeven probability of the
    decision run (test blocks).
D3  Feature-group ablation for the direction targets, scored on the CALIBRATION blocks: LightGBM
    with each fold's M9-selected grid point and tree count, refit on train with all features and
    with each pre-declared group dropped; Brier change (dropped - full), positive = the group
    helps. The test blocks are not used to choose features.

    uv run python scripts/m19r_diagnostics.py
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from qqq1dte.backtesting.artifacts import model_scorers
from qqq1dte.backtesting.bootstrap import session_bootstrap_ci
from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import block_rows, code_commit, dataset_id, load_data, target_name
from qqq1dte.backtesting.registry import complete_run, fail_run, register_run
from qqq1dte.backtesting.splits import walk_forward_folds
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.models.baseline import fit_baseline
from qqq1dte.models.design import KEYS
from qqq1dte.models.implied import ImpliedBenchmark
from qqq1dte.models.lift import lift_table
from qqq1dte.models.metrics import brier

ROOT = Path(__file__).resolve().parents[1]
END = date(2026, 10, 2)
REPORT = ROOT / "reports" / "research" / "m19r_diagnostics.md"
CFG = load_config()
B_TARGETS = [("B_up", "m=0.0025"), ("B_dn", "m=0.0025"), ("B_up", "m=0.005"), ("B_dn", "m=0.005")]
LIFT_TARGETS = ["C_call", "C_put", "A_up", "A_dn"]


def _ci(sid: np.ndarray, fn: Any) -> list[float]:
    m = CFG.models.metrics
    lo, hi = session_bootstrap_ci(
        sid, fn, CFG.validation.bootstrap_reps, m.bootstrap_seed, m.ci_level
    )
    return [lo, hi]


def _bss(y: np.ndarray, p: np.ndarray, ref: np.ndarray, sid: np.ndarray) -> dict[str, Any]:
    return {
        "bss": 1 - brier(y, p) / brier(y, ref),
        "ci": _ci(sid, lambda w: 1 - brier(y, p, w) / brier(y, ref, w)),
    }


def d1(
    wide: pl.DataFrame,
    labels: pl.DataFrame,
    folds: list[Any],
    scorers: dict[Any, Any],
    cal: TradingCalendar,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for lid, var in B_TARGETS:
        name, m = target_name(lid, var), float(var.split("=")[1])
        t = labels.filter((pl.col("label_id") == lid) & (pl.col("variant") == var))
        parts, per_fold = [], []
        for f in folds:
            tr, te = block_rows(wide, t, f.train), block_rows(wide, t, f.test)
            bench = ImpliedBenchmark.fit(tr, tr["y"].cast(pl.Float64).to_numpy(), m, cal, CFG)
            m0 = fit_baseline(tr.with_columns(vix=pl.col("vix_prev_close")), CFG.models.baseline)
            y = te["y"].cast(pl.Float64).to_numpy()
            p2 = scorers[(f.index, name)][1](te)
            pi = bench.predict(te, cal, CFG)
            p0 = m0.predict(te.with_columns(vix=pl.col("vix_prev_close")))
            parts.append(
                pl.DataFrame(
                    {"session_date": te["session_date"], "y": y, "m2": p2, "imp": pi, "m0": p0}
                )
            )
            per_fold.append(
                {
                    "fold": f.index,
                    "m2_vs_imp": 1 - brier(y, p2) / brier(y, pi),
                    "imp_vs_m0": 1 - brier(y, pi) / brier(y, p0),
                    "coef": bench.coef,
                }
            )
        s = pl.concat(parts)
        y, sid = s["y"].to_numpy(), s["session_date"].to_numpy()
        out[name] = {
            "n": s.height,
            "sessions": s["session_date"].n_unique(),
            "m2_vs_imp": _bss(y, s["m2"].to_numpy(), s["imp"].to_numpy(), sid),
            "imp_vs_m0": _bss(y, s["imp"].to_numpy(), s["m0"].to_numpy(), sid),
            "m2_vs_m0": _bss(y, s["m2"].to_numpy(), s["m0"].to_numpy(), sid),
            "folds_m2_beats_imp": sum(r["m2_vs_imp"] > 0 for r in per_fold),
            "per_fold": per_fold,
        }
        print(f"D1 {name}", flush=True)
    return out


def d2(
    wide: pl.DataFrame, labels: pl.DataFrame, folds: list[Any], scorers: dict[Any, Any]
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for tgt in LIFT_TARGETS:
        t = labels.filter((pl.col("label_id") == tgt) & (pl.col("variant") == ""))
        ys, ranks = [], []
        for f in folds:
            te = block_rows(wide, t, f.test)
            score = scorers[(f.index, tgt)][1](te)
            ranks.append(pl.Series(score).rank("average").to_numpy() / len(score))
            ys.append(te["y"].cast(pl.Float64).to_numpy())
        y, r = np.concatenate(ys), np.concatenate(ranks)
        out[tgt] = {
            "base_rate": float(y.mean()),
            "n": int(y.size),
            "rows": lift_table(
                y,
                r,
                deciles=True,
                top=CFG.research.lift_quantiles,
                level=CFG.models.metrics.ci_level,
            ),
        }
    dec = pl.read_parquet(
        ROOT
        / "data"
        / "decisions"
        / CFG.validation_gates.evidence["decision_run"]
        / "decisions.parquet"
    )
    for key, tgt in (("call", "C_call"), ("put", "C_put")):
        pbe = (dec[f"p_{key}"] - dec[f"margin_{key}"]).drop_nulls()
        out[tgt]["breakeven_median"] = float(pbe.median())  # type: ignore[arg-type]
    return out


def _fixed_fit(
    x: np.ndarray, y: np.ndarray, params: dict[str, Any], rounds: int, names: list[str]
) -> lgb.Booster:
    return lgb.train(
        {**CFG.models.gbm.fixed, **params},
        lgb.Dataset(x, y, feature_name=names),
        num_boost_round=rounds,
    )


def d3(
    wide: pl.DataFrame, labels: pl.DataFrame, folds: list[Any], m9: dict[str, Any]
) -> dict[str, Any]:
    groups = CFG.research.feature_groups
    sel = {(r["fold"], r["target"]): r for r in m9["per_fold"]}
    out: dict[str, Any] = {}
    for tgt in CFG.research.ablation_targets:
        t = labels.filter((pl.col("label_id") == tgt) & (pl.col("variant") == ""))
        parts = []
        for f in folds:
            tr, ca = block_rows(wide, t, f.train), block_rows(wide, t, f.calib)
            feats = [c for c in wide.columns if c not in KEYS]
            r = sel[(f.index, tgt)]
            leaves, min_leaf = (int(v.split("=")[1]) for v in r["params"].split(","))
            params = {"num_leaves": leaves, "min_data_in_leaf": min_leaf}
            y_tr, y_ca = (d["y"].cast(pl.Float64).to_numpy() for d in (tr, ca))
            cols: dict[str, np.ndarray] = {}
            full = _fixed_fit(
                tr.select(feats).to_numpy().astype(np.float64),
                y_tr,
                params,
                r["best_iteration"],
                feats,
            )
            cols["full"] = np.asarray(full.predict(ca.select(feats).to_numpy().astype(np.float64)))
            for g, members in groups.items():
                expanded = set(members) | (
                    {f"dow_{k}" for k in (1, 2, 3, 4)} if "day_of_week" in members else set()
                )
                keep = [c for c in feats if c not in expanded]
                b = _fixed_fit(
                    tr.select(keep).to_numpy().astype(np.float64),
                    y_tr,
                    params,
                    r["best_iteration"],
                    keep,
                )
                cols[g] = np.asarray(b.predict(ca.select(keep).to_numpy().astype(np.float64)))
            m0 = fit_baseline(tr.with_columns(vix=pl.col("vix_prev_close")), CFG.models.baseline)
            cols["m0"] = m0.predict(ca.with_columns(vix=pl.col("vix_prev_close")))
            parts.append(pl.DataFrame({"session_date": ca["session_date"], "y": y_ca, **cols}))
        s = pl.concat(parts)
        y, sid, pf = s["y"].to_numpy(), s["session_date"].to_numpy(), s["full"].to_numpy()
        res = {"full_vs_m0": _bss(y, pf, s["m0"].to_numpy(), sid), "groups": {}}
        for g in groups:
            pg = s[g].to_numpy()
            res["groups"][g] = {
                "delta_brier": brier(y, pg) - brier(y, pf),
                "ci": _ci(sid, lambda w, pg=pg, y=y, pf=pf: brier(y, pg, w) - brier(y, pf, w)),
            }
        out[tgt] = res
        print(f"D3 {tgt}", flush=True)
    return out


def _s(d: dict[str, Any], k: str = "bss") -> str:
    return f"{d[k]:+.4f} [{d['ci'][0]:+.4f}, {d['ci'][1]:+.4f}]"


def write_report(
    r1: dict[str, Any], r2: dict[str, Any], r3: dict[str, Any], meta: dict[str, Any]
) -> None:
    lines = [
        "# M19R Stage 1 diagnostics (research iteration 1)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {meta['commit'][:12]}, run "
        f"`{meta['run_id']}`. Walk-forward folds 1-7; final holdout locked (ADR-0011). BSS = 1 - "
        "Brier(model) / Brier(reference), session-bootstrap 95% CIs. Model 2 = saved M9 LightGBM "
        "artifacts (uncalibrated scores).",
        "",
        "## D1: is the move-size (B) skill beyond the option-implied move?",
        "",
        "Implied benchmark: logistic regression on log(m / implied sigma to expiry), log(window "
        "minutes), log(minutes to expiry), fit on each fold's training rows; implied sigma "
        "from the ATM straddle at T (`straddle_move` x sqrt(pi/2)). Test blocks.",
        "",
        "| target | n | sessions | Model 2 vs implied | folds Model 2 better | implied vs Model 0 "
        "| Model 2 vs Model 0 |",
        "|---|---|---|---|---|---|---|",
        *[
            f"| {k} | {v['n']:,} | {v['sessions']} | {_s(v['m2_vs_imp'])} | "
            f"{v['folds_m2_beats_imp']}/7 | {_s(v['imp_vs_m0'])} | {_s(v['m2_vs_m0'])} |"
            for k, v in r1.items()
        ],
        "",
        "## D2: lift of Model 2 scores (within-fold percentile), test blocks",
        "",
    ]
    for tgt, v in r2.items():
        be = v.get("breakeven_median")
        lines += [
            f"### {tgt} (base rate {v['base_rate']:.3f}, n {v['n']:,}"
            + (f"; median breakeven probability {be:.3f}" if be else "")
            + ")",
            "",
            "| bucket | n | observed | 95% Wilson CI |",
            "|---|---|---|---|",
            *[
                f"| {r['bucket']} | {r['n']:,} | {r['observed']:.3f} | [{r['wilson_lo']:.3f}, "
                f"{r['wilson_hi']:.3f}] |"
                for r in v["rows"]
            ],
            "",
        ]
    lines += [
        "## D3: feature-group ablation for direction targets (calibration blocks)",
        "",
        "Δ Brier = Brier(group dropped) - Brier(all features); positive = the group carries "
        "information for that target. Each fold's M9 grid point and tree count, refit on train, "
        "scored on the calibration block (the test blocks are not used to choose features).",
        "",
        "| target | full vs Model 0 (calib) | " + " | ".join(CFG.research.feature_groups) + " |",
        "|---|---|" + "---|" * len(CFG.research.feature_groups),
        *[
            f"| {t} | {_s(v['full_vs_m0'])} | "
            + " | ".join(
                f"{v['groups'][g]['delta_brier']:+.5f} [{v['groups'][g]['ci'][0]:+.5f}, "
                f"{v['groups'][g]['ci'][1]:+.5f}]"
                for g in CFG.research.feature_groups
            )
            + " |"
            for t, v in r3.items()
        ],
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
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
    used = sorted({d for f in folds for d in (*f.train, *f.calib, *f.test)})
    commit = code_commit(ROOT)
    m9_run = CFG.validation_gates.evidence["model_run"]
    run_id = register_run(
        engine,
        run_kind="diagnostic",
        config={
            "model": "m19r_stage1",
            "research": CFG.research.model_dump(mode="json"),
            "model_run": m9_run,
        },
        data_window=(folds[0].train[0], folds[-1].test[-1]),
        dataset_id=dataset_id(engine, f"data/features/{CFG.features.version}"),
        code_commit=commit,
        folds=[],
    )
    print(f"registered run {run_id}")
    try:
        wide, labels = load_data(ROOT, CFG, used)
        scorers = model_scorers(engine, ROOT, "gbm_m2", m9_run)
        with engine.connect() as c:
            m9 = dict(
                c.execute(
                    text("SELECT metrics FROM validation_runs WHERE run_id = :r"), {"r": m9_run}
                ).scalar_one()
            )
        r1 = d1(wide, labels, folds, scorers, cal)
        r2 = d2(wide, labels, folds, scorers)
        r3 = d3(wide, labels, folds, m9)
    except Exception as e:
        fail_run(engine, run_id, repr(e))
        raise
    complete_run(engine, run_id, {"d1": r1, "d2": r2, "d3": r3})
    write_report(r1, r2, r3, {"commit": commit, "run_id": run_id})
    engine.dispose()
    print(f"completed run {run_id}; report {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
