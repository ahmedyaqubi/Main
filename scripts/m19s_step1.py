"""M19S Step 1 (ADR-0012 D2): model-free screen of the study trade definitions against the
direction model's achievable accuracy, on walk-forward test blocks (development data).

1. Direction scores per test-block timestamp: Model 2 A_up / A_dn. h = 90: the saved M9 models
   (`study_1b.reference_m2_run`). h = 45 / 150: refits with each fold's frozen M9 grid point
   (early stopping on the calibration block as in M9), one registered run per horizon (trials).
2. Side = CALL if p_up > p_dn else PUT; s = max. Coverage c = top c by s within each fold (among
   the timestamps the definition can trade). Direction over the definition's horizon (its cap)
   from the study `moves` with the frozen deadband.
3. Per definition x coverage: C, W, D, p_D, a*, Â, Δ with one shared session-block bootstrap,
   guards, the advance rule; plus per-side model-free a*, time-of-day, deadband sensitivity and
   the live-like-policy drawdown for anything that advances. One registered run (a trial).
Rows whose trade is INVALID / UNRESOLVED or whose move is missing are excluded and counted
(never filled). The holdout is never read (ADR-0011).

    uv run python scripts/m19s_step1.py
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text

from qqq1dte.backtesting.artifacts import model_scorers
from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import code_commit, dataset_id, load_data
from qqq1dte.backtesting.registry import complete_run, fail_run, n_trials, register_run
from qqq1dte.backtesting.screen import (
    UNDEFINED,
    Cell,
    advance,
    bootstrap_draws,
    coverage_mask,
    direction,
    max_drawdown,
    policy_trades,
    predicted_side,
    screen_stats,
)
from qqq1dte.backtesting.splits import Fold, walk_forward_folds
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import ET
from qqq1dte.models.design import KEYS
from qqq1dte.models.gbm import fit_gbm, save
from qqq1dte.models.metrics import auc

ROOT = Path(__file__).resolve().parents[1]
END = date(2026, 10, 2)
CFG = load_config()
S = CFG.study_1b
LDIR = ROOT / "data" / "labels" / S.labels_dir
T0_DIR = ROOT / "data" / "labels" / f"{CFG.labels.version}_option"
REPORT = ROOT / "reports" / "research" / "m19s_step1.md"
Arr = np.ndarray


def _point(key: str) -> dict[str, Any]:
    a, b = key.split(",")
    return {"num_leaves": int(a.split("=")[1]), "min_data_in_leaf": int(b.split("=")[1])}


def frozen_points(engine: Engine) -> dict[tuple[int, str], dict[str, Any]]:
    with engine.connect() as c:
        m = c.execute(
            text("SELECT metrics FROM validation_runs WHERE run_id = :r"),
            {"r": S.reference_m2_run},
        ).scalar_one()
    return {
        (r["fold"], r["target"]): _point(r["params"])
        for r in m["per_fold"]
        if r["target"] in ("A_up", "A_dn")
    }


def scores_90(engine: Engine, wide: pl.DataFrame, folds: list[Fold]) -> pl.DataFrame:
    sc = model_scorers(engine, ROOT, "gbm_m2", S.reference_m2_run)
    parts = []
    for f in folds:
        te = wide.filter(pl.col("session_date").is_in(list(f.test))).sort(KEYS)
        parts.append(
            te.select(KEYS).with_columns(
                fold=pl.lit(f.index),
                p_up=pl.Series(sc[(f.index, "A_up")][1](te)),
                p_dn=pl.Series(sc[(f.index, "A_dn")][1](te)),
            )
        )
    return pl.concat(parts)


def refit_scores(
    h: int,
    wide: pl.DataFrame,
    moves: pl.DataFrame,
    folds: list[Fold],
    points: dict[tuple[int, str], dict[str, Any]],
    run_id: str,
) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
    """A_up / A_dn at horizon h: frozen M9 grid point per fold, fit on train, early stopping on
    the calibration block, scores on the test block."""
    db = CFG.labels.direction.deadband
    feats = [c for c in wide.columns if c not in KEYS]
    rows = wide.join(
        moves.select(*KEYS, pl.col(f"ret_{h}").alias("ret")).drop_nulls("ret"), on=KEYS
    ).with_columns(
        A_up=(pl.col("ret") > db).cast(pl.Float64), A_dn=(pl.col("ret") < -db).cast(pl.Float64)
    )
    parts, recs = [], []
    for f in folds:  # scores come from the saved (truncated) model: what is scored is stored
        tr, ca, te = (
            rows.filter(pl.col("session_date").is_in(list(b))).sort(KEYS)
            for b in (f.train, f.calib, f.test)
        )
        x = {
            k: d.select(feats).to_numpy().astype(np.float64)
            for k, d in (("tr", tr), ("ca", ca), ("te", te))
        }
        for tgt in ("A_up", "A_dn"):
            fit = fit_gbm(
                x["tr"],
                tr[tgt].to_numpy(),
                x["ca"],
                ca[tgt].to_numpy(),
                points[(f.index, tgt)],
                CFG.models.gbm,
                feats,
            )
            sha = save(
                fit, ROOT / "data" / "models" / "m2" / run_id / f"fold{f.index}_{tgt}_h{h}.txt"
            )
            recs.append(
                {
                    "fold": f.index,
                    "target": tgt,
                    "params": points[(f.index, tgt)],
                    "best_iteration": fit.best_iteration,
                    "calib_log_loss": fit.calib_log_loss,
                    "auc_test": auc(te[tgt].to_numpy(), fit.predict(x["te"])),
                    "n_train": tr.height,
                    "n_test": te.height,
                    "sha256": sha,
                }
            )
            print(f"h={h} fold {f.index} {tgt}: it={fit.best_iteration}", flush=True)
        # all test-block timestamps are scored (also those whose move is missing)
        all_te = wide.filter(pl.col("session_date").is_in(list(f.test))).sort(KEYS)
        xa = all_te.select(feats).to_numpy().astype(np.float64)
        parts.append(
            all_te.select(KEYS).with_columns(
                fold=pl.lit(f.index),
                p_up=pl.Series(_refit_predict(run_id, f.index, "A_up", h, xa)),
                p_dn=pl.Series(_refit_predict(run_id, f.index, "A_dn", h, xa)),
            )
        )
    return pl.concat(parts), recs


def _refit_predict(run_id: str, fold: int, tgt: str, h: int, x: Arr) -> Arr:
    b = lgb.Booster(
        model_file=str(ROOT / "data" / "models" / "m2" / run_id / f"fold{fold}_{tgt}_h{h}.txt")
    )
    return np.asarray(b.predict(x))


def trades_for(name: str, sessions: list[date]) -> pl.DataFrame:
    src = T0_DIR if name == "T0" else LDIR / name
    return pl.concat(
        [
            pl.read_parquet(src / f"session={d}.parquet").select(
                "prediction_ts", "side", "exit_ts", "net_pnl", "outcome_class"
            )
            for d in sessions
        ]
    )


def bucket(ts: pl.Series) -> pl.Series:
    starts = [time.fromisoformat(b) for b in S.time_buckets]
    et = [t.astimezone(ET).time() for t in ts.to_list()]
    return pl.Series([max(i for i, b in enumerate(starts) if t >= b) for t in et])


def cell_frame(
    name: str, scores: pl.DataFrame, moves: pl.DataFrame, trades: pl.DataFrame, cohort: str
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Scored timestamps the definition can trade (cohort), with predicted side, direction,
    the predicted side's net P&L and exit time; exclusions counted."""
    d = S.definitions[name]
    h = d.cap_minutes
    side, s = predicted_side(scores["p_up"].to_numpy(), scores["p_dn"].to_numpy())
    df = scores.with_columns(side=pl.Series(side), s=pl.Series(s)).join(
        moves.select(*KEYS, pl.col(f"ret_{h}").alias("ret")), on=KEYS, how="left"
    )
    if d.entry_cutoff is not None or name == "T0":
        cut = d.entry_cutoff or S.definitions["T5"].entry_cutoff
        late = pl.Series([t.astimezone(ET).time() > cut for t in df["prediction_ts"].to_list()])
        if cohort == "early":
            df = df.filter(~late)
        elif cohort == "late":
            df = df.filter(late)
    df = df.join(trades, on=["prediction_ts", "side"], how="left").sort("fold", "prediction_ts")
    n0 = df.height
    excl = {
        "no_trade_outcome": int(df["net_pnl"].is_null().sum()),
        "no_move": int(df["ret"].is_null().sum()),
    }
    df = df.with_columns(
        dir=pl.Series(
            direction(df["ret"].fill_null(np.nan).to_numpy(), CFG.labels.direction.deadband)
        ),
        net=pl.col("net_pnl"),
        bucket=bucket(df["prediction_ts"]),
    )
    excl["scored"] = n0
    return df, excl


