"""M24 (ADR-0015, docs/ROADMAP.md): fill feasibility of hypothetical retail limit orders on
near-the-money QQQ options, 0-2 DTE. Data only: no orders, no strategy trial, nothing
registered as a validation run.

Inputs:
- trade prints bought in M24 (`data/raw/databento/m24/trades`);
- QQQ 1-minute quotes already on disk (M4 1/2DTE, M19T 0DTE).

The sessions are the 20 development sessions of `scripts/m24_price_fill_study.py`. Any session
after 2026-04-02 is refused (QQQ holdout).

At every order time t (each minute, 09:55-10:35 and 15:25-15:45 ET; 12:25-12:45 on early
closes), for every contract with a usable quote (two-sided, not rejected, <= 60 s old):
- **Orders:** buy limits at mid, mid + 25% and mid + 50% of the spread; sells at mid, mid - 25%
  and mid - 50% (`execution_sim.fill_feasibility.limit_price`, never better than that level).
- **Fills:** touch / through within k = 1, 5, 15 min, counting only prints inside the bid-ask in
  force at the print (prints outside it are likely multi-leg or late reports; excluding them is
  conservative).
- **Chase cost:** for "limit at mid, chase to the opposite quote after 5 min", as a share of
  the quoted half-spread.
- **Mid move:** mid(t + 5) - mid(t) for filled orders, in half-spreads (negative = against the
  trader).

The "promising" threshold is pre-declared in the approved M24 plan: buy at mid within 5 min,
through >= 25% and touch >= 50%, and a chase cost <= 0.5 half-spread.

    uv run python scripts/m24_fill_study.py
"""

from __future__ import annotations

import bisect
import sys
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import databento as db
import numpy as np
import polars as pl

import m24_price_fill_study as q
from qqq1dte.backtesting.bootstrap import session_bootstrap_ci
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.execution_sim.fill_feasibility import (
    chase_cost_share,
    check_fill,
    limit_price,
    quote_usable,
)
from qqq1dte.labels.option import option_records
from qqq1dte.labels.spread import quote_at

ROOT = q.ROOT
REPORT = ROOT / "reports" / "research" / "m24_fill_feasibility.md"
DEV_END = date(2026, 4, 2)  # QQQ holdout after this (ADR-0011)
ORDER_WINDOWS = [(time(9, 55), time(10, 35)), (time(15, 25), time(15, 45))]
EARLY_ORDER_WINDOW = (time(12, 25), time(12, 45))
FRACS = (0.0, 0.25, 0.5)
KS = (1, 5, 15)
CHASE_K = 5
TICK = 0.01
MAX_AGE_S = 60
THRESH_THROUGH, THRESH_TOUCH, THRESH_COST = 0.25, 0.50, 0.50
NOON = 12
MNY_NEAR, MNY_MID = 0.005, 0.015
SPREAD_ONE, SPREAD_FEW = 1, 3


def quotes_for(d: date) -> pl.DataFrame:
    if d > DEV_END:
        raise RuntimeError(f"holdout session {d} requested: refused (ADR-0011)")
    parts = []
    for c, r in (
        (ROOT / "data/clean/cleaned/cleaned_options_data/cbbo-1m" / f"{d}.parquet",
         ROOT / "data/clean/rejected/cleaned_options_data/cbbo-1m" / f"{d}.parquet"),
        (ROOT / "data/clean/m19t/cleaned/0dte" / f"{d}.parquet",
         ROOT / "data/clean/m19t/rejected/0dte" / f"{d}.parquet"),
    ):  # fmt: skip
        if c.exists():
            parts.append(option_records(pl.read_parquet(c), pl.read_parquet(r)))
    return pl.concat(parts) if parts else pl.DataFrame()


def trades_for(d: date) -> dict[str, tuple[list[datetime], list[float]]]:
    out: dict[str, tuple[list[datetime], list[float]]] = defaultdict(lambda: ([], []))
    for f in sorted((q.OUT / "trades").glob(f"{d}_w*.dbn.zst")):
        df = db.DBNStore.from_file(f).to_df()
        if df.empty:
            continue
        for ts, sym, px in zip(list(df.index), df["symbol"], df["price"], strict=True):
            out[sym][0].append(ts.to_pydatetime().astimezone(UTC))
            out[sym][1].append(float(px))
    for sym, (ts_l, px_l) in out.items():
        order = sorted(range(len(ts_l)), key=ts_l.__getitem__)
        out[sym] = ([ts_l[i] for i in order], [px_l[i] for i in order])
    return out


def inside_nbbo(
    times: list[datetime], prices: list[float], qrec: pl.DataFrame
) -> tuple[list[datetime], list[float]]:
    """Keep prints within the bid-ask of the latest usable 1-minute quote at the print."""
    if qrec.height == 0 or not times:
        return [], []
    qa = qrec["available_at"].to_list()
    qb, qk, qr = qrec["bid"].to_list(), qrec["ask"].to_list(), qrec["rejected"].to_list()
    kt, kp = [], []
    for ts, px in zip(times, prices, strict=True):
        i = bisect.bisect_right(qa, ts) - 1
        if i < 0 or qr[i] or qb[i] is None or qk[i] is None:
            continue
        if qb[i] - 1e-9 <= px <= qk[i] + 1e-9:
            kt.append(ts)
            kp.append(px)
    return kt, kp


