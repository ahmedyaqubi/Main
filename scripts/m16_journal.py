"""M16: journal every test-block prediction of the current decision configuration (spec
Phase 1O) and replay a seeded sample (T-REP-02).

Per test-block prediction timestamp (pre-holdout, M10 folds): the M15 decision pipeline
(`journal.pipeline`, ADR-0010 rule) -> `predictions` (BACKTEST), `prediction_scores` (C_call,
C_put), `trade_candidates` (the chosen contract per side) and `simulated_trades` (entered
trades), one transaction per prediction. Then `journal.replay` re-derives a seeded sample from
the stored references. One `validation_runs` row (run_kind "journal") with the decision
configuration (same config hash as the M15 decision run).

    uv run python scripts/m16_journal.py [--workers 7]
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import uuid
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import code_commit, dataset_id
from qqq1dte.backtesting.registry import complete_run, fail_run, register_run
from qqq1dte.backtesting.session_data import session_inputs
from qqq1dte.backtesting.splits import walk_forward_folds
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import config_hash, load_config
from qqq1dte.journal.pipeline import (
    TsDecision,
    decide_session,
    decision_run_config,
    max_feature_available_at,
    probabilities,
    regime_frame,
)
from qqq1dte.journal.replay import replay
from qqq1dte.journal.writer import PredictionRecord, ScoreRecord, write_prediction

ROOT = Path(__file__).resolve().parents[1]
END = date(2026, 10, 2)
REPORT = ROOT / "reports" / "journal" / "m16_journal.md"
CFG = load_config()
TARGETS = (("C_call", "call", 0), ("C_put", "put", 1))
# spec Phase 1O minimum fields -> where they are journaled
COVERAGE = [
    ("prediction_id", "predictions.prediction_id"),
    ("timestamp", "predictions.prediction_ts"),
    ("underlying price", "predictions.underlying_price"),
    ("option chain snapshot/reference", "predictions.chain_snapshot_ref"),
    ("feature values", "predictions.feature_snapshot_ref (immutable f2 snapshot row)"),
    ("feature version", "predictions.feature_version"),
    ("regime", "predictions.regime (R1 axes + cell)"),
    ("model version", "prediction_scores.model_version_id (per target)"),
    ("raw probability", "prediction_scores.raw_score (uncalibrated score)"),
    ("calibrated probability", "prediction_scores.calibrated_prob"),
    ("calibration version", "prediction_scores.calibration_version_id"),
    ("candidate contracts", "trade_candidates (chosen contract per side, gates)"),
    ("selected contract", "trade_candidates.selected / occ_symbol"),
    ("bid/ask", "trade_candidates.bid / ask"),
    ("assumed entry", "prediction_scores.entry_price; simulated_trades.entry_price"),
    ("target", "simulated_trades.target_price (entered trades)"),
    ("stop", "simulated_trades.stop_price (entered trades)"),
    ("expected value", "prediction_scores.expected_value; predictions.expected_value"),
    ("actual MFE", "simulated_trades.mfe"),
    ("actual MAE", "simulated_trades.mae"),
    ("outcome", "simulated_trades.outcome"),
    ("P&L", "simulated_trades.gross_pnl / net_pnl"),
    ("costs", "simulated_trades.commissions / fees / spread_cost"),
    ("reason for decision", "predictions.decision_reasons; prediction_scores.side_reason"),
    ("CALL/PUT/NO TRADE", "predictions.decision"),
]


def _records(
    x: TsDecision, d: date, maxfa: dict[datetime, datetime], meta: dict[str, Any]
) -> tuple[PredictionRecord, list[ScoreRecord], list[tuple[Any, list[Any]]]]:
    pr, out = x.prob, x.outcome
    ts = pr["prediction_ts"]
    if x.underlying_price is None:
        raise RuntimeError(f"no QQQ quote at or before {ts}: cannot journal the underlying price")
    evs = {"C_call": out.ev_call, "C_put": out.ev_put}
    margins = {"C_call": out.margin_call, "C_put": out.margin_put}
    scores = []
    for tgt, key, i in TARGETS:
        si = x.sides[i].side_input
        m = margins[tgt]
        scores.append(
            ScoreRecord(
                tgt,
                pr[f"mid_{key}"],
                pr[f"ver_{key}"],
                float(pr[f"raw_{key}"]),
                float(pr[f"p_{key}"]),
                int(pr[f"support_{key}"]),
                si.entry_price,
                None if m is None else float(pr[f"p_{key}"]) - m,
                m,
                evs[tgt],
                si.selection_reason,
            )
        )
    reasons = list(out.reasons)
    if x.final == "NO_TRADE" and out.decision in ("CALL", "PUT"):
        reasons = ["MAX_ENTRIES_PER_DAY"]
    lat = timedelta(seconds=CFG.fills.latency_s)
    rec = PredictionRecord(
        prediction_id=uuid.uuid4(),
        run_id=meta["run_id"],
        prediction_ts=ts,
        mode="BACKTEST",
        underlying_price=x.underlying_price,
        chain_snapshot_ref=(
            f"data/clean/cleaned/cleaned_options_data/cbbo-1m/{d}.parquet"
            f"#asof={(ts + lat).isoformat()}"
        ),
        feature_snapshot_ref=f"data/features/{CFG.features.version}/session={d}.parquet"
        f"#ts={ts.isoformat()}",
        feature_version=CFG.features.version,
        max_feature_available_at=maxfa[ts],
        regime={
            "volatility": pr["volatility"],
            "trend": pr["trend"],
            "event": pr["event"],
            "cell": pr["cell"],
            "version": CFG.regimes.version,
        },
        model_version_id=pr["mid_call"],
        calibration_version_id=pr["ver_call"],
        raw_scores={t: s.raw_score for t, s in zip(("C_call", "C_put"), scores, strict=True)},
        calibrated_probs={t: float(pr[f"p_{k}"]) for t, k, _ in TARGETS},
        support_n={t: int(pr[f"support_{k}"]) for t, k, _ in TARGETS},
        decision=x.final,
        decision_reasons=reasons,
        expected_value=evs,
        config_hash=meta["config_hash"],
        code_commit=meta["commit"],
    )
    traded = {tr.side: [tr] for tr in x.trades}
    cands = [
        (sd.candidate, traded.get(sd.candidate.side, []))
        for sd in x.sides
        if sd.candidate is not None
    ]
    return rec, scores, cands


def session_job(
    args: tuple[date, dict[str, pl.DataFrame], list[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    d, t, probs, meta = args
    cfg = load_config()
    engine = create_engine(meta["url"])
    decisions, _ = decide_session(d, t, probs, cfg)
    mf = max_feature_available_at(ROOT, cfg, d)
    maxfa = {r["prediction_ts"]: r["max_feature_available_at"] for r in mf.to_dicts()}
    finals: dict[str, int] = {}
    stale = 0
    for x in decisions:
        rec, scores, cands = _records(x, d, maxfa, meta)
        write_prediction(engine, rec, scores, cands)
        finals[x.final] = finals.get(x.final, 0) + 1
        if (
            x.underlying_quote_ts
            and (x.prob["prediction_ts"] - x.underlying_quote_ts).total_seconds()
            > cfg.liquidity.max_quote_age_s
        ):
            stale += 1
    engine.dispose()
    return {"n": len(decisions), "finals": finals, "stale_underlying": stale}


def main() -> int:  # noqa: PLR0915 (linear pipeline)
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
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
    test = sorted({d for f in folds for d in f.test})
    commit = code_commit(ROOT)
    run_cfg = decision_run_config(CFG)
    run_id = register_run(
        engine,
        run_kind="journal",
        config=run_cfg,
        data_window=(test[0], test[-1]),
        dataset_id=dataset_id(engine, f"data/features/{CFG.features.version}"),
        code_commit=commit,
        folds=[],
    )
    print(f"registered run {run_id}")
    meta = {"run_id": run_id, "config_hash": config_hash(run_cfg), "commit": commit, "url": url}
    try:
        probs = probabilities(engine, ROOT, CFG, folds).join(
            regime_frame(engine, CFG), on="prediction_ts", how="left"
        )
        if probs["cell"].null_count():
            raise RuntimeError("prediction timestamps without an R1 regime label")
        by_session = {d: g.to_dicts() for (d,), g in probs.group_by("session_date")}
        total, stale = 0, 0
        finals: dict[str, int] = {}
        jobs = (
            (d, t, by_session.get(d, []), meta) for d, t in session_inputs(ROOT, test, cal, CFG)
        )
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for i, r in enumerate(pool.map(session_job, jobs, chunksize=2), 1):
                total += r["n"]
                stale += r["stale_underlying"]
                for k, v in r["finals"].items():
                    finals[k] = finals.get(k, 0) + v
                if i % 50 == 0:
                    print(f"journaled sessions {i}/{len(test)}", flush=True)
        with engine.connect() as c:
            counts = {
                tbl: c.execute(text(q), {"r": run_id}).scalar_one()
                for tbl, q in {
                    "predictions": "SELECT count(*) FROM predictions WHERE run_id = :r",
                    "prediction_scores": "SELECT count(*) FROM prediction_scores s JOIN "
                    "predictions p USING (prediction_id) WHERE p.run_id = :r",
                    "trade_candidates": "SELECT count(*) FROM trade_candidates t JOIN "
                    "predictions p USING (prediction_id) WHERE p.run_id = :r",
                    "simulated_trades": "SELECT count(*) FROM simulated_trades s JOIN "
                    "trade_candidates t USING (candidate_id) JOIN predictions p "
                    "USING (prediction_id) WHERE p.run_id = :r",
                }.items()
            }
            ids = [
                r[0]
                for r in c.execute(
                    text(
                        "SELECT prediction_id FROM predictions WHERE "
                        "run_id = :r ORDER BY prediction_id"
                    ),
                    {"r": run_id},
                ).all()
            ]
        sample = random.Random(CFG.journal.replay_seed).sample(
            ids, min(CFG.journal.replay_sample, len(ids))
        )
        with engine.connect() as c:
            sample_sessions = sorted(
                {
                    r[0]
                    for r in c.execute(
                        text(
                            "SELECT DISTINCT (prediction_ts AT TIME ZONE 'America/New_York')::date "
                            "FROM predictions WHERE prediction_id = ANY(:ids)"
                        ),
                        {"ids": sample},
                    ).all()
                }
            )
        markets = dict(session_inputs(ROOT, sample_sessions, cal, CFG))
        results = [replay(engine, ROOT, CFG, pid, lambda d: markets[d]) for pid in sample]
        bad = [r for r in results if not r.ok]
        failures = [{"id": str(r.prediction_id), "diffs": r.diffs[:5]} for r in bad[:10]]
        metrics = {
            "counts": counts,
            "finals": finals,
            "stale_underlying": stale,
            "replayed": len(results),
            "replay_failures": len(bad),
            "replay_checks": sum(r.checked for r in results),
            "failure_examples": failures,
        }
    except Exception as e:
        fail_run(engine, run_id, repr(e))
        raise
    complete_run(engine, run_id, metrics)
    lines = [
        "# M16 prediction / trade journal (spec Phase 1O)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {commit[:12]}, run `{run_id}` "
        f"(decision configuration hash {meta['config_hash'][:12]}, same as the M15 decision run). "
        f"Test blocks {test[0]} → {test[-1]}, {len(test)} sessions; final holdout not opened.",
        "",
        "## Rows journaled",
        "",
        "| table | rows |",
        "|---|---|",
        *[f"| {k} | {v:,} |" for k, v in counts.items()],
        "",
        "| decision | predictions |",
        "|---|---|",
        *[f"| {k} | {v:,} |" for k, v in sorted(finals.items())],
        "",
        f"Underlying price older than {CFG.liquidity.max_quote_age_s} s at T: {stale:,} "
        "predictions (the quote time is used as is and is reproducible from the cleaned NBBO).",
        "",
        "## Replay (T-REP-02)",
        "",
        f"Seeded sample of {len(results)} predictions (seed {CFG.journal.replay_seed}); each "
        "re-derives raw scores and calibrated probabilities (|diff| ≤ 1e-9), ADR-0010 support, "
        "entry fills, EV and margins (≤ 1e-6), the rule decision and its reasons from the stored "
        "references only (config hash, feature snapshot, model / calibrator artifacts by sha256, "
        "cleaned market data).",
        "",
        f"- Checks run: {metrics['replay_checks']:,}",
        f"- Predictions reproduced: **{len(results) - len(bad)} / {len(results)}**",
        *[f"- mismatch {f['id']}: {'; '.join(f['diffs'])}" for f in failures],
        "",
        "## Phase 1O field coverage",
        "",
        "| Phase 1O field | journaled as |",
        "|---|---|",
        *[f"| {a} | {b} |" for a, b in COVERAGE],
        "",
        "Journal tables are append-only (triggers) and the `qqq1dte_journal_writer` role holds "
        "INSERT / SELECT only (migration 0002; `tests/test_journal_schema.py`).",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    engine.dispose()
    print(f"completed run {run_id}; replayed {len(results)}, failures {len(bad)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
