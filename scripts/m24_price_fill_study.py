"""M24 (ADR-0015, docs/ROADMAP.md): exact free price quote for the fill-feasibility study,
Scope A. PRICE ONLY: `metadata.get_cost` is free; nothing is downloaded.

Scope A:
- **Contracts:** QQQ options expiring on D, next_session(D) or the session after (0-2 DTE),
  with strikes within +-3% of the previous session's close. They are taken from the definitions
  already on disk (M4 for D+1/D+2, M19T for 0DTE), so a 1-minute mid exists for every contract.
- **Sessions:** 20 development sessions (2023-03-28 -> 2026-04-02), with a stride coprime with
  5. The QQQ holdout (after 2026-04-02) is never touched.
- **Data:** OPRA `trades` in two print windows: 09:55-10:50 ET and 15:25-16:00 ET (12:25-13:00
  on early closes). Order times are 09:55-10:35 and 15:25-15:45, plus up to 15 min for fills.

    uv run python scripts/m24_price_fill_study.py
"""

from __future__ import annotations

import math
import os
import sys
from datetime import UTC, date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

import databento as db
import polars as pl
import requests
from dotenv import load_dotenv

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.ingestion.databento_fetch import (
    MAX_SYMBOLS_PER_REQUEST,
    FetchRequest,
    RetryPolicy,
    price,
)
from qqq1dte.validation.records import build_definitions

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
OUT = ROOT / "data" / "raw" / "databento" / "m24"
DEV = (date(2023, 3, 29), date(2026, 4, 2))  # first session with a previous QQQ close on disk
N_SESSIONS = 20
BAND = 0.03
WINDOWS = [(time(9, 55), time(10, 50)), (time(15, 25), time(16, 0))]
EARLY_CLOSE_WINDOW = (time(12, 25), time(13, 0))
RETRY = RetryPolicy(
    retry_on=(db.BentoServerError, requests.exceptions.ConnectionError), tries=6, backoff_s=5.0
)


def sample_sessions(cal: TradingCalendar) -> list[date]:
    sessions = [d for d in cal.sessions(*DEV) if cal.exclusion_reason(d) is None]
    stride = len(sessions) // N_SESSIONS
    stride += stride % 5 == 0
    return sessions[::stride][:N_SESSIONS]


def prev_closes() -> dict[date, float]:
    bars = pl.read_parquet(
        ROOT / "data" / "clean" / "cleaned" / "cleaned_market_data" / "ohlcv-1m" / "QQQ.parquet"
    ).filter(pl.col("is_rth"))
    last = bars.sort("ts").group_by("session_date").last()
    return dict(zip(last["session_date"].to_list(), last["close"].to_list(), strict=True))


def definitions(cal: TradingCalendar) -> pl.DataFrame:
    m4 = pl.concat(
        [
            pl.read_parquet(p)
            for p in (ROOT / "data/raw/parquet/OPRA.PILLAR/definition").rglob("*.parquet")
        ],
        how="diagonal_relaxed",
    )
    d0 = pl.read_parquet(ROOT / "data/clean/m19t/definitions/0dte.parquet")
    return pl.concat(
        [build_definitions(m4, cal).drop("first_seen"), d0.drop("first_seen")],
        how="diagonal_relaxed",
    ).select("session_date", "raw_symbol", "expiration", "strike")


def requests_for(d: date, syms: list[str], cal: TradingCalendar) -> list[FetchRequest]:
    wins = [EARLY_CLOSE_WINDOW] if cal.is_early_close(d) else WINDOWS
    out = []
    for w, (a, b) in enumerate(wins):
        s = datetime.combine(d, a, ET).astimezone(UTC)
        e = datetime.combine(d, b, ET).astimezone(UTC)
        for j in range(0, len(syms), MAX_SYMBOLS_PER_REQUEST):
            out.append(
                FetchRequest(
                    "OPRA.PILLAR", "trades", s, e, tuple(syms[j : j + MAX_SYMBOLS_PER_REQUEST]),
                    "raw_symbol",
                    OUT / "trades" / f"{d}_w{w}_{j // MAX_SYMBOLS_PER_REQUEST}.dbn.zst",
                )
            )  # fmt: skip
    return out


def main() -> int:
    load_dotenv(ROOT / ".env")
    cal = TradingCalendar(load_config())
    days = sample_sessions(cal)
    closes = prev_closes()
    defs = definitions(cal)
    client = db.Historical()
    total = 0.0
    n_syms = []
    for d in days:
        prev = max(x for x in closes if x < d)
        c = closes[prev]
        exps = {d, cal.next_session(d), cal.next_session(cal.next_session(d))}
        sub = defs.filter(
            (pl.col("session_date") == d)
            & pl.col("expiration").is_in(list(exps))
            & pl.col("strike").is_between(c * (1 - BAND), c * (1 + BAND))
        )
        syms = sorted(set(sub["raw_symbol"].to_list()))
        n_syms.append(len(syms))
        plan = price(client, requests_for(d, syms, cal), unresolved_errors=(db.BentoClientError,),
                     retry=RETRY)  # fmt: skip
        total += plan.total_usd
        print(
            f"{d}: {len(syms)} contracts, ${plan.total_usd:.4f}, unresolved {len(plan.unresolved)}",
            flush=True,
        )
    print(
        f"EXACT Scope A: {len(days)} sessions {days[0]}..{days[-1]}, contracts/session median "
        f"{sorted(n_syms)[len(n_syms) // 2]}; total ${total:.6f}; approve up to "
        f"${math.ceil(total * 100) / 100:.2f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
