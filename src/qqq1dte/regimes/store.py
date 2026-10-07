"""regime_labels writer (SCHEMA; M14). The database enforces available_at <= ts and the
thresholds_fit_run reference to validation_runs. One transaction per call. Re-writing a label
that already exists for (ts, axis, version) with the same value and available_at is a no-op (the
original thresholds_fit_run is kept); a different value or available_at is an error."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, text


@dataclass(frozen=True)
class RegimeLabel:
    ts: datetime  # prediction timestamp
    axis: str
    value: str
    available_at: datetime


def write_regime_labels(
    engine: Engine, rows: Sequence[RegimeLabel], run_id: str, version: str
) -> int:
    """Insert new labels; return how many were inserted."""
    with engine.begin() as c:
        existing = {
            (r[0], r[1]): (r[2], r[3])
            for r in c.execute(
                text(
                    "SELECT ts, axis, value, available_at FROM regime_labels "
                    "WHERE regime_version = :v AND ts = ANY(:ts)"
                ),
                {"v": version, "ts": list({r.ts for r in rows})},
            )
        }
        new = []
        for r in rows:
            old = existing.get((r.ts, r.axis))
            if old is None:
                new.append(r)
            elif old != (r.value, r.available_at):
                raise ValueError(
                    f"regime label {version} {r.axis} at {r.ts} already stored with a different "
                    f"value: {old} vs {(r.value, r.available_at)}"
                )
        if new:
            c.execute(
                text("""
                    INSERT INTO regime_labels (ts, axis, value, available_at, thresholds_fit_run,
                      regime_version)
                    VALUES (:ts, :axis, :value, :avail, :run, :ver)"""),
                [
                    {
                        "ts": r.ts,
                        "axis": r.axis,
                        "value": r.value,
                        "avail": r.available_at,
                        "run": run_id,
                        "ver": version,
                    }
                    for r in new
                ],
            )
    return len(new)
