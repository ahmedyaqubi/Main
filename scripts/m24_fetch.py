"""M24 (ADR-0015): download the fill-feasibility Scope A trade prints. The owner pre-approved
up to $30 on 2026-10-10 (exact quote $28.510015). The requests are exactly those of
`scripts/m24_price_fill_study.py`. Files on disk are skipped (resumable). The priced total of
the remaining requests must be within `--max-usd`, or nothing is downloaded.

    uv run python scripts/m24_fetch.py --max-usd 30
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor

import databento as db
import polars as pl
from dotenv import load_dotenv

import m24_price_fill_study as q
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.ingestion.databento_fetch import FetchRequest, PricedPlan, download, price

WORKERS = 6


def scope_requests(cal: TradingCalendar) -> list[FetchRequest]:
    days = q.sample_sessions(cal)
    closes = q.prev_closes()
    defs = q.definitions(cal)
    reqs: list[FetchRequest] = []
    for d in days:
        c = closes[max(x for x in closes if x < d)]
        exps = {d, cal.next_session(d), cal.next_session(cal.next_session(d))}
        sub = defs.filter(
            (pl.col("session_date") == d)
            & pl.col("expiration").is_in(list(exps))
            & pl.col("strike").is_between(c * (1 - q.BAND), c * (1 + q.BAND))
        )
        reqs += q.requests_for(d, sorted(set(sub["raw_symbol"].to_list())), cal)
    return reqs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-usd", type=float, required=True)
    args = ap.parse_args()
    load_dotenv(q.ROOT / ".env")
    cal = TradingCalendar(load_config())
    client = db.Historical()
    plan = price(client, scope_requests(cal), unresolved_errors=(db.BentoClientError,),
                 retry=q.RETRY)  # fmt: skip
    print(
        f"to download {len(plan.priced)} files, ${plan.total_usd:.6f}; "
        f"on disk {len(plan.already_present)}; unresolved {len(plan.unresolved)}",
        flush=True,
    )
    if plan.total_usd > args.max_usd:
        print("over the approved amount: nothing downloaded, ask the owner")
        return 1
    singles = [
        PricedPlan(priced=[r], costs=[c]) for r, c in zip(plan.priced, plan.costs, strict=True)
    ]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        saved = list(pool.map(lambda sp: download(client, sp, max_usd=args.max_usd, retry=q.RETRY),
                              singles))  # fmt: skip
    print(f"saved {sum(map(len, saved))} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
