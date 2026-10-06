"""Synthetic raw-layer frames shaped like `ingestion.databento_raw` output (for DQ tests)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import polars as pl

from qqq1dte.core.timeutil import ET

UNDEF = 2**63 - 1
NS = 1_000_000_000
INGESTED = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
D = date(2025, 3, 10)  # Monday, regular session (EDT)


def et_ns(d: date, hh: int, mm: int, ss: int = 0) -> int:
    return int(datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=ET).timestamp()) * NS


def fx(price: float | None) -> int:
    """Price -> Databento fixed point (1e-9); None -> undefined sentinel."""
    return UNDEF if price is None else round(price * NS)


def _prov(n: int, dataset: str, schema: str, ingested: datetime = INGESTED) -> dict[str, Any]:
    return {
        "source": ["databento"] * n,
        "vendor_dataset": [dataset] * n,
        "schema": [schema] * n,
        "raw_file_id": ["f" * 64] * n,
        "ingested_at": pl.Series([ingested] * n, dtype=pl.Datetime("us", "UTC")),
    }


def raw_bars(
    rows: list[tuple[int, float | None, float | None, float | None, float | None]],
    ingested: datetime = INGESTED,
) -> pl.DataFrame:
    """rows: (ts_event_ns, open, high, low, close)."""
    n = len(rows)
    return pl.DataFrame(
        {
            "ts_event": pl.Series([r[0] for r in rows], dtype=pl.UInt64),
            "rtype": pl.Series([33] * n, dtype=pl.UInt8),
            "publisher_id": pl.Series([95] * n, dtype=pl.UInt16),
            "instrument_id": pl.Series([13340] * n, dtype=pl.UInt32),
            "open": pl.Series([fx(r[1]) for r in rows], dtype=pl.Int64),
            "high": pl.Series([fx(r[2]) for r in rows], dtype=pl.Int64),
            "low": pl.Series([fx(r[3]) for r in rows], dtype=pl.Int64),
            "close": pl.Series([fx(r[4]) for r in rows], dtype=pl.Int64),
            "volume": pl.Series([100] * n, dtype=pl.UInt64),
            "symbol": ["QQQ"] * n,
            **_prov(n, "EQUS.MINI", "ohlcv-1m", ingested),
        }
    )


def rth_bars(
    d: date = D, minutes: int = 390, skip: tuple[int, ...] = (), price: float = 480.0
) -> pl.DataFrame:
    """Start-labelled RTH bars 09:30 + i minutes, omitting the indices in `skip`."""
    start = et_ns(d, 9, 30)
    rows = [
        (start + i * 60 * NS, price, price + 0.1, price - 0.1, price + 0.05)
        for i in range(minutes)
        if i not in skip
    ]
    return raw_bars(rows)


def raw_quotes(
    rows: list[tuple[int, int, float | None, float | None]],
    *,
    schema: str = "cbbo-1m",
    instrument_id: int = 1001,
    symbol: str = "QQQ   250311C00480000",
    dataset: str = "OPRA.PILLAR",
    ingested: datetime = INGESTED,
) -> pl.DataFrame:
    """rows: (ts_recv_ns, ts_event_ns, bid, ask)."""
    n = len(rows)
    return pl.DataFrame(
        {
            "ts_recv": pl.Series([r[0] for r in rows], dtype=pl.UInt64),
            "ts_event": pl.Series([r[1] for r in rows], dtype=pl.UInt64),
            "rtype": pl.Series([193] * n, dtype=pl.UInt8),
            "publisher_id": pl.Series([30] * n, dtype=pl.UInt16),
            "instrument_id": pl.Series([instrument_id] * n, dtype=pl.UInt32),
            "side": ["N"] * n,
            "price": pl.Series([UNDEF] * n, dtype=pl.Int64),
            "size": pl.Series([0] * n, dtype=pl.UInt32),
            "flags": pl.Series([0] * n, dtype=pl.UInt8),
            "bid_px_00": pl.Series([fx(r[2]) for r in rows], dtype=pl.Int64),
            "ask_px_00": pl.Series([fx(r[3]) for r in rows], dtype=pl.Int64),
            "bid_sz_00": pl.Series([10] * n, dtype=pl.UInt32),
            "ask_sz_00": pl.Series([10] * n, dtype=pl.UInt32),
            "symbol": [symbol] * n,
            **_prov(n, dataset, schema, ingested),
        }
    )


def concat_quotes(*frames: pl.DataFrame) -> pl.DataFrame:
    return pl.concat(frames, how="vertical")


def raw_definitions(rows: list[dict[str, Any]], recv_ns: int | None = None) -> pl.DataFrame:
    """rows: dicts with instrument_id, raw_symbol, expiration (date), strike, right,
    multiplier (default 100), day (session date of the definition file)."""
    out = []
    for r in rows:
        day = r.get("day", D)
        exp = r["expiration"]
        out.append(
            {
                "ts_recv": recv_ns if recv_ns is not None else et_ns(day, 6, 30),
                "ts_event": recv_ns if recv_ns is not None else et_ns(day, 6, 30),
                "instrument_id": r["instrument_id"],
                "raw_symbol": r["raw_symbol"],
                "expiration": int(datetime(exp.year, exp.month, exp.day, tzinfo=UTC).timestamp())
                * NS,
                "strike_price": fx(r["strike"]),
                "instrument_class": r["right"],
                "contract_multiplier": r.get("multiplier", 100),
                "symbol": r["raw_symbol"],
            }
        )
    df = pl.DataFrame(
        out,
        schema={
            "ts_recv": pl.UInt64, "ts_event": pl.UInt64, "instrument_id": pl.UInt32,
            "raw_symbol": pl.String, "expiration": pl.UInt64, "strike_price": pl.Int64,
            "instrument_class": pl.String, "contract_multiplier": pl.Int32, "symbol": pl.String,
        },
    )  # fmt: skip
    return df.with_columns(**_prov(df.height, "OPRA.PILLAR", "definition"))


def minutes_after(d: date, hh: int, mm: int, k: int) -> int:
    return et_ns(d, hh, mm) + k * 60 * NS


def td_ns(seconds: float) -> int:
    return int(timedelta(seconds=seconds).total_seconds() * NS)