def order_times(d: date, cal: TradingCalendar) -> list[datetime]:
    wins = [EARLY_ORDER_WINDOW] if cal.is_early_close(d) else ORDER_WINDOWS
    out = []
    for a, b in wins:
        t = datetime.combine(d, a, q.ET)
        while t.time() <= b:
            out.append(t.astimezone(UTC))
            t += timedelta(minutes=1)
    return out


def session_rows(d: date, cal: TradingCalendar, close: float) -> list[dict[str, Any]]:
    recs = quotes_for(d)
    trades = trades_for(d)
    if recs.height == 0:
        return []
    by_sym = {s: g.sort("available_at") for (s,), g in recs.group_by(["symbol"])}
    nxt = cal.next_session(d)
    rows: list[dict[str, Any]] = []
    for sym, (tt, pp) in trades.items():
        g = by_sym.get(sym)
        if g is None:
            continue
        kt, kp = inside_nbbo(tt, pp, g)
        expiry = date(2000 + int(sym[6:8]), int(sym[8:10]), int(sym[10:12]))
        dte = 0 if expiry == d else 1 if expiry == nxt else 2
        strike = int(sym[13:21]) / 1000
        mny = abs(strike / close - 1)
        for t in order_times(d, cal):
            q0 = quote_at(g, t).get(sym)
            if q0 is None or not quote_usable(q0.bid, q0.ask, q0.rejected, q0.available_at, t,
                                              MAX_AGE_S):  # fmt: skip
                continue
            assert q0.bid is not None and q0.ask is not None
            mid0 = (q0.bid + q0.ask) / 2
            half = (q0.ask - q0.bid) / 2
            q5 = quote_at(g, t + timedelta(minutes=CHASE_K)).get(sym)
            lo = bisect.bisect_right(kt, t)
            hi = bisect.bisect_right(kt, t + timedelta(minutes=max(KS)))
            wt, wp = kt[lo:hi], kp[lo:hi]
            for side in ("buy", "sell"):
                for frac in FRACS:
                    lim = limit_price(q0.bid, q0.ask, side, frac, TICK)
                    row: dict[str, Any] = {
                        "session": d, "symbol": sym, "t": t, "dte": dte, "mny": mny,
                        "spread_ticks": round((q0.ask - q0.bid) / TICK),
                        "window": "open" if t.astimezone(q.ET).hour < NOON else "close",
                        "side": side, "frac": frac, "half": half,
                    }  # fmt: skip
                    for k in KS:
                        touch, through = check_fill(side, lim, t, k, wt, wp)
                        row[f"touch_{k}"], row[f"through_{k}"] = touch, through
                    if q5 is not None and q5.ask is not None and q5.bid is not None and half > 0:
                        row["chase_cost"] = chase_cost_share(
                            side, row[f"touch_{CHASE_K}"], lim, mid0, half,
                            later_ask=q5.ask, later_bid=q5.bid,
                        )  # fmt: skip
                        move = ((q5.bid + q5.ask) / 2 - mid0) / half
                        row["mid_move"] = move if side == "buy" else -move
                    rows.append(row)
    return rows


def rate_ci(df: pl.DataFrame, col: str) -> tuple[float, float, float]:
    v = df[col].cast(pl.Float64).to_numpy()
    sid = df["session"].to_numpy()

    def stat(w: np.ndarray) -> float:
        return float((w * v).sum() / w.sum())

    lo, hi = session_bootstrap_ci(sid, stat, 2000, 20261010, 0.95)
    return float(v.mean()), lo, hi


