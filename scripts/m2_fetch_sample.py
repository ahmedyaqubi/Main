"""M2 sample-week fetch from Databento (DATA_REQUIREMENTS.md §5).

Prices every request with metadata.get_cost first (free). Downloads only with --download, and
only if the total is under --max-usd. The API key is read from .env (DATABENTO_API_KEY) and is
never printed.

Usage:
    uv run python scripts/m2_fetch_sample.py              # cost only
    uv run python scripts/m2_fetch_sample.py --download   # cost, then fetch if under the cap
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from functools import partial
from pathlib import Path

import certifi

# Windows' certificate store on the dev machine holds an expired chain certificate; use
# certifi's bundle. Verification stays on.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

import databento as db
import exchange_calendars as xcals
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "databento" / "m2_sample"

WEEK = [date(2025, 3, 10) + timedelta(days=i) for i in range(5)]
# QQQ March 2025 monthly high/low (Yahoo Finance, read 2026-10-05). Used only to bound the strike
# list for this sample: strikes from 0.95*low to 1.05*high, wider than a daily ±5%.
MONTH_HIGH, MONTH_LOW = 513.04, 457.33
MAX_SYMBOLS_PER_REQUEST = 1000
EXPIRY_OFFSETS = (1, 2)  # contracts expiring at D+1 and D+2 sessions


@dataclass(frozen=True)
class Request:
    name: str
    dataset: str
    schema: str
    day: date
    symbols: tuple[str, ...]
    stype_in: str
    tag: str = ""

    @property
    def path(self) -> Path:
        suffix = f"_{self.tag}" if self.tag else ""
        return OUT / self.schema / f"{self.dataset}_{self.day.isoformat()}{suffix}.dbn.zst"


def occ_symbol(expiration: date, right: str, strike: float) -> str:
    return f"QQQ   {expiration:%y%m%d}{right}{round(strike * 1000):08d}"


def option_symbols(day: date, sessions: list[date]) -> tuple[str, ...]:
    i = sessions.index(day)
    strikes = range(math.floor(0.95 * MONTH_LOW), math.ceil(1.05 * MONTH_HIGH) + 1)
    return tuple(
        occ_symbol(sessions[i + k], right, k_strike)
        for k in EXPIRY_OFFSETS
        for right in "CP"
        for k_strike in strikes
    )


# Sessions before the sample week whose definitions show when the week's contracts first
# appeared (C5). Databento OPRA definitions leave `activation` empty, so first appearance in
# the daily definition files is the listing-date evidence.
LOOKBACK_START, LOOKBACK_END = "2025-02-24", "2025-03-07"


def atm_tick_symbols(day: date, sessions: list[date]) -> tuple[str, ...]:
    """The D+1 ATM ± 5 contracts that C3/C8 compare; needs that day's bars and definitions."""
    import m2_sample_check as chk  # noqa: PLC0415 (only needed for --tick-atm-only)

    expiry = sessions[sessions.index(day) + 1]
    defs = chk.load_df("definition", "OPRA.PILLAR", day)
    chosen = chk.atm_contracts(day, expiry, defs, chk.rth_open_price(day))
    return tuple(sorted(chosen["raw_symbol"]))


def build_requests(
    skip: set[str], tick_atm_only: bool = False, days: set[date] | None = None
) -> list[Request]:
    cal = xcals.get_calendar("XNYS")
    sessions = [s.date() for s in cal.sessions_in_range("2025-02-24", "2025-03-21")]
    reqs: list[Request] = []
    week_symbols = sorted({s for d in WEEK for s in option_symbols(d, sessions)})
    for d in (s.date() for s in cal.sessions_in_range(LOOKBACK_START, LOOKBACK_END)):
        for j, chunk in enumerate(_chunks(tuple(week_symbols))):
            reqs.append(
                Request(
                    "QQQ options definition (lookback)",
                    "OPRA.PILLAR",
                    "definition",
                    d,
                    tuple(chunk),
                    "raw_symbol",
                    tag=f"lookback{j}",
                )
            )
    for d in WEEK:
        if days is not None and d not in days:
            continue
        syms = option_symbols(d, sessions)
        for schema in ("cmbp-1", "cbbo-1m", "definition", "statistics"):
            if schema in skip:
                continue
            if schema == "cmbp-1" and tick_atm_only:
                # Only the contracts C3/C8 use; full-band tick data is a "Later" item.
                reqs.append(
                    Request(
                        "QQQ options cmbp-1 (ATM)",
                        "OPRA.PILLAR",
                        schema,
                        d,
                        atm_tick_symbols(d, sessions),
                        "raw_symbol",
                        tag="atm",
                    )
                )
                continue
            reqs.append(
                Request(f"QQQ options {schema}", "OPRA.PILLAR", schema, d, syms, "raw_symbol")
            )
        for schema in ("ohlcv-1m", "bbo-1m"):
            if schema in skip:
                continue
            reqs.append(
                Request(f"QQQ stock {schema}", "EQUS.MINI", schema, d, ("QQQ",), "raw_symbol")
            )
    return reqs


