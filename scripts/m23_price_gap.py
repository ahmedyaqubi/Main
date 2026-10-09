"""M23 Step 0 (ADR-0014 D0, R1-R9): price the SPX data scope. PRICE ONLY: this script never
downloads market data. `metadata.get_cost` and `symbology.resolve` are free. The only file fetched
is the free Cboe daily SPX close history (R6), saved with its source URL.

Scope per session D (2013-04-01 -> 2026-10-02; the last 12 months are holdout storage only):
- Entry: the SPX/SPXW expiry whose calendar DTE is closest to each target (7, 30; ties go to the
  earlier one). Strikes within prev close x (1 +- pad). Quotes 09:57-10:01 ET.
- Exit: contracts expiring next_session(D) that any earlier entry could have opened (the union
  of their entry bands). Quotes 15:41-15:46 ET (12:41-12:46 on early closes).
- Definitions for every requested symbol, same session.
The listing universe comes from free symbology resolution (point-in-time per day).

Pricing: every `sample_every`-th session is priced exactly, and the total is extrapolated per
year. The purchase script re-prices exactly and enforces the cap.

    uv run python scripts/m23_price_gap.py [--underlying spx|spy]
"""

from __future__ import annotations

import os
import sys
import time as tm
import urllib.request
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

import databento as db
import polars as pl
import yaml
from dotenv import load_dotenv

from qqq1dte.core.calendar import TradingCalendar, add_months
from qqq1dte.core.config import load_config
from qqq1dte.ingestion.databento_fetch import (
    MAX_SYMBOLS_PER_REQUEST,
    FetchRequest,
    RetryPolicy,
    price,
)

ROOT = Path(__file__).resolve().parents[1]
S0: dict[str, Any] = yaml.safe_load((ROOT / "configs" / "m23_step0.yaml").read_text("utf-8"))
OUT: Path = ROOT / str(S0["out_dir"])
ET = ZoneInfo("America/New_York")
RETRY = RetryPolicy(retry_on=(db.BentoServerError,), tries=6, backoff_s=5.0)
REPORT = ROOT / "reports" / "research" / "m23_price_quote.md"
# Underlyings priced in Step 0 (owner, 2026-10-09: add the SPY comparison). SPY's band uses SPX
# close / 10 as a storage-scope proxy only; it never enters a trade or W.
UNDERLYINGS: dict[str, dict[str, Any]] = {
    "spx": {"parents": None, "close_scale": 1.0, "label": "SPX/SPXW", "sub": ""},
    "spy": {"parents": ["SPY.OPT"], "close_scale": 0.1, "label": "SPY", "sub": "spy"},
}
U: dict[str, Any] = dict(UNDERLYINGS["spx"])


def out_dir() -> Path:
    sub = str(U["sub"])
    return OUT / sub if sub else OUT


def parents() -> list[str]:
    return list(U["parents"] or S0["parents"])


EMPTY_CHUNKS: list[tuple[date, date]] = []
MAX_CLOSE_GAP_DAYS = 7  # a previous close older than this is treated as missing (logged)