def main() -> int:
    cal = TradingCalendar(load_config())
    days = q.sample_sessions(cal)
    closes = q.prev_closes()
    rows: list[dict[str, Any]] = []
    for i, d in enumerate(days, 1):
        prev = max(x for x in closes if x < d)
        rows += session_rows(d, cal, closes[prev])
        print(f"session {i}/{len(days)} {d}: {len(rows):,} order checks", flush=True)
    df = pl.DataFrame(rows, infer_schema_length=None)
    (ROOT / "data" / "clean" / "m24").mkdir(parents=True, exist_ok=True)
    df.write_parquet(ROOT / "data" / "clean" / "m24" / "fill_checks.parquet")
    buy_mid = df.filter((pl.col("side") == "buy") & (pl.col("frac") == 0.0))
    th = rate_ci(buy_mid, f"through_{CHASE_K}")
    tc = rate_ci(buy_mid, f"touch_{CHASE_K}")
    cc = rate_ci(buy_mid.filter(pl.col("chase_cost").is_not_null()), "chase_cost")
    promising = th[0] >= THRESH_THROUGH and tc[0] >= THRESH_TOUCH and cc[0] <= THRESH_COST

    def table(group: list[str]) -> list[str]:
        g = (
            df.group_by([*group, "side", "frac"])
            .agg(
                n=pl.len(),
                **{f"t{k}": pl.col(f"touch_{k}").mean() for k in KS},
                **{f"r{k}": pl.col(f"through_{k}").mean() for k in KS},
                cost=pl.col("chase_cost").mean(),
                move=pl.col("mid_move").filter(pl.col(f"touch_{CHASE_K}")).mean(),
            )
            .sort([*group, "side", "frac"])
        )
        lines = [
            "| " + " | ".join(group) + " | side | limit | orders | touch 1/5/15 min "
            "| through 1/5/15 min | chase cost (half-spreads) | mid move after fill |",
            "|" + "---|" * (len(group) + 7),
        ]
        for r in g.iter_rows(named=True):
            lim = (
                "mid"
                if r["frac"] == 0
                else f"mid {'+' if r['side'] == 'buy' else '-'}{r['frac']:.0%}"
            )
            lines.append(
                "| " + " | ".join(str(r[c]) if not isinstance(r[c], float) else f"{r[c]:.3f}"
                                  for c in group)
                + f" | {r['side']} | {lim} | {r['n']:,} "
                f"| {r['t1']:.1%} / {r['t5']:.1%} / {r['t15']:.1%} "
                f"| {r['r1']:.1%} / {r['r5']:.1%} / {r['r15']:.1%} "
                f"| {r['cost']:.2f} | {r['move']:.2f} |"
            )  # fmt: skip
        return lines

    df = df.with_columns(
        mny_bucket=pl.when(pl.col("mny") <= MNY_NEAR).then(pl.lit("<=0.5%"))
        .when(pl.col("mny") <= MNY_MID).then(pl.lit("0.5-1.5%")).otherwise(pl.lit(">1.5%")),
        spread_bucket=pl.when(pl.col("spread_ticks") <= SPREAD_ONE).then(pl.lit("1 tick"))
        .when(pl.col("spread_ticks") <= SPREAD_FEW).then(pl.lit("2-3 ticks"))
        .otherwise(pl.lit("4+ ticks")),
    )  # fmt: skip
    out = [
        "# M24: fill feasibility of retail limit orders, QQQ options 0-2 DTE (ADR-0015)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m24_fill_study.py`. "
        f"{len(days)} development sessions ({days[0]} → {days[-1]}); the QQQ holdout was not "
        "touched. **Data only:** no orders, no strategy trial (n_trials stays 40).",
        "",
        "Hypothetical limit orders at each minute (09:55-10:35, 15:25-15:45 ET) on near-the-money "
        "contracts (±3% of the previous close) with a usable 1-minute quote.",
        "- *touch*: a print at or through the limit within k minutes.",
        "- *through*: a print strictly better, the conservative version (queue position unknown).",
        "- Only prints inside the bid-ask in force at the print are counted. This excludes likely "
        "multi-leg or late prints, which is conservative.",
        "- *Chase cost*: limit at the level, and after 5 min pay the opposite quote, in units of "
        "the quoted half-spread vs the mid at t. 1.00 = paying the ask/bid outright; 0 = the mid.",
        "",
        f"## Pre-declared verdict: **{'PROMISING' if promising else 'NOT PROMISING'}**",
        "",
        "Buy at mid, k = 5 min, all contracts pooled (session-bootstrap 95% CI):",
        f"- through: {th[0]:.1%} [{th[1]:.1%}, {th[2]:.1%}]; threshold ≥ {THRESH_THROUGH:.0%}",
        f"- touch: {tc[0]:.1%} [{tc[1]:.1%}, {tc[2]:.1%}]; threshold ≥ {THRESH_TOUCH:.0%}",
        f"- chase cost: {cc[0]:.2f} [{cc[1]:.2f}, {cc[2]:.2f}] half-spreads; threshold ≤ "
        f"{THRESH_COST:.2f}",
        "",
        "## By days to expiry",
        "",
        *table(["dte"]),
        "",
        "## By moneyness",
        "",
        *table(["mny_bucket"]),
        "",
        "## By quoted spread",
        "",
        *table(["spread_bucket"]),
        "",
        "## By window",
        "",
        *table(["window"]),
        "",
        "## Limits",
        "- A print at our price doesn't prove our order would fill: queue position and size are "
        "unknown. *through* is the safer read.",
        "- The 1-minute quotes are coarse: the mid at t can be up to 60 s old, and the bid-ask "
        "filter uses the latest 1-minute quote at each print.",
        "- QQQ 0-2 DTE near the money only. Other underlyings, tenors and sizes may differ.",
        "- Paper trading is the real check (ADR-0015 D4).",
        "",
    ]  # fmt: skip
    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(
        f"verdict {'PROMISING' if promising else 'NOT PROMISING'}; wrote {REPORT.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
