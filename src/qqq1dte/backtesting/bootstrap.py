"""Session-block bootstrap (spec §8): resample whole sessions, because predictions within a
session are strongly dependent. Implemented by drawing a multinomial count per session and
passing per-row weights to the statistic (equivalent to copying sessions)."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import numpy.typing as npt


def session_bootstrap_ci(
    session_ids: npt.ArrayLike,
    stat: Callable[[npt.NDArray[np.float64]], float],
    reps: int,
    seed: int,
    level: float,
) -> tuple[float, float]:
    """Percentile CI of stat(row_weights) over `reps` session-level resamples."""
    sid = np.asarray(session_ids)
    uniq, inv = np.unique(sid, return_inverse=True)
    n = len(uniq)
    rng = np.random.default_rng(seed)
    out = np.empty(reps)
    for i in range(reps):
        counts = rng.multinomial(n, np.full(n, 1.0 / n))
        out[i] = stat(counts[inv].astype(np.float64))
    alpha = (1 - level) / 2
    lo, hi = np.quantile(out, [alpha, 1 - alpha])
    return float(lo), float(hi)
