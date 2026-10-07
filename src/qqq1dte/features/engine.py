"""Feature engine: builds one AsOfReader per prediction timestamp and evaluates the registry."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime

import polars as pl

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config, load_config
from qqq1dte.core.pit import AsOfReader
from qqq1dte.features.defs import Ctx, FeatureValue, registry

__all__ = ["FEATURE_NAMES", "Ctx", "FeatureValue", "compute_at", "compute_session"]

FEATURE_NAMES: list[str] = list(registry(load_config()))

SNAPSHOT_SCHEMA: dict[str, pl.DataType] = {
    "session_date": pl.Date(),
    "prediction_ts": pl.Datetime("ns", "UTC"),
    "feature_name": pl.String(),
    "value": pl.Float64(),
    "missing_reason": pl.String(),
    "available_at": pl.Datetime("ns", "UTC"),
    "feature_version": pl.String(),
}


def compute_at(reader: AsOfReader, ctx: Ctx) -> dict[str, FeatureValue]:
    """All features at ctx.T. The reader's cutoff must be ctx.T."""
    if reader.cutoff != ctx.T:
        raise ValueError(f"reader cutoff {reader.cutoff} != prediction time {ctx.T}")
    return {name: fn(reader, ctx) for name, fn in registry(ctx.cfg).items()}


def compute_session(
    tables: Mapping[str, pl.DataFrame],
    session: date,
    cal: TradingCalendar,
    cfg: Phase1Config,
    timestamps: Sequence[datetime] | None = None,
) -> pl.DataFrame:
    """Long-format feature snapshots for a session's prediction timestamps."""
    rows = []
    for t in timestamps if timestamps is not None else cal.prediction_timestamps(session):
        values = compute_at(AsOfReader(tables, t), Ctx(T=t, session=session, cal=cal, cfg=cfg))
        for name, fv in values.items():
            rows.append(
                {
                    "session_date": session,
                    "prediction_ts": t,
                    "feature_name": name,
                    "value": fv.value,
                    "missing_reason": fv.missing_reason,
                    "available_at": fv.available_at,
                    "feature_version": cfg.features.version,
                }
            )
    return pl.DataFrame(rows, schema=SNAPSHOT_SCHEMA)
