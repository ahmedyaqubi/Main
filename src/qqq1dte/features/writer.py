"""feature_snapshots writer: refuses any row whose available_at is after its prediction_ts
(ARCHITECTURE §4, mechanism 2; T-LEAK-03)."""

from __future__ import annotations

from pathlib import Path

import polars as pl


class PitViolationError(RuntimeError):
    """A feature row would use information not available at its prediction time."""


def assert_pit(df: pl.DataFrame) -> None:
    bad = df.filter(pl.col("available_at").is_not_null()
                    & (pl.col("available_at") > pl.col("prediction_ts")))  # fmt: skip
    if bad.height:
        sample = bad.head(5).select("prediction_ts", "feature_name", "available_at").to_dicts()
        raise PitViolationError(
            f"{bad.height} feature rows with available_at > prediction_ts: {sample}"
        )


def write_snapshots(df: pl.DataFrame, path: Path) -> None:
    assert_pit(df)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.write_parquet(tmp)
    tmp.replace(path)
