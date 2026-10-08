"""Append-only journal writer (spec Phase 1O; SCHEMA §journal; M11, M16).

`write_prediction` writes one prediction with its per-target scores (`prediction_scores`), the
chosen contract per side (`trade_candidates`) and any simulated trades, in one transaction.
`write_backtest` adds a candidate with its trades to an existing prediction. The database
enforces point-in-time limits (features <= T, candidate quote <= T + latency), calibration for
CALL / PUT, one trade per (candidate, fill model) and append-only tables."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, Engine, text

from qqq1dte.execution_sim.engine import Candidate, Trade

SIDE = {"C": "CALL", "P": "PUT"}


@dataclass(frozen=True)
class PredictionRecord:
    prediction_id: uuid.UUID
    run_id: str
    prediction_ts: datetime
    mode: str  # BACKTEST | PAPER
    underlying_price: float
    chain_snapshot_ref: str | None
    feature_snapshot_ref: str
    feature_version: str
    max_feature_available_at: datetime
    regime: dict[str, Any]
    model_version_id: str  # CALL side (prediction_scores is authoritative per target)
    calibration_version_id: str | None  # CALL side
    raw_scores: dict[str, float]
    calibrated_probs: dict[str, float] | None
    support_n: dict[str, int] | None
    decision: str
    decision_reasons: list[str]
    expected_value: dict[str, float | None] | None
    config_hash: str
    code_commit: str


@dataclass(frozen=True)
class ScoreRecord:
    target: str
    model_version_id: str
    calibration_version_id: str | None
    raw_score: float
    calibrated_prob: float | None
    support_n: int | None
    entry_price: float | None
    p_breakeven: float | None
    margin: float | None
    expected_value: float | None
    side_reason: str | None


def _j(x: Any) -> str | None:
    return None if x is None else json.dumps(x, default=str)


def _insert_candidate(c: Connection, prediction_id: uuid.UUID, cand: Candidate) -> uuid.UUID:
    cid = uuid.uuid4()
    c.execute(
        text("""
            INSERT INTO trade_candidates (candidate_id, prediction_id, side, occ_symbol,
              expiration, strike, quote_ts, latency_s, bid, ask, bid_size, ask_size,
              passed_gates, gate_failures, selection_rule_version, selected)
            VALUES (:cid, :pid, :side, :sym, :exp, :strike, :qts, :lat, :bid, :ask, :bsz,
              :asz, :passed, :fails, :rule, :selected)"""),
        {
            "cid": cid,
            "pid": prediction_id,
            "side": SIDE[cand.side],
            "sym": cand.symbol,
            "exp": cand.expiration,
            "strike": cand.strike,
            "qts": cand.quote_ts,
            "lat": cand.latency_s,
            "bid": cand.bid,
            "ask": cand.ask,
            "bsz": cand.bid_size,
            "asz": cand.ask_size,
            "passed": cand.passed_gates,
            "fails": list(cand.gate_failures),
            "rule": cand.selection_rule_version,
            "selected": cand.selected,
        },
    )
    return cid


def _insert_trade(c: Connection, candidate_id: uuid.UUID, t: Trade) -> None:
    c.execute(
        text("""
            INSERT INTO simulated_trades (trade_id, candidate_id, fill_model, entry_ts,
              entry_price, exit_ts, exit_price, target_price, stop_price, outcome,
              exit_reason, mfe, mae, gross_pnl, commissions, fees, spread_cost,
              net_pnl, r_multiple, holding_seconds, slippage)
            VALUES (:tid, :cid, :fm, :ets, :ep, :xts, :xp, :tp, :sp, :outcome, :reason,
              :mfe, :mae, :gross, :comm, :fees, :spread, :net, :r, :hold, :slip)"""),
        {
            "tid": uuid.uuid4(),
            "cid": candidate_id,
            "fm": t.fill_model,
            "ets": t.entry_ts,
            "ep": t.entry_price,
            "xts": t.exit_ts,
            "xp": t.exit_price,
            "tp": t.target_price,
            "sp": t.stop_price,
            "outcome": t.outcome,
            "reason": t.exit_reason,
            "mfe": t.mfe,
            "mae": t.mae,
            "gross": t.gross_pnl,
            "comm": t.commissions,
            "fees": t.fees,
            "spread": t.spread_cost,
            "net": t.net_pnl,
            "r": t.r_multiple,
            "hold": t.holding_seconds,
            "slip": t.slippage,
        },
    )


def write_backtest(
    engine: Engine, prediction_id: uuid.UUID, candidate: Candidate, trades: Sequence[Trade]
) -> uuid.UUID:
    """Insert the candidate and its simulated trades; return the candidate_id."""
    with engine.begin() as c:
        cid = _insert_candidate(c, prediction_id, candidate)
        for t in trades:
            _insert_trade(c, cid, t)
    return cid


def write_prediction(
    engine: Engine,
    rec: PredictionRecord,
    scores: Sequence[ScoreRecord],
    candidates: Sequence[tuple[Candidate, Sequence[Trade]]] = (),
) -> dict[str, uuid.UUID]:
    """One transaction: prediction, per-target scores, candidates and trades. Returns
    side -> candidate_id."""
    out: dict[str, uuid.UUID] = {}
    with engine.begin() as c:
        c.execute(
            text("""
                INSERT INTO predictions (prediction_id, run_id, prediction_ts, mode,
                  underlying_price, chain_snapshot_ref, feature_snapshot_ref, feature_version,
                  max_feature_available_at, regime, model_version_id, calibration_version_id,
                  raw_scores, calibrated_probs, support_n, decision, decision_reasons,
                  expected_value, config_hash, code_commit)
                VALUES (:pid, :run, :ts, :mode, :price, :chain, :feat, :fv, :mfa,
                  CAST(:regime AS JSONB), :mv, :cv, CAST(:raw AS JSONB), CAST(:cal AS JSONB),
                  CAST(:sup AS JSONB), :dec, :reasons, CAST(:ev AS JSONB), :h, :commit)"""),
            {
                "pid": rec.prediction_id,
                "run": rec.run_id,
                "ts": rec.prediction_ts,
                "mode": rec.mode,
                "price": rec.underlying_price,
                "chain": rec.chain_snapshot_ref,
                "feat": rec.feature_snapshot_ref,
                "fv": rec.feature_version,
                "mfa": rec.max_feature_available_at,
                "regime": _j(rec.regime),
                "mv": rec.model_version_id,
                "cv": rec.calibration_version_id,
                "raw": _j(rec.raw_scores),
                "cal": _j(rec.calibrated_probs),
                "sup": _j(rec.support_n),
                "dec": rec.decision,
                "reasons": list(rec.decision_reasons),
                "ev": _j(rec.expected_value),
                "h": rec.config_hash,
                "commit": rec.code_commit,
            },
        )
        if scores:
            c.execute(
                text("""
                    INSERT INTO prediction_scores (prediction_id, target, model_version_id,
                      calibration_version_id, raw_score, calibrated_prob, support_n,
                      entry_price, p_breakeven, margin, expected_value, side_reason)
                    VALUES (:pid, :t, :mv, :cv, :raw, :p, :sup, :entry, :pbe, :m, :ev, :r)"""),
                [
                    {
                        "pid": rec.prediction_id,
                        "t": s.target,
                        "mv": s.model_version_id,
                        "cv": s.calibration_version_id,
                        "raw": s.raw_score,
                        "p": s.calibrated_prob,
                        "sup": s.support_n,
                        "entry": s.entry_price,
                        "pbe": s.p_breakeven,
                        "m": s.margin,
                        "ev": s.expected_value,
                        "r": s.side_reason,
                    }
                    for s in scores
                ],
            )
        for cand, trades in candidates:
            cid = _insert_candidate(c, rec.prediction_id, cand)
            out[cand.side] = cid
            for t in trades:
                _insert_trade(c, cid, t)
    return out