# inputs -----------------------------------------------------------------------------------------
def spx_closes() -> dict[date, float]:
    path = ROOT / S0["spx_close_csv"]
    if not path.exists():
        req = urllib.request.Request(S0["spx_close_url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            path.write_bytes(r.read())
    df = pl.read_csv(path).select(
        d=pl.col("DATE").str.strptime(pl.Date, "%m/%d/%Y"), c=pl.col("SPX").cast(pl.Float64)
    )
    return dict(zip(df["d"].to_list(), df["c"].to_list(), strict=True))


def _resolve(client: db.Historical, a: date, b: date) -> dict[str, Any]:
    for attempt in range(RETRY.tries):
        try:
            r: dict[str, Any] = client.symbology.resolve(
                dataset=S0["dataset"], symbols=parents(), stype_in="parent",
                stype_out="instrument_id", start_date=a.isoformat(), end_date=b.isoformat(),
            )  # fmt: skip
            return r
        except db.BentoClientError as e:
            if "symbology_invalid_request" not in str(e):
                raise
            EMPTY_CHUNKS.append((a, b))  # nothing listed in [a, b) (no sessions): logged
            return {"result": {}}
        except db.BentoServerError:
            if attempt == RETRY.tries - 1:
                raise
            tm.sleep(RETRY.backoff_s * 2**attempt)
    raise RuntimeError("unreachable")


def universe(client: db.Historical, start: date, end: date) -> pl.DataFrame:
    """raw_symbol, d0, d1 (listing mapping dates); weekly requests, cached per month so a rerun
    resumes; root / expiry / right / strike parsed from the OCC symbol."""
    cache_dir = out_dir() / "universe"
    cache_dir.mkdir(parents=True, exist_ok=True)
    m = date(start.year, start.month, 1)
    while m <= end:
        nxt = (m + timedelta(days=32)).replace(day=1)
        f = cache_dir / f"{m:%Y-%m}.parquet"
        if not f.exists():
            rows: list[tuple[str, str, str]] = []
            a = m
            while a < min(nxt, end):
                b = min(a + timedelta(days=7), nxt, end)
                for sym, spans in _resolve(client, a, b)["result"].items():
                    rows.extend((sym, sp["d0"], sp["d1"]) for sp in spans)
                a = b
            pl.DataFrame(rows, schema=["raw_symbol", "d0", "d1"], orient="row").write_parquet(f)
            print(f"universe {m:%Y-%m}: {len(rows):,} spans", flush=True)
        m = nxt
    return (
        pl.concat([pl.read_parquet(f) for f in sorted(cache_dir.glob("*.parquet"))])
        .with_columns(pl.col("d0").str.to_date(), pl.col("d1").str.to_date())
        .group_by("raw_symbol")
        .agg(pl.col("d0").min(), pl.col("d1").max())
        .with_columns(
            root=pl.col("raw_symbol").str.slice(0, 6).str.strip_chars(),
            expiry=pl.col("raw_symbol").str.slice(6, 6).str.to_date("%y%m%d"),
            right=pl.col("raw_symbol").str.slice(12, 1),
            strike=pl.col("raw_symbol").str.slice(13, 8).cast(pl.Int64) / 1000,
        )
    )


# scope ------------------------------------------------------------------------------------------
def entry_scope(
    uni: pl.DataFrame, d: date, close: float, sessions: set[date]
) -> dict[int, tuple[date, pl.DataFrame]]:
    """Per target DTE: (chosen expiry, symbols within the band) from contracts listed on d."""
    live = uni.filter((pl.col("d0") <= d) & (pl.col("d1") > d) & (pl.col("expiry") > d))
    exps = sorted(e for e in set(live["expiry"].to_list()) if e in sessions)
    out = {}
    for tgt in S0["target_dte"]:
        if not exps:
            continue
        e = min(exps, key=lambda x: (abs((x - d).days - tgt), x))
        pad = S0["band_pad"][tgt]
        out[tgt] = (
            e,
            live.filter(
                (pl.col("expiry") == e)
                & pl.col("strike").is_between(close * (1 - pad), close * (1 + pad))
            ),
        )
    return out


def window(d: date, cal: TradingCalendar, kind: str) -> tuple[datetime, datetime]:
    key = "entry_window" if kind == "entry" else (
        "early_close_exit_window" if cal.is_early_close(d) else "exit_window"
    )  # fmt: skip
    a, b = (time.fromisoformat(x) for x in S0[key])
    return (
        datetime.combine(d, a, ET).astimezone(UTC),
        datetime.combine(d, b, ET).astimezone(UTC),
    )


def requests_for(
    d: date, entry_syms: list[str], exit_syms: list[str], cal: TradingCalendar
) -> list[FetchRequest]:
    reqs = []
    parts: list[tuple[str, list[str], datetime | date, datetime | date]] = []
    es, ee = window(d, cal, "entry")
    xs, xe = window(d, cal, "exit")
    parts.append(("definition", sorted(set(entry_syms) | set(exit_syms)), d, d + timedelta(1)))
    parts.append(("cbbo-1m", sorted(set(entry_syms)), es, ee))
    parts.append(("cbbo-1m", sorted(set(exit_syms)), xs, xe))
    for schema, syms, a, b in parts:
        tag = "def" if schema == "definition" else ("entry" if a == es else "exit")
        for j in range(0, len(syms), MAX_SYMBOLS_PER_REQUEST):
            reqs.append(
                FetchRequest(
                    S0["dataset"], schema, a, b, tuple(syms[j : j + MAX_SYMBOLS_PER_REQUEST]),
                    "raw_symbol", out_dir() / tag / f"{d}_{j // MAX_SYMBOLS_PER_REQUEST}.dbn.zst",
                )
            )  # fmt: skip
    return reqs


def main() -> int:
    which = sys.argv[sys.argv.index("--underlying") + 1] if "--underlying" in sys.argv else "spx"
    U.update(UNDERLYINGS[which])
    report = REPORT if which == "spx" else REPORT.with_name(f"m23_price_quote_{which}.md")
    load_dotenv(ROOT / ".env")
    cal = TradingCalendar(load_config())
    start, last = date.fromisoformat(S0["start"]), date.fromisoformat(S0["last_session"])
    sessions = cal.sessions(start, last)
    sset = set(cal.sessions(start, last + timedelta(days=60)))
    closes = spx_closes()
    client = db.Historical()
    uni = universe(client, start, last + timedelta(days=1))
    print(f"universe: {uni.height:,} contracts", flush=True)

    # entry bands for every session (cheap, local): needed for the exit unions
    entries: dict[date, dict[int, tuple[date, pl.DataFrame]]] = {}
    held: dict[date, set[str]] = defaultdict(set)  # expiry -> symbols any entry could open
    missing_close = []
    for i, d in enumerate(sessions):
        prev = max((x for x in closes if x < d), default=None)
        if prev is None or (d - prev).days > MAX_CLOSE_GAP_DAYS:
            missing_close.append(d)
            continue
        entries[d] = entry_scope(uni, d, closes[prev] * U["close_scale"], sset)
        for e, syms in entries[d].values():
            held[e] |= set(syms["raw_symbol"].to_list())
        if i % 250 == 0:
            print(f"scope {i}/{len(sessions)}", flush=True)

    sample = sessions[:: S0["sample_every"]]
    priced_rows = []
    for k, d in enumerate(sample, 1):
        if d not in entries:
            continue
        ent = [s for _, syms in entries[d].values() for s in syms["raw_symbol"].to_list()]
        exp_next = cal.next_session(d)
        live = set(uni.filter((pl.col("d0") <= d) & (pl.col("d1") > d))["raw_symbol"].to_list())
        ext = sorted(held.get(exp_next, set()) & live)
        reqs = requests_for(d, ent, ext, cal)
        plan = price(client, reqs, unresolved_errors=(db.BentoClientError,), retry=RETRY)
        by: dict[str, float] = defaultdict(float)
        for r, c in zip(plan.priced, plan.costs, strict=True):
            by[r.path.parent.name] += c
        priced_rows.append(
            {"session": d, "year": d.year, "n_entry": len(ent), "n_exit": len(ext),
             "def": by["def"], "entry": by["entry"], "exit": by["exit"],
             "unresolved": len(plan.unresolved)}
        )  # fmt: skip
        if k % 10 == 0:
            print(f"priced {k}/{len(sample)}", flush=True)
    p = pl.DataFrame(priced_rows).with_columns(
        total=pl.col("def") + pl.col("entry") + pl.col("exit")
    )
    per_year_sessions = pl.DataFrame({"year": [d.year for d in sessions]}).group_by("year").len()
    est = (
        p.group_by("year")
        .agg(pl.col("total").mean(), pl.col("n_entry").mean(), pl.col("n_exit").mean(),
             sampled=pl.len())
        .join(per_year_sessions, on="year")
        .with_columns(est=pl.col("total") * pl.col("len"))
        .sort("year")
    )  # fmt: skip
    total = float(est["est"].sum())
    hold_start = add_months(last, -int(S0["holdout_months"]))  # D3: project holdout
    lines = [
        f"# M23 Step 0: {U['label']} data-scope price quote (ADR-0014)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m23_price_gap.py`. "
        "**Price only: no market data was downloaded.** Prices come from Databento "
        "`metadata.get_cost` (free); the listing universe comes from free symbology resolution.",
        "",
        f"- Sessions {sessions[0]} → {sessions[-1]}: {len(sessions)}. The holdout is every session "
        f"after {hold_start} (storage only, D3).",
        f"- Universe: {uni.height:,} {U['label']} contracts. Sessions with no previous close "
        f"in the Cboe file: {len(missing_close)}. Symbology chunks with nothing to resolve: "
        f"{', '.join(f'{a}..{b}' for a, b in EMPTY_CHUNKS) or 'none'}.",
        f"- Sample: every {S0['sample_every']}th session ({p.height} sessions priced exactly). "
        "The total is extrapolated per year (sample mean x sessions in the year).",
        "",
        "| year | sessions | sampled | entry symbols (mean) | exit symbols (mean) "
        "| $ per session (mean) | estimate $ |",
        "|---|---|---|---|---|---|---|",
        *[
            f"| {r['year']} | {r['len']} | {r['sampled']} | {r['n_entry']:.0f} | {r['n_exit']:.0f} "
            f"| {r['total']:.4f} | {r['est']:.2f} |"
            for r in est.iter_rows(named=True)
        ],
        "",
        f"**Estimated total: ${total:.2f}** (cap ${S0['cap_usd']:.0f}, R8). By part, sample sums: "
        f"definitions ${p['def'].sum():.4f}, entry quotes ${p['entry'].sum():.4f}, exit quotes "
        f"${p['exit'].sum():.4f}. Unresolved requests in the sample: {int(p['unresolved'].sum())}.",
        "",
        "Uncertainty: this is an estimate from a 1-in-"
        f"{S0['sample_every']} sample. The purchase step prices every request exactly and stops at "
        "the cap.",
        "",
    ]
    if which == "spy":
        lines += [
            "SPY band: previous SPX close / 10 as a storage-scope proxy. SPY's own closes are "
            "fetched before any SPY Step 1 (W and labels never use the proxy).",
            "",
        ]  # fmt: skip
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"estimated total ${total:.2f}; wrote {report.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
