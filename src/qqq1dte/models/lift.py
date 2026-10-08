"""D2 lift tables (M19R): observed outcome rate by score rank, with Wilson CIs for the observed
rate. Deciles are equal-count by rank; `top` entries q give the highest (1 - q) share of rows."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import numpy.typing as npt

from qqq1dte.calibration.metrics import wilson_ci


def _row(
    name: str, y: npt.NDArray[np.float64], s: npt.NDArray[np.float64], level: float
) -> dict[str, Any]:
    obs = float(y.mean())
    lo, hi = wilson_ci(obs, int(y.size), level)
    return {
        "bucket": name,
        "n": int(y.size),
        "mean_score": float(s.mean()),
        "observed": obs,
        "wilson_lo": lo,
        "wilson_hi": hi,
    }


def lift_table(
    y: npt.ArrayLike, score: npt.ArrayLike, deciles: bool, top: Sequence[float], level: float
) -> list[dict[str, Any]]:
    ya, sa = np.asarray(y, dtype=np.float64), np.asarray(score, dtype=np.float64)
    order = np.argsort(sa, kind="stable")
    ys, ss = ya[order], sa[order]
    rows: list[dict[str, Any]] = []
    if deciles:
        for k, idx in enumerate(np.array_split(np.arange(ys.size), 10), 1):
            rows.append(_row(f"decile {k}", ys[idx], ss[idx], level))
    for q in top:
        k = ys.size - round(ys.size * q)
        rows.append(_row(f"top {round((1 - q) * 100):g}%", ys[-k:], ss[-k:], level))
    return rows
