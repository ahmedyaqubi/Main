"""M29 (ADR-0021 D6): the one registered screen of setup S1 (amendment A1), pooled over the
tickers. It is a trial (1 of the 3 tests ADR-0021 D7 allows): registered BEFORE any signal or
statistic is computed, from committed code, with n_trials recorded before and after.

Development sessions only (study_options_day.dev_end per ticker). Files are chosen by the date
in their name; no holdout file is opened. AAPL is out (D1: unverified earnings dates).

- Step A: mean signed return of the underlying, entry -> exit, over every ticker-session with a
  signal; one-sided lower bound at step_a_level. <= 0: the setup stops.
- Step B: mean net P&L / premium paid over the trades taken under the one-position rule, buy at
  the ask and sell at the bid, the decision broker's fees. ADVANCE: lower bound > 0 at the D7
  level with >= min_trades. KILL: two-sided upper bound < 0 at the mid fill. Else AMBIGUOUS.
- Session bootstrap, study_options_day.bootstrap_reps, seed models.metrics.bootstrap_seed.

    uv run python scripts/m29_screen.py
    uv run python scripts/m29_screen.py --dry-run-report FILE   # synthetic prices, no database
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import sys
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine

from m26_screen import dirty
from m28_cost_map import M28, M28_CLEAN, QQQ_CLEAN, _quotes, load_ticker, option_day
from qqq1dte.backtesting.cost_map import bs_price
from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import code_commit
from qqq1dte.backtesting.orb_screen import (
    CANDIDATE,
    Bounds,
    cap_hit_index,
    longest_losing_run,
    max_drawdown,
    mean_bounds,
    pick_one,
    screen_outcome,
    session_decision,
    trade_pnl,
)
from qqq1dte.backtesting.registry import complete_run, fail_run, n_trials, register_run
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config, config_hash, load_config
from qqq1dte.execution_sim.selection import Contract, Quote
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.validation.earnings_calendar import earnings_exclusions, earnings_table
from qqq1dte.validation.options_day_data import ticker_config

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "research" / "m29_s1_screen.md"
OUT = ROOT / "data" / "research" / "m29" / "s1_rows.parquet"
EARNINGS = ROOT / "configs" / "reference" / "earnings_calendar.csv"
TICKERS = ["QQQ", "SPY", "IWM", "NVDA", "TSLA"]  # D1 list less AAPL (dropped, M28)
DECISION_BROKER = "ibkr_canada"  # A1: provisional broker; also the dearer for one contract
OTHER_BROKER = "webull_canada"
WORKERS = 6
RULINGS = {  # owner, 2026-11-15 ("Approve all"); recorded in the registered config
    "1_candle_high_low": "max/min of the 1-minute quote mids stamped candle_start..candle_end",
    "2_step_a_population": "every ticker-session with a signal, before option gates and D3",
    "3_d3_competitors": "only contracts passing every gate; ties by ticker order",
    "4_decision_fees": DECISION_BROKER,
    "5_return_denominator": "entry fill x 100, fees in the numerator only",
    "6_kill_at_mid": "the conservative run's trades repriced at the mid, with fees",
    "7_exit_quote": "first later minute with a usable quote; none by forced exit = unresolved",
    "8_loss_cap": "drawdown and cap date reported; the series is not stopped",
    "9_candle_open": "latest quote at or before 09:30:00, at most max_quote_age_s old "
    "(pre-open quotes allowed); none = NO_UNDERLYING_QUOTE",
}


# one ticker-session (worker) ---------------------------------------------------------------
def d2_contracts(
    ch: pl.DataFrame, d: date, cal: TradingCalendar, cfg: Phase1Config
) -> list[Contract]:
    """The chain of the D2 expiry: the nearest listed one min..max sessions after d."""
    s = cfg.study_options_day
    ahead = cal.sessions(d + timedelta(days=1), d + timedelta(days=14))
    ahead = ahead[s.min_sessions_to_expiry - 1 : s.max_sessions_to_expiry]
    exps = sorted(e for e in set(ch["expiration"].to_list()) if e in ahead)
    if not exps:
        return []
    return [
        Contract(r["raw_symbol"], r["strike"], r["right"], r["expiration"], r["available_at"])
        for r in ch.filter(pl.col("expiration") == exps[0]).iter_rows(named=True)
    ]


def work(args: tuple[str, date, pl.DataFrame, pl.DataFrame, bool]) -> dict[str, Any]:
    ticker, d, u, ch, excluded = args
    cfg = ticker_config(load_config(), ticker)
    cal = TradingCalendar(cfg)
    fees = cfg.study_options_day.broker_fees[DECISION_BROKER]  # type: ignore[index]
    uq = _quotes(u.with_columns(rejected=pl.lit(False)))
    contracts = d2_contracts(ch, d, cal, cfg)
    c = session_decision(
        ticker, d, uq, contracts, lambda sym: _quotes(option_day(ticker, d, [sym])),
        cfg, cal, fees, excluded=excluded,
    )  # fmt: skip
    row = asdict(c)
    if c.status == "NO_CONTRACT" and not contracts:
        row["status"] = "NO_D2_EXPIRY"
    return row


def dev_files(ticker: str, sessions: Sequence[date]) -> list[Path]:
    """The option files a ticker's development sessions will read, chosen by date in the name."""
    if ticker == "QQQ":
        base = QQQ_CLEAN / "cleaned_options_data" / "cbbo-1m"
        return [base / f"{d}.parquet" for d in sessions]
    base = M28_CLEAN / ticker / "options" / "cleaned"
    days = {str(d) for d in sessions}
    return sorted(f for f in base.glob("*.parquet") if f.name[:10] in days)


