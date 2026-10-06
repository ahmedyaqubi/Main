"""Synthetic Databento DBN files for ingestion tests (CI has no vendor data)."""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import databento_dbn as dbn
import zstandard

NS = 1_000_000_000
START = 1_741_613_400 * NS  # 2025-03-10 13:30:00 UTC (09:30 ET)


def _write(path: Path, metadata: dbn.Metadata, records: list[object]) -> Path:
    buf = io.BytesIO()
    buf.write(bytes(metadata.encode()))
    for r in records:
        buf.write(bytes(r))  # type: ignore[call-overload]
    path.write_bytes(zstandard.ZstdCompressor().compress(buf.getvalue()))
    return path


def _metadata(
    dataset: str, schema: dbn.Schema, symbols: list[str], instrument_ids: list[int]
) -> dbn.Metadata:
    # Symbology header as Databento writes it: raw symbol -> instrument_id for the day.
    mappings = [
        SimpleNamespace(
            raw_symbol=sym,
            intervals=[
                SimpleNamespace(
                    start_date=date(2025, 3, 10), end_date=date(2025, 3, 11), symbol=str(iid)
                )
            ],
        )
        for sym, iid in zip(symbols, instrument_ids, strict=True)
    ]
    return dbn.Metadata(
        dataset=dataset,
        start=START,
        end=START + 3600 * NS,
        stype_in=dbn.SType.RAW_SYMBOL,
        stype_out=dbn.SType.INSTRUMENT_ID,
        schema=schema,
        symbols=symbols,
        partial=[],
        not_found=[],
        mappings=mappings,
    )


def ohlcv_file(path: Path, n: int = 3, close_offset: int = 0) -> Path:
    """n start-labelled 1-minute QQQ bars; prices in 1e-9 fixed point."""
    recs = [
        dbn.OHLCVMsg(
            rtype=dbn.RType.OHLCV_1M,
            publisher_id=95,
            instrument_id=13340,
            ts_event=START + i * 60 * NS,
            open=483_430_000_000 + i * 10_000_000,
            high=484_000_000_000 + i * 10_000_000,
            low=483_000_000_000 + i * 10_000_000,
            close=483_500_000_000 + i * 10_000_000 + close_offset,
            volume=1000 + i,
        )
        for i in range(n)
    ]
    return _write(path, _metadata("EQUS.MINI", dbn.Schema.OHLCV_1M, ["QQQ"], [13340]), recs)


def cbbo_file(path: Path) -> Path:
    """Two 1-minute option NBBO records; the second has an empty bid (UNDEF_PRICE)."""
    recs = [
        dbn.CBBOMsg(
            rtype=dbn.RType.CBBO_1M,
            publisher_id=30,
            instrument_id=1_107_297_513,
            ts_event=START + 59 * NS,
            price=dbn.UNDEF_PRICE,
            size=0,
            side=dbn.Side.NONE,
            ts_recv=START + 60 * NS,
            levels=dbn.ConsolidatedBidAskPair(
                bid_px=1_000_000_000, ask_px=1_020_000_000, bid_sz=10, ask_sz=12
            ),
        ),
        dbn.CBBOMsg(
            rtype=dbn.RType.CBBO_1M,
            publisher_id=30,
            instrument_id=1_107_297_513,
            ts_event=START + 119 * NS,
            price=dbn.UNDEF_PRICE,
            size=0,
            side=dbn.Side.NONE,
            ts_recv=START + 120 * NS,
            levels=dbn.ConsolidatedBidAskPair(
                bid_px=dbn.UNDEF_PRICE, ask_px=1_030_000_000, bid_sz=0, ask_sz=5
            ),
        ),
    ]
    return _write(
        path,
        _metadata("OPRA.PILLAR", dbn.Schema.CBBO_1M, ["QQQ   250311C00483000"], [1_107_297_513]),
        recs,
    )
