"""Raw layer for Databento DBN files (docs/SCHEMA.md §A.1-2).

Stores each delivered file twice, both unchanged:
- the original bytes, content-addressed by SHA-256 (`raw_file_id`);
- a decoded Parquet copy with every DBN field as delivered (uint64 ns timestamps, int64
  fixed-point prices with the vendor's undefined sentinel), plus provenance columns.

Nothing here filters, fills, converts units, or interprets timestamps. That is M4's job.
Re-ingesting a file that is already present is a no-op.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import databento as db
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from qqq1dte.core.config import config_hash
from qqq1dte.core.timeutil import ensure_utc

SOURCE = "databento"
RAW_FORMAT_VERSION = 1  # bump (with an ADR) if the decoded Parquet layout changes
INT64_UNDEF = int(np.iinfo(np.int64).max)  # Databento UNDEF_PRICE
DECODE_CHUNK_ROWS = 2_000_000
_HASH_BLOCK = 1 << 20


@dataclass(frozen=True)
class RawStore:
    root: Path

    def original_path(self, raw_file_id: str) -> Path:
        return self.root / "files" / f"{raw_file_id}.dbn.zst"

    def parquet_path(
        self, vendor_dataset: str, schema: str, partition_date: date, raw_file_id: str
    ) -> Path:
        return (
            self.root
            / "parquet"
            / vendor_dataset
            / schema
            / f"date={partition_date.isoformat()}"
            / f"{raw_file_id}.parquet"
        )


@dataclass(frozen=True)
class IngestResult:
    raw_file_id: str
    vendor_dataset: str
    schema: str
    partition_date: date
    rows: int
    parquet_path: Path
    already_present: bool


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(_HASH_BLOCK):
            h.update(block)
    return h.hexdigest()


def compute_dataset_id(kind: str, vendor_dataset: str, schema: str, raw_file_ids: list[str]) -> str:
    """Content-only identity: same files + same layout version -> same id (no timestamps)."""
    return config_hash(
        {
            "kind": kind,
            "vendor_dataset": vendor_dataset,
            "schema": schema,
            "raw_file_ids": sorted(raw_file_ids),
            "raw_format_version": RAW_FORMAT_VERSION,
        }
    )


def _store_original(src: Path, store: RawStore, raw_file_id: str) -> Path:
    dest = store.original_path(raw_file_id)
    if dest.exists():
        if sha256_file(dest) != raw_file_id:
            raise ValueError(f"hash mismatch for stored original {dest}; refusing to continue")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.copyfile(src, tmp)
    if sha256_file(tmp) != raw_file_id:
        tmp.unlink()
        raise ValueError(f"hash mismatch while copying {src}")
    os.replace(tmp, dest)
    return dest


def _provenance(
    n: int, vendor_dataset: str, schema: str, raw_file_id: str, ingested_at: datetime
) -> dict[str, pa.Array]:
    return {
        "source": pa.array([SOURCE] * n, pa.string()),
        "vendor_dataset": pa.array([vendor_dataset] * n, pa.string()),
        "schema": pa.array([schema] * n, pa.string()),
        "raw_file_id": pa.array([raw_file_id] * n, pa.string()),
        "ingested_at": pa.array([ingested_at] * n, pa.timestamp("us", tz="UTC")),
    }


def ingest_file(src: Path, store: RawStore, *, now: datetime | None = None) -> IngestResult:
    """Ingest one DBN file into the raw store. Idempotent per file content."""
    ingested_at = ensure_utc(now or datetime.now(UTC))
    raw_file_id = sha256_file(src)
    original = _store_original(src, store, raw_file_id)

    dbn_store = db.DBNStore.from_file(original)
    meta = dbn_store.metadata
    vendor_dataset = str(meta.dataset)
    schema = str(dbn_store.schema)
    partition_date = datetime.fromtimestamp(meta.start / 1e9, tz=UTC).date()
    out = store.parquet_path(vendor_dataset, schema, partition_date, raw_file_id)

    if out.exists():
        rows = pq.read_metadata(out).num_rows
        return IngestResult(raw_file_id, vendor_dataset, schema, partition_date, rows, out, True)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    rows = 0
    writer: pq.ParquetWriter | None = None
    try:
        frames = dbn_store.to_df(
            pretty_ts=False, price_type="fixed", map_symbols=True, count=DECODE_CHUNK_ROWS
        )
        for chunk in frames:
            table = pa.Table.from_pandas(chunk.reset_index(), preserve_index=False)
            for name, col in _provenance(
                table.num_rows, vendor_dataset, schema, raw_file_id, ingested_at
            ).items():
                table = table.append_column(name, col)
            if writer is None:
                writer = pq.ParquetWriter(tmp, table.schema)
            writer.write_table(table)
            rows += table.num_rows
        if writer is None:  # empty file: still record it, with provenance columns only
            empty = pa.table(_provenance(0, vendor_dataset, schema, raw_file_id, ingested_at))
            pq.write_table(empty, tmp)
    finally:
        if writer is not None:
            writer.close()
    os.replace(tmp, out)
    return IngestResult(raw_file_id, vendor_dataset, schema, partition_date, rows, out, False)
