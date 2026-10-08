"""Replay a journaled prediction (T-REP-02; M16). Everything is rebuilt from the stored
references, never from the stored results:

- configuration: the stored config_hash must equal the hash of the current decision config;
- features: the referenced snapshot row; `max_feature_available_at` recomputed;
- per target: model and calibrator artifacts reloaded by version (sha256-checked); raw score
  and calibrated probability recomputed (|diff| <= tol); ADR-0010 support recomputed by
  re-scoring the calibration block named in `calibration_results`;
- decision: selection at T_e from the market data for the session, entry fill, `decide` with
  the stored regime cell; rule decision, reasons, EV and entry compared. A stored
  BLOCKED_POSITION_OPEN must come from a CALL / PUT rule decision.

Returns the list of differences (empty = reproduced)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from sqlalchemy import Engine, text

from qqq1dte.calibration.methods import Calibrator
from qqq1dte.calibration.methods import load as load_calibrator
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config, config_hash
from qqq1dte.core.timeutil import ET
from qqq1dte.execution_sim.decision import CalibratedProbability, SideInput, decide
from qqq1dte.execution_sim.engine import selection_detail_at
from qqq1dte.execution_sim.fills import Moderate
from qqq1dte.execution_sim.selection import NoTrade
from qqq1dte.features.engine import FEATURE_NAMES
from qqq1dte.journal.pipeline import decision_run_config
from qqq1dte.models import gbm, logistic
from qqq1dte.models.design import KEYS, wide_features

Market = Callable[[date], dict[str, pl.DataFrame]]
TARGET_SIDE = {"C_call": "C", "C_put": "P"}
MAX_ENTRIES = "MAX_ENTRIES_PER_DAY"


@dataclass
class ReplayResult:
    prediction_id: uuid.UUID
    diffs: list[str] = field(default_factory=list)
    checked: int = 0

    @property
    def ok(self) -> bool:
        return not self.diffs


def _scorer(engine: Engine, root: Path, mid: str) -> Callable[[pl.DataFrame], np.ndarray]:
    with engine.connect() as c:
        fam, uri, sha = c.execute(
            text(
                "SELECT model_family, artifact_uri, artifact_sha256 FROM model_versions "
                "WHERE model_version_id = :m"
            ),
            {"m": mid},
        ).one()
    if fam == "logistic_l2":
        m, _ = logistic.load(root / uri, expected_sha256=sha)
        return m.score
    b, _ = gbm.load(root / uri, expected_sha256=sha)

    def score(df: pl.DataFrame) -> np.ndarray:
        feats = [c for c in df.columns if c not in (*KEYS, "y")]
        return np.asarray(b.predict(df.select(feats).to_numpy().astype(np.float64)))

    return score


def _calibrator(engine: Engine, root: Path, cid: str) -> tuple[Calibrator, date, date]:
    with engine.connect() as c:
        uri, cs, ce = c.execute(
            text(
                "SELECT artifact_uri, calib_start, calib_end FROM calibration_results "
                "WHERE calibration_version_id = :c"
            ),
            {"c": cid},
        ).one()
    path, _, sha = uri.partition("#sha256=")
    cal, _ = load_calibrator(root / path, expected_sha256=sha or None)
    return cal, cs, ce


def _snapshot(root: Path, ref: str) -> tuple[pl.DataFrame, datetime]:
    path, _, ts = ref.partition("#ts=")
    t = datetime.fromisoformat(ts)
    return pl.read_parquet(root / path), t


def _close(a: float | None, b: float | None, tol: float) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol


def replay(
    engine: Engine,
    root: Path,
    cfg: Phase1Config,
    prediction_id: uuid.UUID,
    market: Market,
    tol: float = 1e-9,
) -> ReplayResult:
    res = ReplayResult(prediction_id)

    def check(ok: bool, msg: str) -> None:
        res.checked += 1
        if not ok:
            res.diffs.append(msg)

    with engine.connect() as c:
        p = (
            c.execute(
                text("SELECT * FROM predictions WHERE prediction_id = :p"), {"p": prediction_id}
            )
            .mappings()
            .one()
        )
        scores = (
            c.execute(
                text("SELECT * FROM prediction_scores WHERE prediction_id = :p ORDER BY target"),
                {"p": prediction_id},
            )
            .mappings()
            .all()
        )
    check(p["config_hash"] == config_hash(decision_run_config(cfg)), "config_hash differs")
    snap, t = _snapshot(root, p["feature_snapshot_ref"])
    check(t == p["prediction_ts"], "feature_snapshot_ref timestamp differs from prediction_ts")
    at_t = snap.filter(pl.col("prediction_ts") == t)
    check(
        at_t["available_at"].max() == p["max_feature_available_at"],
        "max_feature_available_at differs",
    )
    row = wide_features(at_t, FEATURE_NAMES)
    d = t.astimezone(ET).date()
    cal_obj = TradingCalendar(cfg)
    m = market(d)
    fill = Moderate(cfg, cfg.fills.moderate_alpha)
    lat = timedelta(seconds=cfg.fills.latency_s)
    sides: dict[str, SideInput] = {}
    stored: dict[str, Any] = {}
    for s in scores:
        tgt, side = s["target"], TARGET_SIDE[s["target"]]
        stored[side] = s
        score = _scorer(engine, root, s["model_version_id"])
        raw = float(score(row)[0])
        check(_close(raw, s["raw_score"], tol), f"{tgt} raw_score {s['raw_score']} != {raw}")
        cal, cs, ce = _calibrator(engine, root, s["calibration_version_id"])
        prob = float(cal.apply([raw])[0])
        check(
            _close(prob, s["calibrated_prob"], tol),
            f"{tgt} calibrated_prob {s['calibrated_prob']} != {prob}",
        )
        calib = pl.concat(
            [
                wide_features(
                    pl.read_parquet(
                        root / "data" / "features" / cfg.features.version / f"session={x}.parquet"
                    ),
                    FEATURE_NAMES,
                )
                for x in cal_obj.research_sessions(cs, ce)
            ]
        )
        calib_raw = np.sort(score(calib))
        support = int(calib_raw.size - np.searchsorted(calib_raw, raw, side="left"))
        check(support == s["support_n"], f"{tgt} support_n {s['support_n']} != {support}")
        sel, _, _ = selection_detail_at(
            d, side, t + lat, m["und"], m["chain"], m["records"], cal_obj, cfg
        )
        cp = CalibratedProbability(prob, s["calibration_version_id"])
        if isinstance(sel, NoTrade):
            sides[side] = SideInput(side, cp, sel.reason, None, support)
        else:
            sides[side] = SideInput(side, cp, None, fill.buy(sel.quote), support)
        check(_close(sides[side].entry_price, s["entry_price"], tol), f"{tgt} entry_price differs")
    out = decide(sides["C"], sides["P"], cfg, regime_cell=p["regime"].get("cell"))
    for side, ev, margin in (
        ("C", out.ev_call, out.margin_call),
        ("P", out.ev_put, out.margin_put),
    ):
        s = stored[side]
        check(_close(ev, s["expected_value"], 1e-6), f"{s['target']} expected_value differs")
        check(_close(margin, s["margin"], 1e-6), f"{s['target']} margin differs")
    engine_refused = p["decision"] == "BLOCKED_POSITION_OPEN" or (
        p["decision"] == "NO_TRADE" and list(p["decision_reasons"]) == [MAX_ENTRIES]
    )
    if engine_refused:  # the rule said CALL / PUT; the position engine refused it
        check(
            out.decision in ("CALL", "PUT"), f"engine-refused prediction replays as {out.decision}"
        )
    else:
        check(out.decision == p["decision"], f"decision {p['decision']} != {out.decision}")
        check(
            list(out.reasons) == list(p["decision_reasons"]),
            f"reasons {p['decision_reasons']} != {list(out.reasons)}",
        )
    return res
