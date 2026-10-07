"""Model 0 (spec Phase 1J): the honest baseline every later model must beat.

- unconditional: the training base rate p0;
- conditional: the rate per (time-of-day bucket x VIX tercile) cell, shrunk towards p0 as
  (k + n0 * p0) / (n + n0), so sparse cells fall back to the base rate.

Everything (p0, VIX cut points, cell counts) is fit on training rows only. VIX cut points use
one `vix_prev_close` value per training session, so sessions with more rows do not move them.
Rows with a null VIX get p0. Rows with a null target (unresolved label) are excluded from fitting.

Input frames carry: session_date, prediction_ts (UTC), vix (nullable), y (0/1, nullable).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import time

import numpy as np
import numpy.typing as npt
import polars as pl

from qqq1dte.core.config import Baseline

ET = "America/New_York"


def tod_bucket(prediction_ts: pl.Series, starts: Sequence[time]) -> pl.Series:
    """Index of the last bucket start <= the New York wall-clock time of each timestamp."""
    local = prediction_ts.dt.convert_time_zone(ET)
    minutes = (local.dt.hour().cast(pl.Int32) * 60 + local.dt.minute().cast(pl.Int32)).to_numpy()
    edges = np.array([s.hour * 60 + s.minute for s in starts])
    idx = np.searchsorted(edges, minutes, side="right") - 1
    if (idx < 0).any():
        raise ValueError("prediction time before the first time-of-day bucket start")
    return pl.Series("tod_bucket", idx, dtype=pl.Int32)


def _vix_tercile(vix: npt.NDArray[np.float64], cuts: tuple[float, ...]) -> npt.NDArray[np.int64]:
    return np.searchsorted(np.asarray(cuts), vix, side="right").astype(np.int64)


@dataclass(frozen=True)
class BaselineModel:
    p0: float
    n_train: int
    vix_cuts: tuple[float, ...]
    tod_starts: tuple[time, ...]
    prior_n: int
    cells: dict[tuple[int, int], tuple[int, int]] = field(default_factory=dict)  # (k, n)

    def cell_rate(self, tod: int, tercile: int) -> float:
        k, n = self.cells.get((tod, tercile), (0, 0))
        return (k + self.prior_n * self.p0) / (n + self.prior_n)

    def predict_unconditional(self, df: pl.DataFrame) -> npt.NDArray[np.float64]:
        return np.full(df.height, self.p0)

    def predict(self, df: pl.DataFrame) -> npt.NDArray[np.float64]:
        tod = tod_bucket(df["prediction_ts"], self.tod_starts).to_numpy()
        vix = df["vix"].cast(pl.Float64).fill_null(np.nan).to_numpy()
        ok = ~np.isnan(vix)
        terc = _vix_tercile(np.where(ok, vix, 0.0), self.vix_cuts)
        out = np.full(df.height, self.p0)
        for i in np.flatnonzero(ok):
            out[i] = self.cell_rate(int(tod[i]), int(terc[i]))
        return out


def fit_baseline(train: pl.DataFrame, cfg: Baseline) -> BaselineModel:
    rows = train.filter(pl.col("y").is_not_null())
    if rows.height == 0:
        raise ValueError("no resolved training rows")
    y = rows["y"].cast(pl.Float64).to_numpy()
    p0 = float(y.mean())
    per_session = (
        rows.filter(pl.col("vix").is_not_null()).group_by("session_date").agg(pl.col("vix").first())
    )
    if per_session.height == 0:
        raise ValueError("no training session has a VIX value")
    cuts = tuple(float(c) for c in np.quantile(per_session["vix"].to_numpy(), cfg.vix_quantiles))
    tod = tod_bucket(rows["prediction_ts"], cfg.tod_bucket_starts).to_numpy()
    vix = rows["vix"].cast(pl.Float64).fill_null(np.nan).to_numpy()
    ok = ~np.isnan(vix)
    terc = _vix_tercile(np.where(ok, vix, 0.0), cuts)
    cells: dict[tuple[int, int], tuple[int, int]] = {}
    for t, v, yy in zip(tod[ok], terc[ok], y[ok], strict=True):
        k, n = cells.get((int(t), int(v)), (0, 0))
        cells[(int(t), int(v))] = (k + int(yy), n + 1)
    return BaselineModel(
        p0=p0,
        n_train=rows.height,
        vix_cuts=cuts,
        tod_starts=tuple(cfg.tod_bucket_starts),
        prior_n=cfg.shrinkage_prior_n,
        cells=cells,
    )
