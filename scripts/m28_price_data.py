"""M28 step 5 (ADR-0021 D1, D2, D7): price the data for SPY, IWM, NVDA, TSLA and AAPL to the
cent. PRICE ONLY: no market data is downloaded. Databento `metadata.get_cost` and
`symbology.resolve` are free; Tiingo daily prices (free) give each day's raw low/high, used only
to choose which strikes to store.

Scope per ticker and session D (configs/m28_data.yaml):
- the D2 expiry: the nearest listed expiration 1..max_sessions_to_expiry sessions after D;
- its listed strikes inside D's low..high plus `extra_strikes_each_side`, calls and puts;
- OPRA cbbo-1m over the regular session and the day's definitions for those symbols;
- EQUS.MINI bbo-1m and ohlcv-1m for the ticker, by month.
Development (to dev_end) and holdout storage (to holdout_end) are priced and reported apart.
Every request is priced exactly (no sampling); prices are cached, so a rerun resumes.

    uv run python scripts/m28_price_data.py [--tickers SPY,IWM]
    uv run python scripts/m28_price_data.py --download --max-usd 7.66

--download buys exactly the priced requests (cached prices), only if their total, rounded to the
cent, is within --max-usd (the owner-approved figure); files already on disk are skipped, each file
is written atomically, and every saved file is logged in download_log.jsonl with its price.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time as tm
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

import databento as db
import polars as pl
import requests
import yaml
from dotenv import load_dotenv

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.ingestion.databento_fetch import (
    MAX_SYMBOLS_PER_REQUEST,
    CostCapExceededError,
    FetchRequest,
    PricedPlan,
    RetryPolicy,
    download,
)
from qqq1dte.ingestion.etf_data import TIINGO_URL

ROOT = Path(__file__).resolve().parents[1]
C: dict[str, Any] = yaml.safe_load((ROOT / "configs" / "m28_data.yaml").read_text("utf-8"))
OUT = ROOT / str(C["out_dir"])
CACHE = OUT / "price_cache.json"
REPORT = ROOT / "reports" / "research" / "m28_step5_price_quote.md"
TRIES, BACKOFF = 6, 5.0
WORKERS = 4


# inputs -----------------------------------------------------------------------------------------
def tiingo_ranges(ticker: str, start: date, end: date) -> dict[date, tuple[float, float]]:
    """Raw (unadjusted) daily low/high, fetched once and stored unchanged with its URL."""
    path = OUT / "tiingo" / f"{ticker}.json"
    url = TIINGO_URL.format(ticker=ticker.lower(), start=start, end=end)
    if not path.exists():
        r = requests.get(
            url, headers={"Authorization": f"Token {os.environ['TIINGO_API_KEY']}"}, timeout=120
        )
        r.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        meta = {"source_url": url, "fetched_at": datetime.now(UTC).isoformat()}
        path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1), "utf-8")
    rows = json.loads(path.read_text("utf-8"))
    return {date.fromisoformat(r["date"][:10]): (float(r["low"]), float(r["high"])) for r in rows}


def _call[T](f: Any, **kw: Any) -> T:
    for attempt in range(TRIES):
        try:
            return f(**kw)  # type: ignore[no-any-return]
        except (db.BentoServerError, requests.exceptions.ConnectionError):
            if attempt == TRIES - 1:
                raise
            tm.sleep(BACKOFF * 2**attempt)
    raise RuntimeError("unreachable")


def universe(client: db.Historical, ticker: str, start: date, end: date) -> pl.DataFrame:
    """Every listed contract of the ticker's options with its listing span (free symbology,
    weekly requests cached per month); expiry/right/strike parsed from the OCC symbol."""
    cache = OUT / ticker / "universe"
    cache.mkdir(parents=True, exist_ok=True)
    m = date(start.year, start.month, 1)
    while m <= end:
        nxt = (m + timedelta(days=32)).replace(day=1)
        f = cache / f"{m:%Y-%m}.parquet"
        if not f.exists():
            rows: list[tuple[str, str, str]] = []
            a = max(m, start)
            while a < min(nxt, end):
                b = min(a + timedelta(days=7), nxt, end)
                try:
                    res = _call(
                        client.symbology.resolve,
                        dataset=C["option_dataset"],
                        symbols=[f"{ticker}.OPT"],
                        stype_in="parent",
                        stype_out="instrument_id",
                        start_date=a.isoformat(),
                        end_date=b.isoformat(),
                    )
                except db.BentoClientError as e:
                    if "symbology_invalid_request" not in str(e):
                        raise
                    res = {"result": {}}  # nothing listed in [a, b): no sessions
                for sym, spans in res["result"].items():
                    rows.extend((sym, sp["d0"], sp["d1"]) for sp in spans)
                a = b
            pl.DataFrame(rows, schema=["raw_symbol", "d0", "d1"], orient="row").write_parquet(f)
            print(f"{ticker} universe {m:%Y-%m}: {len(rows):,} spans", flush=True)
        m = nxt
    return (
        pl.concat([pl.read_parquet(f) for f in sorted(cache.glob("*.parquet"))])
        .with_columns(pl.col("d0").str.to_date(), pl.col("d1").str.to_date())
        .group_by("raw_symbol")
        .agg(pl.col("d0").min(), pl.col("d1").max())
        .with_columns(
            expiry=pl.col("raw_symbol").str.slice(6, 6).str.to_date("%y%m%d"),
            right=pl.col("raw_symbol").str.slice(12, 1),
            strike=pl.col("raw_symbol").str.slice(13, 8).cast(pl.Int64) / 1000,
        )
    )


# scope ------------------------------------------------------------------------------------------
def day_symbols(
    uni: pl.DataFrame, d: date, lo: float, hi: float, sessions: list[date], max_ahead: int
) -> tuple[date | None, list[str]]:
    """The D2 expiry and the stored symbols for session d (empty when no expiry qualifies)."""
    live = uni.filter((pl.col("d0") <= d) & (pl.col("d1") > d) & (pl.col("expiry") > d))
    i = sessions.index(d)
    ahead = {s: k for k, s in enumerate(sessions[i + 1 : i + 1 + max_ahead], 1)}
    exps = sorted(e for e in set(live["expiry"].to_list()) if e in ahead)
    if not exps:
        return None, []
    e = exps[0]
    ch = live.filter(pl.col("expiry") == e)
    strikes = sorted(set(ch["strike"].to_list()))
    # first: the highest strike <= the day's low (a put at the low); last: the lowest strike
    # >= the day's high (a call at the high); then n more listed strikes beyond each.
    first = max((j for j, k in enumerate(strikes) if k <= lo), default=0)
    last = min((j for j, k in enumerate(strikes) if k >= hi), default=len(strikes) - 1)
    n = int(C["extra_strikes_each_side"])
    keep = set(strikes[max(0, first - n) : last + n + 1])
    return e, sorted(ch.filter(pl.col("strike").is_in(list(keep)))["raw_symbol"].to_list())


def _key(r: FetchRequest) -> str:
    return hashlib.sha256(json.dumps(r.kwargs(), sort_keys=True).encode()).hexdigest()


def price_all(client: db.Historical, reqs: list[FetchRequest], cache: dict[str, float]) -> None:
    todo = [r for r in reqs if _key(r) not in cache]

    def one(r: FetchRequest) -> tuple[str, float]:
        try:
            return _key(r), float(_call(client.metadata.get_cost, **r.kwargs()))
        except db.BentoClientError as e:
            if "symbology_invalid_request" not in str(e):
                raise
            return _key(r), 0.0  # nothing resolves: nothing to buy (logged as zero)

    with ThreadPoolExecutor(WORKERS) as ex:
        for n, (k, v) in enumerate(ex.map(one, todo), 1):
            cache[k] = v
            if n % 200 == 0:
                CACHE.write_text(json.dumps(cache), "utf-8")
                print(f"  priced {n}/{len(todo)}", flush=True)
    CACHE.write_text(json.dumps(cache), "utf-8")


def main() -> int:  # noqa: PLR0912, PLR0915 (linear report)
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    s = cfg.study_options_day
    cal = TradingCalendar(cfg)
    tickers = (
        sys.argv[sys.argv.index("--tickers") + 1].split(",")
        if "--tickers" in sys.argv
        else list(C["tickers"])
    )
    start, dev_end = date.fromisoformat(C["start"]), date.fromisoformat(C["dev_end"])
    end = date.fromisoformat(C["holdout_end"])
    assert dev_end == s.dev_end["SPY"] and end == s.holdout_end
    sessions = cal.sessions(start, end)
    ahead = cal.sessions(start, end + timedelta(days=14))
    OUT.mkdir(parents=True, exist_ok=True)
    cache: dict[str, float] = json.loads(CACHE.read_text("utf-8")) if CACHE.exists() else {}
    client = db.Historical()
    rows: list[dict[str, Any]] = []
    everything: list[FetchRequest] = []
    for t in tickers:
        ranges = tiingo_ranges(t, start, end)
        uni = universe(client, t, start, end + timedelta(days=1))
        print(f"{t}: universe {uni.height:,} contracts", flush=True)
        reqs: list[tuple[str, str, FetchRequest]] = []
        no_range, no_expiry, nsym = [], [], []
        for d in sessions:
            part = "dev" if d <= dev_end else "holdout"
            if d not in ranges:
                no_range.append(d)
                continue
            e, syms = day_symbols(uni, d, *ranges[d], ahead, s.max_sessions_to_expiry)
            if e is None:
                no_expiry.append(d)
                continue
            nsym.append(len(syms))
            open_, close = cal.open_close(d)
            for j in range(0, len(syms), MAX_SYMBOLS_PER_REQUEST):
                chunk = tuple(syms[j : j + MAX_SYMBOLS_PER_REQUEST])
                reqs.append(
                    (
                        part,
                        "cbbo-1m",
                        FetchRequest(
                            C["option_dataset"],
                            "cbbo-1m",
                            open_,
                            close,
                            chunk,
                            "raw_symbol",  # type: ignore[arg-type]
                            OUT / t / "cbbo-1m" / f"{d}_{j}.dbn.zst",
                        ),
                    )
                )
                reqs.append(
                    (
                        part,
                        "definition",
                        FetchRequest(
                            C["option_dataset"],
                            "definition",
                            d,
                            d + timedelta(days=1),
                            chunk,
                            "raw_symbol",
                            OUT / t / "definition" / f"{d}_{j}.dbn.zst",
                        ),
                    )
                )
        m = start.replace(day=1)
        while m <= end:
            nxt = (m + timedelta(days=32)).replace(day=1)
            a, b = max(m, start), min(nxt, end + timedelta(days=1))
            for part, pa, pb in (
                ("dev", a, min(b, dev_end + timedelta(days=1))),
                ("holdout", max(a, dev_end + timedelta(days=1)), b),
            ):
                if pa >= pb:
                    continue
                for schema in C["underlying_schemas"]:
                    reqs.append(
                        (
                            part,
                            f"underlying {schema}",
                            FetchRequest(
                                C["underlying_dataset"],
                                schema,
                                pa,
                                pb,
                                (t,),
                                "raw_symbol",
                                OUT / t / schema / f"{pa}.dbn.zst",
                            ),
                        )
                    )
            m = nxt
        print(f"{t}: {len(reqs):,} requests to price", flush=True)
        price_all(client, [r for _, _, r in reqs], cache)
        everything += [r for _, _, r in reqs]
        by: dict[tuple[str, str], float] = defaultdict(float)
        for part, kind, r in reqs:
            by[(part, kind)] += cache[_key(r)]
        rows.append(
            {
                "ticker": t,
                "by": dict(by),
                "no_range": no_range,
                "no_expiry": no_expiry,
                "mean_symbols": sum(nsym) / max(len(nsym), 1),
            }
        )

    kinds = ["cbbo-1m", "definition", "underlying bbo-1m", "underlying ohlcv-1m"]
    lines = [
        "# M28 step 5: data price quote, SPY / IWM / NVDA / TSLA / AAPL (ADR-0021 D7)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m28_price_data.py`. "
        "**Price only: no market data was downloaded.** Every request priced exactly with "
        "Databento `metadata.get_cost`; scope in `configs/m28_data.yaml`.",
        "",
        f"Development {start} → {dev_end}; holdout storage {dev_end + timedelta(days=1)} → {end}.",
        "",
        "| ticker | part | " + " | ".join(kinds) + " | total |",
        "|---|---|" + "---|" * (len(kinds) + 1),
    ]
    totals: dict[str, float] = defaultdict(float)
    for row in rows:
        for part in ("dev", "holdout"):
            vals = [row["by"].get((part, k), 0.0) for k in kinds]
            totals[part] += sum(vals)
            lines.append(
                f"| {row['ticker']} | {part} | "
                + " | ".join(f"${v:.4f}" for v in vals)
                + f" | **${sum(vals):.2f}** |"
            )
    lines += [
        "",
        f"**Development total: ${totals['dev']:.2f}. Holdout storage total: "
        f"${totals['holdout']:.2f}. Both: ${totals['dev'] + totals['holdout']:.2f}.** "
        f"Budget left (D7): ${s.data_budget_usd:.2f}.",
        "",
        "| ticker | mean symbols per session | sessions with no Tiingo row | sessions with no D2 "
        "expiry |",
        "|---|---|---|---|",
        *[
            f"| {r['ticker']} | {r['mean_symbols']:.1f} | {len(r['no_range'])} "
            f"{r['no_range'][:5] if r['no_range'] else ''} | {len(r['no_expiry'])} "
            f"{r['no_expiry'][:5] if r['no_expiry'] else ''} |"
            for r in rows
        ],
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"dev ${totals['dev']:.2f}, holdout ${totals['holdout']:.2f}; wrote "
        f"{REPORT.relative_to(ROOT)}"
    )
    if "--download" in sys.argv:
        buy(client, everything, cache, float(sys.argv[sys.argv.index("--max-usd") + 1]))
    return 0


def buy(
    client: db.Historical, reqs: list[FetchRequest], cache: dict[str, float], max_usd: float
) -> None:
    """Download every priced request within the owner-approved cap; the cap is checked on the
    whole set before any file is fetched. A request whose symbols do not resolve (priced $0) is
    logged as unresolved, not silently skipped."""
    todo = [r for r in reqs if not r.path.exists()]
    total = sum(cache[_key(r)] for r in reqs)
    left = sum(cache[_key(r)] for r in todo)
    print(
        f"buy: {len(todo):,} files, ${left:.4f} left of ${total:.4f} (cap ${max_usd:.2f})",
        flush=True,
    )
    if round(total, 2) > max_usd:
        raise CostCapExceededError(f"priced ${total:.4f} > approved ${max_usd:.2f}")
    log = OUT / "download_log.jsonl"
    retry = RetryPolicy((db.BentoServerError, requests.exceptions.ConnectionError))

    lock = threading.Lock()
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else WORKERS
    done = 0

    def one(r: FetchRequest) -> None:
        nonlocal done
        status = "saved"
        try:
            download(client, PricedPlan([r], [cache[_key(r)]]), max_usd=max_usd, retry=retry)
        except db.BentoClientError as e:
            if "symbology_invalid_request" not in str(e):
                raise
            status = "unresolved"
        entry = {
            "path": r.path.relative_to(ROOT).as_posix(),
            "usd": cache[_key(r)],
            "status": status,
            "saved_at": datetime.now(UTC).isoformat(),
        }
        with lock:  # logged as each file lands, so an interrupted run leaves a true log
            with log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            done += 1
            if done % 500 == 0:
                print(f"  downloaded {done}/{len(todo)}", flush=True)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, todo))
    missing = [r for r in reqs if not r.path.exists()]
    print(f"buy: done; {len(missing)} requests without a file (see download_log.jsonl)")


if __name__ == "__main__":
    sys.exit(main())
