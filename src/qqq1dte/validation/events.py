"""Aggregated data_quality_events: one row per (check, instrument/contract, session)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

import polars as pl
from sqlalchemy import Engine, text

from qqq1dte.core.config import Phase1Config
from qqq1dte.validation.rules import CHECKS

MAX_SAMPLES = 5


@dataclass(frozen=True)
class DQEvent:
    check_name: str
    severity: str
    action: str
    instrument: str
    session_date: date | None
    count: int
    contract: str | None = None
    samples: list[str] = field(default_factory=list)
    reason: str = ""


def _event(
    name: str,
    instrument: str,
    d: date | None,
    count: int,
    *,
    contract: str | None = None,
    samples: Iterable[object] = (),
    reason: str = "",
) -> DQEvent:
    c = CHECKS[name]
    return DQEvent(
        check_name=name,
        severity=c.severity.value,
        action=c.action.value,
        instrument=instrument,
        session_date=d,
        count=count,
        contract=contract,
        samples=[str(s) for s in list(samples)[:MAX_SAMPLES]],
        reason=reason or c.rule,
    )


def record_events(cleaned: pl.DataFrame, rejected: pl.DataFrame, instrument: str) -> list[DQEvent]:
    """Rejections per (reason, contract, session); flags per (flag, session)."""
    out: list[DQEvent] = []
    if rejected.height:
        rej = (
            rejected.select("session_date", "symbol", "ts", "dq_reasons")
            .explode("dq_reasons", empty_as_null=False)
            .group_by(["dq_reasons", "symbol", "session_date"])
            .agg(n=pl.len(), samples=pl.col("ts").sort().head(MAX_SAMPLES))
        )
        for r in rej.sort(["session_date", "dq_reasons", "symbol"]).to_dicts():
            out.append(
                _event(
                    r["dq_reasons"],
                    instrument,
                    r["session_date"],
                    r["n"],
                    contract=r["symbol"],
                    samples=r["samples"],
                )
            )
    flagged = cleaned.filter(pl.col("dq_flags").list.len() > 0)
    if flagged.height:
        fl = (
            flagged.select("session_date", "ts", "dq_flags")
            .explode("dq_flags", empty_as_null=False)
            .group_by(["dq_flags", "session_date"])
            .agg(n=pl.len(), samples=pl.col("ts").sort().head(MAX_SAMPLES))
        )
        for r in fl.sort(["session_date", "dq_flags"]).to_dicts():
            out.append(
                _event(r["dq_flags"], instrument, r["session_date"], r["n"], samples=r["samples"])
            )
    return out


def session_events(
    bar_cov: pl.DataFrame | None,
    one_dte: pl.DataFrame | None,
    chain_cov: pl.DataFrame | None,
    invalid_rate: pl.DataFrame | None,
    cfg: Phase1Config,
) -> list[DQEvent]:
    q = cfg.dq
    out: list[DQEvent] = []
    if bar_cov is not None:
        for r in bar_cov.to_dicts():
            if r["missing"]:
                out.append(
                    _event(
                        "MISSING_BAR",
                        "QQQ",
                        r["session_date"],
                        len(r["missing"]),
                        samples=r["missing"],
                    )
                )
            if r["coverage"] < q.min_bar_coverage:
                out.append(
                    _event(
                        "BAR_COVERAGE_LOW",
                        "QQQ",
                        r["session_date"],
                        r["received"],
                        reason=f"{r['received']}/{r['expected']} RTH bars ({r['coverage']:.2%})",
                    )
                )
    if one_dte is not None:
        for r in one_dte.filter(~pl.col("listed")).to_dicts():
            out.append(
                _event(
                    "NO_1DTE_EXPIRY",
                    "QQQ options",
                    r["session_date"],
                    1,
                    reason=f"expiration {r['next_session']} not in definitions",
                )
            )
    if chain_cov is not None:
        for r in chain_cov.filter(pl.col("share") < q.min_chain_timestamp_share).to_dicts():
            out.append(
                _event(
                    "CHAIN_COVERAGE_LOW",
                    "QQQ options",
                    r["session_date"],
                    r["n_valid"],
                    reason=f"{r['n_valid']}/{r['n_timestamps']} prediction timestamps "
                    f"with a valid call and put ({r['share']:.2%})",
                )
            )
    if invalid_rate is not None:
        for r in invalid_rate.filter(pl.col("rate") > q.max_invalid_quote_rate).to_dicts():
            out.append(
                _event(
                    "INVALID_QUOTE_RATE_HIGH",
                    "QQQ options",
                    r["session_date"],
                    r["n_rejected"],
                    reason=f"{r['n_rejected']}/{r['n_total']} ATM records rejected "
                    f"({r['rate']:.2%})",
                )
            )
    return out


def resolved_from_config(cfg: Phase1Config) -> dict[tuple[str, date], str]:
    """(check, session) -> ADR for CRITICAL events closed by an ADR: explicit entries plus
    every session-level CRITICAL on an ADR-excluded session."""
    out = {(r.check, r.session): r.adr for r in cfg.dq.resolved_critical}
    for e in cfg.history.excluded_sessions:
        for name in ("BAR_COVERAGE_LOW", "NO_1DTE_EXPIRY", "CHAIN_COVERAGE_LOW"):
            out[(name, e.date)] = e.adr
    return out


def open_critical(
    events: Iterable[DQEvent], resolved: set[tuple[str, date]] | dict[tuple[str, date], str]
) -> int:
    """CRITICAL events not closed by an ADR. `resolved` = {(check_name, session_date)}."""
    return sum(
        1
        for e in events
        if e.severity == "CRITICAL" and (e.check_name, e.session_date) not in resolved
    )


def write_events(
    engine: Engine,
    dataset_id: str,
    events: list[DQEvent],
    resolved: dict[tuple[str, date], str] | None = None,
) -> int:
    """Insert events for a dataset, replacing nothing: re-running for the same dataset_id is a
    no-op (events are a function of the dataset's content)."""
    with engine.begin() as c:
        existing = c.execute(
            text("SELECT count(*) FROM data_quality_events WHERE dataset_id = :d"),
            {"d": dataset_id},
        ).scalar_one()
        if existing:
            return 0
        c.execute(
            text("""
                INSERT INTO data_quality_events (dataset_id, check_name, severity, instrument,
                  contract, record_ts, session_date, action, reason, details, resolved_by_adr)
                VALUES (:dataset_id, :check_name, :severity, :instrument, :contract, NULL,
                  :session_date, :action, :reason, CAST(:details AS JSONB), :resolved_by_adr)"""),
            [
                {
                    "dataset_id": dataset_id,
                    "check_name": e.check_name,
                    "severity": e.severity,
                    "instrument": e.instrument,
                    "contract": e.contract,
                    "session_date": e.session_date,
                    "action": "NONE" if e.action == "NONE" else e.action,
                    "reason": e.reason,
                    "details": json.dumps({"count": e.count, "samples": e.samples}),
                    "resolved_by_adr": (resolved or {}).get((e.check_name, e.session_date))
                    if e.severity == "CRITICAL" and e.session_date is not None
                    else None,
                }
                for e in events
            ],
        )
    return len(events)
