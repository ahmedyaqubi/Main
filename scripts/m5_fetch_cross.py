"""M5 cross-market fetch (ADR-0004 option A): ETF/stock 1-minute bars or BBO from EQUS.MINI.

SPY, SOXX, NVDA, AMD, AVGO, TSM (MASTER_PROMPT list), UUP (dollar proxy for DX), IEF / SHY
(10Y / 2Y rate proxies). One file per symbol-month; priced first, capped, atomic, resumable.

    uv run python scripts/m5_fetch_cross.py                       # price only
    uv run python scripts/m5_fetch_cross.py --download --max-usd 3
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())  # M2 open issue 6
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

import databento as db
from dotenv import load_dotenv

from qqq1dte.core.config import load_config
from qqq1dte.ingestion.databento_fetch import FetchRequest, RetryPolicy, download, price

ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "data" / "raw" / "databento" / "history" / "EQUS.MINI"
END = date(2026, 10, 2)
SYMBOLS = ("SPY", "SOXX", "NVDA", "AMD", "AVGO", "TSM", "UUP", "IEF", "SHY")
RETRY = RetryPolicy(retry_on=(db.BentoServerError,), tries=6, backoff_s=5.0)


def requests(
    start: date, symbols: tuple[str, ...] = SYMBOLS, schema: str = "ohlcv-1m"
) -> list[FetchRequest]:
    reqs = []
    m = start.replace(day=1)
    while m <= END:
        nxt = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
        s, e = max(m, start), min(nxt, END + timedelta(days=1))
        for sym in symbols:
            reqs.append(
                FetchRequest(
                    "EQUS.MINI",
                    schema,
                    s,
                    e,
                    (sym,),
                    "raw_symbol",
                    OUT_ROOT / f"{schema}-cross" / f"{sym}_{m:%Y-%m}.dbn.zst",
                )
            )
        m = nxt
    return reqs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--max-usd", type=float, default=0.0)
    ap.add_argument("--symbols", nargs="*", default=list(SYMBOLS), help="subset (parallel runs)")
    ap.add_argument("--schema", default="ohlcv-1m", choices=["ohlcv-1m", "bbo-1m"])
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    client = db.Historical()
    plan = price(
        client,
        requests(load_config().history.option_era_start, tuple(args.symbols), args.schema),
        unresolved_errors=(db.BentoClientError,),
        retry=RETRY,
    )
    print(
        f"to download: {len(plan.priced)} files, ${plan.total_usd:.2f}; already present: "
        f"{len(plan.already_present)}; unresolved: {len(plan.unresolved)}"
    )
    for r in plan.unresolved:
        print(f"  unresolved: {r.symbols[0]} {r.start}")
    if args.download:
        saved = download(client, plan, max_usd=args.max_usd, retry=RETRY)
        print(f"downloaded {len(saved)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
