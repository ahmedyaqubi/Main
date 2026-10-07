"""Report helpers for trading P&L (gate 9: net of costs, enforced by type, M12 Q6).

Every dollar P&L figure that reaches a report goes through these helpers, which accept only
`NetPnl` (built from gross P&L and round-trip costs). Frames read back from Parquet are converted
with `net_from_frame`, which requires the gross and cost columns and checks the stored net."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

from qqq1dte.backtesting.bootstrap import session_bootstrap_ci
from qqq1dte.core.config import Phase1Config
from qqq1dte.execution_sim.accounting import NetPnl

TOL = 1e-9
COST_COLUMNS = ("gross_pnl", "commissions", "fees", "net_pnl")


def net_from_frame(df: pl.DataFrame) -> list[NetPnl]:
    """NetPnl per row from gross_pnl - commissions - fees; must equal the stored net_pnl."""
    missing = [c for c in COST_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"P&L frame lacks cost columns: {missing}")
    out = []
    for g, c, f, n in df.select(COST_COLUMNS).iter_rows():
        p = NetPnl(g, c + f)
        if abs(float(p) - n) > TOL:
            raise ValueError(f"stored net_pnl {n} != gross {g} - costs {c + f}")
        out.append(p)
    return out


@dataclass(frozen=True)
class NetSummary:
    n: int
    mean: float
    ci: tuple[float, float]
    median: float
    total: float


def summarize_net(
    pnl: Sequence[NetPnl], session_ids: Sequence[date], cfg: Phase1Config
) -> NetSummary:
    """Mean (session-block bootstrap CI), median and total of net P&L."""
    if any(not isinstance(p, NetPnl) for p in pnl):
        raise TypeError("report P&L must be NetPnl (net of costs, gate 9)")
    v = np.array([float(p) for p in pnl], dtype=np.float64)
    if v.size == 0:
        return NetSummary(0, float("nan"), (float("nan"), float("nan")), float("nan"), 0.0)
    m = cfg.models.metrics
    lo, hi = session_bootstrap_ci(
        np.asarray(session_ids),
        lambda w: float(np.average(v, weights=w)),
        cfg.validation.bootstrap_reps,
        m.bootstrap_seed,
        m.ci_level,
    )
    return NetSummary(int(v.size), float(v.mean()), (lo, hi), float(np.median(v)), float(v.sum()))