def covered(df: pl.DataFrame, c: float) -> pl.DataFrame:
    """Top c by score within each fold among all eligible timestamps, then drop the excluded."""
    m = coverage_mask(df["fold"].to_numpy(), df["s"].to_numpy(), c)
    return df.filter(pl.Series(m)).drop_nulls(["net", "ret"])


def _q(a: Arr, lo: float, hi: float) -> list[float]:
    v = a[~np.isnan(a)]
    return np.quantile(v, [lo, hi]).tolist() if v.size else [float("nan")] * 2


def evaluate(df: pl.DataFrame) -> dict[str, Any]:
    pt = screen_stats(df, np.ones(df.height))
    dr = bootstrap_draws(df, CFG)
    dl = dr["delta"]
    lb = float(np.quantile(np.where(np.isnan(dl), UNDEFINED, dl), 1 - S.lower_bound_level))
    net = df["net"].to_numpy()
    return {
        **pt,
        "c_minus_w": pt["C"] - pt["W"],
        "delta_lb": lb,
        "a_star_ci": _q(dr["a_star"], 0.025, 0.975),
        "a_hat_ci": _q(dr["a_hat"], 0.025, 0.975),
        "mean_net_ci": _q(dr["mean_net"], 0.025, 0.975),
        "a_star_undefined_share": float(np.isnan(dr["a_star"]).mean()),
        "median_net": float(np.median(net)),
        "loss_share": float((net < 0).mean()),
        "n_trades": df.height,
        "n_sessions": df["session_date"].n_unique(),
    }


