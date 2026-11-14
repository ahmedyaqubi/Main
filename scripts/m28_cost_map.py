"""M28 step 6 (ADR-0021 D5): the cost map, before any signal. M28 is not a trial.

Development sessions only (study_options_day.dev_end per ticker); no holdout file is opened.
No signal and no return of either setup is computed: at each setup's entry time the D2
contract is found for BOTH sides (ATM call and ATM put) and only its quote is read. The one
underlying quantity used, as D5 requires, is the ABSOLUTE move over the holding window.

Per ticker, setup (S1 09:35 -> 15:50; S2 15:30 -> 15:50; S2 is NO_TRADE on early-close
sessions, owner 2026-11-14) and broker (study_options_day.broker_fees, both):
- round-trip cost share: (spread x 100 + both orders' fees) / (ask x 100 + buy fees);
- share of sessions under the D2 ceiling (ask x 100 + buy fees <= max_premium_usd);
- break-even move (backtesting.cost_map.breakeven_move) and the D5 rule 1 check against the
  75th percentile of |underlying move| entry -> exit;
- required edge at the D7 ADVANCE level, with the spread of per-trade option returns taken
  from the M11 development trades (ADR-0021 D5 names M11/M12 as the source).

"Tradeable" = the D2 contract's quote is present, passes the spec §4.9 liquidity gates, and is
under the ceiling. Rule 1 is applied to tradeable contracts; an unknown break-even (no implied
volatility, or > 50%) counts as infinite, never dropped.

    uv run python scripts/m28_cost_map.py [--tickers QQQ,SPY]
"""

from __future__ import annotations

import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import yaml

from qqq1dte.backtesting.cost_map import (
    breakeven_move,
    cost_share,
    outlay,
    remaining_session_seconds,
    required_edge,
)
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import BrokerFees, Phase1Config, load_config
from qqq1dte.core.timeutil import ET, ensure_utc
from qqq1dte.execution_sim.selection import Contract, Quote, choose_contract, liquidity_failures
from qqq1dte.features.inputs import chain_table
from qqq1dte.labels.option import option_records
from qqq1dte.validation.options_day_data import (
    data_present,
    dev_partitions,
    quote_at,
    ticker_config,
)
from qqq1dte.validation.records import build_definitions

ROOT = Path(__file__).resolve().parents[1]
M28: dict[str, Any] = yaml.safe_load((ROOT / "configs" / "m28_data.yaml").read_text("utf-8"))
QQQ_CLEAN = ROOT / "data" / "clean" / "cleaned"
QQQ_REJECTED = ROOT / "data" / "clean" / "rejected"
QQQ_DEFS = ROOT / "data" / "raw" / "parquet" / "OPRA.PILLAR" / "definition"
M28_CLEAN = ROOT / "data" / "clean" / "m28"
M11_TRADES = ROOT / "data" / "backtest" / "m11_diagnostic" / "diagnostic-f52a8c29246a"
OUT = ROOT / "data" / "research" / "m28" / "cost_map_rows.parquet"
REPORT = ROOT / "reports" / "research" / "m28_step6_cost_map.md"
YEAR_S = 365.0 * 86400.0
TRADING_YEAR_S = 252 * 6.5 * 3600.0  # sensitivity: only open-market time decays
WORKERS = 6


@dataclass(frozen=True)
class Setup:
    name: str
    entry: Any  # datetime.time
    exit: Any


def _quotes(df: pl.DataFrame) -> list[Quote]:
    return [
        Quote(r["bid"], r["ask"], r.get("bid_sz"), r.get("ask_sz"), r["available_at"],
              bool(r.get("rejected", False)))
        for r in df.sort("available_at").iter_rows(named=True)
    ]  # fmt: skip


