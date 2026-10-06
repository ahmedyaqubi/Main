"""Full-history Databento fetch for M4 (QQQ underlying + QQQ options), cost-capped.

Phase `underlying`: EQUS.MINI ohlcv-1m and bbo-1m, one file per month.
Phase `options`:   OPRA.PILLAR cbbo-1m and definition, one file per session, for contracts
                   expiring at D+1 and D+2 with strikes in [0.95 * day low, 1.05 * day high]
                   (the day's own range from the downloaded bars; storage scope only).

Pricing is free and cached in data/raw/databento/history/price_cache.json, so it resumes.
Downloads skip files already present and stop after --max-minutes (re-run to continue).

    uv run python scripts/m4_fetch_history.py underlying            # price only
    uv run python scripts/m4_fetch_history.py underlying --download --max-usd 2
    uv run python scripts/m4_fetch_history.py options                 # price only (slow)
    uv run python scripts/m4_fetch_history.py options --download --max-usd 25 --max-minutes 100
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())  # see M2 open issue 6
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

import databento as db
import pandas as pd
from dotenv import load_dotenv

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import ET
from qqq1dte.ingestion.databento_fetch import (
    FetchRequest,
    PricedPlan,
    RetryPolicy,
    download,
    occ_symbol,
    option_symbols_for_day,
    price,
    strike_band,
)
from qqq1dte.validation.records import STRIKE_GRID_TOL

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "databento" / "history"
CACHE = OUT / "price_cache.json"
END = date(2026, 10, 2)  # last complete session at the time of the M4 pull
BAND_PAD = 0.05
EXPIRY_OFFSETS = (1, 2)
RETRY = RetryPolicy(retry_on=(db.BentoServerError,), tries=6, backoff_s=5.0)


def month_starts(start: date, end: date) -> list[date]:
    out, d = [], start.replace(day=1)
    while d <= end:
        out.append(d)
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def underlying_requests(start: date) -> list[FetchRequest]:
    reqs = []
    for m in month_starts(start, END):
        nxt = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
        s, e = max(m, start), min(nxt, END + timedelta(days=1))
        for schema in ("ohlcv-1m", "bbo-1m"):
            reqs.append(
                FetchRequest("EQUS.MINI", schema, s, e, ("QQQ",), "raw_symbol",
                             OUT / "EQUS.MINI" / schema / f"{m:%Y-%m}.dbn.zst")
            )  # fmt: skip
    return reqs


def daily_ranges() -> dict[date, tuple[float, float]]:
    """Per-ET-session low/high of QQQ from the downloaded 1-minute bars (all hours)."""
    lows: dict[date, float] = {}
    highs: dict[date, float] = {}
    for f in sorted((OUT / "EQUS.MINI" / "ohlcv-1m").glob("*.dbn.zst")):
        df = db.DBNStore.from_file(f).to_df()
        d = pd.DatetimeIndex(df.index).tz_convert(ET).date
        g = df.groupby(d)
        for day, lo in g["low"].min().items():
            assert isinstance(day, date)
            lows[day] = min(lows.get(day, float(lo)), float(lo))
        for day, hi in g["high"].max().items():
            assert isinstance(day, date)
            highs[day] = max(highs.get(day, float(hi)), float(hi))
    return {d: (lows[d], highs[d]) for d in lows}


def option_requests(cal: TradingCalendar, start: date) -> tuple[list[FetchRequest], list[date]]:
    sessions = cal.sessions(start, END + timedelta(days=10))
    ranges = daily_ranges()
    reqs, no_bars = [], []
    for day in (s for s in sessions if s <= END):
        if day not in ranges:
            no_bars.append(day)  # reported, never guessed
            continue
        lo, hi = ranges[day]
        syms = option_symbols_for_day(
            "QQQ", day, sessions, strike_band(lo, hi, BAND_PAD), EXPIRY_OFFSETS
        )
        for schema in ("cbbo-1m", "definition"):
            reqs.append(
                FetchRequest("OPRA.PILLAR", schema, day, day + timedelta(days=1), syms,
                             "raw_symbol", OUT / "OPRA.PILLAR" / schema / f"{day}.dbn.zst")
            )  # fmt: skip
    return reqs, no_bars


ADJ_DIAG = ROOT / "data" / "raw" / "databento" / "diag" / "definition_QQQ.OPT_2023-12-28.dbn.zst"


def adjusted_expirations() -> set[date]:
    """Expirations carrying OCC-adjusted strikes (ADR-0005), read from the full-chain
    definitions of 2023-12-28 (the day after OCC memo #53847 took effect)."""
    df = db.DBNStore.from_file(ADJ_DIAG).to_df()
    k = df["strike_price"].astype(float)
    off_grid = ((k / 0.5) - (k / 0.5).round()).abs() > STRIKE_GRID_TOL
    return set(df.loc[off_grid, "expiration"].dt.date)


def adjusted_option_requests(
    cal: TradingCalendar, start: date, reduction: float, ex_date: date
) -> list[FetchRequest]:
    """Supplemental requests: adjusted-strike symbols for sessions whose D+1/D+2 expiry was
    listed before the OCC adjustment (strike = round(K - reduction, 2), K on the $0.50 grid)."""
    adj_exps = adjusted_expirations()
    sessions = cal.sessions(start, END + timedelta(days=10))
    ranges = daily_ranges()
    reqs = []
    for i, day in enumerate(s for s in sessions if s <= END):
        if day < ex_date or day not in ranges:
            continue
        exps = [sessions[i + k] for k in EXPIRY_OFFSETS if sessions[i + k] in adj_exps]
        if not exps:
            continue
        lo, hi = ranges[day]
        grid = [
            x / 2 for x in range(int(lo * (1 - BAND_PAD) * 2), int(hi * (1 + BAND_PAD) * 2) + 2)
        ]
        strikes = sorted({round(k - reduction, 2) for k in grid})
        syms = tuple(occ_symbol("QQQ", e, r, k) for e in exps for r in "CP" for k in strikes)
        for j in range(0, len(syms), 1000):
            part = syms[j : j + 1000]
            for schema in ("cbbo-1m", "definition"):
                reqs.append(
                    FetchRequest(
                        "OPRA.PILLAR",
                        schema,
                        day,
                        day + timedelta(days=1),
                        part,
                        "raw_symbol",
                        OUT / "OPRA.PILLAR" / schema / f"{day}_adj{j // 1000}.dbn.zst",
                    )
                )
    return reqs


def load_cache() -> dict[str, float | None]:
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def priced_plan(client: db.Historical, reqs: list[FetchRequest]) -> PricedPlan:
    """Price with a resumable cache keyed by output path."""
    cache = load_cache()
    todo = [r for r in reqs if str(r.path) not in cache and not r.path.exists()]
    for i in range(0, len(todo), 25):
        batch = todo[i : i + 25]
        part = price(client, batch, unresolved_errors=(db.BentoClientError,), retry=RETRY)
        for r, c in zip(part.priced, part.costs, strict=True):
            cache[str(r.path)] = c
        for r in part.unresolved:
            cache[str(r.path)] = None
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, indent=0))
        print(f"priced {min(i + 25, len(todo))}/{len(todo)}", flush=True)
    plan = PricedPlan()
    for r in reqs:
        if r.path.exists():
            plan.already_present.append(r)
        elif cache.get(str(r.path)) is None:
            plan.unresolved.append(r)
        else:
            plan.priced.append(r)
            plan.costs.append(float(cache[str(r.path)]))  # type: ignore[arg-type]
    return plan


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["underlying", "options", "options-adjusted"])
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--max-usd", type=float, default=0.0)
    ap.add_argument("--max-minutes", type=float, default=100.0)
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    cfg = load_config()
    start = cfg.history.option_era_start
    client = db.Historical()

    if args.phase == "underlying":
        reqs, no_bars = underlying_requests(start), list[date]()
    elif args.phase == "options":
        reqs, no_bars = option_requests(TradingCalendar(cfg), start)
    else:
        adj = cfg.dq.strike_adjustments[0]
        reqs = adjusted_option_requests(TradingCalendar(cfg), start, adj.reduction, adj.ex_date)
        no_bars = []
    plan = priced_plan(client, reqs)

    by_schema: dict[str, float] = {}
    for r, c in zip(plan.priced, plan.costs, strict=True):
        by_schema[r.schema] = by_schema.get(r.schema, 0.0) + c
    for k, v in sorted(by_schema.items()):
        print(f"{args.phase} {k:<12} ${v:8.2f}")
    print(
        f"to download: {len(plan.priced)} files, ${plan.total_usd:.2f}; already present: "
        f"{len(plan.already_present)}; unresolved (no listed symbols): {len(plan.unresolved)}; "
        f"sessions without bars: {len(no_bars)}"
    )
    log = OUT / f"{args.phase}_unresolved.txt"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "".join(f"{r.schema}\t{r.start}\tno symbols resolved\n" for r in plan.unresolved)
        + "".join(f"bars\t{d}\tno underlying bars\n" for d in no_bars),
        encoding="utf-8",
    )

    if not args.download:
        return 0
    deadline = time.monotonic() + args.max_minutes * 60
    # Cap applies to the whole remaining plan, checked before the first byte is fetched.
    chunk = PricedPlan()
    for r, c in zip(plan.priced, plan.costs, strict=True):
        chunk.priced.append(r)
        chunk.costs.append(c)
    if chunk.total_usd > args.max_usd:
        print(
            f"remaining ${chunk.total_usd:.2f} exceeds cap ${args.max_usd:.2f}; nothing downloaded"
        )
        return 2
    done = 0
    for r, c in zip(chunk.priced, chunk.costs, strict=True):
        if time.monotonic() > deadline:
            print(f"time budget reached after {done} files; re-run to continue")
            return 3
        one = PricedPlan(priced=[r], costs=[c])
        download(client, one, max_usd=args.max_usd, retry=RETRY)
        done += 1
        if done % 20 == 0:
            print(f"downloaded {done}/{len(chunk.priced)}", flush=True)
    print(f"downloaded {done} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
