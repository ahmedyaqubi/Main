"""D1 benchmark (M19R): what the option-implied move alone says about touching +/- m within the
label window. Inputs known at T, per row:

- x1 = log(m / sigma_exp), sigma_exp = straddle_move * sqrt(pi / 2) (an ATM straddle is worth
  about sigma sqrt(tau) S sqrt(2 / pi), so this is the implied move to expiry as a fraction);
- x2 = log(label window minutes) = log(min(T + horizon, forced flat) - T);
- x3 = log(trading minutes to expiry) = log(minutes to today's close + next_session_minutes).

Theory (driftless Brownian motion, reflection principle) gives P(touch) = 2(1 - Phi(z)) with
log z = x1 - x2 / 2 + x3 / 2; the benchmark is a logistic regression on (x1, x2, x3) fit on the
training rows, so it nests that relation with free coefficients. Rows without a straddle get the
training base rate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
import numpy.typing as npt
import polars as pl
from sklearn.linear_model import LogisticRegression

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config
from qqq1dte.core.timeutil import ET

Arr = npt.NDArray[np.float64]


def implied_inputs(rows: pl.DataFrame, m: float, cal: TradingCalendar, cfg: Phase1Config) -> Arr:
    """n x 3 matrix (x1, x2, x3); x1 is NaN where straddle_move is missing."""
    horizon = timedelta(minutes=cfg.labels.horizon_minutes)
    out = np.empty((rows.height, 3))
    straddle = rows["straddle_move"].cast(pl.Float64).fill_null(np.nan).to_numpy()
    bounds: dict[date, tuple[datetime, datetime]] = {}  # session -> (close, forced flat)
    for i, t in enumerate(rows["prediction_ts"].to_list()):
        d = t.astimezone(ET).date()
        if d not in bounds:
            bounds[d] = (cal.open_close(d)[1], cal.forced_exit_time(d))
        close, forced = bounds[d]
        window = (min(t + horizon, forced) - t).total_seconds() / 60
        to_expiry = (close - t).total_seconds() / 60 + cfg.research.next_session_minutes
        s = straddle[i]
        out[i, 0] = math.log(m / (s * math.sqrt(math.pi / 2))) if s > 0 else np.nan
        out[i, 1] = math.log(window)
        out[i, 2] = math.log(to_expiry)
    return out


@dataclass(frozen=True)
class ImpliedBenchmark:
    m: float
    coef: tuple[float, float, float]
    intercept: float
    base_rate: float

    @classmethod
    def fit(
        cls, rows: pl.DataFrame, y: Arr, m: float, cal: TradingCalendar, cfg: Phase1Config
    ) -> ImpliedBenchmark:
        x = implied_inputs(rows, m, cal, cfg)
        ok = np.isfinite(x).all(axis=1)
        lr = LogisticRegression(C=cfg.research.implied_c, max_iter=2000).fit(x[ok], y[ok])
        c = lr.coef_[0]
        return cls(
            m, (float(c[0]), float(c[1]), float(c[2])), float(lr.intercept_[0]), float(np.mean(y))
        )

    def predict(self, rows: pl.DataFrame, cal: TradingCalendar, cfg: Phase1Config) -> Arr:
        x = implied_inputs(rows, self.m, cal, cfg)
        ok = np.isfinite(x).all(axis=1)
        out = np.full(rows.height, self.base_rate)
        z = x[ok] @ np.asarray(self.coef) + self.intercept
        out[ok] = 1.0 / (1.0 + np.exp(-z))
        return out