RETRIES = 6


def with_retry[T](call: Callable[[], T], what: str) -> T:
    """Retry transient Databento server errors (e.g. 504 gateway timeouts) with backoff."""
    for attempt in range(RETRIES):
        try:
            return call()
        except db.BentoServerError as e:
            wait = 5 * 2**attempt
            print(
                f"server error on {what} ({e.http_status}); "
                f"retry {attempt + 1}/{RETRIES} in {wait}s"
            )
            time.sleep(wait)
    return call()  # final attempt: let the error propagate


def _chunks(symbols: tuple[str, ...], n: int = MAX_SYMBOLS_PER_REQUEST) -> list[list[str]]:
    return [list(symbols[i : i + n]) for i in range(0, len(symbols), n)]


def main() -> int:  # noqa: PLR0915 (linear CLI script)
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--max-usd", type=float, default=20.0)
    parser.add_argument("--skip-schemas", nargs="*", default=[], help="e.g. cmbp-1")
    parser.add_argument(
        "--tick-atm-only",
        action="store_true",
        help="cmbp-1 only for the D+1 ATM ± 5 contracts used by C3/C8",
    )
    parser.add_argument("--days", nargs="*", type=date.fromisoformat, help="restrict sample days")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    if not os.environ.get("DATABENTO_API_KEY"):
        print("DATABENTO_API_KEY not set (expected in .env)")
        return 1
    client = db.Historical()
    days = set(args.days) if args.days else None
    reqs = build_requests(set(args.skip_schemas), args.tick_atm_only, days)
    if days is not None:  # lookback definitions are not day-specific to the sample; keep them
        reqs = [r for r in reqs if r.day in days or r.tag.startswith("lookback")]

    total = 0.0
    by_name: dict[str, float] = {}
    unresolved: list[Request] = []
    priced: list[Request] = []
    already = [r for r in reqs if r.path.exists()]
    for r in reqs:
        if r.path.exists():
            continue  # already downloaded: not re-priced, not re-fetched
        start, end = r.day.isoformat(), (r.day + timedelta(days=1)).isoformat()
        try:
            cost = with_retry(
                partial(
                    client.metadata.get_cost,
                    dataset=r.dataset,
                    schema=r.schema,
                    stype_in=r.stype_in,
                    symbols=list(r.symbols),
                    start=start,
                    end=end,
                ),
                f"get_cost {r.schema} {r.day}",
            )
        except db.BentoClientError as e:
            if "symbology_invalid_request" not in str(e):
                raise
            unresolved.append(r)  # none of the symbols existed that day: listing evidence
            continue
        priced.append(r)
        by_name[r.name] = by_name.get(r.name, 0.0) + cost
        total += cost
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "unresolved_requests.txt").write_text(
        "".join(f"{r.schema}\t{r.day}\t{r.tag}\tno symbols resolved\n" for r in unresolved),
        encoding="utf-8",
    )
    print(f"{len(already)} files already downloaded (not priced)")
    print(f"{len(unresolved)} requests had no resolvable symbols (logged)")
    for name, cost in by_name.items():
        print(f"{name:<28} ${cost:8.2f}")
    print(f"{'TOTAL (new data only)':<28} ${total:8.2f}  (cap ${args.max_usd:.2f})")

    if not args.download:
        return 0
    if total > args.max_usd:
        print("Total exceeds cap; nothing downloaded.")
        return 2
    for r in priced:
        r.path.parent.mkdir(parents=True, exist_ok=True)
        start, end = r.day.isoformat(), (r.day + timedelta(days=1)).isoformat()
        if len(r.symbols) > MAX_SYMBOLS_PER_REQUEST:
            raise ValueError(f"split requests to <= 1000 symbols: {r}")
        # Write to a temporary name and rename only when complete, so an interrupted
        # download can never be mistaken for a full file.
        tmp = r.path.with_name(r.path.name + ".partial")
        if tmp.exists():  # leftover from an interrupted run: incomplete by construction
            print(f"removing stale {tmp.relative_to(ROOT)}")
            tmp.unlink()
        with_retry(
            partial(
                client.timeseries.get_range,
                dataset=r.dataset,
                schema=r.schema,
                stype_in=r.stype_in,
                symbols=list(r.symbols),
                start=start,
                end=end,
                path=tmp,
            ),
            f"get_range {r.schema} {r.day}",
        )
        tmp.replace(r.path)
        print(f"saved {r.path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
