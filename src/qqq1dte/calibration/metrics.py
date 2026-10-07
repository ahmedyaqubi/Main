"""Calibration diagnostics (spec §11 gate 12; Phase 1L): calibration slope, Wilson intervals,
reliability bins (10 equal-count bins, shared with ECE) and the gate-12 checks (bin rule per
ADR-0009: per-bin level adjusted for the number of checked bins)."""

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
    """Per equal-count bin: n, mean predicted, observed rate, and whether the observed rate lies
    inside the Wilson CI of the mean predicted value. ADR-0009: bins with n >= bin_min_n are
    checked at the per-bin level 1 - (1 - wilson_level) / k (k = number of checked bins); the
    unadjusted `wilson_level` result is kept as `inside_95` for reference."""
    ya, pa = np.asarray(y, dtype=np.float64), np.asarray(p, dtype=np.float64)
    g = cfg.calibration.gate12
    b = ece_bins(pa, cfg.models.metrics.ece_bins)
    groups = [(int(k), b == k) for k in np.unique(b)]
    k_checked = sum(int(m.sum()) >= g.bin_min_n for _, m in groups)
    level = 1 - (1 - g.wilson_level) / max(k_checked, 1)
    out = []
    for k, m in groups:
        n = int(m.sum())
        mean_p, obs = float(pa[m].mean()), float(ya[m].mean())
        lo, hi = wilson_ci(mean_p, n, level)
        lo95, hi95 = wilson_ci(mean_p, n, g.wilson_level)
        out.append(
            {
                "bin": k,
                "n": n,
                "mean_pred": mean_p,
                "observed": obs,
                "level": level,
                "wilson_lo": lo,
                "wilson_hi": hi,
                "checked": n >= g.bin_min_n,
                "inside": lo <= obs <= hi,
                "inside_95": lo95 <= obs <= hi95,
            }
        )
    return out


def gate12(y: npt.ArrayLike, p: npt.ArrayLike, cfg: Phase1Config) -> dict[str, Any]:
    """Spec §11 gate 12 with the ADR-0009 bin rule."""
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
        "bins_failed_95": sum(not b["inside_95"] for b in checked),
        "bin_level": bins[0]["level"] if bins else g.wilson_level,
        "ece_ok": e <= g.ece_max,
        "slope_ok": g.slope_min <= slope <= g.slope_max,
        "bins_ok": not failed,
    }
    res["pass"] = bool(res["ece_ok"] and res["slope_ok"] and res["bins_ok"])
    return res
