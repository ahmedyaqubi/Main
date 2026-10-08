"""Journal: `write_prediction` (prediction + per-target scores + candidates in one transaction) and
`replay` (T-REP-02: stored scores reproduced to 1e-9, decision re-derived). Synthetic model,
calibrator, feature snapshots and market data. PostgreSQL; skipped without TEST_DATABASE_URL."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
from sqlalchemy import Engine, text

from qqq1dte.backtesting.registry import ModelVersion, record_model_version, register_run
from qqq1dte.calibration.methods import Calibrator
from qqq1dte.calibration.methods import save as save_calibrator
from qqq1dte.calibration.store import CalibrationRecord, record_calibration
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import config_hash, load_config
from qqq1dte.execution_sim.decision import CalibratedProbability, SideInput, decide
from qqq1dte.execution_sim.engine import Candidate, selection_detail_at
from qqq1dte.execution_sim.fills import Moderate
from qqq1dte.execution_sim.selection import NoTrade
from qqq1dte.features.engine import FEATURE_NAMES
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.journal.pipeline import decision_run_config
from qqq1dte.journal.replay import replay
from qqq1dte.journal.writer import PredictionRecord, ScoreRecord, write_prediction
from qqq1dte.models.design import fit_design, wide_features
from qqq1dte.models.logistic import LogisticModel
from qqq1dte.models.logistic import save as save_model
from test_backtest_engine import CALL, PUT, D, chain, et, records, und

CFG = load_config()
CAL = TradingCalendar(CFG)
CALIB = [date(2025, 3, 6), date(2025, 3, 7)]
T = et(11, 0)
LAT = timedelta(seconds=CFG.fills.latency_s)


def _snapshot(root: Path, d: date, seed: int) -> None:
    rng = np.random.default_rng(seed)
    rows = []
    for ts in CAL.prediction_timestamps(d)[:30]:
        for name in FEATURE_NAMES:
            v = float(rng.integers(0, 5)) if name == "day_of_week" else float(rng.normal())
            rows.append((d, ts, name, v, None, ts - timedelta(minutes=1), "f2"))
    df = pl.DataFrame(
        rows,
        orient="row",
        schema={
            "session_date": pl.Date,
            "prediction_ts": pl.Datetime("ns", "UTC"),
            "feature_name": pl.String,
            "value": pl.Float64,
            "missing_reason": pl.String,
            "available_at": pl.Datetime("ns", "UTC"),
            "feature_version": pl.String,
        },
    )
    path = root / "data" / "features" / "f2" / f"session={d}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def _wide(root: Path, d: date) -> pl.DataFrame:
    return wide_features(
        pl.read_parquet(root / "data" / "features" / "f2" / f"session={d}.parquet"), FEATURE_NAMES
    )


@pytest.fixture
def env(migrated_engine: Engine, tmp_path: Path) -> dict[str, Any]:
    e = migrated_engine
    for i, d in enumerate([*CALIB, D]):
        _snapshot(tmp_path, d, i)
    record_dataset(
        e,
        DatasetVersion(
            "feat",
            "features",
            "q",
            date(2025, 1, 1),
            date(2025, 12, 31),
            1,
            "data/features/f2",
            "c",
            "h",
        ),
    )
    calib_wide = pl.concat([_wide(tmp_path, d) for d in CALIB])
    design = fit_design(calib_wide, 5.0)
    rng = np.random.default_rng(42)
    model = LogisticModel(
        design, tuple(float(v) for v in rng.normal(0, 0.3, len(design.out_columns))), -0.4, 1.0
    )
    msha = save_model(model, tmp_path / "models" / "m.json")
    cal = Calibrator("platt", {"a": 0.9, "b": 0.1}, CFG.calibration.prob_clip)
    csha = save_calibrator(cal, tmp_path / "cal" / "c.json")
    out: dict[str, Any] = {"engine": e, "root": tmp_path, "model": model, "cal": cal}
    for tgt in ("C_call", "C_put"):
        record_model_version(
            e,
            ModelVersion(
                f"mv-{tgt}",
                "logistic_l2",
                tgt,
                date(2024, 1, 1),
                date(2025, 3, 5),
                "feat",
                "f2",
                "L2",
                {},
                "models/m.json",
                msha,
                "c",
                "h",
            ),
        )
        record_calibration(
            e,
            CalibrationRecord(
                f"cal-{tgt}",
                f"mv-{tgt}",
                "platt",
                CALIB[0],
                CALIB[-1],
                D,
                D,
                60,
                64,
                0.2,
                0.6,
                0.01,
                1.0,
                0.0,
                [],
                "cal/c.json",
                csha,
            ),
        )
    out["run"] = register_run(
        e,
        run_kind="decision",
        config=decision_run_config(CFG),
        data_window=(D, D),
        dataset_id="feat",
        code_commit="c",
        folds=[],
    )
    out["calib_raw"] = np.sort(model.score(calib_wide))
    return out


def _recs() -> pl.DataFrame:
    return pl.concat([records(), records(symbol=PUT)]).sort("symbol", "available_at")


def _market(_: date) -> dict[str, pl.DataFrame]:
    return {"und": und(), "chain": chain(), "records": _recs()}


def _journal(env: dict[str, Any], tamper: float = 0.0) -> uuid.UUID:
    """Compute a decision exactly like the pipeline and journal it."""
    root, model, cal = env["root"], env["model"], env["cal"]
    row = _wide(root, D).filter(pl.col("prediction_ts") == T)
    raw = float(model.score(row)[0])
    p = float(cal.apply([raw])[0])
    support = int(env["calib_raw"].size - np.searchsorted(env["calib_raw"], raw, side="left"))
    fill = Moderate(CFG, CFG.fills.moderate_alpha)
    sides, cands, scores = [], [], []
    for s, tgt in (("C", "C_call"), ("P", "C_put")):
        sel, chosen, quote = selection_detail_at(D, s, T + LAT, und(), chain(), _recs(), CAL, CFG)
        cp = CalibratedProbability(p, f"cal-{tgt}")
        si = (
            SideInput(s, cp, sel.reason, None, support)
            if isinstance(sel, NoTrade)
            else SideInput(s, cp, None, fill.buy(sel.quote), support)
        )
        sides.append(si)
        if chosen is not None:
            cands.append(
                (
                    Candidate(
                        T,
                        s,
                        chosen.symbol,
                        chosen.strike,
                        chosen.expiration,
                        quote.available_at,
                        quote.bid,
                        quote.ask,
                        quote.bid_sz,
                        quote.ask_sz,
                        CFG.fills.latency_s,
                        True,
                        (),
                        True,
                    ),
                    [],
                )
            )
    out = decide(sides[0], sides[1], CFG, regime_cell="LOW/TREND/NORMAL")
    for si, tgt, ev, m in (
        (sides[0], "C_call", out.ev_call, out.margin_call),
        (sides[1], "C_put", out.ev_put, out.margin_put),
    ):
        scores.append(
            ScoreRecord(
                tgt,
                f"mv-{tgt}",
                f"cal-{tgt}",
                raw + tamper,
                p,
                support,
                si.entry_price,
                None if m is None else float(si.p) - m,
                m,
                ev,
                si.selection_reason,
            )
        )
    rec = PredictionRecord(
        prediction_id=uuid.uuid4(),
        run_id=env["run"],
        prediction_ts=T,
        mode="BACKTEST",
        underlying_price=500.40,
        chain_snapshot_ref=f"market:{D}",
        feature_snapshot_ref=f"data/features/f2/session={D}.parquet#ts={T.isoformat()}",
        feature_version="f2",
        max_feature_available_at=T - timedelta(minutes=1),
        regime={
            "volatility": "LOW",
            "trend": "TREND",
            "event": "NORMAL",
            "cell": "LOW/TREND/NORMAL",
            "version": "R1",
        },
        model_version_id="mv-C_call",
        calibration_version_id="cal-C_call",
        raw_scores={"C_call": raw + tamper, "C_put": raw + tamper},
        calibrated_probs={"C_call": p, "C_put": p},
        support_n={"C_call": support, "C_put": support},
        decision=out.decision,
        decision_reasons=list(out.reasons),
        expected_value={"C_call": out.ev_call, "C_put": out.ev_put},
        config_hash=config_hash(decision_run_config(CFG)),
        code_commit="c",
    )
    write_prediction(env["engine"], rec, scores, cands)
    return rec.prediction_id


def test_write_prediction_round_trip(env: dict[str, Any]) -> None:
    pid = _journal(env)
    with env["engine"].connect() as c:
        n_s = c.execute(
            text("SELECT count(*) FROM prediction_scores WHERE prediction_id = :p"), {"p": pid}
        ).scalar_one()
        cands = c.execute(
            text(
                "SELECT side, occ_symbol, selected FROM trade_candidates "
                "WHERE prediction_id = :p ORDER BY side"
            ),
            {"p": pid},
        ).all()
    assert n_s == 2
    assert cands[0][0] == "CALL" and cands[0][1] == CALL and cands[0][2]


def test_rep_02_replay_reproduces_scores_and_decision(env: dict[str, Any]) -> None:
    pid = _journal(env)
    r = replay(env["engine"], env["root"], CFG, pid, _market)
    assert r.ok, r.diffs
    assert r.checked >= 10  # scores, probabilities, support, EV, entries, decision


def test_rep_02_replay_detects_a_tampered_score(env: dict[str, Any]) -> None:
    pid = _journal(env, tamper=1e-6)
    r = replay(env["engine"], env["root"], CFG, pid, _market)
    assert not r.ok and any("raw_score" in d for d in r.diffs)
