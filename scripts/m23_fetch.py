"""M23 Step 0 (ADR-0014 R1-R9): exact price and, only after the owner approves that exact amount,
the download of the SPX data scope (`scripts/m23_price_gap.py` defines it). R8 cap $50.

Every session 2013-04-01 -> 2026-10-02 (the last 12 months are holdout storage only):
definitions plus entry/exit cbbo-1m windows for the symbols in scope. Prices are cached
(`price_cache.json`), so a rerun resumes. Files already on disk are skipped.

    uv run python scripts/m23_fetch.py                                # exact price only
    uv run python scripts/m23_fetch.py --download --max-usd <approved>
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import databento as db
import polars as pl
from dotenv import load_dotenv

import m23_price_gap as gap
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.ingestion.databento_fetch import FetchRequest, PricedPlan, download, price

WORKERS = 6
CACHE = gap.OUT / "price_cache.json"


def all_requests(cal: TradingCalendar, client: db.Historical) -> list[FetchRequest]:
    start, last = date.fromisoformat(gap.S0["start"]), date.fromisoformat(gap.S0["last_session"])
    sessions = cal.sessions(start, last)
    sset = set(cal.sessions(start, last + timedelta(days=60)))
    closes = gap.spx_closes()
    uni = gap.universe(client, start, last + timedelta(days=1))
    entries = {}
    held: dict[date, set[str]] = defaultdict(set)
    for d in sessions:
        prev = max(x for x in closes if x < d)
        entries[d] = gap.entry_scope(uni, d, closes[prev], sset)
        for e, f in entries[d].values():
            held[e] |= set(f["raw_symbol"].to_list())
    reqs: list[FetchRequest] = []
    for i, d in enumerate(sessions):
        ent = [s for _, f in entries[d].values() for s in f["raw_symbol"].to_list()]
        live = set(uni.filter((pl.col("d0") <= d) & (pl.col("d1") > d))["raw_symbol"].to_list())
        ext = sorted(held.get(cal.next_session(d), set()) & live)
        reqs += gap.requests_for(d, ent, ext, cal)
        if i % 500 == 0:
            print(f"requests {i}/{len(sessions)}", flush=True)
    return reqs


def priced_all(client: db.Historical, reqs: list[FetchRequest]) -> dict[str, float | None]:
    cache: dict[str, float | None] = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [r for r in reqs if str(r.path) not in cache]
    chunks = [todo[i : i + 25] for i in range(0, len(todo), 25)]

    def run(chunk: list[FetchRequest]) -> PricedPlan:
        return price(client, chunk, unresolved_errors=(db.BentoClientError,), retry=gap.RETRY)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for k, plan in enumerate(pool.map(run, chunks), 1):
            for r, c in zip(plan.priced, plan.costs, strict=True):
                cache[str(r.path)] = c
            for r in plan.unresolved:
                cache[str(r.path)] = None
            if k % 20 == 0:
                CACHE.write_text(json.dumps(cache))
                print(f"priced {k * 25}/{len(todo)}", flush=True)
    CACHE.write_text(json.dumps(cache))
    return {str(r.path): cache[str(r.path)] for r in reqs}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--max-usd", type=float, default=0.0)
    args = ap.parse_args()
    load_dotenv(gap.ROOT / ".env")
    gap.U.update(gap.UNDERLYINGS["spx"])
    cal = TradingCalendar(load_config())
    client = db.Historical()
    reqs = all_requests(cal, client)
    costs = priced_all(client, reqs)
    plan = PricedPlan()
    for r in reqs:
        c = costs[str(r.path)]
        if r.path.exists():
            plan.already_present.append(r)
        elif c is None:
            plan.unresolved.append(r)
        else:
            plan.priced.append(r)
            plan.costs.append(c)
    by: dict[str, float] = defaultdict(float)
    for r, c in zip(plan.priced, plan.costs, strict=True):
        by[r.path.parent.name] += c
    print(
        f"EXACT: {len(reqs)} requests, to download {len(plan.priced)} (${plan.total_usd:.6f}; "
        f"approve up to ${math.ceil(plan.total_usd * 100) / 100:.2f}: "
        + ", ".join(f"{k} ${v:.2f}" for k, v in sorted(by.items()))
        + f"), on disk {len(plan.already_present)}, unresolved {len(plan.unresolved)}; "
        f"cap ${gap.S0['cap_usd']:.0f}",
        flush=True,
    )
    if not args.download:
        return 0
    if plan.total_usd > min(args.max_usd, float(gap.S0["cap_usd"])):
        print("over the approved amount: nothing downloaded, ask the owner")
        return 1
    singles = [
        PricedPlan(priced=[r], costs=[c]) for r, c in zip(plan.priced, plan.costs, strict=True)
    ]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        saved = list(
            pool.map(
                lambda sp: download(client, sp, max_usd=args.max_usd, retry=gap.RETRY), singles
            )
        )
    print(f"saved {sum(map(len, saved))} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
