"""M28 step 6 input (ADR-0021 D5, D8): convert the SPY / IWM / NVDA / TSLA / AAPL download to
Parquet and clean it with the M4 data-quality rules. Data only: no signal, no return.

Development files only. A file is chosen by the date in its name before it is opened
(`dev_partitions`), so no holdout row is ingested, decoded or cleaned here; the holdout files
stay on disk exactly as delivered (D8: stored, not read).

1. Ingest each development DBN file into its own raw store (data/raw/m28_store), unchanged and
   content-addressed, as in M3.
2. Per ticker, with `ticker_config` (the M23 precedent: its own option root, none of QQQ's
   ADR-backed exceptions):
   - underlying bbo-1m -> `clean_quotes`;
   - definitions -> `build_definitions`;
   - option cbbo-1m per session -> `clean_option_quotes` against that session's definitions.
   Every rejected record is written with its reasons; conservation is asserted per file.
3. data/clean/m28/{ticker}/dq_log.parquet holds per-session counts per reason and flag.

    uv run python scripts/m28_build_data.py [--tickers SPY,IWM]
"""

from __future__ import annotations

import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.ingestion.databento_raw import IngestResult, RawStore, ingest_file
from qqq1dte.validation.options_day_data import dev_partitions, ticker_config
from qqq1dte.validation.records import build_definitions, clean_option_quotes, clean_quotes
from qqq1dte.validation.rules import DQ_RULES_VERSION

ROOT = Path(__file__).resolve().parents[1]
C: dict[str, Any] = yaml.safe_load((ROOT / "configs" / "m28_data.yaml").read_text("utf-8"))
RAW = ROOT / str(C["out_dir"])
STORE = ROOT / "data" / "raw" / "m28_store"
CLEAN = ROOT / "data" / "clean" / "m28"
WORKERS = 6


def _ingest(args: tuple[Path, datetime]) -> IngestResult:
    src, now = args
    return ingest_file(src, RawStore(STORE), now=now)


def counts(values: pl.Series) -> Counter[str]:
    return Counter(values.explode(empty_as_null=True).drop_nulls().to_list())


def read(results: list[IngestResult]) -> pl.DataFrame:
    frames = [pl.read_parquet(r.parquet_path) for r in results if r.rows]
    return pl.concat(frames, how="vertical_relaxed") if frames else pl.DataFrame()


def dev_files(ticker: str, schema: str, dev_end: date) -> list[Path]:
    folder = RAW / ticker / schema
    names = [p.name for p in folder.glob("*.dbn.zst")]
    return [folder / n for n in sorted(dev_partitions(names, dev_end))]


def build(ticker: str, dev_end: date) -> dict[str, Any]:
    cfg = ticker_config(load_config(), ticker)
    cal = TradingCalendar(cfg)
    out = CLEAN / ticker
    now = datetime.now(UTC)
    ingested: dict[str, list[IngestResult]] = {}
    with ProcessPoolExecutor(WORKERS) as pool:
        for schema in ("bbo-1m", "definition", "cbbo-1m"):
            files = dev_files(ticker, schema, dev_end)
            ingested[schema] = list(pool.map(_ingest, [(f, now) for f in files], chunksize=8))
            print(f"{ticker} {schema}: ingested {len(files)} files", flush=True)

    und_raw = read(ingested["bbo-1m"])
    und = clean_quotes(und_raw, cal, cfg)
    if und.cleaned.height + und.rejected.height != und_raw.height:
        raise AssertionError(f"{ticker}: underlying conservation failed")
    if und.cleaned.height and und.cleaned["session_date"].max() > dev_end:  # type: ignore[operator]
        raise AssertionError(f"{ticker}: a holdout session reached the underlying")
    (out / "underlying").mkdir(parents=True, exist_ok=True)
    und.cleaned.write_parquet(out / "underlying" / "cleaned.parquet")
    und.rejected.write_parquet(out / "underlying" / "rejected.parquet")

    defs = build_definitions(read(ingested["definition"]), cal)
    defs.write_parquet(out / "definitions.parquet")

    log: list[dict[str, Any]] = []
    for r in sorted(ingested["cbbo-1m"], key=lambda r: r.partition_date):
        d = r.partition_date
        if d > dev_end:
            raise AssertionError(f"{ticker}: holdout option file {d}")
        raw = pl.read_parquet(r.parquet_path) if r.rows else pl.DataFrame()
        if raw.height == 0:
            log.append({"session_date": d, "n_raw": 0, "n_cleaned": 0, "n_rejected": 0,
                        "reasons": "", "flags": ""})  # fmt: skip
            continue
        res = clean_option_quotes(raw, defs.filter(pl.col("session_date") == d), cal, cfg)
        if res.cleaned.height + res.rejected.height != raw.height:
            raise AssertionError(f"{ticker} {d}: option conservation failed")
        for kind, df in (("cleaned", res.cleaned), ("rejected", res.rejected)):
            # one session may come in several files (<= 1,000 symbols each): append by name
            path = out / "options" / kind / f"{d}_{r.raw_file_id[:12]}.parquet"
            df.write_parquet(path, mkdir=True)
        rc, fc = counts(res.rejected["dq_reasons"]), counts(res.cleaned["dq_flags"])
        log.append(
            {
                "session_date": d, "n_raw": raw.height, "n_cleaned": res.cleaned.height,
                "n_rejected": res.rejected.height,
                "reasons": ";".join(f"{k}={v}" for k, v in sorted(rc.items())),
                "flags": ";".join(f"{k}={v}" for k, v in sorted(fc.items())),
            }
        )  # fmt: skip
    df = pl.DataFrame(log, schema_overrides={"session_date": pl.Date}, infer_schema_length=None)
    df.with_columns(dq_rules_version=pl.lit(DQ_RULES_VERSION)).write_parquet(out / "dq_log.parquet")
    summary = {
        "ticker": ticker,
        "underlying_raw": und_raw.height,
        "underlying_rejected": und.rejected.height,
        "underlying_reasons": dict(counts(und.rejected["dq_reasons"])),
        "definition_rows": defs.height,
        "option_files": len(ingested["cbbo-1m"]),
        "option_raw": int(df["n_raw"].sum()),
        "option_rejected": int(df["n_rejected"].sum()),
    }
    print(summary, flush=True)
    return summary


def main() -> int:
    tickers = (
        sys.argv[sys.argv.index("--tickers") + 1].split(",")
        if "--tickers" in sys.argv
        else list(C["tickers"])
    )
    dev_end = date.fromisoformat(C["dev_end"])
    assert dev_end == load_config().study_options_day.dev_end["SPY"]
    for t in tickers:
        build(t, dev_end)
    return 0


if __name__ == "__main__":
    sys.exit(main())