def real_rows(cfg0: Phase1Config, plan: dict[str, list[date]]) -> list[dict[str, Any]]:
    s = cfg0.study_options_day
    table = earnings_table(EARNINGS)
    rows: list[dict[str, Any]] = []
    for t, sessions in plan.items():
        cfg = ticker_config(cfg0, t)
        cal = TradingCalendar(cfg)
        excl = (
            earnings_exclusions(table, t, cal, s.earnings_exclusion_sessions)
            if t in s.single_stocks
            else {}
        )
        u, ch = load_ticker(t, cfg, s.dev_end[t])
        assert u["session_date"].max() <= s.dev_end[t]  # type: ignore[operator]
        args = [
            (t, d, u.filter(pl.col("session_date") == d), ch.filter(pl.col("session_date") == d),
             d in excl)
            for d in sessions
        ]  # fmt: skip
        with ProcessPoolExecutor(WORKERS) as pool:
            rows.extend(pool.map(work, args, chunksize=4))
        print(f"{t}: {len(sessions)} sessions", flush=True)
    return rows


# synthetic inputs (dry run) ----------------------------------------------------------------
def synthetic_rows(cfg0: Phase1Config) -> list[dict[str, Any]]:
    """Random-walk underlyings and Black-Scholes option quotes: exercises the whole pipeline
    without market data or the database. The numbers mean nothing."""
    rng = np.random.default_rng(cfg0.models.metrics.bootstrap_seed)
    s = cfg0.study_options_day
    fees = s.broker_fees[DECISION_BROKER]  # type: ignore[index]
    cal = TradingCalendar(cfg0)
    sessions = cal.sessions(date(2024, 1, 2), date(2024, 4, 30))
    rows = []
    for ticker, s0 in (("QQQ", 420.0), ("SPY", 480.0), ("IWM", 200.0)):
        cfg = ticker_config(cfg0, ticker)
        for d in sessions:
            open_, close = cal.open_close(d)
            n = int((close - open_).total_seconds() // 60)
            mids = s0 * np.exp(np.cumsum(rng.normal(0, 0.0006, n + 2)))
            times = [open_ + timedelta(minutes=i) for i in range(n + 1)]
            uq = [
                Quote(round(m - 0.005, 2), round(m - 0.005, 2) + 0.01, 100, 100, t)
                for t, m in zip(times, mids, strict=False)
            ]
            expiry = cal.next_session(d)
            _, exp_close = cal.open_close(expiry)
            listed = open_ - timedelta(hours=12)
            base = round(s0)
            chain = [
                Contract(f"{ticker}{k}{r}", float(k), r, expiry, listed)
                for k in range(base - 40, base + 41)
                for r in "CP"
            ]
            strikes = {c.symbol: c for c in chain}

            def quotes_for(
                sym: str,
                strikes: dict[str, Contract] = strikes,
                times: list[datetime] = times,
                mids: Any = mids,
                exp_close: datetime = exp_close,
            ) -> list[Quote]:
                c = strikes[sym]
                out = []
                for t, m in zip(times, mids, strict=False):
                    yrs = (exp_close - t).total_seconds() / (365 * 86400)
                    p = bs_price(float(m), c.strike, yrs, 0.18, c.right)
                    bid = math.floor(p * 100) / 100 - 0.01
                    out.append(Quote(bid if bid > 0 else None, bid + 0.03, 10, 10, t))
                return out

            rows.append(asdict(session_decision(ticker, d, uq, chain, quotes_for, cfg, cal, fees)))
    return rows


# pooling and statistics --------------------------------------------------------------------
_OPTION_PNL = ("exit_time", "exit_reason", "exit_delay_minutes", "exit_no_bid", "exit_fill",
               "net_usd", "ret", "exit_mid", "net_usd_mid", "ret_mid")  # fmt: skip


def apply_one_position(rows: list[dict[str, Any]], order: list[str]) -> list[dict[str, Any]]:
    """D3: per session, the candidate with the lowest cost share trades; the others become
    POSITION_OPEN and their option exit is blanked (it was never a trade)."""
    by_day: dict[date, list[dict[str, Any]]] = {}
    for r in rows:
        if r["status"] == CANDIDATE:
            by_day.setdefault(r["session_date"], []).append(r)
    for cands in by_day.values():
        cands.sort(key=lambda r: order.index(r["ticker"]))
        keep = pick_one([(r["ticker"], r["cost_share"]) for r in cands])
        for r in cands:
            if r["ticker"] == keep:
                r["status"] = "TRADE"
            else:
                r["status"] = "POSITION_OPEN"
                for k in _OPTION_PNL:
                    r[k] = None
    return rows


def _b(b: Bounds) -> dict[str, Any]:
    return asdict(b)


def analyse(
    rows: list[dict[str, Any]], cfg: Phase1Config, n_trials_total: int | None = None
) -> dict[str, Any]:
    """`n_trials_total`: the full recorded trial count this run is judged against in the
    descriptive row (default: the config's count plus this run, as in M29)."""
    s = cfg.study_options_day
    reps, seed = s.bootstrap_reps, cfg.models.metrics.bootstrap_seed
    fees, other = s.broker_fees[DECISION_BROKER], s.broker_fees[OTHER_BROKER]  # type: ignore[index]
    sig = [r for r in rows if r["und_return"] is not None]
    a = mean_bounds([r["session_date"] for r in sig], [r["und_return"] for r in sig],
                    reps=reps, seed=seed, lower_level=s.step_a_level)  # fmt: skip
    taken = sorted((r for r in rows if r["status"] == "TRADE"), key=lambda r: r["session_date"])
    done = [r for r in taken if r["ret"] is not None]
    unresolved = [r for r in taken if r["ret"] is None]
    sid = [r["session_date"] for r in done]
    ret = [r["ret"] for r in done]
    level_all = 1 - s.family_alpha / (n_trials_total or s.n_trials_recorded + 1)
    b = mean_bounds(sid, ret, reps=reps, seed=seed, lower_level=s.advance_level,
                    two_sided_level=s.kill_level)  # fmt: skip
    b_all = mean_bounds(sid, ret, reps=reps, seed=seed, lower_level=level_all)
    k = mean_bounds(sid, [r["ret_mid"] for r in done], reps=reps, seed=seed,
                    lower_level=s.advance_level, two_sided_level=s.kill_level)  # fmt: skip
    outcome = screen_outcome(
        step_a_lower=a.lower, b_lower=b.lower, trades=len(done), min_trades=s.min_trades,
        kill_upper=k.two_sided_high,
    )  # fmt: skip
    usd = [r["net_usd"] for r in done]
    lost = [trade_pnl(r["entry_fill"], 0.0, fees)[1] for r in unresolved]
    cap = cap_hit_index(usd, s.account_usd * s.total_loss_cap)
    worst = min(done, key=lambda r: r["ret"]) if done else None

    def group(key: Any) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for g in sorted({key(r) for r in done}):
            x = [r for r in done if key(r) == g]
            out[str(g)] = {
                "trades": len(x),
                "mean_ret": float(np.mean([r["ret"] for r in x])),
                "win_share": float(np.mean([r["ret"] > 0 for r in x])),
                "sum_usd": float(sum(r["net_usd"] for r in x)),
                "calls": sum(r["side"] == "C" for r in x),
            }
        return out

    return {
        "outcome": outcome,
        "step_a": _b(a), "step_a_passes": a.lower > 0,
        "step_b": _b(b), "step_b_lower_all_trials": b_all.lower, "level_all_trials": level_all,
        "mid_fill": _b(k),
        "trades": len(done), "unresolved": len(unresolved), "few_trades": len(done) < s.min_trades,
        "mean_ret_unresolved_as_total_loss": float(np.mean([*ret, *lost])) if done else math.nan,
        "mean_ret_other_broker": float(
            np.mean([trade_pnl(r["entry_fill"], r["exit_fill"], other)[1] for r in done])
        ) if done else math.nan,
        "mean_usd": float(np.mean(usd)) if done else math.nan,
        "sum_usd": float(sum(usd)),
        "win_share": float(np.mean([x > 0 for x in ret])) if done else math.nan,
        "exit_reasons": dict(Counter(r["exit_reason"] for r in taken)),
        "und_exit_reasons_all_signals": dict(Counter(r["und_exit_reason"] for r in sig)),
        "worst_trade": None if worst is None else {
            "ticker": worst["ticker"], "session_date": str(worst["session_date"]),
            "ret": worst["ret"], "net_usd": worst["net_usd"],
        },
        "longest_losing_run": longest_losing_run(usd),
        "max_drawdown_usd": max_drawdown(usd),
        "loss_cap_hit": None if cap is None else str(done[cap]["session_date"]),
        "delayed_exits": sum(1 for r in done if r["exit_delay_minutes"]),
        "no_bid_exits": sum(1 for r in done if r["exit_no_bid"]),
        "und_gap_minutes": sum(r["und_gap_minutes"] for r in rows),
        "max_strike_gap": max((abs(r["strike"] / r["und_entry"] - 1) for r in taken), default=0.0),
        "statuses": {
            t: dict(Counter(r["status"] for r in rows if r["ticker"] == t))
            for t in sorted({r["ticker"] for r in rows})
        },
        "per_ticker": group(lambda r: r["ticker"]),
        "per_year": group(lambda r: r["session_date"].year),
    }  # fmt: skip


# registration ------------------------------------------------------------------------------
def register(
    engine: Engine, cfg: Phase1Config, plan: dict[str, list[date]]
) -> tuple[int, str, int]:
    """Record the data and register the trial BEFORE any signal or statistic is computed."""
    s = cfg.study_options_day
    h = hashlib.sha256()
    n_files = 0
    for t, sessions in plan.items():
        for f in dev_files(t, sessions):
            h.update(f"{t}/{f.name}:{f.stat().st_size}".encode())
            n_files += 1
    window = (cfg.history.option_era_start, max(s.dev_end[t] for t in plan))
    ds_id = f"options_day_dev_{h.hexdigest()[:16]}"
    commit = code_commit(ROOT)
    record_dataset(
        engine,
        DatasetVersion(
            dataset_id=ds_id, kind="cleaned_options_data", source="databento",
            coverage_start=window[0], coverage_end=window[1], row_count=n_files,
            storage_uri="data/clean", code_commit=commit,
            config_hash=config_hash(s.model_dump(mode="json")),
        ),
    )  # fmt: skip
    n_before = n_trials(engine, *window)
    run_id = register_run(
        engine,
        run_kind="screen_orb",
        config={
            "study_options_day": s.model_dump(mode="json"),
            "setup": "S1 (ADR-0021 amendment A1)",
            "tickers": list(plan),
            "sessions_per_ticker": {t: len(v) for t, v in plan.items()},
            "decision_broker": DECISION_BROKER,
            "bootstrap_seed": cfg.models.metrics.bootstrap_seed,
            "owner_rulings_2026_11_15": RULINGS,
            "phase1_config_hash": config_hash(cfg.model_dump(mode="json")),
            "adr": "ADR-0021 D6, test 1 of 3",
        },
        data_window=window,
        dataset_id=ds_id,
        code_commit=commit,
        folds=[],
    )
    n_after = n_trials(engine, *window)
    print(f"registered {run_id}; n_trials {n_before} -> {n_after}", flush=True)
    return n_before, run_id, n_after


def session_plan(cfg0: Phase1Config) -> dict[str, list[date]]:
    """Development sessions per ticker; HoldoutGuard refuses any session after dev_end."""
    s = cfg0.study_options_day
    plan = {}
    for t in TICKERS:
        cfg = ticker_config(cfg0, t)
        start = cfg.history.option_era_start if t == "QQQ" else date.fromisoformat(M28["start"])
        sessions = TradingCalendar(cfg).research_sessions(start, s.dev_end[t])
        HoldoutGuard(s.dev_end[t], None).check(sessions)
        plan[t] = sessions
    return plan


# report ------------------------------------------------------------------------------------
def pc(x: float | None, nd: int = 2) -> str:
    return "-" if x is None or math.isnan(x) else f"{x:.{nd}%}"


def write_report(
    path: Path, m: dict[str, Any], cfg: Phase1Config, run_id: str, n_before: int, n_after: int,
    plan: dict[str, list[date]] | None,
) -> None:  # fmt: skip
    s = cfg.study_options_day
    a, b, k = m["step_a"], m["step_b"], m["mid_fill"]
    dry = plan is None
    a_text = "above 0: Step A passes" if m["step_a_passes"] else "not above 0: the setup stops here"
    cap_text = "never reached" if m["loss_cap_hit"] is None else f"reached on {m['loss_cap_hit']}"
    over_cap = sum(v.get("PREMIUM_OVER_CAP", 0) for v in m["statuses"].values())
    pos_open = sum(v.get("POSITION_OPEN", 0) for v in m["statuses"].values())
    seed = cfg.models.metrics.bootstrap_seed
    out = [
        "# M29: D6 screen of setup S1, first 5-minute candle (ADR-0021, amendment A1)"
        + (" — DRY RUN, SYNTHETIC PRICES" if dry else ""),
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m29_screen.py`, code "
        f"{code_commit(ROOT)[:12]}. Registered run `{run_id}` (n_trials {n_before} → {n_after}). "
        "Test 1 of the 3 that ADR-0021 D7 allows. Development sessions only; no holdout file "
        "was opened.",
        "",
        f"## Outcome: **{m['outcome']}**",
        "",
        "### Step A: the underlying",
        f"- Mean signed return, entry → exit, over {a['n']:,} ticker-sessions with a signal "
        f"({a['sessions']:,} sessions): **{pc(a['mean'], 4)}**",
        f"- One-sided {s.step_a_level:.0%} lower bound: **{pc(a['lower'], 4)}** "
        f"({a_text})",
        f"- Two-sided {s.kill_level:.0%} interval: [{pc(a['two_sided_low'], 4)}, "
        f"{pc(a['two_sided_high'], 4)}]",
        "",
        "### Step B: the option trades"
        + ("" if m["step_a_passes"] else " (descriptive only: Step A did not pass)"),
        f"- Trades: **{m['trades']:,}** (guard ≥ {s.min_trades}"
        f"{', NOT MET' if m['few_trades'] else ', met'}); one position at a time; buy at the ask, "
        f"sell at the bid; `{DECISION_BROKER}` fees",
        f"- Mean net P&L per trade as a share of the premium paid: **{pc(b['mean'])}**",
        f"- One-sided {s.advance_level:.2%} lower bound: **{pc(b['lower'])}** (ADVANCE needs > 0)",
        f"- Two-sided {s.kill_level:.0%} interval: [{pc(b['two_sided_low'])}, "
        f"{pc(b['two_sided_high'])}]",
        f"- Lower bound at the full recorded count ({s.n_trials_recorded} + 1 trials, one-sided "
        f"{m['level_all_trials']:.3%}): {pc(m['step_b_lower_all_trials'])}",
        f"- **Mid fill (KILL row), same trades:** mean {pc(k['mean'])}, two-sided "
        f"{s.kill_level:.0%} interval [{pc(k['two_sided_low'])}, {pc(k['two_sided_high'])}] "
        "(KILL needs the upper bound < 0)",
        f"- Session bootstrap, {s.bootstrap_reps:,} reps, seed {seed}.",
        "",
        "Development-data result with its uncertainty. Not a claim of profitability, and not "
        "out-of-sample.",
        "",
        "## Risk rows (always reported)",
        "",
        f"- Mean net per trade: ${m['mean_usd']:.2f}; total over the period: ${m['sum_usd']:,.2f} "
        "(one contract per trade)",
        f"- Winning trades: {pc(m['win_share'], 1)}",
        "- Worst trade: "
        + ("-" if m["worst_trade"] is None else
           f"{m['worst_trade']['ticker']} {m['worst_trade']['session_date']}, "
           f"{pc(m['worst_trade']['ret'])} (${m['worst_trade']['net_usd']:.2f})"),
        f"- Longest losing run: {m['longest_losing_run']} trades",
        f"- Largest drawdown: ${m['max_drawdown_usd']:,.2f}",
        f"- ${s.account_usd * s.total_loss_cap:,.0f} total loss cap (reported, the series is not "
        f"stopped): {cap_text}",
        f"- `PREMIUM_OVER_CAP`: {over_cap:,}; `POSITION_OPEN`: {pos_open:,}",
        f"- Exits of the trades taken: {m['exit_reasons']}",
        f"- Trades with no usable exit quote by the forced exit (`UNRESOLVED_DATA`, left out): "
        f"{m['unresolved']}; mean with those counted as a total loss: "
        f"{pc(m['mean_ret_unresolved_as_total_loss'])}",
        f"- Exits sold later than the trigger minute (no usable quote at it): {m['delayed_exits']}"
        f"; exits with no bid (sold at 0): {m['no_bid_exits']}",
        f"- Underlying path minutes with no usable quote (stop and target not checked there): "
        f"{m['und_gap_minutes']:,}",
        f"- Same trades under `{OTHER_BROKER}` fees: mean {pc(m['mean_ret_other_broker'])}",
        f"- Largest distance between a traded strike and the underlying at entry: "
        f"{pc(m['max_strike_gap'])} (a check that the listed chain reached the money)",
        "",
        "## Every ticker-session, by result",
        "",
        "TRADE = took the position. Everything else is NO_TRADE with its reason.",
        "",
    ]  # fmt: skip
    reasons = sorted({r for v in m["statuses"].values() for r in v})
    out += ["| ticker | sessions | " + " | ".join(reasons) + " |",
            "|---|---|" + "---|" * len(reasons)]  # fmt: skip
    for t, v in m["statuses"].items():
        out.append(f"| {t} | {sum(v.values())} | " + " | ".join(str(v.get(r, 0)) for r in reasons)
                   + " |")  # fmt: skip
    out += ["", f"Underlying exits over all signals (Step A): {m['und_exit_reasons_all_signals']}",
            "", "## Per ticker (descriptive only; D6)", "",
            "| ticker | trades | calls | mean net / premium | winning | total $ |",
            "|---|---|---|---|---|---|"]  # fmt: skip
    for name in ("per_ticker", "per_year"):
        if name == "per_year":
            out += ["", "## Per year (descriptive only)", "",
                    "| year | trades | calls | mean net / premium | winning | total $ |",
                    "|---|---|---|---|---|---|"]  # fmt: skip
        for g, v in m[name].items():
            out.append(f"| {g} | {v['trades']} | {v['calls']} | {pc(v['mean_ret'])} | "
                       f"{pc(v['win_share'], 1)} | {v['sum_usd']:,.2f} |")  # fmt: skip
    out += ["", "## How it was run", ""]
    if plan is not None:
        out += [f"- {t}: {len(v)} development sessions, {v[0]} → {v[-1]}" for t, v in plan.items()]
    out += [
        "- AAPL is out (D1: five earnings dates not verified in advance). NVDA and TSLA earnings "
        "sessions, and the session on each side, are `EARNINGS_WINDOW`.",
        "- After 2025-10-02 only QQQ has development data, so the pooled sample is uneven in time.",
        "- The underlying is the mid of 1-minute quotes. The candle's high and low are the "
        "highest and lowest of the mids stamped 09:30 to 09:35, so moves inside a minute are "
        "not seen; the same holds for the stop and the target.",
        "- The candle's open is the last quote at or before 09:30:00 (a pre-open quote), at most "
        "60 seconds old; the record stamped 09:30:00 is missing on 1 to 27 sessions per ticker.",
        "- Owner rulings of 2026-11-15 used by this run:",
        *[f"  - {key}: {val}" for key, val in RULINGS.items()],
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run-report", type=Path, default=None)
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    dry = args.dry_run_report is not None
    if dry and args.dry_run_report.resolve() == REPORT.resolve():
        print("--dry-run-report must not overwrite the real report")
        return 1
    if dry:
        rows = apply_one_position(synthetic_rows(cfg), TICKERS)
        write_report(args.dry_run_report, analyse(rows, cfg), cfg, "dry-run", -1, -1, None)
        print(f"dry run: wrote {args.dry_run_report}")
        return 0
    if dirty():
        print("the screen is a registered trial: commit src/scripts/configs first")
        return 1
    if "DATABASE_URL" not in os.environ:
        print("DATABASE_URL not set: every run must be registered in validation_runs")
        return 1
    plan = session_plan(cfg)
    engine = create_engine(os.environ["DATABASE_URL"])
    n_before, run_id, n_after = register(engine, cfg, plan)
    try:
        rows = apply_one_position(real_rows(cfg, plan), TICKERS)
        HoldoutGuard(max(cfg.study_options_day.dev_end.values()), None).check(
            r["session_date"] for r in rows
        )
        OUT.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(rows, infer_schema_length=None).write_parquet(OUT)
        m = analyse(rows, cfg)
        complete_run(engine, run_id, {**m, "n_trials_before": n_before, "n_trials_after": n_after})
    except Exception as e:
        fail_run(engine, run_id, repr(e))
        raise
    finally:
        engine.dispose()
    write_report(REPORT, m, cfg, run_id, n_before, n_after, plan)
    print(f"outcome {m['outcome']}; trades {m['trades']}; wrote {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
