"""ADR-0012 D2 (M19S Step 1): the model-free screen of a trade definition against the direction
model's achievable accuracy.

Inputs are one row per covered timestamp: the predicted side ("C"/"P"), the underlying direction
over the definition's horizon (+1 / -1 / 0 = deadband) and the net P&L of the predicted side's
trade under the definition. From these:
- C, W, D = mean net P&L when the predicted side was correct, wrong, or the move was in the
  deadband; p_D = deadband share;
- a* = (-p_D·D/(1-p_D) - W) / (C - W), the accuracy at which expected net P&L is zero
  (undefined when C ≤ W);
- Â = share of correct sides among non-deadband rows; Δ = Â - a*.
Both sides of Δ are computed on the same rows, so a session-block bootstrap resamples them
together (paired). Weights are per-row session copy counts, as in `session_bootstrap_ci`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import polars as pl

from qqq1dte.core.config import Phase1Config

Arr = npt.NDArray[np.float64]
UNDEFINED = -1e9  # Δ of a resample where a* is undefined: never counts in favour of advancing


def a_star(c: float, w: float, d: float, p_d: float) -> float:
    if not c > w or not p_d < 1:
        return math.nan
    return (-p_d * d / (1 - p_d) - w) / (c - w)


def ev_at(a: float, c: float, w: float, d: float, p_d: float) -> float:
    """Expected net P&L per row at non-deadband accuracy a."""
    return (1 - p_d) * (a * c + (1 - a) * w) + p_d * d


def direction(ret: npt.ArrayLike, deadband: float) -> Arr:
    """+1 / -1 outside the deadband (strict, as the §3 A labels), 0 inside, NaN when missing."""
    r = np.asarray(ret, dtype=np.float64)
    out = np.where(r > deadband, 1.0, np.where(r < -deadband, -1.0, 0.0))
    return np.where(np.isnan(r), np.nan, out)


def predicted_side(p_up: npt.ArrayLike, p_dn: npt.ArrayLike) -> tuple[npt.NDArray[Any], Arr]:
    """CALL if p_up > p_dn, otherwise PUT; score s = max(p_up, p_dn) (ADR-0012 D2)."""
    up, dn = np.asarray(p_up, dtype=np.float64), np.asarray(p_dn, dtype=np.float64)
    return np.where(up > dn, "C", "P"), np.maximum(up, dn)


def coverage_mask(fold: npt.ArrayLike, s: npt.ArrayLike, c: float) -> npt.NDArray[np.bool_]:
    """Top ceil(c·n) rows by score within each fold (ties: earlier row first)."""
    f, sc = np.asarray(fold), np.asarray(s, dtype=np.float64)
    out = np.zeros(len(sc), dtype=bool)
    for k in np.unique(f):
        idx = np.flatnonzero(f == k)
        n = math.ceil(c * len(idx) - 1e-9)
        order = idx[np.lexsort((idx, -sc[idx]))]
        out[order[:n]] = True
    return out


KEYS_STATS = ("C", "W", "D", "p_D", "a_star", "a_hat", "delta", "mean_net")


def _stats(side: npt.NDArray[Any], d: Arr, net: Arr, w: Arr) -> dict[str, float]:
    correct = ((side == "C") & (d == 1)) | ((side == "P") & (d == -1))
    dead = d == 0
    wrong = ~correct & ~dead

    def mean(m: npt.NDArray[np.bool_]) -> float:
        tot = float(w[m].sum())
        return float((w[m] * net[m]).sum() / tot) if tot > 0 else math.nan

    tot = float(w.sum())
    c, wr, dd = mean(correct), mean(wrong), mean(dead)
    p_d = float(w[dead].sum() / tot)
    nd = float(w[~dead].sum())
    a_hat = float(w[correct].sum() / nd) if nd > 0 else math.nan
    a = a_star(c, wr, 0.0 if math.isnan(dd) else dd, p_d)
    return {
        "C": c,
        "W": wr,
        "D": dd,
        "p_D": p_d,
        "a_star": a,
        "a_hat": a_hat,
        "delta": a_hat - a,
        "mean_net": float((w * net).sum() / tot),
    }


def _arrays(df: pl.DataFrame) -> tuple[npt.NDArray[Any], Arr, Arr]:
    return (
        df["side"].to_numpy(),
        df["dir"].to_numpy().astype(np.float64),
        df["net"].to_numpy().astype(np.float64),
    )


def screen_stats(df: pl.DataFrame, w: Arr) -> dict[str, float]:
    """C, W, D, p_D, a*, Â, Δ and mean net for rows with columns side, dir, net."""
    return _stats(*_arrays(df), w)


def bootstrap_draws(df: pl.DataFrame, cfg: Phase1Config) -> dict[str, Arr]:
    """Every statistic on the same session-block resamples (the RNG of `session_bootstrap_ci`:
    same seed, same multinomial draws), so Δ is paired and all CIs share the resamples."""
    side, d, net = _arrays(df)
    _, inv = np.unique(df["session_date"].to_numpy(), return_inverse=True)
    n = int(inv.max()) + 1
    rng = np.random.default_rng(cfg.models.metrics.bootstrap_seed)
    reps = cfg.validation.bootstrap_reps
    out = {k: np.empty(reps) for k in KEYS_STATS}
    for i in range(reps):
        w = rng.multinomial(n, np.full(n, 1.0 / n))[inv].astype(np.float64)
        for k, v in _stats(side, d, net, w).items():
            out[k][i] = v
    return out


def delta_lower_bound(df: pl.DataFrame, cfg: Phase1Config) -> float:
    """One-sided lower bound of Δ at `study_1b.lower_bound_level` (paired session bootstrap);
    a resample with undefined a* counts as UNDEFINED (against advancing)."""
    dl = bootstrap_draws(df, cfg)["delta"]
    return float(
        np.quantile(np.where(np.isnan(dl), UNDEFINED, dl), 1 - cfg.study_1b.lower_bound_level)
    )


@dataclass(frozen=True)
class Cell:
    definition: str
    coverage: float
    delta_lb: float
    n_trades: int
    n_sessions: int
    c_minus_w: float
    cohort_ok: bool  # False for a cohort that can never advance (T5 entries after the cutoff)

    def barred(self, cfg: Phase1Config) -> list[str]:
        s = cfg.study_1b
        out = []
        if not self.c_minus_w > 0:
            out.append("C_NOT_ABOVE_W")
        if self.n_trades < s.min_trades:
            out.append("FEW_TRADES")
        if self.n_sessions < s.min_sessions:
            out.append("FEW_SESSIONS")
        if not self.cohort_ok:
            out.append("COHORT_AFTER_CUTOFF")
        return out

    def qualifies(self, cfg: Phase1Config) -> bool:
        return self.delta_lb > 0 and not self.barred(cfg)


def advance(cells: list[Cell], cfg: Phase1Config) -> list[Cell]:
    """At most `max_advance` definitions, each at its best qualifying coverage; ties within
    `tie_tolerance` of the best remaining lower bound go to more sessions, then `tie_order`."""
    s = cfg.study_1b
    best: dict[str, Cell] = {}
    for c in cells:
        if c.qualifies(cfg) and (
            c.definition not in best or c.delta_lb > best[c.definition].delta_lb
        ):
            best[c.definition] = c
    pool, out = list(best.values()), list[Cell]()
    while pool and len(out) < s.max_advance:
        top = max(c.delta_lb for c in pool)
        near = [c for c in pool if top - c.delta_lb <= s.tie_tolerance + 1e-12]
        pick = min(near, key=lambda c: (-c.n_sessions, s.tie_order.index(c.definition)))
        out.append(pick)
        pool.remove(pick)
    return out


def policy_trades(df: pl.DataFrame, max_entries: int) -> pl.DataFrame:
    """Live-like limits (ADR-0012 D3): per session, in time order, enter a covered timestamp only
    when no position is open (max_open_positions = 1) and fewer than `max_entries` were taken.
    Rows need session_date, prediction_ts, exit_ts."""
    keep = []
    for _, g in df.sort("prediction_ts").group_by("session_date", maintain_order=True):
        n, free_at = 0, None
        for i, (ts, ex) in enumerate(g.select("prediction_ts", "exit_ts").iter_rows()):
            if n < max_entries and (free_at is None or ts >= free_at):
                keep.append(g[i])
                n, free_at = n + 1, ex
    return pl.concat(keep) if keep else df.clear()


def max_drawdown(session_net: Arr) -> float:
    """Largest peak-to-trough fall of cumulative net P&L (starting from 0)."""
    cum = np.concatenate([[0.0], np.cumsum(session_net)])
    return float(np.max(np.maximum.accumulate(cum) - cum))
