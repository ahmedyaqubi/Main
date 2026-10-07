"""Calibration diagnostics (spec §11 gate 12; Phase 1L): calibration slope, Wilson intervals,
reliability bins (10 equal-count bins, shared with ECE) and the gate-12 checks."""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

import numpy as np
import numpy.typing as npt

from qqq1dte.calibration.methods import logistic_fit, logit
from qqq1dte.core.config import Phase1Config
from qqq1dte.models.metrics import ece, ece_bins


def calibration_slope(y: npt.ArrayLike, p: npt.ArrayLike) -> tuple[float, float]:
    """(slope, intercept) of an unregularised logistic regression of y on logit(p)."""
    return logistic_fit(logit(p), np.asarray(y, dtype=np.float64))


def wilson_ci(p: float, n: int, level: float) -> tuple[float, float]:
    z = NormalDist().inv_cdf(1 - (1 - level) / 2)
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z / d * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return centre - half, centre + half


def reliability(y: npt.ArrayLike, p: npt.ArrayLike, cfg: Phase1Config) -> list[dict[str, Any]]:
    """Per equal-count bin: n, mean predicted, observed rate, the Wilson CI around the mean
    predicted value, and whether the observed rate lies inside it (bins with n >= bin_min_n)."""
    ya, pa = np.asarray(y, dtype=np.float64), np.asarray(p, dtype=np.float64)
    g = cfg.calibration.gate12
    b = ece_bins(pa, cfg.models.metrics.ece_bins)
    out = []
    for k in np.unique(b):
        m = b == k
        n = int(m.sum())
        mean_p, obs = float(pa[m].mean()), float(ya[m].mean())
        lo, hi = wilson_ci(mean_p, n, g.wilson_level)
        out.append(
            {
                "bin": int(k),
                "n": n,
                "mean_pred": mean_p,
                "observed": obs,
                "wilson_lo": lo,
                "wilson_hi": hi,
                "checked": n >= g.bin_min_n,
                "inside": lo <= obs <= hi,
            }
        )
    return out


def gate12(y: npt.ArrayLike, p: npt.ArrayLike, cfg: Phase1Config) -> dict[str, Any]:
    g = cfg.calibration.gate12
    e = ece(y, p, cfg.models.metrics.ece_bins)
    slope, intercept = calibration_slope(y, p)
    bins = reliability(y, p, cfg)
    checked = [b for b in bins if b["checked"]]
    failed = [b for b in checked if not b["inside"]]
    res: dict[str, Any] = {
        "ece": e,
        "slope": slope,
        "intercept": intercept,
        "bins_checked": len(checked),
        "bins_failed": len(failed),
        "ece_ok": e <= g.ece_max,
        "slope_ok": g.slope_min <= slope <= g.slope_max,
        "bins_ok": not failed,
    }
    res["pass"] = bool(res["ece_ok"] and res["slope_ok"] and res["bins_ok"])
    return res
