"""Append-only journal writer for backtest candidates and simulated trades (SCHEMA §journal,
M11). One transaction per candidate: either the candidate and all its trades are written or
nothing is. The database enforces point-in-time selection (quote_ts <= prediction_ts + latency),
one trade per (candidate, fill model), and append-only tables."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import Engine, text

from qqq1dte.execution_sim.engine import Candidate, Trade

SIDE = {"C": "CALL", "P": "PUT"}


def write_backtest(
    engine: Engine, prediction_id: uuid.UUID, candidate: Candidate, trades: Sequence[Trade]
) -> uuid.UUID:
    """Insert the candidate and its simulated trades; return the candidate_id."""
    cid = uuid.uuid4()
    with engine.begin() as c:
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
                "side": SIDE[candidate.side],
                "sym": candidate.symbol,
                "exp": candidate.expiration,
                "strike": candidate.strike,
                "qts": candidate.quote_ts,
                "lat": candidate.latency_s,
                "bid": candidate.bid,
                "ask": candidate.ask,
                "bsz": candidate.bid_size,
                "asz": candidate.ask_size,
                "passed": candidate.passed_gates,
                "fails": list(candidate.gate_failures),
                "rule": candidate.selection_rule_version,
                "selected": candidate.selected,
            },
        )
        for t in trades:
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
                    "cid": cid,
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
    return cid