# data per ticker (development only) ---------------------------------------------------------
def load_ticker(ticker: str, cfg: Phase1Config, dev_end: date) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(underlying quotes, standard-contract chain), development sessions only."""
    if ticker == "QQQ":
        und = pl.scan_parquet(QQQ_CLEAN / "cleaned_market_data" / "bbo-1m" / "QQQ.parquet")
        names = [p.name for p in QQQ_DEFS.iterdir()]
        raw = pl.concat(
            [pl.read_parquet(f) for d in dev_partitions(names, dev_end)
             for f in (QQQ_DEFS / d).glob("*.parquet")],
            how="diagonal_relaxed",
        )  # fmt: skip
        defs = build_definitions(raw, TradingCalendar(cfg))
    else:
        und = pl.scan_parquet(M28_CLEAN / ticker / "underlying" / "cleaned.parquet")
        defs = pl.read_parquet(M28_CLEAN / ticker / "definitions.parquet")
    u = (
        und.filter(pl.col("session_date") <= dev_end)
        .select("session_date", "available_at", "bid", "ask", "bid_sz", "ask_sz", "is_rth")
        .collect()
    )
    chain = chain_table(defs, cfg).filter(pl.col("session_date") <= dev_end)
    return u, chain


def option_day(ticker: str, d: date, symbols: list[str]) -> pl.DataFrame:
    if ticker == "QQQ":
        name = f"{d}.parquet"
        cl = pl.read_parquet(QQQ_CLEAN / "cleaned_options_data" / "cbbo-1m" / name)
        rj = pl.read_parquet(QQQ_REJECTED / "cleaned_options_data" / "cbbo-1m" / name)
    else:
        base = M28_CLEAN / ticker / "options"
        cl = pl.concat([pl.read_parquet(f) for f in (base / "cleaned").glob(f"{d}_*.parquet")],
                       how="diagonal_relaxed")  # fmt: skip
        rjf = list((base / "rejected").glob(f"{d}_*.parquet"))
        rj = (
            pl.concat([pl.read_parquet(f) for f in rjf], how="diagonal_relaxed")
            if rjf
            else cl.head(0).with_columns(ts=pl.col("available_at"))
        )
    return option_records(cl, rj).filter(pl.col("symbol").is_in(symbols))


# per session ------------------------------------------------------------------------------
def session_rows(args: tuple[str, date, pl.DataFrame, pl.DataFrame]) -> list[dict[str, Any]]:  # noqa: PLR0915
    ticker, d, u, ch = args
    cfg = ticker_config(load_config(), ticker)
    cal = TradingCalendar(cfg)
    s = cfg.study_options_day
    fees = s.broker_fees
    uq = _quotes(u.filter(pl.col("is_rth")).with_columns(rejected=pl.lit(False)))
    i_ahead = cal.sessions(d + timedelta(days=1), d + timedelta(days=14))
    ahead = i_ahead[s.min_sessions_to_expiry - 1 : s.max_sessions_to_expiry]
    exps = sorted(e for e in set(ch["expiration"].to_list()) if e in ahead)
    base: dict[str, Any] = {"ticker": ticker, "session_date": d}
    if not exps:
        return [{**base, "setup": n, "status": "NO_D2_EXPIRY"} for n in ("S1", "S2")]
    expiry = exps[0]
    ech = ch.filter(pl.col("expiration") == expiry)
    contracts = [
        Contract(r["raw_symbol"], r["strike"], r["right"], r["expiration"], r["available_at"])
        for r in ech.iter_rows(named=True)
    ]
    recs = option_day(ticker, d, ech["raw_symbol"].to_list())
    by_sym = {k[0]: _quotes(g) for k, g in recs.group_by("symbol")}
    _, exp_close = cal.open_close(expiry)
    windows = [cal.open_close(x) for x in cal.sessions(d, expiry)]
    forced = cal.forced_exit_time(d)
    rows: list[dict[str, Any]] = []
    for st in (Setup("S1", s.orb.entry_time, s.orb.exit_time),
               Setup("S2", s.half_hour.entry_time, s.half_hour.exit_time)):  # fmt: skip
        b = {**base, "setup": st.name, "expiry": expiry}
        if st.name == "S2" and cal.is_early_close(d):
            rows.append({**b, "status": "EARLY_CLOSE"})
            continue
        t_e = ensure_utc(datetime.combine(d, st.entry, tzinfo=ET))
        t_x = min(ensure_utc(datetime.combine(d, st.exit, tzinfo=ET)), forced)
        sq, xq = quote_at(uq, t_e), quote_at(uq, t_x)
        if not (data_present(sq, t_e, cfg) and data_present(xq, t_x, cfg)):
            rows.append({**b, "status": "NO_UNDERLYING_QUOTE"})
            continue
        assert sq is not None and xq is not None
        spot = (float(sq.bid) + float(sq.ask)) / 2  # type: ignore[arg-type]
        spot_x = (float(xq.bid) + float(xq.ask)) / 2  # type: ignore[arg-type]
        move = abs(spot_x / spot - 1)  # absolute: direction is never looked at
        t_entry = (exp_close - t_e).total_seconds() / YEAR_S
        t_exit = (exp_close - t_x).total_seconds() / YEAR_S
        tt_entry = remaining_session_seconds(t_e, windows) / TRADING_YEAR_S
        tt_exit = remaining_session_seconds(t_x, windows) / TRADING_YEAR_S
        for side in ("C", "P"):
            r = {**b, "side": side, "abs_move": move, "spot": spot}
            c = choose_contract(contracts, spot, side, t_e)
            if c is None:
                rows.append({**r, "status": "NO_CONTRACT"})
                continue
            q = quote_at(by_sym.get(c.symbol, []), t_e)
            if not data_present(q, t_e, cfg) or q is None:
                rows.append({**r, "symbol": c.symbol, "status": "NO_OPTION_QUOTE"})
                continue
            bid, ask = float(q.bid), float(q.ask)  # type: ignore[arg-type]
            liq = liquidity_failures(q, t_e, cfg)
            r |= {"symbol": c.symbol, "strike": c.strike, "bid": bid, "ask": ask,
                  "liquid": not liq, "liquidity_reasons": ";".join(sorted(liq)),
                  "status": "PRICED"}  # fmt: skip
            for broker, f in fees.items():
                out = outlay(ask, f)
                r[f"{broker}_outlay"] = out
                r[f"{broker}_under_cap"] = out <= s.max_premium_usd
                r[f"{broker}_cost_share"] = cost_share(bid, ask, f)
                r[f"{broker}_breakeven"] = breakeven_move(
                    spot, c.strike, side, t_entry, t_exit, bid, ask, f
                )
                r[f"{broker}_breakeven_tt"] = breakeven_move(
                    spot, c.strike, side, tt_entry, tt_exit, bid, ask, f
                )
            rows.append(r)
    return rows


# M11 spread of per-trade returns ------------------------------------------------------------
def m11_sd(fees: BrokerFees, dev_end: date) -> tuple[float, int, int]:
    """Per-trade net return as a share of the premium paid, M11 conservative development
    trades, costs re-applied with this broker's fees (not the Phase 1 costs block). Trades
    with no exit price (M11 PATH_GAP_TOO_LONG) have no return; they are counted, not used."""
    t = pl.read_parquet(M11_TRADES / "trades.parquet").filter(
        (pl.col("fill_model") == "CONSERVATIVE") & (pl.col("session_date") <= dev_end)
    )
    no_exit = t.filter(pl.col("exit_price").is_null()).height
    t = t.filter(pl.col("exit_price").is_not_null())
    ret = [
        ((x - e) * 100 - fees.order_cost(1, e, sell=False) - fees.order_cost(1, x, sell=True))
        / (e * 100)
        for e, x in zip(t["entry_price"].to_list(), t["exit_price"].to_list(), strict=True)
    ]
    return float(np.std(ret, ddof=1)), len(ret), no_exit


def degraded_days(start: date, end: date) -> dict[str, list[str]]:
    """Days Databento marks as not fully available (free metadata call; cached unchanged)."""
    path = OUT.parent / "dataset_condition.json"
    if not path.exists():
        import certifi  # noqa: PLC0415 (only for this network call)
        import databento as db  # noqa: PLC0415
        from dotenv import load_dotenv  # noqa: PLC0415

        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        load_dotenv(ROOT / ".env")
        client = db.Historical()
        raw = {
            ds: client.metadata.get_dataset_condition(
                dataset=ds, start_date=start.isoformat(), end_date=end.isoformat()
            )
            for ds in (M28["option_dataset"], M28["underlying_dataset"])
        }
        path.write_text(json.dumps(raw, indent=1), "utf-8")
    raw = json.loads(path.read_text("utf-8"))
    return {
        ds: [r["date"] for r in rows if r["condition"] != "available"] for ds, rows in raw.items()
    }


# report -------------------------------------------------------------------------------------
def _q(x: list[float], p: float) -> float:
    return float(np.quantile(np.asarray(x, dtype=float), p)) if x else math.nan


def summarise(df: pl.DataFrame, cfg: Phase1Config) -> list[dict[str, Any]]:
    s = cfg.study_options_day
    out: list[dict[str, Any]] = []
    for (ticker, setup), g in sorted(df.group_by(["ticker", "setup"]), key=lambda kv: kv[0]):
        sessions = g["session_date"].n_unique()
        priced = g.filter(pl.col("status") == "PRICED")
        moves = (
            g.filter(pl.col("abs_move").is_not_null())
            .unique("session_date")["abs_move"].to_list()
        )  # fmt: skip
        p75 = _q(moves, s.breakeven_move_percentile)
        for broker in s.broker_fees:
            trad = priced.filter(pl.col("liquid") & pl.col(f"{broker}_under_cap"))
            be = [math.inf if v is None else v for v in trad[f"{broker}_breakeven"].to_list()]
            med_be = float(np.median(be)) if be else math.nan
            bt = [math.inf if v is None else v for v in trad[f"{broker}_breakeven_tt"].to_list()]
            med_bt = float(np.median(bt)) if bt else math.nan
            out.append(
                {
                    "ticker": ticker, "setup": setup, "broker": broker,
                    "sessions": sessions,
                    "statuses": dict(g.group_by("status").len().iter_rows()),
                    "priced_contracts": priced.height,
                    "liquid_share": priced["liquid"].mean() if priced.height else math.nan,
                    "under_cap_share": (
                        priced[f"{broker}_under_cap"].mean() if priced.height else math.nan
                    ),
                    "tradeable": trad.height,
                    "tradeable_per_side": trad.height / 2,
                    "cost_share_median": _q(trad[f"{broker}_cost_share"].to_list(), 0.5),
                    "cost_share_p25": _q(trad[f"{broker}_cost_share"].to_list(), 0.25),
                    "cost_share_p75": _q(trad[f"{broker}_cost_share"].to_list(), 0.75),
                    "outlay_median": _q(trad[f"{broker}_outlay"].to_list(), 0.5),
                    "breakeven_median": med_be,
                    "breakeven_unknown": sum(math.isinf(v) for v in be),
                    "abs_move_p75": p75,
                    "rule1_pass": bool(be) and med_be <= p75,
                    "breakeven_tt_median": med_bt,
                    "breakeven_tt_unknown": sum(math.isinf(v) for v in bt),
                    "rule1_tt_pass": bool(bt) and med_bt <= p75,
                }
            )  # fmt: skip
    return out


def main() -> int:
    cfg0 = load_config()
    s = cfg0.study_options_day
    tickers = (
        sys.argv[sys.argv.index("--tickers") + 1].split(",")
        if "--tickers" in sys.argv
        else list(s.tickers)
    )
    rows: list[dict[str, Any]] = []
    for t in tickers:
        cfg = ticker_config(cfg0, t)
        cal = TradingCalendar(cfg)
        dev_end = s.dev_end[t]
        start = cfg.history.option_era_start if t == "QQQ" else date.fromisoformat(M28["start"])
        sessions = cal.research_sessions(start, dev_end)
        u, ch = load_ticker(t, cfg, dev_end)
        assert u["session_date"].max() <= dev_end  # type: ignore[operator]
        args = [
            (t, d, u.filter(pl.col("session_date") == d), ch.filter(pl.col("session_date") == d))
            for d in sessions
        ]
        with ProcessPoolExecutor(WORKERS) as pool:
            for n, rs in enumerate(pool.map(session_rows, args, chunksize=4), 1):
                rows.extend(rs)
                if n % 200 == 0:
                    print(f"{t}: {n}/{len(sessions)} sessions", flush=True)
        print(f"{t}: done, {len(sessions)} sessions", flush=True)

    df = pl.DataFrame(rows, infer_schema_length=None)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(OUT)
    summ = summarise(df, cfg0)
    level = 1 - s.family_alpha / s.max_tests
    sds = {b: m11_sd(f, s.dev_end["QQQ"]) for b, f in s.broker_fees.items()}
    bad = degraded_days(date.fromisoformat(M28["start"]), max(s.dev_end.values()))
    write_report(summ, sds, level, tickers, cfg0, df, bad)
    print(f"wrote {REPORT.relative_to(ROOT)}")
    return 0


def _fmt(x: float, pct: bool = True) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    if isinstance(x, float) and math.isinf(x):
        return "inf"
    return f"{x:.2%}" if pct else f"{x:.2f}"


def write_report(
    summ: list[dict[str, Any]],
    sds: dict[Any, tuple[float, int, int]],
    level: float,
    tickers: list[str],
    cfg: Phase1Config,
    df: pl.DataFrame,
    bad: dict[str, list[str]],
) -> None:
    s = cfg.study_options_day
    lines = [
        "# M28 step 6: cost map (ADR-0021 D5). Not a trial.",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m28_cost_map.py`. "
        "Development sessions only; no signal or return of either setup was computed (calls "
        "and puts priced alike; the underlying move is used only as an absolute value).",
        "",
        "## Per ticker, setup and broker",
        "",
        "Tradeable = quote present, passes the §4.9 liquidity gates, and ask x 100 + buy fees "
        f"<= ${s.max_premium_usd:.0f}. Cost share and break-even are over tradeable contracts "
        "(call and put rows both counted).",
        "",
        "| ticker | setup | broker | sessions | liquid | under cap | tradeable/side | cost share "
        "median (P25-P75) | median outlay | median break-even, calendar / trading hours (unknown) "
        "| P75 abs move | D5 rule 1, calendar / trading hours |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in summ:
        lines.append(
            f"| {r['ticker']} | {r['setup']} | {r['broker']} | {r['sessions']} | "
            f"{_fmt(r['liquid_share'])} | {_fmt(r['under_cap_share'])} | "
            f"{r['tradeable_per_side']:.0f} | {_fmt(r['cost_share_median'])} "
            f"({_fmt(r['cost_share_p25'])}-{_fmt(r['cost_share_p75'])}) | "
            f"${_fmt(r['outlay_median'], False)} | {_fmt(r['breakeven_median'])} / "
            f"{_fmt(r['breakeven_tt_median'])} ({r['breakeven_unknown']} / "
            f"{r['breakeven_tt_unknown']}) | {_fmt(r['abs_move_p75'])} | "
            f"{'kept' if r['rule1_pass'] else '**DROPPED**'} / "
            f"{'kept' if r['rule1_tt_pass'] else '**DROPPED**'} |"
        )
    lines += ["", "Session statuses (rows per side):", ""]
    seen = set()
    for r in summ:
        k = (r["ticker"], r["setup"])
        if k not in seen:
            seen.add(k)
            lines.append(f"- {k[0]} {k[1]}: {r['statuses']}")
    lines += [
        "",
        "## Required edge (D5 rule 2: information only, ADR-0021 amendment A2)",
        "",
        "Rule 2 is **not applied**: for S1 the required edge (share of premium) and the paper's "
        "0.13 (of the stop distance on shares) are in different units, and converting needs the "
        "signal; S2's paper effect is unverified. The figures below are also too low, especially "
        "for S1: the M11 trades they come from were closed by target and stop exits (median hold "
        "about 20-25 minutes); S1 holds 09:35 -> 15:50 with no such limit. Drops are decided by "
        "rule 1 alone.",
        "",
        f"ADVANCE level (D7): {level:.4%}, one-sided. Spread of per-trade net returns, as a "
        "share of the premium paid, from the M11 conservative development trades with each "
        "broker's fees re-applied:",
        "",
    ]
    for b, (sd, n, no_exit) in sds.items():
        lines.append(
            f"- {b}: sd {sd:.4f} over {n:,} trades ({no_exit} M11 trades with no exit price "
            "left out: no return exists for them)"
        )
    lines += [
        "",
        "Expected trades per setup = tradeable sessions per side, summed over the tickers kept "
        "by rule 1 (one trade per ticker-session; D6 pools the tickers in one run).",
        "",
        "| setup | broker | tickers kept | expected trades | required mean net return per trade |",
        "|---|---|---|---|---|",
    ]
    for setup in ("S1", "S2"):
        for b, (sd, _, _) in sds.items():
            kept = [r for r in summ if r["setup"] == setup and r["broker"] == b and r["rule1_pass"]]
            n = int(sum(r["tradeable_per_side"] for r in kept))
            req = required_edge(sd, n, level) if n else math.nan
            lines.append(
                f"| {setup} | {b} | {', '.join(r['ticker'] for r in kept) or 'none'} | {n:,} | "
                f"{_fmt(req)} of premium |"
            )
    lines += [
        "",
        "## Days Databento marks as reduced quality",
        "",
        "From `metadata.get_dataset_condition` (cached in `data/research/m28/"
        "dataset_condition.json`). Rows are this map's D2 contracts on those days, per ticker "
        "(development sessions only), by status:",
        "",
        *[
            f"- {ds} {day}: "
            + (
                "; ".join(
                    f"{k[0]} {dict(g.group_by('status').len().iter_rows())}"
                    for k, g in sorted(
                        df.filter(pl.col("session_date") == date.fromisoformat(day)).group_by(
                            "ticker"
                        ),
                        key=lambda kv: str(kv[0]),
                    )
                )
                or "not a development session of any ticker in this run"
            )
            for ds, days in bad.items()
            for day in days
        ],
        "",
        "Tickers in this run: " + ", ".join(tickers) + ".",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
