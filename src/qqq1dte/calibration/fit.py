"""Fit a calibrator on a fold's calibration block only (T-CAL-03) and choose the method without
test data (M13 Q3): fit each candidate on the first `inner_split` share of the block's sessions
(chronological), score log loss on the rest, keep the lowest (ties -> earlier in the configured
list), then refit the chosen method on the whole block."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
import numpy.typing as npt

from qqq1dte.calibration.methods import Calibrator, fit_method
from qqq1dte.core.config import Phase1Config
from qqq1dte.models.metrics import log_loss


@dataclass(frozen=True)
class CalibrationFit:
    method: str
    calibrator: Calibrator
    inner_log_loss: dict[str, float]
    n_fit: int
    n_inner_fit: int


def fit_calibration(
    p: npt.ArrayLike,
    y: npt.ArrayLike,
    sessions: Sequence[date],
    train_end: date,
    test_start: date,
    cfg: Phase1Config,
) -> CalibrationFit:
    pa, ya = np.asarray(p, dtype=np.float64), np.asarray(y, dtype=np.float64)
    sa = np.asarray(sessions)
    if any(d <= train_end for d in sessions):
        raise ValueError("calibration rows overlap the model's training period")
    if any(d >= test_start for d in sessions):
        raise ValueError("calibration rows overlap the test block")
    uniq = sorted(set(sessions))
    k = int(len(uniq) * cfg.calibration.inner_split)
    if k < 1 or k >= len(uniq):
        raise ValueError("calibration block too short for the inner split")
    cut = uniq[k]  # first session of the inner evaluation part
    fit_m, eval_m = sa < cut, sa >= cut
    losses: dict[str, float] = {}
    for m in cfg.calibration.methods:
        c = fit_method(m, pa[fit_m], ya[fit_m], cfg)
        losses[m] = log_loss(ya[eval_m], c.apply(pa[eval_m]))
    best = cfg.calibration.methods[0]
    for m in cfg.calibration.methods[1:]:
        if losses[m] < losses[best]:
            best = m
    return CalibrationFit(best, fit_method(best, pa, ya, cfg), losses, len(pa), int(fit_m.sum()))
