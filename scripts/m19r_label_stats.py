"""M19R closing: descriptive statistics of the current C trade definition (pre-holdout only).

Outcome mix and mean net $ per outcome class for every stored L2 option label, and the relative
NBBO spread at entry for every 10th session's labelled contracts. Descriptive, no model, no
fitting; holdout sessions (after `holdout_start`) are never read.

    uv run python scripts/m19r_label_stats.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import polars as pl

from qqq1dte.core.config import load_config

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config()
LABELS = ROOT / "data" / "labels" / f"{CFG.labels.version}_option"
QUOTES = ROOT / "data" / "clean" / "cleaned" / "cleaned_options_data" / "cbbo-1m"
LAST_PRE_HOLDOUT = date(2026, 4, 2)  # ADR-0011


def main() -> int:
    files = sorted(
        f
        for f in LABELS.glob("session=*.parquet")
        if date.fromisoformat(f.stem.split("=")[1]) <= LAST_PRE_HOLDOUT
    )
    d = pl.concat([pl.read_parquet(f) for f in files]).filter(pl.col("net_pnl").is_not_null())
    print(f"labelled trades {d.height:,} over {d['session_date'].n_unique()} sessions")
    print(
        d.group_by("side", "outcome_class")
        .agg(n=pl.len(), share=pl.len() / d.height * 2, mean_net=pl.col("net_pnl").mean())
        .sort("side", "outcome_class")
    )
    print(
        d.group_by("side").agg(
            median_entry=pl.col("entry_price").median(),
            mean_net=pl.col("net_pnl").mean(),
            win_rate=(pl.col("outcome_class") == "WIN").mean(),
        )
    )
    parts = []
    for f in files[::10]:
        q = (
            pl.read_parquet(QUOTES / f"{f.stem.split('=')[1]}.parquet")
            .select(pl.col("symbol").alias("contract"), "available_at", "bid", "ask")
            .sort("contract", "available_at")
        )
        lab = (
            pl.read_parquet(f)
            .filter(pl.col("entry_price").is_not_null())
            .select("contract", "entry_ts")
            .sort("contract", "entry_ts")
        )
        parts.append(
            lab.join_asof(
                q,
                left_on="entry_ts",
                right_on="available_at",
                by="contract",
                check_sortedness=False,
            )
        )
    s = pl.concat(parts).drop_nulls("bid")
    rel = (s["ask"] - s["bid"]) / ((s["ask"] + s["bid"]) / 2)
    print(
        f"entry spread (every 10th session, {s.height:,} entries): median abs "
        f"{(s['ask'] - s['bid']).median():.3f}, median relative {rel.median():.4f}, "
        f"mean relative {rel.mean():.4f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
