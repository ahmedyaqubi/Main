"""M19T Step 0 (ADR-0013 D0): convert the Step-0 download to Parquet and clean it with the M4
data-quality rules. Data only: no trial, no P&L.

  1. Ingest every DBN file under configs/m19t_step0.yaml `raw_dir` into its own raw store
     (`store_dir`). Content-addressed and unchanged, as in M3. The M4 store is not touched,
     because earlier scripts read every definition file in it.
  2. Per source (0dte, ext): definitions -> `build_definitions`; each session's cbbo-1m ->
     `clean_option_quotes` (DQ rules v2). Every rejected record is written with its reasons.
  3. Per-session DQ log (`clean_dir`/dq_log.parquet): raw / cleaned / rejected counts and counts
     per reason and flag. Conservation (raw = cleaned + rejected) is asserted per file.
  4. If DATABASE_URL is set: one `dataset_versions` row per raw folder and per cleaned source
     (idempotent, as in M4). Run from committed code so `code_commit` is clean.

Holdout sessions (after `dev_end`) are stored and cleaned only. The coverage report
(scripts/m19t_coverage.py) never reads them. The QQQ daily bars are ingested but not cleaned:
they set the download band only and enter no label.

    uv run python scripts/m19t_build_data.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import yaml
from dotenv import load_dotenv
from sqlalchemy import create_engine

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import config_hash, load_config
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.ingestion.databento_raw import (
    IngestResult,
    RawStore,
    compute_dataset_id,
    ingest_file,
)
from qqq1dte.validation.records import build_definitions, clean_option_quotes
from qqq1dte.validation.rules import DQ_RULES_VERSION

ROOT = Path(__file__).resolve().parents[1]
STEP0 = ROOT / "configs" / "m19t_step0.yaml"
WORKERS = 6


def load_step0() -> dict[str, Any]:
    cfg: dict[str, Any] = yaml.safe_load(STEP0.read_text(encoding="utf-8"))
    return cfg


def _ingest(args: tuple[Path, Path, datetime]) -> tuple[str, IngestResult]:
    src, store_root, now = args
    return src.parent.name, ingest_file(src, RawStore(store_root), now=now)


def ingest_all(raw_dir: Path, store_root: Path) -> dict[str, list[IngestResult]]:
    files = sorted(raw_dir.rglob("*.dbn.zst"))
    now = datetime.now(UTC)
    groups: dict[str, list[IngestResult]] = defaultdict(list)
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        for i, (folder, r) in enumerate(
            pool.map(_ingest, [(f, store_root, now) for f in files], chunksize=8), 1
        ):
            groups[folder].append(r)
            if i % 500 == 0:
                print(f"ingested {i}/{len(files)}", flush=True)
    return groups


def read_raw(results: list[IngestResult]) -> pl.DataFrame:
    frames = [pl.read_parquet(r.parquet_path) for r in results if r.rows]
    return pl.concat(frames, how="vertical_relaxed") if frames else pl.DataFrame()


def counts(values: pl.Series) -> Counter[str]:
    return Counter(values.explode(empty_as_null=True).drop_nulls().to_list())


def clean_source(
    name: str,
    cbbo: list[IngestResult],
    defn: list[IngestResult],
    out: Path,
    cal: TradingCalendar,
) -> list[dict[str, Any]]:
    cfg = cal.cfg
    defs = build_definitions(read_raw(defn), cal)
    defs.write_parquet(out / "definitions" / f"{name}.parquet", mkdir=True)
    log: list[dict[str, Any]] = []
    # A session can have several files: the main pull plus OCC-adjusted strikes (ADR-0013 Q3).
    by_day: dict[date, list[IngestResult]] = defaultdict(list)
    for r in cbbo:
        by_day[r.partition_date].append(r)
    for i, (d, files) in enumerate(sorted(by_day.items()), 1):
        raw = read_raw(files)
        row: dict[str, Any] = {
            "source": name,
            "session_date": d,
            "raw_file_id": ",".join(sorted(f.raw_file_id for f in files)),
        }
        if raw.height == 0:
            log.append({**row, "n_raw": 0, "n_cleaned": 0, "n_rejected": 0, "reasons": "",
                        "flags": ""})  # fmt: skip
            continue
        res = clean_option_quotes(raw, defs.filter(pl.col("session_date") == d), cal, cfg)
        if res.cleaned.height + res.rejected.height != raw.height:
            raise AssertionError(f"conservation failed for {name} {d}")
        for kind, df in (("cleaned", res.cleaned), ("rejected", res.rejected)):
            df.write_parquet(out / kind / name / f"{d}.parquet", mkdir=True)
        rc, fc = counts(res.rejected["dq_reasons"]), counts(res.cleaned["dq_flags"])
        log.append(
            {
                **row,
                "n_raw": raw.height,
                "n_cleaned": res.cleaned.height,
                "n_rejected": res.rejected.height,
                "reasons": ";".join(f"{k}={v}" for k, v in sorted(rc.items())),
                "flags": ";".join(f"{k}={v}" for k, v in sorted(fc.items())),
            }
        )
        if i % 100 == 0:
            print(f"{name}: cleaned {i}/{len(by_day)}", flush=True)
    return log


def code_commit() -> str:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "src", "scripts", "configs"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return head + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def register(
    groups: dict[str, list[IngestResult]], log: pl.DataFrame, s0: dict[str, Any], cfg_h: str
) -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return "DATABASE_URL not set: datasets not registered"
    commit = code_commit()
    engine = create_engine(url)
    raw_ids: dict[str, str] = {}
    new = 0
    for folder, res in sorted(groups.items()):
        vds, schema = res[0].vendor_dataset, res[0].schema
        kind = "raw_options_data" if vds == "OPRA.PILLAR" else "raw_market_data"
        raw_ids[folder] = compute_dataset_id(
            f"{kind}:m19t:{folder}", vds, schema, [r.raw_file_id for r in res]
        )
        new += record_dataset(
            engine,
            DatasetVersion(
                dataset_id=raw_ids[folder],
                kind=kind,
                source="databento",
                coverage_start=min(r.partition_date for r in res),
                coverage_end=max(r.partition_date for r in res),
                row_count=sum(r.rows for r in res),
                storage_uri=f"{s0['store_dir']}/parquet/{vds}/{schema}",
                code_commit=commit,
                config_hash=cfg_h,
            ),
        )
    for suffix, name in s0["sources"].items():
        parents = [raw_ids[f"cbbo-1m-{suffix}"], raw_ids[f"definition-{suffix}"]]
        sub = log.filter(pl.col("source") == name)
        new += record_dataset(
            engine,
            DatasetVersion(
                dataset_id=compute_dataset_id(
                    "cleaned_options_data:m19t",
                    "OPRA.PILLAR",
                    "cbbo-1m",
                    [*parents, cfg_h, f"dq-v{DQ_RULES_VERSION}"],
                ),
                kind="cleaned_options_data",
                source="databento",
                parent_ids=parents,
                coverage_start=sub["session_date"].min(),  # type: ignore[arg-type]
                coverage_end=sub["session_date"].max(),  # type: ignore[arg-type]
                row_count=int(sub["n_cleaned"].sum()),
                storage_uri=f"{s0['clean_dir']}/cleaned/{name}",
                code_commit=commit,
                config_hash=cfg_h,
            ),
        )
    engine.dispose()
    return f"dataset_versions: {new} new rows ({len(groups) + len(s0['sources'])} datasets)"


def main() -> int:
    load_dotenv(ROOT / ".env")
    s0 = load_step0()
    cal = TradingCalendar(load_config())
    groups = ingest_all(ROOT / s0["raw_dir"], ROOT / s0["store_dir"])
    print("ingest done:", {k: len(v) for k, v in groups.items()}, flush=True)
    out = ROOT / s0["clean_dir"]
    log: list[dict[str, Any]] = []
    for suffix, name in s0["sources"].items():
        log += clean_source(
            name, groups[f"cbbo-1m-{suffix}"], groups[f"definition-{suffix}"], out, cal
        )
    df = pl.DataFrame(log, schema_overrides={"session_date": pl.Date}).with_columns(
        dq_rules_version=pl.lit(DQ_RULES_VERSION)
    )
    df.write_parquet(out / "dq_log.parquet")
    manifest = pl.DataFrame(
        [
            {
                "folder": k,
                "partition_date": r.partition_date,
                "raw_file_id": r.raw_file_id,
                "schema": r.schema,
                "rows": r.rows,
                "parquet_path": str(r.parquet_path.relative_to(ROOT)),
            }
            for k, v in groups.items()
            for r in v
        ],
        schema_overrides={"partition_date": pl.Date},
    ).sort("folder", "partition_date")
    manifest.write_parquet(out / "ingest_manifest.parquet")
    cfg_h = config_hash({"phase1": cal.cfg.model_dump(mode="json"), "m19t_step0": s0})
    print(register(groups, df, s0, cfg_h), flush=True)
    total = int(df["n_raw"].sum())
    print(
        f"done: {df.height} session files, {total:,} raw option quotes, "
        f"{int(df['n_rejected'].sum()):,} rejected; conservation held for every file; "
        f"last cleaned session {max(df['session_date'].to_list()) if df.height else date.min}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
