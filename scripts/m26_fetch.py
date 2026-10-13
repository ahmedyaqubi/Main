"""M26 (ADR-0017 D2): fetch Tiingo SPY daily prices from 1993 and FRED DTB3 (both free), stored
unchanged under `study_tom.raw_dir`, each with a `.meta.json` (source URL, fetch time). The token
comes from TIINGO_API_KEY in .env and is sent in a header only. Nothing is analysed here; every
loader applies the holdout lock.

    uv run python scripts/m26_fetch.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from m25_fetch import TIMEOUT, save
from qqq1dte.core.config import load_config
from qqq1dte.ingestion.etf_data import FRED_URL, TIINGO_URL

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    load_dotenv(ROOT / ".env")
    s = load_config().study_tom
    out = ROOT / s.raw_dir
    token = os.environ.get("TIINGO_API_KEY")
    if not token:
        print("TIINGO_API_KEY is not set in .env")
        return 1
    url = TIINGO_URL.format(ticker=s.ticker.lower(), start=s.data_start, end=s.holdout_end)
    r = requests.get(url, headers={"Authorization": f"Token {token}"}, timeout=TIMEOUT)
    if r.status_code != 200:  # noqa: PLR2004
        print(f"Tiingo {s.ticker}: HTTP {r.status_code}")
        return 1
    save(out / "tiingo" / f"{s.ticker}.json", r.content, url)
    print(f"Tiingo {s.ticker}: {len(r.json())} rows", flush=True)
    url = FRED_URL.format(series=s.fred_series)
    r = requests.get(url, timeout=TIMEOUT)
    if r.status_code != 200:  # noqa: PLR2004
        print(f"FRED: HTTP {r.status_code}")
        return 1
    save(out / "fred" / f"{s.fred_series}.csv", r.content, url)
    print(f"FRED {s.fred_series}: {r.text.count(chr(10))} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
