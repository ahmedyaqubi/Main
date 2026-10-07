"""Chronological walk-forward splitter (spec §8). Expanding training window, then a 1-session
embargo, a calibration block and a test block, rolling forward by `step_months`.

Blocks follow calendar months measured from the window start; sessions are assigned by date.
Only complete test blocks that end on or before the final-holdout boundary are produced, and
holdout sessions are refused as input. There is deliberately no shuffling or sampling option.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from qqq1dte.core.calendar import add_months
from qqq1dte.core.config import Phase1Config


@dataclass(frozen=True)
class Fold:
    index: int
    train: tuple[date, ...]
    embargo: tuple[date, ...]
    calib: tuple[date, ...]
    test: tuple[date, ...]


def walk_forward_folds(
    sessions: Sequence[date], holdout_after: date, cfg: Phase1Config
) -> list[Fold]:
    """Folds over pre-holdout `sessions` (sorted research sessions)."""
    s = sorted(sessions)
    if any(d > holdout_after for d in s):
        raise ValueError(f"sessions after the final-holdout boundary {holdout_after} were passed")
    v = cfg.validation
    start = s[0]
    folds: list[Fold] = []
    k = 0
    while True:
        train_end = add_months(start, v.initial_train_months + k * v.step_months)
        calib_end = add_months(train_end, v.calibration_months)
        test_end = add_months(calib_end, v.test_months)
        if test_end - timedelta(days=1) > holdout_after:
            break  # the block would be incomplete or reach into the holdout (M7 Q1)
        train = tuple(d for d in s if d < train_end)
        after = [d for d in s if d >= train_end]
        embargo = tuple(after[: v.embargo_sessions])
        rest = after[v.embargo_sessions :]
        calib = tuple(d for d in rest if d < calib_end)
        test = tuple(d for d in rest if calib_end <= d < test_end)
        if not (train and calib and test):
            break
        folds.append(Fold(k + 1, train, embargo, calib, test))
        k += 1
    return folds
