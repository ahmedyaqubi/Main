"""M15: the §4.1 decision engine on every test-block prediction timestamp; NO_TRADE analysis and
the gate-13 / gate-14 checks.

For each test-block timestamp T (pre-holdout, M10 folds):
- calibrated P(C_call WIN), P(C_put WIN) from the pre-declared model family (decision.model_family,
  saved artifacts) and its M13 calibrators (sha256-checked); computed from features only, never
  conditioned on labels;
- per side, the frozen selection and §4.9 gates at T_e, and the moderate entry fill;
- `decide` (§4.1, binary-conservative EV) with the R1 regime cell (gate-13 hook);
- CALL / PUT decisions go through the event engine (moderate fill, one position, <= 3 entries):
  BLOCKED_POSITION_OPEN is kept distinct from NO_TRADE;
- gate 14 counterfactual: at every NO_TRADE timestamp the higher-EV side is simulated anyway
  (one independent trade, moderate fill).
One `validation_runs` row (run_kind "decision"); Parquet in data/decisions/<run_id>/.

    uv run python scripts/m15_decisions.py [--workers 7]
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text

from qqq1dte.backtesting.artifacts import calibrators, model_scorers
from qqq1dte.backtesting.bootstrap import session_bootstrap_ci
from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import code_commit, dataset_id
from qqq1dte.backtesting.registry import complete_run, fail_run, register_run
from qqq1dte.backtesting.reporting import net_from_frame, summarize_net
from qqq1dte.backtesting.session_data import session_inputs
from qqq1dte.backtesting.splits import Fold, walk_forward_folds
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.execution_sim.decision import CalibratedProbability, SideInput, decide
from qqq1dte.execution_sim.engine import Signal, run_session, selection_at
from qqq1dte.execution_sim.fills import Moderate
from qqq1dte.execution_sim.selection import NoTrade
from qqq1dte.features.engine import FEATURE_NAMES
from qqq1dte.models.design import wide_features

ROOT = Path(__file__).resolve().parents[1]
END = date(2026, 10, 2)
REPORT = ROOT / "reports" / "decisions" / "m15_no_trade.md"
CFG = load_config()
DT = pl.Datetime("us", "UTC")
TRADE_COLS = [
    "side",
    "outcome",
    "entry_price",
    "exit_price",
    "gross_pnl",
    "commissions",
    "fees",
    "net_pnl",
]


def probabilities(engine: Engine, folds: list[Fold]) -> pl.DataFrame:
    """Calibrated P(WIN) for C_call / C_put at every test-block timestamp (features only)."""
    fam = CFG.decision.model_family
    scorers = model_scorers(engine, ROOT, fam, CFG.calibration.reference_runs[fam])
    cals = calibrators(engine, ROOT, CFG.regimes.calibration_runs[fam])
    fdir = ROOT / "data" / "features" / CFG.features.version
    parts = []
    for f in folds:
        wide = pl.concat(
            [
                wide_features(pl.read_parquet(fdir / f"session={d}.parquet"), FEATURE_NAMES)
                for d in f.test
            ]
        )
        cols: dict[str, Any] = {}
        for tgt, key in (("C_call", "call"), ("C_put", "put")):
            mid, scorer = scorers[(f.index, tgt)]
            cid, calib = cals[mid]
            cols[f"p_{key}"] = pl.Series(calib.apply(scorer(wide)))
            cols[f"ver_{key}"] = pl.lit(cid)
        parts.append(wide.select("session_date", "prediction_ts").with_columns(**cols))
    return pl.concat(parts).with_columns(pl.col("prediction_ts").cast(DT))


def regime_cells(engine: Engine) -> pl.DataFrame:
    with engine.connect() as c:
        rows = c.execute(
            text("SELECT ts, axis, value FROM regime_labels WHERE regime_version = :v"),
            {"v": CFG.regimes.version},
        ).all()
    df = pl.DataFrame(rows, schema={"ts": DT, "axis": pl.String, "value": pl.String}, orient="row")
    wide = df.pivot(on="axis", index="ts", values="value")
    return wide.select(
        pl.col("ts").alias("prediction_ts"),
        cell=pl.concat_str(["volatility", "trend", "event"], separator="/"),
    )


def _trade_row(tr: Any) -> dict[str, Any]:
    return {k: getattr(tr, k) for k in TRADE_COLS}


def session_job(args: tuple[date, dict[str, pl.DataFrame], list[dict[str, Any]]]) -> dict[str, Any]:
    d, t, probs = args
    cfg = load_config()
    cal = TradingCalendar(cfg)
    fill = Moderate(cfg, cfg.fills.moderate_alpha)
    lat = timedelta(seconds=cfg.fills.latency_s)
    rows, signals = [], []
    for pr in probs:
        ts = pr["prediction_ts"]
        sides = []
        for s, key in (("C", "call"), ("P", "put")):
            p = CalibratedProbability(pr[f"p_{key}"], pr[f"ver_{key}"])
            sel = selection_at(d, s, ts + lat, t["und"], t["chain"], t["records"], cal, cfg)
            if isinstance(sel, NoTrade):
                sides.append(SideInput(s, p, sel.reason, None))
            else:
                sides.append(SideInput(s, p, None, fill.buy(sel.quote)))
        out = decide(sides[0], sides[1], cfg, regime_cell=pr["cell"])
        rows.append(
            {
                **pr,
                "decision": out.decision,
                "reasons": list(out.reasons),
                "ev_call": out.ev_call,
                "ev_put": out.ev_put,
                "margin_call": out.margin_call,
                "margin_put": out.margin_put,
                "entry_call": sides[0].entry_price,
                "entry_put": sides[1].entry_price,
            }
        )
        if out.decision in ("CALL", "PUT"):
            signals.append(Signal(ts, "C" if out.decision == "CALL" else "P"))
    res = run_session(d, signals, t["und"], t["chain"], t["records"], cal, cfg, fill)
    final = {dec.prediction_ts: dec for dec in res.decisions}
    trades = [
        {"session_date": d, "prediction_ts": tr.prediction_ts, **_trade_row(tr)}
        for tr in res.trades
        if tr.net_pnl is not None
    ]
    cfs = []
    for r in rows:
        e = final.get(r["prediction_ts"])
        r["final"] = (
            r["decision"] if e is None else ({"ENTERED": r["decision"]}.get(e.decision, e.decision))
        )
        if r["decision"] != "NO_TRADE":
            continue
        evs = [(r["ev_call"], "C"), (r["ev_put"], "P")]
        evs = [x for x in evs if x[0] is not None]
        if not evs:
            continue
        side = max(evs, key=lambda x: (x[0], x[1] == "C"))[1]
        cf = run_session(
            d,
            [Signal(r["prediction_ts"], side)],
            t["und"],
            t["chain"],
            t["records"],
            cal,
            cfg,
            fill,
        )
        tr = cf.trades[0] if cf.trades else None
        if tr is not None and tr.net_pnl is not None:
            cfs.append(
                {
                    "session_date": d,
                    "prediction_ts": r["prediction_ts"],
                    "cell": r["cell"],
                    **_trade_row(tr),
                }
            )
    return {"rows": rows, "trades": trades, "counterfactual": cfs}


def _quant(v: pl.Series) -> str:
    q = v.drop_nulls()
    if q.is_empty():
        return "—"
    qs = np.quantile(q.to_numpy(), [0.05, 0.5, 0.95])
    return f"{qs[0]:+.3f} / {qs[1]:+.3f} / {qs[2]:+.3f} (max {float(q.to_numpy().max()):+.3f})"


def write_report(
    dec: pl.DataFrame,
    trades: pl.DataFrame,
    cf: pl.DataFrame,
    g: dict[str, Any],
    meta: dict[str, Any],
) -> None:
    n = dec.height
    lines = [
        "# M15 decision engine and NO_TRADE analysis (spec §4.1)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {meta['commit'][:12]}, run "
        f"`{meta['run_id']}`. Test blocks {meta['first']} → {meta['last']} "
        f"({meta['n_sessions']} sessions, {n:,} prediction timestamps); final holdout not opened.",
        "",
        f"**Rule.** Model family `{CFG.decision.model_family}` with its M13 calibrators "
        "(test-block "
        "probabilities from features only). Per side: calibrated P(WIN) - p_breakeven > "
        f"{CFG.decision.edge_margin} and EV > 0 at the moderate entry fill (alpha = "
        f"{CFG.fills.moderate_alpha}), binary-conservative EV (every non-WIN outcome = full "
        "-20% stop), §4.9 gates at T_e. Both sides qualifying: higher EV. Blocked regime cells: "
        f"{CFG.decision.blocked_regime_cells or 'none'}.",
        "",
        "## Decisions",
        "",
        "| final decision | timestamps | share |",
        "|---|---|---|",
        *[
            f"| {r['final']} | {r['len']:,} | {r['len'] / n:.2%} |"
            for r in dec.group_by("final").len().sort("len", descending=True).to_dicts()
        ],
        "",
        "## Rule decision vs engine outcome",
        "",
        "CALL / PUT decisions pass through the event engine (one open position, at most "
        f"{CFG.trade.max_entries_per_day} entries per session); NO_TRADE there is "
        "MAX_ENTRIES_PER_DAY.",
        "",
        "| rule decision | engine outcome | timestamps |",
        "|---|---|---|",
        *[
            f"| {r['decision']} | {r['final']} | {r['len']:,} |"
            for r in dec.group_by("decision", "final").len().sort("decision", "final").to_dicts()
        ],
        "",
        "## NO_TRADE by reason (per side; rule-level NO_TRADE only)",
        "",
        "| reason | timestamps |",
        "|---|---|",
        *[
            f"| {r['reasons']} | {r['len']:,} |"
            for r in dec.filter(pl.col("decision") == "NO_TRADE")
            .explode("reasons", empty_as_null=True)
            .group_by("reasons")
            .len()
            .sort("len", descending=True)
            .to_dicts()
        ],
        "",
        "## NO_TRADE rate by regime cell (R1)",
        "",
        "| cell | timestamps | NO_TRADE | rate |",
        "|---|---|---|---|",
        *[
            f"| {r['cell']} | {r['n']:,} | {r['nt']:,} | {r['nt'] / r['n']:.2%} |"
            for r in dec.group_by("cell")
            .agg(n=pl.len(), nt=(pl.col("decision") == "NO_TRADE").sum())
            .sort("cell")
            .to_dicts()
        ],
        "",
        "## Distance from the decision threshold",
        "",
        "margin = calibrated P(WIN) - p_breakeven; a side needs margin > "
        f"{CFG.decision.edge_margin}. Quantiles 5% / 50% / 95% over timestamps where the side's "
        "selection passed.",
        "",
        "| side | calibrated P(WIN) 5/50/95% | p_breakeven 5/50/95% | margin 5/50/95% "
        "| timestamps with margin > 0 | > edge margin |",
        "|---|---|---|---|---|---|",
    ]
    for key, name in (("call", "CALL"), ("put", "PUT")):
        m = dec[f"margin_{key}"]
        pbe = (dec[f"p_{key}"] - m).alias("pbe")
        lines.append(
            f"| {name} | {_quant(dec[f'p_{key}'])} | {_quant(pbe)} | {_quant(m)} "
            f"| {int((m.drop_nulls() > 0).sum()):,} "
            f"| {int((m.drop_nulls() > CFG.decision.edge_margin).sum()):,} |"
        )
    cfs = (
        summarize_net(net_from_frame(cf), cf["session_date"].to_list(), CFG) if cf.height else None
    )
    lines += [
        "",
        "## Gate 13 (regime behaviour) and gate 14 (NO_TRADE validated)",
        "",
        f"- Traded timestamps (entered trades with a P&L): **{trades.height:,}**.",
        f"- Gate 13: {g['gate13']}",
        f"- Gate 14: {g['gate14']}",
    ]
    if cfs is not None:
        lines.append(
            f"- Counterfactual at NO_TRADE timestamps (higher-EV side simulated anyway, one "
            f"independent trade each, moderate fill, net of costs): {cfs.n:,} trades, mean net "
            f"${cfs.mean:+.2f} [{cfs.ci[0]:+.2f}, {cfs.ci[1]:+.2f}], median ${cfs.median:+.2f}."
        )
    lines += [
        "",
        "Not a claim of profitability (rule 12): these are research decisions on pre-holdout "
        "test blocks.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def gates(trades: pl.DataFrame, cf: pl.DataFrame) -> dict[str, Any]:
    if trades.height == 0:
        return {
            "gate13": "not evaluable: no traded regime cell (0 trades).",
            "gate14": "**not evaluable: 0 traded timestamps** (rule 11; nothing to compare the "
            "NO_TRADE counterfactual with).",
        }
    tn, cn = net_from_frame(trades), net_from_frame(cf)
    v = np.array([float(x) for x in tn] + [float(x) for x in cn])
    is_t = np.array([True] * len(tn) + [False] * len(cn))
    sid = np.array(trades["session_date"].to_list() + cf["session_date"].to_list())

    def diff(w: np.ndarray) -> float:
        a, b = w * is_t, w * ~is_t
        if a.sum() == 0 or b.sum() == 0:
            return float("nan")
        return float(np.average(v, weights=a) - np.average(v, weights=b))

    m = CFG.models.metrics
    lo, hi = session_bootstrap_ci(
        sid, diff, CFG.validation.bootstrap_reps, m.bootstrap_seed, m.ci_level
    )
    d0 = diff(np.ones(v.size))
    ok = lo > 0
    return {
        "gate13": "cells with >= 100 trades are listed in the run metrics (none expected).",
        "gate14": f"traded - NO_TRADE counterfactual mean net {d0:+.2f} [{lo:+.2f}, {hi:+.2f}]: "
        + ("would PASS" if ok else "would FAIL"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()
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
    test = sorted({d for f in folds for d in f.test})
    commit = code_commit(ROOT)
    run_id = register_run(
        engine,
        run_kind="decision",
        config={
            "model": "decision_engine",
            "decision": CFG.decision.model_dump(mode="json"),
            "fills": CFG.fills.model_dump(mode="json"),
            "trade": CFG.trade.model_dump(mode="json"),
            "costs": CFG.costs.model_dump(mode="json"),
            "calibration_run": CFG.regimes.calibration_runs[CFG.decision.model_family],
            "model_run": CFG.calibration.reference_runs[CFG.decision.model_family],
            "regime_version": CFG.regimes.version,
        },
        data_window=(test[0], test[-1]),
        dataset_id=dataset_id(engine, f"data/features/{CFG.features.version}"),
        code_commit=commit,
        folds=[],
    )
    print(f"registered run {run_id}")
    try:
        probs = probabilities(engine, folds).join(
            regime_cells(engine), on="prediction_ts", how="left"
        )
        by_session = {d: g.to_dicts() for (d,), g in probs.group_by("session_date")}
        parts: dict[str, list[dict[str, Any]]] = {"rows": [], "trades": [], "counterfactual": []}
        jobs = ((d, t, by_session.get(d, [])) for d, t in session_inputs(ROOT, test, cal, CFG))
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for i, res in enumerate(pool.map(session_job, jobs, chunksize=2), 1):
                for k in parts:
                    parts[k] += res[k]
                if i % 50 == 0:
                    print(f"sessions {i}/{len(test)}", flush=True)
        dec = pl.DataFrame(parts["rows"], infer_schema_length=None)
        trades = (
            pl.DataFrame(
                parts["trades"], schema_overrides={"prediction_ts": DT}, infer_schema_length=None
            )
            if parts["trades"]
            else pl.DataFrame(
                schema={
                    "session_date": pl.Date,
                    "prediction_ts": DT,
                    **{c: pl.Float64 for c in TRADE_COLS},
                }
            )
        )
        cf = pl.DataFrame(parts["counterfactual"], infer_schema_length=None)
        odir = ROOT / "data" / "decisions" / run_id
        odir.mkdir(parents=True, exist_ok=True)
        dec.write_parquet(odir / "decisions.parquet")
        trades.write_parquet(odir / "trades.parquet")
        cf.write_parquet(odir / "counterfactual.parquet")
        g = gates(trades, cf)
        metrics = {
            "final": dec.group_by("final").len().to_dicts(),
            "reasons": dec.filter(pl.col("decision") == "NO_TRADE")
            .explode("reasons", empty_as_null=True)
            .group_by("reasons")
            .len()
            .to_dicts(),
            "traded": trades.height,
            "counterfactual": cf.height,
            **g,
        }
    except Exception as e:
        fail_run(engine, run_id, repr(e))
        raise
    complete_run(engine, run_id, metrics)
    write_report(
        dec,
        trades,
        cf,
        g,
        {
            "commit": commit,
            "run_id": run_id,
            "first": test[0],
            "last": test[-1],
            "n_sessions": len(test),
        },
    )
    engine.dispose()
    print(f"completed run {run_id}; report {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
