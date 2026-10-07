"""Model input design (M8 Q2/Q3). Turns long feature snapshots into a numeric matrix:

- wide pivot, one column per feature; `day_of_week` becomes one-hot dow_1..dow_4 (Monday base);
- standardisation with the TRAINING fold's mean and population std (T-LEAK-11), nulls ignored;
  a constant training column gets std 1;
- a null value becomes the training mean (z = 0). Features with any missing training value get
  a 0/1 `missing_<name>` indicator. Fills are counted and reported, the stored data is unchanged;
- z values are clipped to +/- z_clip.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import polars as pl

KEYS = ["session_date", "prediction_ts"]
DOW = "day_of_week"
DOW_LEVELS = (1, 2, 3, 4)


def wide_features(long: pl.DataFrame, feature_names: Sequence[str]) -> pl.DataFrame:
    """One row per (session_date, prediction_ts), feature columns in `feature_names` order."""
    missing = set(feature_names) - set(long["feature_name"].unique().to_list())
    if missing:
        raise ValueError(f"features absent from the snapshots: {sorted(missing)}")
    wide = (
        long.filter(pl.col("feature_name").is_in(list(feature_names)))
        .pivot(on="feature_name", index=KEYS, values="value")
        .sort(KEYS)
    )
    cols: list[pl.Expr] = []
    for f in feature_names:
        if f == DOW:
            cols += [(pl.col(DOW) == k).cast(pl.Float64).alias(f"dow_{k}") for k in DOW_LEVELS]
        else:
            cols.append(pl.col(f).cast(pl.Float64))
    return wide.select(*KEYS, *cols)


@dataclass(frozen=True)
class DesignSpec:
    columns: tuple[str, ...]
    mean: tuple[float, ...]
    std: tuple[float, ...]
    indicator_for: tuple[str, ...]
    z_clip: float

    @property
    def out_columns(self) -> tuple[str, ...]:
        return (*self.columns, *(f"missing_{c}" for c in self.indicator_for))


def fit_design(train_wide: pl.DataFrame, z_clip: float) -> DesignSpec:
    columns = tuple(c for c in train_wide.columns if c not in KEYS)
    mean, std, ind = [], [], []
    for c in columns:
        v = train_wide[c].drop_nulls().to_numpy().astype(np.float64)
        if v.size == 0:
            raise ValueError(f"feature {c} has no training values")
        m, s = float(v.mean()), float(v.std())
        mean.append(m)
        std.append(s if s > 0 else 1.0)
        if train_wide[c].null_count() > 0:
            ind.append(c)
    return DesignSpec(columns, tuple(mean), tuple(std), tuple(ind), z_clip)


def transform(
    spec: DesignSpec, wide: pl.DataFrame
) -> tuple[npt.NDArray[np.float64], dict[str, int]]:
    """Model matrix (rows in `wide` order) and the number of filled values per feature."""
    raw = (
        np.column_stack(
            [wide[c].cast(pl.Float64).fill_null(np.nan).to_numpy() for c in spec.columns]
        )
        if wide.height
        else np.empty((0, len(spec.columns)))
    )
    null = np.isnan(raw)
    z = (raw - np.asarray(spec.mean)) / np.asarray(spec.std)
    z = np.clip(np.where(null, 0.0, z), -spec.z_clip, spec.z_clip)
    idx = [spec.columns.index(c) for c in spec.indicator_for]
    x = np.hstack([z, null[:, idx].astype(np.float64)])
    fills = {c: int(n) for c, n in zip(spec.columns, null.sum(axis=0), strict=True) if n}
    return x, fills
