"""M3 raw ingestion: unchanged storage, provenance, idempotency, content-only dataset_id."""

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

import databento as db
import numpy as np
import polars as pl
import pytest

from dbn_fixtures import cbbo_file, ohlcv_file
from qqq1dte.ingestion.databento_raw import (
    INT64_UNDEF,
    RawStore,
    compute_dataset_id,
    ingest_file,
)

T1 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> RawStore:
    return RawStore(tmp_path / "raw")


def test_original_file_stored_byte_identical(tmp_path: Path, store: RawStore) -> None:
    src = ohlcv_file(tmp_path / "bars.dbn.zst")
    res = ingest_file(src, store, now=T1)
    assert res.raw_file_id == hashlib.sha256(src.read_bytes()).hexdigest()
    assert store.original_path(res.raw_file_id).read_bytes() == src.read_bytes()


def test_parquet_values_equal_dbn_fields(tmp_path: Path, store: RawStore) -> None:
    src = ohlcv_file(tmp_path / "bars.dbn.zst", n=5)
    res = ingest_file(src, store, now=T1)
    pq = pl.read_parquet(res.parquet_path)
    arr = db.DBNStore.from_file(src).to_ndarray()
    assert pq.height == len(arr) == 5
    for field in arr.dtype.names:
        if field == "length":  # DBN framing, not data
            continue
        assert pq[field].to_list() == arr[field].tolist(), field
    assert pq.schema["ts_event"] == pl.UInt64  # vendor type, no conversion
    assert pq.schema["close"] == pl.Int64  # fixed-point 1e-9, no float conversion


def test_undefined_price_sentinel_kept(tmp_path: Path, store: RawStore) -> None:
    res = ingest_file(cbbo_file(tmp_path / "q.dbn.zst"), store, now=T1)
    pq = pl.read_parquet(res.parquet_path)
    assert pq["bid_px_00"].to_list() == [1_000_000_000, INT64_UNDEF]
    assert np.iinfo(np.int64).max == INT64_UNDEF


def test_provenance_and_partition(tmp_path: Path, store: RawStore) -> None:
    res = ingest_file(cbbo_file(tmp_path / "q.dbn.zst"), store, now=T1)
    pq = pl.read_parquet(res.parquet_path)
    assert set(pq["source"]) == {"databento"}
    assert set(pq["vendor_dataset"]) == {"OPRA.PILLAR"}
    assert set(pq["schema"]) == {"cbbo-1m"}
    assert set(pq["raw_file_id"]) == {res.raw_file_id}
    assert pq.schema["ingested_at"] == pl.Datetime("us", "UTC")
    assert pq["ingested_at"].to_list() == [T1, T1]
    assert res.partition_date == date(2025, 3, 10)
    assert "date=2025-03-10" in res.parquet_path.as_posix()
    assert pq["symbol"].to_list() == ["QQQ   250311C00483000"] * 2


def test_reingest_is_idempotent(tmp_path: Path, store: RawStore) -> None:
    src = ohlcv_file(tmp_path / "bars.dbn.zst")
    first = ingest_file(src, store, now=T1)
    second = ingest_file(src, store, now=T2)
    assert not first.already_present
    assert second.already_present
    assert second.raw_file_id == first.raw_file_id
    assert second.parquet_path == first.parquet_path
    files = list((store.root / "parquet").rglob("*.parquet"))
    assert len(files) == 1
    pq = pl.read_parquet(first.parquet_path)
    assert pq.height == 3
    assert pq["ingested_at"].to_list() == [T1] * 3  # first ingest kept, not rewritten


def test_dataset_id_depends_on_content_only(tmp_path: Path, store: RawStore) -> None:
    a = ingest_file(ohlcv_file(tmp_path / "a.dbn.zst"), store, now=T1)
    b = ingest_file(ohlcv_file(tmp_path / "b.dbn.zst", close_offset=1), store, now=T2)
    assert a.raw_file_id != b.raw_file_id

    def ds(ids: list[str]) -> str:
        return compute_dataset_id("raw_market_data", "EQUS.MINI", "ohlcv-1m", ids)

    assert ds([a.raw_file_id, b.raw_file_id]) == ds([b.raw_file_id, a.raw_file_id])
    assert ds([a.raw_file_id]) != ds([a.raw_file_id, b.raw_file_id])
    assert ds([a.raw_file_id]) != compute_dataset_id(
        "raw_market_data", "EQUS.MINI", "ohlcv-1d", [a.raw_file_id]
    )


def test_tampered_original_detected(tmp_path: Path, store: RawStore) -> None:
    src = ohlcv_file(tmp_path / "bars.dbn.zst")
    res = ingest_file(src, store, now=T1)
    store.original_path(res.raw_file_id).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="hash mismatch"):
        ingest_file(src, store, now=T2)
