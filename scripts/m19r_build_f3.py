"""M19R Stage 2 (E1): build the f3 extra features for every research session, next to the
stored f2 snapshots (f3 = f2 + these extras; f2 is not recomputed).

Inputs: M4 cleaned QQQ NBBO (with sizes), raw OPRA definitions (chain), cleaned + rejected
OPRA cbbo-1m quotes (with sizes; rejected minutes hide older quotes). Output:
data/features/<features_f3.extras_dir>/session=<D>.parquet (same long snapshot schema, feature
version f3); every file passes the writer's available_at <= prediction_ts check. Registered as a
features dataset.

    uv run python scripts/m19r_build_f3.py [--workers 7]
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import polars as pl
from dotenv import load_dotenv
from sqlalchemy import create_engine

from qqq1dte.backtesting.oos import code_commit
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import config_hash, load_config
from qqq1dte.features.defs_f3 import registry_f3_extra
from qqq1dte.features.engine import compute_session
from qqq1dte.features.inputs import chain_table
from qqq1dte.features.writer import write_snapshots
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.ingestion.databento_raw import compute_dataset_id
from qqq1dte.validation.records import build_definitions

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean" / "cleaned"
REJECTED = ROOT / "data" / "clean" / "rejected"
END = date(2026, 10, 2)
CFG = load_config()
OUT = ROOT / "data" / "features" / CFG.features_f3.extras_dir


def option_quotes_sized(cleaned: pl.DataFrame, rejected: pl.DataFrame) -> pl.DataFrame:
    good = cleaned.select(
        "symbol",
        "available_at",
        "bid",
        "ask",
        bid_sz=pl.col("bid_sz").cast(pl.Int64),
        ask_sz=pl.col("ask_sz").cast(pl.Int64),
        valid=pl.col("bid").is_not_null()
        & pl.col("ask").is_not_null()
        & (pl.col("bid") > 0)
        & (pl.col("bid") <= pl.col("ask")),
    )
    bad = rejected.select(
        "symbol",
        available_at=pl.col("ts"),
        bid=pl.lit(None, pl.Float64),
        ask=pl.lit(None, pl.Float64),
        bid_sz=pl.lit(None, pl.Int64),
        ask_sz=pl.lit(None, pl.Int64),
        valid=pl.lit(False),
    )
    return pl.concat([good, bad]).sort(["symbol", "available_at"])


def session_job(args: tuple[date, dict[str, pl.DataFrame]]) -> int:
    d, tables = args
    cfg = load_config()
    df = compute_session(
        tables,
        d,
        TradingCalendar(cfg),
        cfg,
        features=registry_f3_extra(cfg),
        version=cfg.features_f3.version,
    )
    write_snapshots(df, OUT / f"session={d}.parquet")
    return df.height


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    cal = TradingCalendar(CFG)
    sessions = cal.research_sessions(CFG.history.option_era_start, END)
    und = pl.read_parquet(CLEAN / "cleaned_market_data" / "bbo-1m" / "QQQ.parquet").select(
        "session_date",
        "available_at",
        "bid",
        "ask",
        pl.col("bid_sz").cast(pl.Int64),
        pl.col("ask_sz").cast(pl.Int64),
    )
    raw_defs = pl.concat(
        [
            pl.read_parquet(p)
            for p in (ROOT / "data" / "raw" / "parquet" / "OPRA.PILLAR" / "definition").rglob(
                "*.parquet"
            )
        ],
        how="diagonal_relaxed",
    )
    chain = chain_table(build_definitions(raw_defs, cal), CFG)

    def jobs() -> Iterator[tuple[date, dict[str, pl.DataFrame]]]:
        for d in sessions:
            ch = chain.filter(
                (pl.col("session_date") == d) & (pl.col("expiration") == cal.next_session(d))
            )
            c = CLEAN / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"
            r = REJECTED / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"
            opts = option_quotes_sized(pl.read_parquet(c), pl.read_parquet(r)).filter(
                pl.col("symbol").is_in(ch["raw_symbol"].to_list())
            )
            yield (
                d,
                {
                    "und_quotes": und.filter(pl.col("session_date") == d).drop("session_date"),
                    "chain": ch,
                    "options": opts,
                },
            )

    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, n in enumerate(pool.map(session_job, jobs(), chunksize=2), 1):
            total += n
            if i % 100 == 0:
                print(f"f3 extras {i}/{len(sessions)}", flush=True)
    url = os.environ.get("DATABASE_URL")
    if url:
        commit = code_commit(ROOT)
        cfg_h = config_hash(CFG.model_dump(mode="json"))
        fid = compute_dataset_id("features", "QQQ", CFG.features_f3.extras_dir, [cfg_h, commit])
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
                storage_uri=f"data/features/{CFG.features_f3.extras_dir}",
                code_commit=commit,
                config_hash=cfg_h,
            ),
        )
        engine.dispose()
        print(f"registered features dataset {fid[:16]}")
    print(f"wrote {total:,} f3 extra feature rows to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
