"""M19T Step 0 (ADR-0013 D0): price the data gap for the short-premium family. PRICE ONLY:
this script never downloads (Databento `metadata.get_cost` is free); purchases need the owner's
approval and a separate run.

Line items:
  A  expiry-day (0DTE) contracts, development sessions 2023-03-28 -> 2026-04-02: OPRA.PILLAR
     cbbo-1m + definition for contracts expiring on D, strikes in the M4 band (D's own range)
  H  the same for holdout sessions 2026-04-03 -> 2026-10-02 (optional; storage only, the holdout
     stays locked by ADR-0011 until D7 allows an access)
  X  QQQ daily bars 2020-01-02 -> 2023-03-27 (XNAS.ITCH ohlcv-1d): needed only to choose which
     strikes to download for the D2 extension
  E  the D2 extension options (contracts expiring D and D+1): ROUGH estimate only until X is
     downloaded (the band needs the daily range)
  F  forward collection per month: recent M4 option and underlying costs (price cache) plus A's
     recent 0DTE cost

    uv run python scripts/m19t_price_gap.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

import databento as db
import pandas as pd
from dotenv import load_dotenv

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import ET
from qqq1dte.ingestion.databento_fetch import (
    FetchRequest,
    RetryPolicy,
    option_symbols_for_day,
    price,
    strike_band,
)

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "data" / "raw" / "databento" / "history"
OUT = ROOT / "data" / "raw" / "databento" / "m19t"
CACHE = OUT / "price_cache.json"
M4_CACHE = HIST / "price_cache.json"
BAND_PAD = 0.05  # as M4
DEV = (date(2023, 3, 28), date(2026, 4, 2))
HOLD = (date(2026, 4, 3), date(2026, 10, 2))
EXT = (date(2020, 1, 2), date(2023, 3, 27))
RETRY = RetryPolicy(retry_on=(db.BentoServerError,), tries=6, backoff_s=5.0)


def daily_ranges() -> dict[date, tuple[float, float]]:
    """QQQ low/high per ET session from the M4 EQUS.MINI 1-minute bars on disk."""
    lows: dict[date, float] = {}
    highs: dict[date, float] = {}
    for f in sorted((HIST / "EQUS.MINI" / "ohlcv-1m").glob("*.dbn.zst")):
        df = db.DBNStore.from_file(f).to_df()
        g = df.groupby(pd.DatetimeIndex(df.index).tz_convert(ET).date)
        for day, lo in g["low"].min().items():
            lows[day] = min(lows.get(day, float(lo)), float(lo))  # type: ignore[index, call-overload]
        for day, hi in g["high"].max().items():
            highs[day] = max(highs.get(day, float(hi)), float(hi))  # type: ignore[index, call-overload]
    return {d: (lows[d], highs[d]) for d in lows}


def zero_dte(
    cal: TradingCalendar, span: tuple[date, date], ranges: dict[date, tuple[float, float]]
) -> tuple[list[FetchRequest], list[date]]:
    sessions = cal.sessions(span[0], span[1] + timedelta(days=10))
    reqs, missing = [], []
    for day in (s for s in sessions if s <= span[1]):
        if day not in ranges:
            missing.append(day)  # reported, never guessed
            continue
        syms = option_symbols_for_day(
            "QQQ", day, sessions, strike_band(*ranges[day], BAND_PAD), (0,)
        )
        for schema in ("cbbo-1m", "definition"):
            reqs.append(
                FetchRequest(
                    "OPRA.PILLAR",
                    schema,
                    day,
                    day + timedelta(days=1),
                    syms,
                    "raw_symbol",
                    OUT / "OPRA.PILLAR" / f"{schema}-0dte" / f"{day}.dbn.zst",
                )
            )
    return reqs, missing


def priced(client: db.Historical, reqs: list[FetchRequest]) -> dict[str, float | None]:
    """{path: usd}, resuming from the cache; unresolved requests are reported as None."""
    cache: dict[str, float | None] = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [r for r in reqs if str(r.path) not in cache]
    for i in range(0, len(todo), 50):
        chunk = todo[i : i + 50]
        plan = price(client, chunk, unresolved_errors=(db.BentoClientError,), retry=RETRY)
        for r, c in zip(plan.priced, plan.costs, strict=True):
            cache[str(r.path)] = float(c)
        for r in plan.unresolved:
            cache[str(r.path)] = None
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, indent=0))
        print(f"priced {min(i + 50, len(todo))}/{len(todo)}", flush=True)
    return {str(r.path): cache[str(r.path)] for r in reqs}


def total(costs: dict[str, float | None]) -> tuple[float, int]:
    vals = [v for v in costs.values() if v is not None]
    return float(sum(vals)), sum(v is None for v in costs.values())


def main() -> int:
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    cal = TradingCalendar(cfg)
    client = db.Historical()
    ranges = daily_ranges()
    a_req, a_miss = zero_dte(cal, DEV, ranges)
    h_req, _ = zero_dte(cal, HOLD, ranges)
    a, h = priced(client, a_req), priced(client, h_req)
    (a_usd, a_unres), (h_usd, h_unres) = total(a), total(h)
    x = FetchRequest(
        "XNAS.ITCH",
        "ohlcv-1d",
        EXT[0],
        EXT[1] + timedelta(days=1),
        ("QQQ",),
        "raw_symbol",
        OUT / "XNAS.ITCH" / "ohlcv-1d" / "QQQ_2020-2023.dbn.zst",
    )
    x_usd = total(priced(client, [x]))[0]

    # E (rough): per-session 0DTE cost in the first year of A, x 2 expiries, x extension sessions
    first_year = [
        v for r in a_req if r.start < date(2024, 3, 28) and (v := a[str(r.path)]) is not None
    ]
    n_a_sessions = len({r.start for r in a_req if r.start < date(2024, 3, 28)})
    per_session = sum(first_year) / max(n_a_sessions, 1)
    n_ext = len(cal.sessions(*EXT))
    e_rough = per_session * 2 * n_ext

    # F: forward month = last 21 dev sessions of M4 options (D+1, D+2) + EQUS.MINI month + 0DTE
    m4 = json.loads(M4_CACHE.read_text())
    recent = cal.sessions(date(2026, 9, 1), date(2026, 9, 30))
    m4_opts = sum(
        v
        for k, v in m4.items()
        if "OPRA.PILLAR" in k and v and any(f"{d}.dbn" in k for d in recent)
    )
    m4_und = sum(v for k, v in m4.items() if "EQUS.MINI" in k and "2026-09" in k and v)
    h_recent = sum(v for r in h_req if r.start in recent and (v := h[str(r.path)]) is not None)
    m4_total = sum(v for v in m4.values() if v)

    lines = [
        "# M19T Step 0: data-gap price quote (ADR-0013 D0) - price only, nothing downloaded",
        "",
        f"Databento metadata.get_cost, {datetime.now(UTC):%Y-%m-%d}. Retail usage-based rates; "
        "M4's whole "
        f"history purchase was priced at ${m4_total:,.2f} (reference).",
        "",
        "| item | scope | sessions | priced USD | unresolved requests | note |",
        "|---|---|---|---|---|---|",
        f"| A | 0DTE contracts, dev {DEV[0]} -> {DEV[1]} | {len(a_req) // 2} | {a_usd:,.2f} "
        f"| {a_unres} | missing daily range: {len(a_miss)} |",
        f"| H | 0DTE contracts, holdout {HOLD[0]} -> {HOLD[1]} (optional) | {len(h_req) // 2} "
        f"| {h_usd:,.2f} | {h_unres} | storage only; access per ADR-0011 / ADR-0013 D7 |",
        f"| X | QQQ daily bars {EXT[0]} -> {EXT[1]} (XNAS.ITCH) | {n_ext} | {x_usd:,.4f} | - "
        "| strike-band selection only |",
        f"| E | D2 extension options (expiring D and D+1) | {n_ext} | ~{e_rough:,.0f} (ROUGH) | - "
        "| exact quote needs X first; per-session cost and quote volume pre-2023 may differ |",
        f"| F | forward collection, per month (Sept 2026 as proxy) | {len(recent)} "
        f"| {m4_opts + m4_und + h_recent:,.2f} | - | options D+1/D+2 {m4_opts:,.2f} + "
        f"underlying {m4_und:,.2f} + 0DTE {h_recent:,.2f}; excludes cross-asset feeds |",
    ]
    rep = ROOT / "reports" / "research" / "m19t_price_quote.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
