"""Phase 1V gates 1-2 (spec §11) evaluated from session-level DQ results."""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

from qqq1dte.core.config import Phase1Config


@dataclass(frozen=True)
class GateResult:
    gate: int
    name: str
    passed: bool
    numbers: dict[str, float | int] = field(default_factory=dict)
    rule: str = ""


def gate1(bar_cov: pl.DataFrame, chain_cov: pl.DataFrame, cfg: Phase1Config) -> GateResult:
    """Every session >= min_bar_coverage, and >= min_chain_session_share of sessions with a
    valid chain at >= min_chain_timestamp_share of prediction timestamps."""
    q = cfg.dq
    below = int((bar_cov["coverage"] < q.min_bar_coverage).sum())
    n = chain_cov.height
    chain_ok = int((chain_cov["share"] >= q.min_chain_timestamp_share).sum())
    share = chain_ok / n if n else 0.0
    return GateResult(
        gate=1,
        name="Data coverage",
        passed=below == 0 and share >= q.min_chain_session_share and n > 0,
        numbers={
            "sessions": bar_cov.height,
            "sessions_below_bar_coverage": below,
            "min_bar_coverage_seen": min(bar_cov["coverage"].to_list(), default=0.0),
            "sessions_with_valid_chain": chain_ok,
            "valid_chain_session_share": share,
        },
        rule=(
            f"all sessions >= {q.min_bar_coverage:.0%} RTH bars; >= "
            f"{q.min_chain_session_share:.0%} of sessions with a valid chain at >= "
            f"{q.min_chain_timestamp_share:.0%} of prediction timestamps"
        ),
    )


def gate2(open_critical_events: int, invalid_rate: float, cfg: Phase1Config) -> GateResult:
    q = cfg.dq
    return GateResult(
        gate=2,
        name="Data quality",
        passed=open_critical_events == 0 and invalid_rate <= q.max_invalid_quote_rate,
        numbers={"open_critical_events": open_critical_events, "invalid_quote_rate": invalid_rate},
        rule=(
            f"0 open CRITICAL events; invalid-quote rate <= {q.max_invalid_quote_rate:.0%} "
            f"(D+1, ATM +- {q.atm_half_width}, RTH)"
        ),
    )
