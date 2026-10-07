"""M5: build feature_snapshots (feature_version f1) for every research session.

Inputs: M4 cleaned QQQ bars/quotes and options, raw definitions, cross-market NBBO (cleaned here
with the M4 checks), the Cboe VIX file and the macro calendar. Each session is computed from
per-session table slices through AsOfReader in worker processes. Every snapshot passes the
writer's available_at <= prediction_ts check before it is stored.

    uv run python scripts/m5_build_features.py [--workers 7] [--limit-sessions N]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
from dotenv import load_dotenv
from sqlalchemy import create_engine

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config, config_hash, load_config
from qqq1dte.features.engine import compute_session
from qqq1dte.features.inputs import (
    chain_table,
    daily_stats,
    macro_table,
    minute_profile,
    option_quotes_table,
    vix_table,
)
from qqq1dte.features.writer import write_snapshots
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.ingestion.databento_raw import RawStore, compute_dataset_id, ingest_file
from qqq1dte.validation.records import build_definitions, clean_quotes

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean" / "cleaned"
REJECTED = ROOT / "data" / "clean" / "rejected"
CROSS_RAW = ROOT / "data" / "raw" / "databento" / "history" / "EQUS.MINI" / "bbo-1m-cross"
OUT = ROOT / "data" / "features"
REPORTS = ROOT / "reports" / "features"
END = date(2026, 10, 2)


def _bars_cols(df: pl.DataFrame, symbol: str | None = None) -> pl.DataFrame:
    cols = [
        "session_date",
        "ts",
        "available_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "is_rth",
    ]
    out = df.select(cols).with_columns(volume=pl.col("volume").cast(pl.Int64))
    return (
        out.with_columns(symbol=pl.lit(symbol))
        if symbol
        else out.with_columns(symbol=pl.lit("QQQ"))
    )


def load_cross(
    cal: TradingCalendar, cfg: Phase1Config, sessions: list[date]
) -> tuple[pl.DataFrame, list[str]]:
    """Ingest + clean cross-market NBBO (bbo-1m) with the M4 quote checks (f2, ADR-0004
    amendment). Coverage = RTH minute stamps with a valid two-sided quote / session minutes."""
    store = RawStore(ROOT / "data" / "raw")
    by_sym: dict[str, list[pl.DataFrame]] = {}
    for f in sorted(CROSS_RAW.glob("*.dbn.zst")):
        r = ingest_file(f, store)
        if r.rows:
            by_sym.setdefault(f.name.split("_")[0], []).append(pl.read_parquet(r.parquet_path))
    minutes = pl.DataFrame(
        {
            "session_date": sessions,
            "expected": [
                int((c - o).total_seconds() // 60) for o, c in map(cal.open_close, sessions)
            ],
        },
        schema={"session_date": pl.Date, "expected": pl.Int64},
    )
    frames: list[pl.DataFrame] = []
    lines = [
        "| symbol | raw | cleaned | rejected | sessions < 98% valid RTH quotes | worst session |",
        "|---|---|---|---|---|---|",
    ]
    for sym, parts in sorted(by_sym.items()):
        raw = pl.concat(parts, how="vertical_relaxed")
        res = clean_quotes(raw, cal, cfg)
        valid = (
            res.cleaned.filter(
                pl.col("is_rth")
                & pl.col("bid").is_not_null()
                & pl.col("ask").is_not_null()
                & (pl.col("bid") > 0)
                & (pl.col("bid") <= pl.col("ask"))
            )
            .group_by("session_date")
            .agg(n=pl.len())
        )
        cov = minutes.join(valid, on="session_date", how="left").with_columns(
            coverage=pl.col("n").fill_null(0) / pl.col("expected")
        )
        low = int((cov["coverage"] < cfg.dq.min_bar_coverage).sum())
        lines.append(
            f"| {sym} | {raw.height:,} | {res.cleaned.height:,} | {res.rejected.height:,} "
            f"| {low} | {min(cov['coverage'].to_list(), default=0.0):.4f} |"
        )
        frames.append(
            res.cleaned.select("session_date", "ts", "available_at", "bid", "ask").with_columns(
                symbol=pl.lit(sym)
            )
        )
    return pl.concat(frames), lines


def session_job(args: tuple[date, dict[str, pl.DataFrame]]) -> pl.DataFrame:
    d, tables = args
    cfg = load_config()
    return compute_session(tables, d, TradingCalendar(cfg), cfg)


def main() -> int:  # noqa: PLR0915 (linear pipeline)
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--limit-sessions", type=int, default=0)
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    cal = TradingCalendar(cfg)
    sessions = cal.research_sessions(cfg.history.option_era_start, END)
    if args.limit_sessions:
        sessions = sessions[: args.limit_sessions]

    qqq = _bars_cols(pl.read_parquet(CLEAN / "cleaned_market_data" / "ohlcv-1m" / "QQQ.parquet"))
    und = pl.read_parquet(CLEAN / "cleaned_market_data" / "bbo-1m" / "QQQ.parquet").select(
        "session_date", "ts", "available_at", "bid", "ask"
    )
    cross, cross_dq = load_cross(cal, cfg, sessions)
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
    print(f"inputs ready: {len(sessions)} sessions", flush=True)

    def jobs() -> Iterator[tuple[date, dict[str, pl.DataFrame]]]:
        for d in sessions:
            opt_c = CLEAN / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"
            opt_r = REJECTED / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"
            opts = (
                option_quotes_table(pl.read_parquet(opt_c), pl.read_parquet(opt_r))
                if opt_c.exists()
                else pl.DataFrame(
                    schema={
                        "symbol": pl.String,
                        "available_at": pl.Datetime("ns", "UTC"),
                        "bid": pl.Float64,
                        "ask": pl.Float64,
                        "valid": pl.Boolean,
                    }
                )
            )
            yield (
                d,
                {
                    "qqq_bars": qqq.filter(pl.col("session_date") == d),
                    "cross_quotes": cross.filter(pl.col("session_date") == d),
                    "daily": daily.filter(pl.col("session_date") < d),
                    "profile": profile.filter(pl.col("session_date") < d),
                    "vix": vix.filter(pl.col("date") < d),
                    "macro": macro.filter(pl.col("session_date") == d),
                    "und_quotes": und.filter(pl.col("session_date") == d),
                    "options": opts,
                    "chain": chain.filter(pl.col("session_date") == d),
                },
            )

    out_dir = OUT / cfg.features.version
    missing: Counter[tuple[str, str]] = Counter()
    total = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, df in enumerate(pool.map(session_job, jobs(), chunksize=2), 1):
            d = df["session_date"][0]
            write_snapshots(df, out_dir / f"session={d}.parquet")  # refuses any PIT violation
            total += df.height
            for name, reason in (
                df.filter(pl.col("value").is_null())
                .select("feature_name", "missing_reason")
                .iter_rows()
            ):
                missing[(name, reason)] += 1
            if i % 50 == 0:
                print(f"features {i}/{len(sessions)}", flush=True)

    # Summary report --------------------------------------------------------------------------
    allf = pl.scan_parquet(out_dir / "*.parquet")
    stats = (
        allf.group_by("feature_name")
        .agg(
            n=pl.len(),
            missing=pl.col("value").is_null().sum(),
            p01=pl.col("value").quantile(0.01),
            p50=pl.col("value").quantile(0.5),
            p99=pl.col("value").quantile(0.99),
        )
        .collect()
    )
    order = {n: i for i, n in enumerate(stats["feature_name"].to_list())}
    from qqq1dte.features.engine import FEATURE_NAMES  # noqa: PLC0415

    order = {n: i for i, n in enumerate(FEATURE_NAMES)}
    stats = stats.with_columns(o=pl.col("feature_name").replace_strict(order)).sort("o")
    commit = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
        or "unknown"
    )
    lines = [
        f"# Feature snapshots {cfg.features.version}: summary",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {commit[:12]}. Sessions "
        f"{len(sessions)} ({sessions[0]} → {sessions[-1]}), rows {total:,} "
        f"(sessions x timestamps x {len(FEATURE_NAMES)} features).",
        "",
        "| feature | rows | missing | missing % | p01 | p50 | p99 |",
        "|---|---|---|---|---|---|---|",
        *[
            f"| {r['feature_name']} | {r['n']:,} | {r['missing']:,} | {r['missing'] / r['n']:.2%} "
            f"| {r['p01'] if r['p01'] is None else f'{r["p01"]:.4g}'} "
            f"| {r['p50'] if r['p50'] is None else f'{r["p50"]:.4g}'} "
            f"| {r['p99'] if r['p99'] is None else f'{r["p99"]:.4g}'} |"
            for r in stats.to_dicts()
        ],
        "",
        "## Missing values by reason",
        "",
        "| feature | reason | rows |",
        "|---|---|---|",
        *[f"| {n} | {r} | {c:,} |" for (n, r), c in sorted(missing.items())],
        "",
        "## Cross-market NBBO data quality (M4 quote checks)",
        "",
        *cross_dq,
    ]
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    url = os.environ.get("DATABASE_URL")
    if url and not args.limit_sessions:
        cfg_h = config_hash(cfg.model_dump(mode="json"))
        fid = compute_dataset_id("features", "QQQ", cfg.features.version, [cfg_h, commit])
        engine = create_engine(url)
        record_dataset(
            engine,
            DatasetVersion(
                dataset_id=fid,
                kind="features",
                source="qqq1dte",
                coverage_start=sessions[0],
                coverage_end=sessions[-1],
                row_count=total,
                storage_uri=f"data/features/{cfg.features.version}",
                code_commit=commit,
                config_hash=cfg_h,
            ),
        )
        engine.dispose()
        print(f"registered features dataset {fid[:16]}")
    print(f"wrote {total:,} feature rows; report reports/features/summary.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