def per_side(trades: pl.DataFrame, moves: pl.DataFrame, h: int, test: set[date]) -> dict[str, Any]:
    """Model-free a* per side at c = 100%: every test-block trade of that side."""
    out = {}
    mv = moves.filter(pl.col("session_date").is_in(list(test))).select(
        *KEYS, pl.col(f"ret_{h}").alias("ret")
    )
    for side in ("C", "P"):
        df = (
            trades.filter(pl.col("side") == side)
            .join(mv, on="prediction_ts")
            .drop_nulls(["net_pnl", "ret"])
            .with_columns(net=pl.col("net_pnl"))
        )
        df = df.with_columns(
            dir=pl.Series(direction(df["ret"].to_numpy(), CFG.labels.direction.deadband))
        )
        out[side] = {**screen_stats(df, np.ones(df.height)), "n": df.height}
    return out


def drawdown(df: pl.DataFrame, test_sessions: list[date]) -> dict[str, Any]:
    pol = policy_trades(
        df.select("session_date", "prediction_ts", "exit_ts", "net"), CFG.trade.max_entries_per_day
    )
    per = (
        pl.DataFrame({"session_date": test_sessions})
        .join(pol.group_by("session_date").agg(pl.col("net").sum()), on="session_date", how="left")
        .fill_null(0.0)
        .sort("session_date")
    )
    v = per["net"].to_numpy()
    rng = np.random.default_rng(CFG.models.metrics.bootstrap_seed)
    dd = [
        max_drawdown(rng.choice(v, size=len(v), replace=True))
        for _ in range(CFG.validation.bootstrap_reps)
    ]
    return {
        "policy_trades": pol.height,
        "policy_sessions": pol["session_date"].n_unique(),
        "mean_session_net": float(v.mean()),
        "sd_session_net": float(v.std(ddof=1)),
        "max_drawdown_observed": max_drawdown(v),
        "max_drawdown_boot_median": float(np.median(dd)),
        "max_drawdown_boot_p95": float(np.quantile(dd, 0.95)),
    }


