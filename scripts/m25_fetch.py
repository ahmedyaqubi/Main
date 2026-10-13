"""M25 (ADR-0016 D2): fetch the free ETF data, stored unchanged under
`study_etf_trend.raw_dir`, each file next to a `.meta.json` with its source URL and fetch time:
- Tiingo daily prices for each ticker (data_start -> holdout_end). The token comes from
  TIINGO_API_KEY in .env and is sent in a header, never in the URL or the saved metadata.
- FRED DTB3 (3-month T-bill rate), CSV.
- Stooq daily CSV per ticker, for the development-only cross-check.

Nothing is read or analysed here, so the holdout lock is applied by every loader (ADR-0016 D3).

    uv run python scripts/m25_fetch.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from qqq1dte.core.config import load_config
from qqq1dte.ingestion.etf_data import FRED_URL, STOOQ_URL, TIINGO_URL

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 60


def save(path: Path, content: bytes, url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    meta = {"source_url": url, "fetched_at": datetime.now(UTC).isoformat(), "bytes": len(content)}
    path.with_suffix(path.suffix + ".meta.json").write_text(json.dumps(meta, indent=1), "utf-8")


def main() -> int:
    load_dotenv(ROOT / ".env")
    s = load_config().study_etf_trend
    out = ROOT / s.raw_dir
    token = os.environ.get("TIINGO_API_KEY")
    if not token:
        print("TIINGO_API_KEY is not set in .env")
        return 1
    problems = []
    for t in s.tickers:
        url = TIINGO_URL.format(ticker=t.lower(), start=s.data_start, end=s.holdout_end)
        r = requests.get(url, headers={"Authorization": f"Token {token}"}, timeout=TIMEOUT)
        if r.status_code != 200:  # noqa: PLR2004
            problems.append(f"Tiingo {t}: HTTP {r.status_code}")
            continue
        save(out / "tiingo" / f"{t}.json", r.content, url)
        print(f"Tiingo {t}: {len(r.json())} rows", flush=True)
    url = FRED_URL.format(series=s.fred_series)
    r = requests.get(url, timeout=TIMEOUT)
    if r.status_code == 200:  # noqa: PLR2004
        save(out / "fred" / f"{s.fred_series}.csv", r.content, url)
        print(f"FRED {s.fred_series}: {r.text.count(chr(10))} lines", flush=True)
    else:
        problems.append(f"FRED: HTTP {r.status_code}")
    for t in s.tickers:
        url = STOOQ_URL.format(ticker=t.lower())
        r = requests.get(url, timeout=TIMEOUT)
        ok = r.status_code == 200 and r.text.startswith("Date")  # noqa: PLR2004
        if not ok:
            problems.append(f"Stooq {t}: HTTP {r.status_code}, starts {r.text[:40]!r}")
            continue
        save(out / "stooq" / f"{t}.csv", r.content, url)
        print(f"Stooq {t}: {r.text.count(chr(10))} lines", flush=True)
    print("problems: " + ("; ".join(problems) if problems else "none"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
