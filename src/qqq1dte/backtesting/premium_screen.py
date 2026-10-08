"""ADR-0013 D3-D4 (M19T Step 1): the model-free screen of the defined-risk short-premium cells.

Unit of analysis is the session (D1.b): the mean net P&L of a session's resolved trades.
Sessions without one are dropped and counted. The statistic is the mean over sessions.

Uncertainty comes from a session-block bootstrap. One shared set of multinomial draws over all
development sessions is used, so every cell and fill model is resampled on the same sessions; a
cell's resample mean is weighted by the draw counts of its own sessions.

Cell outcome:
- ADVANCE: the one-sided lower bound at the conservative fill is > 0 and no D4 guard applies.
- KILL: the two-sided upper bound at the mid fill is < 0.
- AMBIGUOUS otherwise.

Family outcome:
- ADVANCE: at most `max_advance` cells, by the largest lower bound; ties go to more sessions from
  `recent_from` on.
- KILL: every cell is KILL.
- AMBIGUOUS otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import polars as pl

from qqq1dte.core.config import Phase1Config

Arr = npt.NDArray[np.float64]
ADVANCE, KILL, AMBIGUOUS = "ADVANCE", "KILL", "AMBIGUOUS"
FILLS = ("conservative", "moderate", "mid")
_TIE = 1e-12


@dataclass(frozen=True)
class CellResult:
    cell: str
    outcome: str
    lb_conservative: float
    ub_mid: float
    n_trades: int
    n_sessions: int
    n_recent: int
    barred: list[str]
    era_flag: bool


def session_means(trades: pl.DataFrame) -> pl.DataFrame:
    """Per session: mean net per fill model and mean max risk over OK trades, and n_trades."""
    ok = trades.filter(pl.col("status") == "OK")
    return (
        ok.group_by("session_date")
        .agg(
            *[pl.col(f"net_{f}").mean().alias(f) for f in FILLS],
            pl.col("max_risk").mean(),
            n_trades=pl.len(),
        )
        .sort("session_date")
    )


def draw_weights(n_sessions: int, reps: int, seed: int) -> npt.NDArray[np.int64]:
    """reps x n multinomial session counts (each row resamples n sessions with replacement)."""
    rng = np.random.default_rng(seed)
    return rng.multinomial(n_sessions, np.full(n_sessions, 1.0 / n_sessions), size=reps)


def weighted_means(values: Arr, weights: npt.NDArray[np.int64]) -> Arr:
    """Per resample: count-weighted mean of a cell's session values (NaN if none drawn)."""
    tot = weights.sum(axis=1).astype(np.float64)
    num = (weights * values[None, :]).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(tot > 0, num / tot, np.nan)


def guards(n_trades: int, n_sessions: int, n_recent: int, cfg: Phase1Config) -> list[str]:
    s = cfg.study_1c
    out = []
    if n_trades < s.min_trades:
        out.append("FEW_TRADES")
    if n_sessions < s.min_sessions:
        out.append("FEW_SESSIONS")
    if n_recent < s.min_sessions_recent:
        out.append("FEW_RECENT_SESSIONS")
    return out


def cell_outcome(lb_conservative: float, ub_mid: float, barred: list[str]) -> str:
    if ub_mid < 0:
        return KILL
    if lb_conservative > 0 and not barred:
        return ADVANCE
    return AMBIGUOUS


def family_outcome(results: list[CellResult], cfg: Phase1Config) -> tuple[str, list[str]]:
    adv = [r for r in results if r.outcome == ADVANCE]
    if adv:
        ranked = sorted(adv, key=lambda r: (-r.lb_conservative, -r.n_recent, r.cell))
        return ADVANCE, [r.cell for r in ranked[: cfg.study_1c.max_advance]]
    if results and all(r.outcome == KILL for r in results):
        return KILL, []
    return AMBIGUOUS, []


def breakeven_loss_freq(net: Arr) -> float:
    """Loss share at which mean net is 0 given this set's mean win and mean loss sizes."""
    wins, losses = net[net > 0], -net[net < 0]
    if not len(wins) or not len(losses):
        return float("nan")
    w, lo = float(wins.mean()), float(losses.mean())
    return w / (w + lo)


def max_consecutive_losses(session_net: Arr) -> int:
    best = run = 0
    for x in session_net:
        run = run + 1 if x < 0 else 0
        best = max(best, run)
    return best


def era_driven(session_net: Arr, era: npt.NDArray[np.str_]) -> bool:
    """D2 flag: the pooled mean's sign changes when any single era is left out."""
    pooled = np.sign(session_net.mean())
    for e in np.unique(era):
        rest = session_net[era != e]
        if len(rest) and np.sign(rest.mean()) != pooled:
            return True
    return False