def main() -> int:
    load_dotenv(ROOT / ".env")
    engine = create_engine(os.environ["DATABASE_URL"])
    cal = TradingCalendar(CFG)
    hold = cal.final_holdout_start(END)
    sessions = cal.research_sessions(CFG.history.option_era_start, hold)
    HoldoutGuard(hold, engine).check(sessions)
    folds = walk_forward_folds(sessions, hold, CFG)
    window = (folds[0].train[0], folds[-1].test[-1])
    before = n_trials(engine, *window)
    new = len(S.refit_horizons) + 1
    if before - S.n_trials_at_acceptance + new > S.max_new_trials:
        raise RuntimeError(f"budget: n_trials {before} + {new} exceeds ADR-0012 cap")
    commit = code_commit(ROOT)
    mid = dataset_id(engine, f"data/labels/{S.labels_dir}/moves")
    test_sessions = sorted({d for f in folds for d in f.test})
    wide, _ = load_data(ROOT, CFG, sessions)
    moves = pl.concat([pl.read_parquet(LDIR / "moves" / f"session={d}.parquet") for d in sessions])
    points = frozen_points(engine)

    scores = {90: scores_90(engine, wide, folds)}
    refit_runs: dict[int, str] = {}
    refit_recs: dict[int, list[dict[str, Any]]] = {}
    for h in S.refit_horizons:
        rid = register_run(
            engine,
            run_kind="refit",
            config={
                "model": f"m19s_A_refit_h{h}",
                "adr": "0012",
                "horizon_minutes": h,
                "frozen_from": S.reference_m2_run,
                "gbm": CFG.models.gbm.model_dump(mode="json"),
                "deadband": CFG.labels.direction.deadband,
            },
            data_window=window,
            dataset_id=mid,
            code_commit=commit,
            folds=[],
        )
        refit_runs[h] = rid
        try:
            scores[h], refit_recs[h] = refit_scores(h, wide, moves, folds, points, rid)
            complete_run(engine, rid, {"per_fold": refit_recs[h]})
        except Exception as e:
            fail_run(engine, rid, repr(e))
            raise

    sid = register_run(
        engine,
        run_kind="screen",
        config={
            "model": "m19s_step1_screen",
            "adr": "0012",
            "study_1b": S.model_dump(mode="json"),
            "deadband": CFG.labels.direction.deadband,
            "refit_configs": [f"m19s_A_refit_h{h}" for h in S.refit_horizons],
        },
        data_window=window,
        dataset_id=mid,
        code_commit=commit,
        folds=[],
    )
    try:
        res = screen(scores, moves, test_sessions, set(test_sessions))
        res["refits"] = {h: refit_runs[h] for h in refit_runs}
        res["n_trials_before"] = before
        res["n_trials_after"] = n_trials(engine, *window)
        complete_run(engine, sid, res)
    except Exception as e:
        fail_run(engine, sid, repr(e))
        raise
    write_report(res, sid, refit_runs, refit_recs, commit)
    engine.dispose()
    print(f"report {REPORT.relative_to(ROOT)}; advance: {res['advance'] or 'none (kill rule)'}")
    return 0


COHORTS = {"T0": ["all", "early", "late"], "T5": ["early", "late"]}


def screen(
    scores: dict[int, pl.DataFrame], moves: pl.DataFrame, test_sessions: list[date], test: set[date]
) -> dict[str, Any]:
    cells: list[Cell] = []
    out: dict[str, Any] = {
        "cells": [],
        "exclusions": {},
        "per_side": {},
        "buckets": [],
        "sensitivity": [],
    }
    frames: dict[tuple[str, str, float], pl.DataFrame] = {}
    for name, d in S.definitions.items():
        tr = trades_for(name, test_sessions)
        out["per_side"][name] = per_side(tr, moves, d.cap_minutes, test)
        for cohort in COHORTS.get(name, ["all"]):
            df, excl = cell_frame(name, scores[d.cap_minutes], moves, tr, cohort)
            out["exclusions"][f"{name}/{cohort}"] = excl
            cohort_ok = not (name == "T5" and cohort != "early")
            report_only = name == "T0" and cohort != "all"
            can_advance = cohort_ok and not report_only
            for c in S.coverages:
                cv = covered(df, c)
                ev = evaluate(cv)
                cell = Cell(
                    name,
                    c,
                    ev["delta_lb"],
                    ev["n_trades"],
                    ev["n_sessions"],
                    ev["c_minus_w"],
                    cohort_ok,
                )
                barred = cell.barred(CFG) + (["REPORT_ONLY_COHORT"] if report_only else [])
                rec = {
                    "definition": name,
                    "cohort": cohort,
                    "coverage": c,
                    **ev,
                    "barred": barred,
                    "qualifies": can_advance and cell.qualifies(CFG),
                }
                out["cells"].append(rec)
                if can_advance:
                    cells.append(cell)
                    frames[(name, cohort, c)] = cv
                for b in range(len(S.time_buckets)):
                    sub = cv.filter(pl.col("bucket") == b)
                    if sub.height:
                        st = screen_stats(sub, np.ones(sub.height))
                        out["buckets"].append(
                            {
                                "definition": name,
                                "cohort": cohort,
                                "coverage": c,
                                "bucket": S.time_buckets[b],
                                "n": sub.height,
                                "a_star": st["a_star"],
                                "a_hat": st["a_hat"],
                                "delta": st["delta"],
                            }
                        )
                if can_advance:
                    for db in S.sensitivity_deadbands:
                        sub = cv.with_columns(dir=pl.Series(direction(cv["ret"].to_numpy(), db)))
                        st = screen_stats(sub, np.ones(sub.height))
                        out["sensitivity"].append(
                            {
                                "definition": name,
                                "coverage": c,
                                "deadband": db,
                                "a_star": st["a_star"],
                                "a_hat": st["a_hat"],
                                "delta": st["delta"],
                            }
                        )
    adv = advance(cells, CFG)
    out["advance"] = [
        {"definition": c.definition, "coverage": c.coverage, "delta_lb": c.delta_lb} for c in adv
    ]
    out["drawdown"] = {
        c.definition: drawdown(
            frames[(c.definition, "early" if c.definition == "T5" else "all", c.coverage)],
            test_sessions,
        )
        for c in adv
    }
    return out


