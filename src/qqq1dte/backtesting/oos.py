"""Shared out-of-sample evaluation helpers for the model scripts (M9+): targets, data loading
for pre-holdout sessions, block row selection, scores with session-bootstrap CIs."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import polars as pl
from sqlalchemy import Engine, text

from qqq1dte.backtesting.bootstrap import session_bootstrap_ci
from qqq1dte.core.config import Phase1Config
from qqq1dte.features.engine import FEATURE_NAMES
from qqq1dte.models.design import KEYS, wide_features
from qqq1dte.models.metrics import brier, ece, log_loss

TARGETS = [
    ("A_up", ""),
    ("A_dn", ""),
    ("B_up", "m=0.0025"),
    ("B_dn", "m=0.0025"),
    ("B_up", "m=0.005"),
    ("B_dn", "m=0.005"),
    ("C_call", ""),
    ("C_put", ""),
    ("D_call", ""),
    ("D_put", ""),
]
Arr = npt.NDArray[np.float64]


def target_name(label_id: str, variant: str) -> str:
    return f"{label_id}[{variant}]" if variant else label_id


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "_", name).strip("_")


def load_data(
    root: Path, cfg: Phase1Config, sessions: list[date]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Wide features and long label values for the given (pre-holdout) sessions."""
    fdir = root / "data" / "features" / cfg.features.version
    ldir = root / "data" / "labels" / cfg.labels.version
    wide = pl.concat(
        [
            wide_features(pl.read_parquet(fdir / f"session={d}.parquet"), FEATURE_NAMES)
            for d in sessions
        ]
    )
    labels = pl.concat(
        [
            pl.read_parquet(ldir / f"session={d}.parquet").select(
                *KEYS, "label_id", "variant", pl.col("value").alias("y")
            )
            for d in sessions
        ]
    )
    return wide, labels


def block_rows(wide: pl.DataFrame, t: pl.DataFrame, block: tuple[date, ...]) -> pl.DataFrame:
    """Feature rows of `block` sessions joined to their resolved target value `y`."""
    rows = t.filter(pl.col("session_date").is_in(list(block)) & pl.col("y").is_not_null())
    return wide.join(rows.select(*KEYS, "y"), on=KEYS, how="inner", validate="1:1").sort(KEYS)


def ci(sid: npt.NDArray[Any], fn: Callable[[Arr], float], cfg: Phase1Config) -> list[float]:
    m = cfg.models.metrics
    lo, hi = session_bootstrap_ci(
        sid, fn, cfg.validation.bootstrap_reps, m.bootstrap_seed, m.ci_level
    )
    return [lo, hi]


def _bss(y: Arr, p: Arr, ref: Arr) -> Callable[[Arr], float]:
    return lambda w: 1 - brier(y, p, w) / brier(y, ref, w)


def score(y: Arr, p: Arr, sid: npt.NDArray[Any], cfg: Phase1Config) -> dict[str, Any]:
    bins = cfg.models.metrics.ece_bins
    return {
        "brier": brier(y, p),
        "brier_ci": ci(sid, lambda w: brier(y, p, w), cfg),
        "log_loss": log_loss(y, p),
        "log_loss_ci": ci(sid, lambda w: log_loss(y, p, w), cfg),
        "ece": ece(y, p, bins),
        "ece_ci": ci(sid, lambda w: ece(y, p, bins, w), cfg),
    }


def skill(
    y: Arr, p: Arr, refs: dict[str, Arr], sid: npt.NDArray[Any], cfg: Phase1Config
) -> dict[str, Any]:
    """Brier skill score of p against each reference, with session-bootstrap CIs."""
    out: dict[str, Any] = {}
    for k, ref in refs.items():
        out[f"bss_vs_{k}"] = 1 - brier(y, p) / brier(y, ref)
        out[f"bss_vs_{k}_ci"] = ci(sid, _bss(y, p, ref), cfg)
    return out


def dataset_id(engine: Engine, uri: str) -> str:
    with engine.connect() as c:
        return str(
            c.execute(
                text("SELECT dataset_id FROM dataset_versions WHERE storage_uri = :u"), {"u": uri}
            ).scalar_one()
        )


def code_commit(root: Path) -> str:
    return (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
        ).stdout.strip()
        or "unknown"
    )
