"""M23 Step 0 (ADR-0014 D0/D1): convert the SPX download to Parquet and clean it with the M4
data-quality rules. Data only: no trial, no P&L.

1. Ingest every DBN file under `configs/m23_step0.yaml` out_dir (def / entry / exit) into its own
   raw store (data/raw/m23_store), unchanged and content-addressed, as in M3.
2. Definitions -> `build_definitions`. Per session, the entry and exit windows ->
   `clean_option_quotes`, once per root (SPX, SPXW). An SPX copy of the config is used:
   - `dq.option_root` set to that root;
   - no QQQ strike adjustment (ADR-0005 memo #53847 is QQQ-only);
   - no QQQ excluded session (ADR-0006).
   Every rejection is written with its reasons. Conservation is asserted per session.
3. `data/clean/m23/dq_log.parquet` holds per-session counts per reason and flag.

Holdout sessions (after `last_session` minus `holdout_months`) are stored and cleaned only.

    uv run python scripts/m23_build_data.py
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config, load_config
from qqq1dte.ingestion.databento_raw import IngestResult, RawStore, ingest_file
from qqq1dte.validation.records import build_definitions, clean_option_quotes
from qqq1dte.validation.rules import DQ_RULES_VERSION

ROOT = Path(__file__).resolve().parents[1]
S0: dict[str, Any] = yaml.safe_load((ROOT / "configs" / "m23_step0.yaml").read_text("utf-8"))
RAW = ROOT / str(S0["out_dir"])
STORE = ROOT / "data" / "raw" / "m23_store"
CLEAN = ROOT / "data" / "clean" / "m23"
ROOTS = ("SPX", "SPXW")
WORKERS = 6


def spx_config(cfg: Phase1Config, root: str) -> Phase1Config:
    dq = cfg.dq.model_copy(update={"option_root": root, "strike_adjustments": []})
    hist = cfg.history.model_copy(update={"excluded_sessions": []})
    return cfg.model_copy(update={"dq": dq, "history": hist})


def _ingest(args: tuple[Path, datetime]) -> tuple[str, IngestResult]:
    src, now = args
    return src.parent.name, ingest_file(src, RawStore(STORE), now=now)


def read_raw(results: list[IngestResult]) -> pl.DataFrame:
    frames = [pl.read_parquet(r.parquet_path) for r in results if r.rows]
    return pl.concat(frames, how="vertical_relaxed") if frames else pl.DataFrame()


def counts(values: pl.Series) -> Counter[str]:
    return Counter(values.explode(empty_as_null=True).drop_nulls().to_list())


def main() -> int:
    cfg = load_config()
    files = sorted(f for sub in ("def", "entry", "exit") for f in (RAW / sub).glob("*.dbn.zst"))
    now = datetime.now(UTC)
    groups: dict[str, list[IngestResult]] = defaultdict(list)
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        for i, (folder, r) in enumerate(
            pool.map(_ingest, [(f, now) for f in files], chunksize=8), 1
        ):
            groups[folder].append(r)
            if i % 1000 == 0:
                print(f"ingested {i}/{len(files)}", flush=True)
    print("ingest done:", {k: len(v) for k, v in groups.items()}, flush=True)

    cal = TradingCalendar(spx_config(cfg, "SPX"))
    defs = build_definitions(read_raw(groups["def"]), cal)
    CLEAN.mkdir(parents=True, exist_ok=True)
    defs.write_parquet(CLEAN / "definitions.parquet")
    by_day: dict[date, list[IngestResult]] = defaultdict(list)
    for r in groups["entry"] + groups["exit"]:
        by_day[r.partition_date].append(r)
    log: list[dict[str, Any]] = []
    for i, (d, day_files) in enumerate(sorted(by_day.items()), 1):
        raw = read_raw(day_files)
        if raw.height == 0:
            log.append({"session_date": d, "root": None, "n_raw": 0, "n_cleaned": 0,
                        "n_rejected": 0, "reasons": "", "flags": ""})  # fmt: skip
            continue
        day_defs = defs.filter(pl.col("session_date") == d)
        root_of = pl.col("symbol").str.slice(0, 6).str.strip_chars()
        cleaned, rejected = [], []
        for root in ROOTS:
            part = raw.filter(root_of == root)
            if part.height == 0:
                continue
            res = clean_option_quotes(part, day_defs, cal, spx_config(cfg, root))
            if res.cleaned.height + res.rejected.height != part.height:
                raise AssertionError(f"conservation failed {d} {root}")
            cleaned.append(res.cleaned)
            rejected.append(res.rejected)
            rc, fc = counts(res.rejected["dq_reasons"]), counts(res.cleaned["dq_flags"])
            log.append(
                {
                    "session_date": d, "root": root, "n_raw": part.height,
                    "n_cleaned": res.cleaned.height, "n_rejected": res.rejected.height,
                    "reasons": ";".join(f"{k}={v}" for k, v in sorted(rc.items())),
                    "flags": ";".join(f"{k}={v}" for k, v in sorted(fc.items())),
                }
            )  # fmt: skip
        other = raw.filter(~root_of.is_in(ROOTS)).height
        if other:
            raise AssertionError(f"{d}: {other} records with an unexpected root")
        for kind, parts in (("cleaned", cleaned), ("rejected", rejected)):
            if parts:
                pl.concat(parts, how="diagonal_relaxed").write_parquet(
                    CLEAN / kind / f"{d}.parquet", mkdir=True
                )
        if i % 500 == 0:
            print(f"cleaned {i}/{len(by_day)}", flush=True)
    df = pl.DataFrame(log, schema_overrides={"session_date": pl.Date}, infer_schema_length=None)
    df.with_columns(dq_rules_version=pl.lit(DQ_RULES_VERSION)).write_parquet(
        CLEAN / "dq_log.parquet"
    )
    print(
        f"done: {by_day.__len__()} sessions, {int(df['n_raw'].sum()):,} raw quotes, "
        f"{int(df['n_rejected'].sum()):,} rejected; {defs.height:,} definition rows; "
        "conservation held for every session"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
