"""M19T Step 0 (ADR-0013 D0): download the short-premium data gap, owner-approved 2026-10-08 with a
hard cap of $20 for everything (X + A + H + E). If the exact total exceeds the cap, nothing more is
downloaded and the owner is asked again.

  X  QQQ daily bars 2020-01-02 -> 2023-03-27 (XNAS.ITCH ohlcv-1d; strike-band selection only)
  E  D2 extension: contracts expiring D and D+1, sessions 2020-01-02 -> 2023-03-27 (priced
     exactly once X is on disk; band from X's Nasdaq-venue range, storage scope only)
  A  expiry-day (0DTE) contracts, development sessions 2023-03-28 -> 2026-04-02
  H  the same for holdout sessions (storage only; locked by ADR-0011 / ADR-0013 D7)

Resumable: files already on disk are skipped; prices come from the M19T price cache.

    uv run python scripts/m19t_fetch.py
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import databento as db
import pandas as pd
from dotenv import load_dotenv

from m19t_price_gap import (
    BAND_PAD,
    DEV,
    EXT,
    HOLD,
    OUT,
    RETRY,
    ROOT,
    daily_ranges,
    priced,
    zero_dte,
)
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.ingestion.databento_fetch import (
    FetchRequest,
    PricedPlan,
    download,
    option_symbols_for_day,
    strike_band,
)

WORKERS = 6
CAP_USD = 20.0  # owner approval 2026-10-08: all items together, re-ask above this


def x_request() -> FetchRequest:
    return FetchRequest(
        "XNAS.ITCH",
        "ohlcv-1d",
        EXT[0],
        EXT[1] + timedelta(days=1),
        ("QQQ",),
        "raw_symbol",
        OUT / "XNAS.ITCH" / "ohlcv-1d" / "QQQ_2020-2023.dbn.zst",
    )


def ext_ranges(path: object) -> dict[date, tuple[float, float]]:
    df = db.DBNStore.from_file(path).to_df()  # type: ignore[arg-type]
    idx = pd.DatetimeIndex(df.index)
    return {
        d.date(): (float(lo), float(hi))
        for d, lo, hi in zip(idx, df["low"], df["high"], strict=True)
    }


def ext_requests(
    cal: TradingCalendar, ranges: dict[date, tuple[float, float]]
) -> tuple[list[FetchRequest], list[date]]:
    sessions = cal.sessions(EXT[0], EXT[1] + timedelta(days=10))
    reqs, missing = [], []
    for day in (s for s in sessions if s <= EXT[1]):
        if day not in ranges:
            missing.append(day)  # reported, never guessed
            continue
        syms = option_symbols_for_day(
            "QQQ", day, sessions, strike_band(*ranges[day], BAND_PAD), (0, 1)
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
                    OUT / "OPRA.PILLAR" / f"{schema}-ext" / f"{day}.dbn.zst",
                )
            )
    return reqs, missing


def plan_of(reqs: list[FetchRequest], costs: dict[str, float | None]) -> PricedPlan:
    """Requests not yet on disk with a resolved price (unresolved ones are reported)."""
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
    return plan


def main() -> int:
    load_dotenv(ROOT / ".env")
    cal = TradingCalendar(load_config())
    client = db.Historical()
    x = x_request()
    x_cost = priced(client, [x])
    download(client, plan_of([x], x_cost), max_usd=0.01, retry=RETRY)
    e_req, e_miss = ext_requests(cal, ext_ranges(x.path))
    ranges = daily_ranges()
    a_req, _ = zero_dte(cal, DEV, ranges)
    h_req, _ = zero_dte(cal, HOLD, ranges)
    costs = {**priced(client, a_req), **priced(client, h_req), **priced(client, e_req)}
    items = {"A": a_req, "H": h_req, "E": e_req}
    full = {k: sum(costs[str(r.path)] or 0.0 for r in v) for k, v in items.items()}
    total = sum(full.values()) + sum(v or 0.0 for v in x_cost.values())
    print(
        "exact prices: "
        + ", ".join(f"{k} ${v:.2f}" for k, v in full.items())
        + f"; total incl. X ${total:.2f} (cap ${CAP_USD:.2f}); E sessions without a daily "
        f"range: {len(e_miss)}",
        flush=True,
    )
    if total > CAP_USD:
        print("over the approved cap: nothing more downloaded, ask the owner")
        return 1
    unresolved = 0
    for k, reqs in items.items():
        plan = plan_of(reqs, costs)
        unresolved += len(plan.unresolved)
        print(f"{k}: downloading {len(plan.priced)} files (${plan.total_usd:.2f})", flush=True)
        singles = [
            PricedPlan(priced=[r], costs=[c]) for r, c in zip(plan.priced, plan.costs, strict=True)
        ]  # the total was checked against the cap above; files download in parallel
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            done = list(
                pool.map(lambda sp: download(client, sp, max_usd=CAP_USD, retry=RETRY), singles)
            )
        print(f"{k}: saved {sum(map(len, done))}; unresolved {len(plan.unresolved)}", flush=True)
    print(f"done; unresolved requests (no listed symbols) {unresolved}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
