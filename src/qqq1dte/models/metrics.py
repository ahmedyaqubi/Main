"""Probability metrics for OOS evaluation (spec Phase 1L / gate 5). All accept row weights, so
the session-block bootstrap can resample by weighting instead of copying rows."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

FloatArr = npt.NDArray[np.float64]
EPS = 1e-15


def _w(y: npt.ArrayLike, w: npt.ArrayLike | None) -> FloatArr:
    n = np.asarray(y).shape[0]
    return np.ones(n) if w is None else np.asarray(w, dtype=np.float64)


def brier(y: npt.ArrayLike, p: npt.ArrayLike, w: npt.ArrayLike | None = None) -> float:
    ya, pa = np.asarray(y, dtype=np.float64), np.asarray(p, dtype=np.float64)
    return float(np.average((pa - ya) ** 2, weights=_w(y, w)))


def log_loss(y: npt.ArrayLike, p: npt.ArrayLike, w: npt.ArrayLike | None = None) -> float:
    ya = np.asarray(y, dtype=np.float64)
    pa = np.clip(np.asarray(p, dtype=np.float64), EPS, 1 - EPS)
    ll = -(ya * np.log(pa) + (1 - ya) * np.log(1 - pa))
    return float(np.average(ll, weights=_w(y, w)))


def ece_bins(p: npt.ArrayLike, bins: int, w: npt.ArrayLike | None = None) -> npt.NDArray[np.int64]:
    """Equal-count (by weight) bin index per row; rows with identical predictions share a bin."""
    pa, wa = np.asarray(p, dtype=np.float64), _w(p, w)
    uniq, inv = np.unique(pa, return_inverse=True)
    uw = np.bincount(inv, weights=wa, minlength=len(uniq))
    before = np.concatenate([[0.0], np.cumsum(uw)[:-1]])
    total = uw.sum()
    ubin = (
        np.minimum((before / (total / bins)).astype(np.int64), bins - 1)
        if total > 0
        else 0 * before.astype(np.int64)
    )
    return np.asarray(ubin[inv], dtype=np.int64)


def ece(
    y: npt.ArrayLike, p: npt.ArrayLike, bins: int = 10, w: npt.ArrayLike | None = None
) -> float:
    """Expected calibration error: sum over bins of weight share x |mean(y) - mean(p)|."""
    ya, pa, wa = np.asarray(y, dtype=np.float64), np.asarray(p, dtype=np.float64), _w(y, w)
    b = ece_bins(pa, bins, wa)
    tw = np.bincount(b, weights=wa, minlength=bins)
    ty = np.bincount(b, weights=wa * ya, minlength=bins)
    tp = np.bincount(b, weights=wa * pa, minlength=bins)
    ok = tw > 0
    return float(np.sum(np.abs(ty[ok] - tp[ok])) / tw.sum())


def n_effective(n_sessions: int, minutes_in_window: int, horizon_minutes: int) -> int:
    """Spec §8: non-overlapping label windows = sessions x floor(window / horizon)."""
    return n_sessions * (minutes_in_window // horizon_minutes)


def auc(y: npt.ArrayLike, p: npt.ArrayLike) -> float:
    """ROC AUC via the Mann-Whitney rank formula; tied scores count 1/2."""
    ya, pa = np.asarray(y, dtype=np.float64), np.asarray(p, dtype=np.float64)
    n_pos = int((ya == 1).sum())
    n_neg = len(ya) - n_pos
    if n_pos == 0 or n_neg == 0:
        raise ValueError("AUC needs both classes")
    _, inv, counts = np.unique(pa, return_inverse=True, return_counts=True)
    first = np.concatenate([[0], np.cumsum(counts)[:-1]])
    avg_rank = first + (counts + 1) / 2.0  # 1-based average rank of each tie group
    rank_sum = float(avg_rank[inv][ya == 1].sum())
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
