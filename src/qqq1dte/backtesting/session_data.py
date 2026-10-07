"""Per-session backtest inputs from the cleaned/rejected stores (M11/M12 scripts): QQQ NBBO,
the 1DTE chain definitions and the option quote records (cleaned + rejected)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import date
from pathlib import Path

import polars as pl

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config
from qqq1dte.features.inputs import chain_table
from qqq1dte.labels.option import option_records
from qqq1dte.validation.records import build_definitions


def session_inputs(
    root: Path, sessions: Sequence[date], cal: TradingCalendar, cfg: Phase1Config
) -> Iterator[tuple[date, dict[str, pl.DataFrame]]]:
    clean, rejected = root / "data" / "clean" / "cleaned", root / "data" / "clean" / "rejected"
    und = pl.read_parquet(clean / "cleaned_market_data" / "bbo-1m" / "QQQ.parquet").select(
        "session_date", "available_at", "bid", "ask"
    )
    raw_defs = pl.concat(
        [
            pl.read_parquet(p)
            for p in (root / "data" / "raw" / "parquet" / "OPRA.PILLAR" / "definition").rglob(
                "*.parquet"
            )
        ],
        how="diagonal_relaxed",
    )
    chain = chain_table(build_definitions(raw_defs, cal), cfg)
    for d in sessions:
        nxt = cal.next_session(d)
        ch = chain.filter((pl.col("session_date") == d) & (pl.col("expiration") == nxt))
        c = clean / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"
        r = rejected / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"
        recs = option_records(pl.read_parquet(c), pl.read_parquet(r))
        recs = recs.filter(pl.col("symbol").is_in(ch["raw_symbol"].to_list()))
        yield d, {"und": und.filter(pl.col("session_date") == d), "chain": ch, "records": recs}
