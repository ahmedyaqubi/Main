"""M23 Step 0 (ADR-0014, owner 2026-10-09): SPX vs SPY entry-friction comparison sample.

Data only, entry quotes only: no exit, P&L or outcome is computed, and nothing is registered.

Sample: `--sessions` sessions spread evenly over 2013-04-01 -> the last development session
(an odd stride, so weekdays rotate). For each underlying and target DTE (7, 30), the expiry and
strike band come from `m23_price_gap.entry_scope`, with quotes 09:57-10:01 ET.

Measures, at T_e = 10:00:05 ET, the frozen credit rule's put-spread pick
(`execution_sim.spreads.credit_pick`) at X = 0.20 with W = 0.5% of the previous close:
- conservative credit (short bid - long ask) and mid credit;
- friction = mid - conservative, in $ per spread and as a share of the mid credit;
- both legs' quoted spreads.
SPY's W and band use SPX close / 10 (a descriptive comparison only, never a label).

    uv run python scripts/m23_compare_sample.py             # price only (free)
    uv run python scripts/m23_compare_sample.py --download  # after the owner approves the price
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import databento as db
import polars as pl
from dotenv import load_dotenv

import m23_price_gap as gap
from qqq1dte.core.calendar import TradingCalendar, add_months
from qqq1dte.core.config import load_config
from qqq1dte.execution_sim.spreads import LegQuote, credit_pick
from qqq1dte.ingestion.databento_fetch import (
    MAX_SYMBOLS_PER_REQUEST,
    FetchRequest,
    download,
    price,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = gap.OUT / "compare"
REPORT = ROOT / "reports" / "research" / "m23_spx_vs_spy.md"
X = 0.20
W_SHARE = 0.005
GRID = {"spx": 5.0, "spy": 1.0}
MIN_W = {"spx": 10.0, "spy": 1.0}
TE = time(10, 0, 5)
MAX_AGE = timedelta(seconds=60)


def sample_sessions(cal: TradingCalendar, n: int) -> list[date]:
    start = date.fromisoformat(gap.S0["start"])
    last = date.fromisoformat(gap.S0["last_session"])
    dev_end = add_months(last, -int(gap.S0["holdout_months"]))
    sessions = cal.sessions(start, dev_end)
    stride = max(1, len(sessions) // n)
    stride += stride % 5 == 0  # never a multiple of 5: weekdays rotate
    return sessions[::stride][:n]


def build_requests(
    cal: TradingCalendar, days: list[date]
) -> tuple[list[FetchRequest], dict[Any, Any]]:
    closes = gap.spx_closes()
    client = db.Historical()
    reqs: list[FetchRequest] = []
    scope: dict[Any, Any] = {}
    sset = set(cal.sessions(days[0], days[-1] + timedelta(days=60)))
    for under in ("spx", "spy"):
        gap.U.update(gap.UNDERLYINGS[under])
        start = date.fromisoformat(gap.S0["start"])
        end = date.fromisoformat(gap.S0["last_session"]) + timedelta(days=1)
        uni = gap.universe(client, start, end)
        for d in days:
            prev = max(x for x in closes if x < d)
            close = closes[prev] * gap.U["close_scale"]
            ent = gap.entry_scope(uni, d, close, sset)
            syms = sorted({s for _, f in ent.values() for s in f["raw_symbol"].to_list()})
            scope[(under, d)] = (close, ent)
            a, b = gap.window(d, cal, "entry")
            for j in range(0, len(syms), MAX_SYMBOLS_PER_REQUEST):
                reqs.append(
                    FetchRequest(
                        gap.S0["dataset"], "cbbo-1m", a, b,
                        tuple(syms[j : j + MAX_SYMBOLS_PER_REQUEST]), "raw_symbol",
                        OUT / under / f"{d}_{j // MAX_SYMBOLS_PER_REQUEST}.dbn.zst",
                    )
                )  # fmt: skip
    return reqs, scope


def measure(scope: dict[Any, Any]) -> pl.DataFrame:
    rows = []
    for (under, d), (close, ent) in scope.items():
        files = sorted((OUT / under).glob(f"{d}_*.dbn.zst"))
        if not files:
            continue
        q = pl.concat(
            [pl.from_pandas(db.DBNStore.from_file(f).to_df().reset_index()) for f in files]
        )
        t_e = datetime.combine(d, TE, gap.ET).astimezone(UTC)
        q = q.with_columns(ts=pl.col("ts_recv").dt.convert_time_zone("UTC")).filter(
            pl.col("ts") <= t_e
        )
        last = q.sort("ts").group_by("symbol", maintain_order=True).last()
        w = max(MIN_W[under], round(close * W_SHARE / GRID[under]) * GRID[under])
        for tgt, (exp, f) in ent.items():
            book = {}
            raw = {}
            legs = f.select("raw_symbol", "right", "strike")
            joined = last.join(legs, left_on="symbol", right_on="raw_symbol")
            for r in joined.iter_rows(named=True):
                if r["right"] != "P":
                    continue
                ok = (t_e - r["ts"]) <= MAX_AGE and r["bid_px_00"] == r["bid_px_00"]
                book[r["strike"]] = LegQuote(r["strike"], r["bid_px_00"], r["ask_px_00"], ok)
                raw[r["strike"]] = r
            p = credit_pick(book, "P", X, w)
            row: dict[str, Any] = {"under": under, "session": d, "dte_target": tgt,
                                   "expiry": exp, "W": w, "status": p.status}  # fmt: skip
            if p.short is not None and p.long is not None:
                s, lg = raw[p.short], raw[p.long]
                mid = (s["bid_px_00"] + s["ask_px_00"]) / 2 - (
                    lg["bid_px_00"] + lg["ask_px_00"]
                ) / 2
                row |= {
                    "credit_cons": p.credit,
                    "credit_mid": mid,
                    "friction": mid - (p.credit or 0.0),
                    "short_spread": s["ask_px_00"] - s["bid_px_00"],
                    "long_spread": lg["ask_px_00"] - lg["bid_px_00"],
                }
            rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=30)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--max-usd", type=float, default=0.0)
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    cal = TradingCalendar(load_config())
    days = sample_sessions(cal, args.sessions)
    reqs, scope = build_requests(cal, days)
    client = db.Historical()
    plan = price(client, reqs, unresolved_errors=(db.BentoClientError,), retry=gap.RETRY)
    by = {u: sum(c for r, c in zip(plan.priced, plan.costs, strict=True) if r.path.parent.name == u)
          for u in ("spx", "spy")}  # fmt: skip
    print(f"{len(days)} sessions {days[0]}..{days[-1]}; {len(reqs)} requests; "
          f"price ${plan.total_usd:.4f} (SPX ${by['spx']:.4f}, SPY ${by['spy']:.4f}); "
          f"on disk {len(plan.already_present)}; unresolved {len(plan.unresolved)}")  # fmt: skip
    if not args.download:
        return 0
    download(client, plan, max_usd=args.max_usd, retry=gap.RETRY)
    m = measure(scope)
    ok = m.filter(pl.col("credit_mid").is_not_null())
    summary = (
        ok.group_by("under", "dte_target")
        .agg(
            n=pl.len(),
            W=pl.col("W").median(),
            credit_mid=pl.col("credit_mid").median(),
            credit_cons=pl.col("credit_cons").median(),
            friction=pl.col("friction").median(),
            friction_share=(pl.col("friction") / pl.col("credit_mid")).median(),
            short_spread=pl.col("short_spread").median(),
            long_spread=pl.col("long_spread").median(),
        )
        .sort("dte_target", "under")
    )
    lines = [
        "# M23 Step 0: SPX vs SPY entry friction (ADR-0014)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m23_compare_sample.py`. "
        f"Entry quotes only (10:00:05 ET) on {len(days)} development sessions, {days[0]} → "
        f"{days[-1]}. No exit, P&L or outcome computed; nothing registered. Sample cost "
        f"${plan.total_usd:.4f}.",
        "",
        f"Put-spread pick by the frozen credit rule, X = {X}, W = {W_SHARE:.1%} of the previous "
        "close (SPY: SPX close / 10, descriptive only). Medians; prices in index or ETF points "
        "(x 100 = $ per spread). *Friction share*: (mid credit - conservative credit) / "
        "mid credit.",
        "",
        "| target DTE | underlying | picks | W | mid credit | conservative credit | friction "
        "| friction share | short-leg spread | long-leg spread |",
        "|---|---|---|---|---|---|---|---|---|---|",
        *[
            f"| {r['dte_target']} | {r['under'].upper()} | {r['n']} | {r['W']:g} "
            f"| {r['credit_mid']:.3f} | {r['credit_cons']:.3f} | {r['friction']:.3f} "
            f"| {r['friction_share']:.1%} | {r['short_spread']:.3f} | {r['long_spread']:.3f} |"
            for r in summary.iter_rows(named=True)
        ],
        "",
        "Status counts (OK / AT_BAND_EDGE / NO_QUALIFYING): "
        + ", ".join(
            f"{r['under'].upper()} {r['dte_target']}d {r['status']} {r['n']}"
            for r in m.group_by("under", "dte_target", "status").agg(n=pl.len())
            .sort("under", "dte_target", "status").iter_rows(named=True)
        )
        + ".",
        "",
        "Commissions and fees are not included: they depend on the broker schedule (R3). SPX "
        "carries an index-option fee per contract on top; SPY a much smaller equity fee. One SPX "
        "spread is about 10x the notional of one SPY spread.",
        "",
    ]  # fmt: skip
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    m.write_parquet(OUT / "measures.parquet")
    print(f"wrote {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