def _f(x: float, nd: int = 3, sign: bool = False) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def _row(*cells: object) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def _ci(x: float, ci: list[float], nd: int = 3, sign: bool = False) -> str:
    return f"{_f(x, nd, sign)} [{_f(ci[0], nd, sign)}, {_f(ci[1], nd, sign)}]"


def write_report(
    res: dict[str, Any],
    sid: str,
    refit_runs: dict[int, str],
    refit_recs: dict[int, list[dict[str, Any]]],
    commit: str,
) -> None:
    refits = ", ".join(f"h={h} `{r}`" for h, r in refit_runs.items())
    cap = S.n_trials_at_acceptance + S.max_new_trials
    lines = [
        "# M19S Step 1: model-free screen (ADR-0012 D2)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {commit[:12]}. Screen run "
        f"`{sid}`; refits {refits}. n_trials {res['n_trials_before']} → "
        f"{res['n_trials_after']} (cap {cap}).",
        "",
        "Population: walk-forward **test blocks** (development data under ADR-0012 D0; 7 folds, "
        "2024-05-28 → 2026-02-27). Holdout not read. Direction scores: Model 2 A_up / A_dn "
        "(h = 90: saved M9 models; h = 45 / 150: refits with the frozen M9 grid point). Side = "
        "CALL if p_up > p_dn else PUT; coverage = top c by max(p_up, p_dn) within each fold, among "
        "the timestamps the definition can trade. a* and Â are computed on the same covered rows; "
        f"Δ = Â - a*; Δ LB = one-sided {S.lower_bound_level:.0%} lower bound (paired session-block "
        f"bootstrap, {CFG.validation.bootstrap_reps} reps). Conservative fills, §4.8 costs, "
        "1 contract.",
        "",
        "**Disclosure (D0.4):** one registered screen run, but about 14 definition x side cells x "
        "3 coverages are compared; qualifying at any coverage counts. The screen is a selection on "
        "development data.",
        "",
        "## Screen",
        "",
        _row(
            "def",
            "cohort",
            "c",
            "trades",
            "sessions",
            "mean net $ [CI]",
            "median $",
            "loss %",
            "C",
            "W",
            "D",
            "p_D",
            "a* [CI]",
            "Â [CI]",
            "Δ",
            "Δ LB",
            "barred",
            "qualifies",
        ),
        "|" + "---|" * 18,
    ]
    for r in res["cells"]:
        lines.append(
            _row(
                r["definition"],
                r["cohort"],
                f"{r['coverage']:.0%}",
                f"{r['n_trades']:,}",
                r["n_sessions"],
                _ci(r["mean_net"], r["mean_net_ci"], 2, True),
                _f(r["median_net"], 2, True),
                f"{r['loss_share']:.0%}",
                _f(r["C"], 1),
                _f(r["W"], 1),
                _f(r["D"], 1),
                f"{r['p_D']:.2f}",
                _ci(r["a_star"], r["a_star_ci"]),
                _ci(r["a_hat"], r["a_hat_ci"]),
                _f(r["delta"], 3, True),
                _f(r["delta_lb"], 3, True),
                ", ".join(r["barred"]) or "-",
                "yes" if r["qualifies"] else "no",
            )
        )
    adv = res["advance"]
    decision = (
        "**Advance:** "
        + ", ".join(
            f"{a['definition']} at c = {a['coverage']:.0%} (Δ LB {a['delta_lb']:+.3f})" for a in adv
        )
        if adv
        else "**No definition qualifies: the kill rule fires.** The long-premium direction line "
        "is closed (ADR-0012 D2)."
    )
    lines += [
        "",
        "## Decision",
        "",
        decision,
        "",
        "## Per-side model-free a* (c = 100%, every test-block trade of that side)",
        "",
        _row("def", "side", "n", "mean net $", "C", "W", "p_D", "a*", "direction base rate"),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, sides in res["per_side"].items():
        for side, r in sides.items():
            lines.append(
                _row(
                    name,
                    side,
                    f"{r['n']:,}",
                    _f(r["mean_net"], 2, True),
                    _f(r["C"], 1),
                    _f(r["W"], 1),
                    f"{r['p_D']:.2f}",
                    _f(r["a_star"]),
                    _f(r["a_hat"]),
                )
            )
    lines += [
        "",
        "## Time of day (points; report only)",
        "",
        _row("def", "cohort", "c", "from (ET)", "n", "a*", "Â", "Δ"),
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in res["buckets"]:
        lines.append(
            _row(
                r["definition"],
                r["cohort"],
                f"{r['coverage']:.0%}",
                r["bucket"],
                f"{r['n']:,}",
                _f(r["a_star"]),
                _f(r["a_hat"]),
                _f(r["delta"], 3, True),
            )
        )
    lines += [
        "",
        "## Deadband sensitivity (points; report only)",
        "",
        _row("def", "c", "deadband", "a*", "Â", "Δ"),
        "|---|---|---|---|---|---|",
    ]
    for r in res["sensitivity"]:
        lines.append(
            _row(
                r["definition"],
                f"{r['coverage']:.0%}",
                f"{r['deadband'] * 1e4:.0f} bp",
                _f(r["a_star"]),
                _f(r["a_hat"]),
                _f(r["delta"], 3, True),
            )
        )
    lines += [
        "",
        "Edge-margin sensitivity (0.01 / 0.03 / 0.05) needs calibrated direction probabilities, "
        "which exist only in Step 2 (rule 6: raw scores are not probabilities); it is reported "
        "there.",
        "",
        "## Exclusions (never filled)",
        "",
        _row("def / cohort", "scored", "no trade outcome (INVALID / UNRESOLVED)", "no move"),
        "|---|---|---|---|",
    ]
    for k, e in res["exclusions"].items():
        lines.append(_row(k, f"{e['scored']:,}", f"{e['no_trade_outcome']:,}", f"{e['no_move']:,}"))
    if res["drawdown"]:
        lines += [
            "",
            "## Live-like policy for advancing definitions (≤ 3 entries/day, 1 open position)",
            "",
            _row(
                "def",
                "trades",
                "sessions",
                "mean / SD per session $",
                "max DD observed $",
                "max DD bootstrap median / 95% $",
            ),
            "|---|---|---|---|---|---|",
        ]
        for k, v in res["drawdown"].items():
            lines.append(
                _row(
                    k,
                    f"{v['policy_trades']:,}",
                    v["policy_sessions"],
                    f"{v['mean_session_net']:+.2f} / {v['sd_session_net']:.2f}",
                    f"{v['max_drawdown_observed']:.0f}",
                    f"{v['max_drawdown_boot_median']:.0f} / {v['max_drawdown_boot_p95']:.0f}",
                )
            )
    lines += [
        "",
        "## Refits (h = 45 / 150; frozen M9 grid point)",
        "",
        _row("h", "fold", "target", "params", "trees", "test AUC"),
        "|---|---|---|---|---|---|",
    ]
    for h, recs in refit_recs.items():
        for r in recs:
            pt = r["params"]
            lines.append(
                _row(
                    h,
                    r["fold"],
                    r["target"],
                    f"leaves={pt['num_leaves']}, min_leaf={pt['min_data_in_leaf']}",
                    r["best_iteration"],
                    _f(r["auc_test"]),
                )
            )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
