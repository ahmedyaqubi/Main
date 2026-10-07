"""Spec §11 gate 3 (point-in-time integrity) for feature snapshots.

1. Every stored row (all sessions, not a sample) satisfies available_at <= prediction_ts.
2. Replay: 20 random (session, timestamp) pairs are recomputed from freshly built input tables,
   with all data up to the end of the window available to the builder, and must match the
   stored values bit for bit.

    uv run python scripts/m5_gate3.py [--seed 7] [--n 20]
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m5_build_features as build
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import to_et
from qqq1dte.features.engine import compute_session

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args()
    cfg = load_config()
    cal = TradingCalendar(cfg)
    out_dir = build.OUT / cfg.features.version
    allf = pl.scan_parquet(out_dir / "*.parquet")
    counts = (
        allf.select(
            rows=pl.len(),
            violations=(
                pl.col("available_at").is_not_null()
                & (pl.col("available_at") > pl.col("prediction_ts"))
            ).sum(),
            null_available=pl.col("available_at").is_null().sum(),
        )
        .collect()
        .row(0, named=True)
    )

    # Replay: rebuild inputs exactly as the builder does, recompute, compare bit for bit.
    sessions = cal.research_sessions(cfg.history.option_era_start, build.END)
    rng = random.Random(args.seed)
    picks = sorted(rng.sample(sessions, args.n))
    qqq = build._bars_cols(
        pl.read_parquet(build.CLEAN / "cleaned_market_data" / "ohlcv-1m" / "QQQ.parquet")
    )
    und = pl.read_parquet(build.CLEAN / "cleaned_market_data" / "bbo-1m" / "QQQ.parquet").select(
        "session_date", "ts", "available_at", "bid", "ask"
    )
    cross, _ = build.load_cross(cal, cfg, sessions)
    from qqq1dte.features.inputs import (  # noqa: PLC0415
        chain_table,
        daily_stats,
        macro_table,
        minute_profile,
        option_quotes_table,
        vix_table,
    )
    from qqq1dte.validation.records import build_definitions  # noqa: PLC0415

    daily, profile = daily_stats(qqq), minute_profile(qqq, cal)
    vix = vix_table(ROOT / "data" / "raw" / "cboe" / "VIX_History.csv", cfg)
    macro = macro_table(ROOT / "configs" / "reference" / "macro_calendar.csv")
    raw_defs = pl.concat(
        [
            pl.read_parquet(p)
            for p in (ROOT / "data" / "raw" / "parquet" / "OPRA.PILLAR" / "definition").rglob(
                "*.parquet"
            )
        ],
        how="diagonal_relaxed",
    )
    chain = chain_table(build_definitions(raw_defs, cal), cfg)
    lines = ["| session | timestamp (ET) | features | identical |", "|---|---|---|---|"]
    all_ok = True
    for d in picks:
        t = rng.choice(cal.prediction_timestamps(d))
        opts = option_quotes_table(
            pl.read_parquet(build.CLEAN / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"),
            pl.read_parquet(build.REJECTED / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"),
        )
        # Unlike the builder, give the replay ALL history (no per-session slicing): the result
        # must still be identical, because the reader hides everything after T.
        tables = {
            "qqq_bars": qqq,
            "cross_quotes": cross,
            "daily": daily,
            "profile": profile,
            "vix": vix,
            "macro": macro,
            "und_quotes": und,
            "options": opts,
            "chain": chain,
        }
        fresh = compute_session(tables, d, cal, cfg, timestamps=[t]).sort("feature_name")
        stored = (
            pl.read_parquet(out_dir / f"session={d}.parquet")
            .filter(pl.col("prediction_ts") == t)
            .sort("feature_name")
        )
        ok = fresh.select("feature_name", "value", "missing_reason", "available_at").equals(
            stored.select("feature_name", "value", "missing_reason", "available_at")
        )
        all_ok &= ok
        lines.append(f"| {d} | {to_et(t):%H:%M} | {fresh.height} | {'yes' if ok else '**NO**'} |")
    passed = counts["violations"] == 0 and all_ok
    report = [
        "# Gate 3 — point-in-time integrity of feature snapshots",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC; "
        f"feature_version {cfg.features.version}.",
        "",
        f"**Result: {'PASS' if passed else 'FAIL'}**",
        "",
        f"- Rows checked: {counts['rows']:,} (all stored rows, not a sample)",
        f"- Rows with available_at > prediction_ts: **{counts['violations']}**",
        f"- Rows with null available_at (missing values): {counts['null_available']:,}",
        f"- Replay of {args.n} random timestamps (seed {args.seed}) from inputs holding the "
        f"full history, i.e. including data after T: {'all identical' if all_ok else 'MISMATCH'}",
        "",
        *lines,
    ]
    out = ROOT / "reports" / "features" / "gate3.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"gate 3: {'PASS' if passed else 'FAIL'}; {counts}; replay identical={all_ok}")
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
