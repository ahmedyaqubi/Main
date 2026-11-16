"""ADR-0022 (M32): reads and append-only writes for the paper journal (migration 0004).

The database refuses an `available_at` later than the run or before the session's close, a
fill for an evening without an order, a second row for the same evening, and any update or
delete."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import Connection, text

from qqq1dte.monitoring.paper_review import FillRecord, SignalRecord
from qqq1dte.strategies.pullback_live import Instruction


def write_signal(  # noqa: PLR0913 (one journal row)
    c: Connection,
    ins: Instruction,
    *,
    next_session: date,
    ticker: str,
    instruction: str,
    run_at: datetime,
    available_at: datetime,
    code_commit: str,
    data_sha256: str,
    config_hash: str,
) -> None:
    c.execute(
        text("""
            INSERT INTO paper_signals (data_date, next_session, ticker, run_at, available_at,
              close, adj_close, rsi, sma_trend, sma_exit, entry_signal, exit_signal,
              position_before, halted, action, shares, instruction, code_commit, data_sha256,
              config_hash)
            VALUES (:d, :n, :t, :run, :av, :c, :ac, :rsi, :st, :se, :en, :ex, :pos, :h, :a, :sh,
              :txt, :commit, :sha, :ch)
        """),
        {
            "d": ins.data_date,
            "n": next_session,
            "t": ticker,
            "run": run_at,
            "av": available_at,
            "c": ins.close,
            "ac": ins.adj_close,
            "rsi": ins.rsi,
            "st": ins.sma_trend,
            "se": ins.sma_exit,
            "en": ins.entry_signal,
            "ex": ins.exit_signal,
            "pos": ins.position_before,
            "h": ins.halted,
            "a": ins.action,
            "sh": ins.shares,
            "txt": instruction,
            "commit": code_commit,
            "sha": data_sha256,
            "ch": config_hash,
        },
    )


def write_fill(c: Connection, f: FillRecord) -> None:
    c.execute(
        text("""
            INSERT INTO paper_fills (data_date, status, price, quantity, commission, filled_at,
              reason)
            VALUES (:d, :s, :p, :q, :c, :t, :r)
        """),
        {
            "d": f.data_date,
            "s": f.status,
            "p": f.price,
            "q": f.quantity,
            "c": f.commission,
            "t": f.filled_at,
            "r": f.reason,
        },
    )


def write_event(c: Connection, kind: str, data_date: date | None, detail: dict[str, Any]) -> None:
    c.execute(
        text(
            "INSERT INTO paper_events (kind, data_date, detail) VALUES (:k, :d, CAST(:j AS JSONB))"
        ),
        {"k": kind, "d": data_date, "j": json.dumps(detail, default=str)},
    )


def read_signals(c: Connection) -> list[SignalRecord]:
    rows = c.execute(
        text("""SELECT data_date, next_session, action, shares, entry_signal, exit_signal,
                       position_before, halted FROM paper_signals ORDER BY data_date""")
    )
    return [SignalRecord(*r) for r in rows]


def read_fills(c: Connection) -> list[FillRecord]:
    rows = c.execute(
        text("""SELECT data_date, status, price, quantity, commission, filled_at, reason
                FROM paper_fills ORDER BY data_date""")
    )
    return [FillRecord(*r) for r in rows]


def read_events(c: Connection, kind: str | None = None) -> list[dict[str, Any]]:
    rows = c.execute(
        text("""SELECT at, kind, data_date, detail FROM paper_events
                WHERE CAST(:k AS TEXT) IS NULL OR kind = :k ORDER BY event_id"""),
        {"k": kind},
    )
    return [dict(r._mapping) for r in rows]


def position_after(signals: list[SignalRecord], fills: list[FillRecord]) -> int:
    """Shares held after every recorded fill."""
    by = {s.data_date: s for s in signals}
    pos = 0
    for f in sorted(fills, key=lambda x: x.data_date):
        if f.status == "FILLED" and f.quantity is not None:
            pos += f.quantity if by[f.data_date].action == "BUY" else -f.quantity
    return pos


def unrecorded_orders(signals: list[SignalRecord], fills: list[FillRecord]) -> list[date]:
    """BUY or SELL evenings whose outcome the owner has not recorded yet."""
    have = {f.data_date for f in fills}
    return [s.data_date for s in signals if s.action in ("BUY", "SELL") and s.data_date not in have]
