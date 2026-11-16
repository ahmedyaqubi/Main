"""M33 (ADR-0021 D6): the one registered screen of setup S3 (amendment A3, the noise-area
breakout of Zarattini, Aziz & Barbon, 2024), pooled over the tickers. It is a trial (test 3 of
the 3 ADR-0021 D7 allows, the last): registered BEFORE any signal or statistic is computed, from
committed code, with n_trials recorded before and after.

Development sessions only (study_options_day.dev_end per ticker). Files are chosen by the date
in their name; no holdout file is opened. AAPL is out (D1: unverified earnings dates).

- Signal: at each half-hour check from first_check to last_entry_check, the first quote wholly
  above the upper boundary (call) or below the lower (put). Exit: the first later check wholly
  beyond the opposite boundary, else exit_time.
- Step A: mean signed return of the underlying mid, entry check -> exit, over every
  ticker-session with a signal; one-sided lower bound at step_a_level. <= 0: the setup stops.
- Step B: mean net P&L / premium paid over the trades taken under the one-position rule, buy at
  the ask and sell at the bid, the decision broker's fees. ADVANCE: lower bound > 0 at the D7
  level with >= min_trades. KILL: two-sided upper bound < 0 at the mid fill. Else AMBIGUOUS.
- Session bootstrap, study_options_day.bootstrap_reps, seed models.metrics.bootstrap_seed.

The plan, the statistics and the risk rows are M29's (`m29_screen`).

    uv run python scripts/m33_screen.py
    uv run python scripts/m33_screen.py --dry-run-report FILE   # synthetic prices, no database
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine

from m26_screen import dirty
from m28_cost_map import _quotes, load_ticker, option_day
from m29_screen import (
    DECISION_BROKER,
    EARNINGS,
    OTHER_BROKER,
    TICKERS,
    WORKERS,
    analyse,
    d2_contracts,
    dev_files,
    pc,
    session_plan,
)
from m30_screen import previous_sessions
from qqq1dte.backtesting.cost_map import bs_price
from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.noise_area_screen import (
    SessionMoves,
    apply_one_position_timed,
    session_decision,
    session_moves,
)
from qqq1dte.backtesting.oos import code_commit
from qqq1dte.backtesting.registry import complete_run, fail_run, n_trials, register_run
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config, config_hash, load_config
from qqq1dte.core.timeutil import ET
from qqq1dte.execution_sim.selection import Contract, Quote
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.validation.earnings_calendar import earnings_exclusions, earnings_table
from qqq1dte.validation.options_day_data import ticker_config

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "research" / "m33_s3_screen.md"
OUT = ROOT / "data" / "research" / "m33" / "s3_rows.parquet"
RULINGS = {  # owner, 2026-11-16 (plan approved); recorded in the registered config
    "1_todays_open": "mid of the quote in force open_offset_minutes after the open; at most "
    "max_quote_age_s old, two-sided, not crossed; none = NO_UNDERLYING_QUOTE",
    "2_previous_close": "M30 ruling 1: mid of the quote in force prev_close_offset_minutes "
    "before the previous session's close; none = NO_PREV_CLOSE; dividends not adjusted",
    "3_check_prices": "the quote in force at each check; boundaries and sigma use mids; call "
    "only if bid > upper, put only if ask < lower; exit a call only if ask < lower, a put only "
    "if bid > upper; a check with no usable quote is skipped and counted",
    "4_history": "the lookback_sessions most recent usable sessions before today; usable = not "
    "an early close, with the open quote and every check quote; earnings-window sessions count "
    "as history; fewer = NO_HISTORY; split_sessions are CORPORATE_ACTION",
    "5_one_position": "signals in time order; a position is open from its entry until its "
    "option is sold; a first signal at or before that sale is POSITION_OPEN and the ticker does "
    "not trade later that session; same-check ties by cost share, then ticker order",
    "6_step_a": "signed mid(exit) / mid(entry check) - 1 on every ticker-session with a "
    "signal, before option gates and the one-position rule; no exit quote = left out, counted",
    "7_carried_over": "M29 rulings 3-8 and M30 ruling 8",
    "early_close": "EARLY_CLOSE (A3)",
}


# one ticker-session (worker) ---------------------------------------------------------------
def work(
    args: tuple[str, date, date | None, pl.DataFrame, pl.DataFrame, list[SessionMoves], bool, bool],
) -> dict[str, Any]:
    ticker, d, prev, u, ch, history, excluded, split = args
    cfg = ticker_config(load_config(), ticker)
    cal = TradingCalendar(cfg)
    fees = cfg.study_options_day.broker_fees[DECISION_BROKER]  # type: ignore[index]
    uq = _quotes(u.with_columns(rejected=pl.lit(False)))
    contracts = d2_contracts(ch, d, cal, cfg)
    c = session_decision(
        ticker, d, uq, contracts, lambda sym: _quotes(option_day(ticker, d, [sym])),
        cfg, cal, fees, prev_session=prev, history=history, excluded=excluded, split=split,
    )  # fmt: skip
    row = asdict(c)
    if c.status == "NO_CONTRACT" and not contracts:
        row["status"] = "NO_D2_EXPIRY"
    return row


def history_for(
    usable: list[SessionMoves], d: date, lookback: int
) -> list[SessionMoves]:  # fmt: skip
    """The `lookback` most recent usable sessions strictly before d (`usable` is in date order)."""
    return [m for m in usable if m.session_date < d][-lookback:]


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
        splits = set(s.split_sessions.get(t, []))
        prev = previous_sessions(cfg, sessions[0], sessions)
        u, ch = load_ticker(t, cfg, s.dev_end[t])
        assert u["session_date"].max() <= s.dev_end[t]  # type: ignore[operator]
        by_day = {k[0]: v for k, v in u.partition_by("session_date", as_dict=True).items()}
        empty = u.clear()
        # every research session's moves, each from its own records only (ruling 4)
        usable = [
            m for d in sessions
            if (m := session_moves(
                d, _quotes(by_day.get(d, empty).with_columns(rejected=pl.lit(False))), cfg, cal
            )) is not None
        ]  # fmt: skip
        args = [
            (t, d, prev[d],
             pl.concat([by_day.get(x, empty) for x in (prev[d], d) if x is not None]),
             ch.filter(pl.col("session_date") == d),
             history_for(usable, d, s.noise_area.lookback_sessions), d in excl, d in splits)
            for d in sessions
        ]  # fmt: skip
        with ProcessPoolExecutor(WORKERS) as pool:
            rows.extend(pool.map(work, args, chunksize=4))
        print(f"{t}: {len(sessions)} sessions, {len(usable)} usable as history", flush=True)
    return rows


# synthetic inputs (dry run) ----------------------------------------------------------------
def synthetic_rows(cfg0: Phase1Config) -> list[dict[str, Any]]:
    """Random-walk underlyings and Black-Scholes option quotes: exercises the whole pipeline
    without market data or the database. The numbers mean nothing."""
    rng = np.random.default_rng(cfg0.models.metrics.bootstrap_seed)
    fees = cfg0.study_options_day.broker_fees[DECISION_BROKER]  # type: ignore[index]
    cal = TradingCalendar(cfg0)
    lookback = cfg0.study_options_day.noise_area.lookback_sessions
    sessions = cal.sessions(date(2024, 1, 2), date(2024, 4, 30))
    rows = []
    for ticker, s0 in (("QQQ", 420.0), ("SPY", 480.0), ("IWM", 200.0)):
        cfg = ticker_config(cfg0, ticker)
        prev_d: date | None = None
        prev_uq: list[Quote] = []
        usable: list[SessionMoves] = []
        level = s0
        for d in sessions:
            open_, close = cal.open_close(d)
            n = int((close - open_).total_seconds() // 60)
            mids = level * np.exp(np.cumsum(rng.normal(0, 0.0006, n + 1)))
            level = float(mids[-1])
            times = [open_ + timedelta(minutes=i) for i in range(n + 1)]
            uq = [
                Quote(round(m - 0.005, 2), round(m - 0.005, 2) + 0.01, 100, 100, t)
                for t, m in zip(times, mids, strict=True)
            ]
            expiry = cal.next_session(d)
            _, exp_close = cal.open_close(expiry)
            base = round(float(mids[0]))
            chain = [
                Contract(f"{ticker}{k}{r}", float(k), r, expiry, open_ - timedelta(hours=12))
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
                for t, m in zip(times, mids, strict=True):
                    yrs = (exp_close - t).total_seconds() / (365 * 86400)
                    p = bs_price(float(m), c.strike, yrs, 0.18, c.right)
                    bid = math.floor(p * 100) / 100 - 0.01
                    out.append(Quote(bid if bid > 0 else None, bid + 0.03, 10, 10, t))
                return out

            rows.append(asdict(session_decision(
                ticker, d, prev_uq + uq, chain, quotes_for, cfg, cal, fees, prev_session=prev_d,
                history=history_for(usable, d, lookback),
            )))  # fmt: skip
            m = session_moves(d, uq, cfg, cal)
            if m is not None:
                usable.append(m)
            prev_d, prev_uq = d, uq
    return rows


def pooled(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ruling 5, then time order, so that runs and drawdowns follow the order of the trades."""
    rows = apply_one_position_timed(rows, TICKERS)
    far = datetime.max.replace(tzinfo=UTC)
    return sorted(rows, key=lambda r: (r["session_date"], r["entry_time"] or far))


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
    ds_id = f"options_day_dev_s3_{h.hexdigest()[:16]}"
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
        run_kind="screen_noise_area",
        config={
            "study_options_day": s.model_dump(mode="json"),
            "setup": "S3 (ADR-0021 amendment A3)",
            "tickers": list(plan),
            "sessions_per_ticker": {t: len(v) for t, v in plan.items()},
            "decision_broker": DECISION_BROKER,
            "bootstrap_seed": cfg.models.metrics.bootstrap_seed,
            "owner_rulings_2026_11_16": RULINGS,
            "phase1_config_hash": config_hash(cfg.model_dump(mode="json")),
            "adr": "ADR-0021 D6, test 3 of 3",
        },
        data_window=window,
        dataset_id=ds_id,
        code_commit=commit,
        folds=[],
    )
    n_after = n_trials(engine, *window)
    print(f"registered {run_id}; n_trials {n_before} -> {n_after}", flush=True)
    return n_before, run_id, n_after


# report ------------------------------------------------------------------------------------
def _clock(t: datetime) -> str:
    return f"{t.astimezone(ET):%H:%M}"


def signal_counts(rows: list[dict[str, Any]], cfg: Phase1Config) -> dict[str, Any]:
    sig = [r for r in rows if r["side"] is not None]
    trades = [r for r in rows if r["status"] == "TRADE"]
    per_day = Counter(r["session_date"] for r in trades)
    return {
        "signals": len(sig),
        "up": sum(r["side"] == "C" for r in sig),
        "und_exits": dict(Counter(r["und_exit_reason"] for r in sig)),
        "no_exit_quote": sum(r["und_exit_reason"] == "NO_EXIT_QUOTE" for r in sig),
        "signals_by_check": dict(sorted(Counter(_clock(r["entry_time"]) for r in sig).items())),
        "trades_by_check": dict(sorted(Counter(_clock(r["entry_time"]) for r in trades).items())),
        "checks_skipped": sum(r["checks_skipped"] for r in rows),
        "sessions_with_trades": len(per_day),
        "max_trades_in_a_session": max(per_day.values(), default=0),
        "sessions_with_more_than_one_trade": sum(v > 1 for v in per_day.values()),
        "max_outlay_in_a_session": max(
            (sum(r["outlay"] for r in trades if r["session_date"] == d) for d in per_day),
            default=0.0,
        ),
        "saved_row_checks": saved_row_checks(rows, cfg),
    }


def saved_row_checks(rows: list[dict[str, Any]], cfg: Phase1Config) -> dict[str, bool]:
    """Checks of the rules on the rows themselves; every value should be True."""
    s = cfg.study_options_day
    na = s.noise_area
    trades = [r for r in rows if r["status"] == "TRADE"]
    by_day: dict[date, list[dict[str, Any]]] = {}
    for r in trades:
        by_day.setdefault(r["session_date"], []).append(r)
    no_overlap = True
    for day in by_day.values():
        day.sort(key=lambda r: r["entry_time"])
        for a, b in pairwise(day):
            no_overlap &= a["exit_time"] is not None and b["entry_time"] > a["exit_time"]

    def local(t: datetime) -> Any:
        return t.astimezone(ET).time()

    sig = [r for r in rows if r["side"] is not None]
    return {
        "one_position_at_a_time": no_overlap,
        "one_row_per_ticker_session": len({(r["ticker"], r["session_date"]) for r in rows})
        == len(rows),
        "every_outlay_within_the_ceiling": all(r["outlay"] <= s.max_premium_usd for r in trades),
        "every_entry_at_a_check_by_the_last_entry_check": all(
            na.first_check <= local(r["entry_time"]) <= na.last_entry_check
            and local(r["entry_time"]).minute % na.check_interval_minutes == 0
            for r in sig
        ),
        "every_sale_by_the_forced_exit": all(
            r["exit_time"] is None or local(r["exit_time"]) <= na.exit_time for r in trades
        ),
        "every_signal_has_a_full_history": all(
            len(r["history_dates"]) == na.lookback_sessions
            and max(r["history_dates"]) < r["session_date"]
            for r in sig
        ),
        "no_session_after_dev_end": all(r["session_date"] <= s.dev_end[r["ticker"]] for r in rows),
    }


def write_report(
    path: Path, m: dict[str, Any], cfg: Phase1Config, run_id: str, n_before: int, n_after: int,
    plan: dict[str, list[date]] | None, n_total: int,
) -> None:  # fmt: skip
    s = cfg.study_options_day
    na = s.noise_area
    a, b, k, sc = m["step_a"], m["step_b"], m["mid_fill"], m["signals"]
    dry = plan is None
    a_text = "above 0: Step A passes" if m["step_a_passes"] else "not above 0: the setup stops here"
    cap_text = "never reached" if m["loss_cap_hit"] is None else f"reached on {m['loss_cap_hit']}"
    over_cap = sum(v.get("PREMIUM_OVER_CAP", 0) for v in m["statuses"].values())
    pos_open = sum(v.get("POSITION_OPEN", 0) for v in m["statuses"].values())
    out = [
        "# M33: D6 screen of setup S3, the noise-area breakout (ADR-0021 amendment A3)"
        + (" — DRY RUN, SYNTHETIC PRICES" if dry else ""),
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m33_screen.py`, code "
        f"{code_commit(ROOT)[:12]}. Registered run `{run_id}` (n_trials {n_before} → {n_after}). "
        "Test 3 of the 3 that ADR-0021 D7 allows, the last. Development sessions only; no "
        "holdout file was opened.",
        "",
        f"## Outcome: **{m['outcome']}**",
        "",
        "### Step A: the underlying",
        f"- Mean signed return, entry check → exit, over {a['n']:,} ticker-sessions with a "
        f"signal ({a['sessions']:,} sessions): **{pc(a['mean'], 4)}**",
        f"- One-sided {s.step_a_level:.0%} lower bound: **{pc(a['lower'], 4)}** ({a_text})",
        f"- Two-sided {s.kill_level:.0%} interval: [{pc(a['two_sided_low'], 4)}, "
        f"{pc(a['two_sided_high'], 4)}]",
        f"- Signals: {sc['signals']:,}, of which up {sc['up']:,}; underlying exits: "
        + ", ".join(f"{key} {v:,}" for key, v in sorted(sc["und_exits"].items()))
        + f"; left out of Step A for want of an underlying quote at {na.exit_time:%H:%M}: "
        f"{sc['no_exit_quote']}",
        f"- Checks skipped for want of a usable underlying quote: {sc['checks_skipped']}",
        "",
        "### Step B: the option trades"
        + ("" if m["step_a_passes"] else " (descriptive only: Step A did not pass)"),
        f"- Trades: **{m['trades']:,}** (guard ≥ {s.min_trades}"
        f"{', NOT MET' if m['few_trades'] else ', met'}); one position at a time; buy at the ask "
        f"at the signal's check, sell at the bid at the exit; `{DECISION_BROKER}` fees",
        f"- Mean net P&L per trade as a share of the premium paid: **{pc(b['mean'])}**",
        f"- One-sided {s.advance_level:.2%} lower bound: **{pc(b['lower'])}** (ADVANCE needs > 0)",
        f"- Two-sided {s.kill_level:.0%} interval: [{pc(b['two_sided_low'])}, "
        f"{pc(b['two_sided_high'])}]",
        f"- Lower bound at the full recorded count ({n_total} trials, one-sided "
        f"{m['level_all_trials']:.3%}): {pc(m['step_b_lower_all_trials'])}",
        f"- **Mid fill (KILL row), same trades:** mean {pc(k['mean'])}, two-sided "
        f"{s.kill_level:.0%} interval [{pc(k['two_sided_low'])}, {pc(k['two_sided_high'])}] "
        "(KILL needs the upper bound < 0)",
        f"- Session bootstrap, {s.bootstrap_reps:,} reps, seed "
        f"{cfg.models.metrics.bootstrap_seed}. Sessions are resampled whole, so trades of one "
        "day stay together.",
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
        "- Option exits: "
        + ", ".join(f"{key} {v:,}" for key, v in sorted(m["exit_reasons"].items())),
        f"- Trades with no usable option quote by {na.exit_time:%H:%M} (`UNRESOLVED_DATA`, left "
        f"out): {m['unresolved']}; mean with those counted as a total loss: "
        f"{pc(m['mean_ret_unresolved_as_total_loss'])}",
        f"- Sales made at a later minute than the exit: {m['delayed_exits']}; exits with no bid "
        f"(sold at 0): {m['no_bid_exits']}",
        f"- Sessions with a trade: {sc['sessions_with_trades']:,}; with more than one: "
        f"{sc['sessions_with_more_than_one_trade']:,}; most trades in one session: "
        f"{sc['max_trades_in_a_session']}; largest premium spent in one session: "
        f"${sc['max_outlay_in_a_session']:,.2f} (D2: must not exceed the settled balance)",
        f"- Same trades under `{OTHER_BROKER}` fees: mean {pc(m['mean_ret_other_broker'])}",
        f"- Largest distance between a traded strike and the underlying at entry: "
        f"{pc(m['max_strike_gap'])} (a check that the listed chain reached the money)",
        "",
        "## Signals and trades by check (descriptive only)",
        "",
        "| check | signals | trades |",
        "|---|---|---|",
        *[f"| {t} | {n} | {sc['trades_by_check'].get(t, 0)} |"
          for t, n in sc["signals_by_check"].items()],
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
    out += ["", "## Per ticker (descriptive only; D6)", "",
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
    out += ["", "## Checks on the saved rows", ""]
    out += [f"- {key.replace('_', ' ')}: {'yes' if v else '**NO**'}"
            for key, v in sc["saved_row_checks"].items()]  # fmt: skip
    out += ["", "## How it was run", ""]
    if plan is not None:
        out += [f"- {t}: {len(v)} development sessions, {v[0]} → {v[-1]}" for t, v in plan.items()]
    out += [
        "- AAPL is out (D1: five earnings dates not verified in advance). NVDA and TSLA earnings "
        "sessions, and the session on each side, are `EARNINGS_WINDOW`; they still count as "
        "history for later sessions.",
        "- After 2025-10-02 only QQQ has development data, so the pooled sample is uneven in time.",
        "- The underlying is read from 1-minute quotes. Today's open is the quote in force "
        f"{na.open_offset_minutes} minute after the open; the previous close is the quote in "
        f"force {na.prev_close_offset_minutes} minute before the previous session's close. "
        "Neither is the official opening or closing trade price "
        "(`reports/research/m33_quote_survey.md`, measured before the run).",
        "- A signal or an exit needs the whole quote beyond the boundary, so a wide quote gives "
        "neither.",
        "- Dividends are not adjusted: on an ex-dividend session the previous close, and with it "
        "the upper boundary, is higher by about the dividend. Split sessions are "
        "`CORPORATE_ACTION`: "
        + ", ".join(f"{t} {d}" for t, v in s.split_sessions.items() for d in v)
        + ".",
        "- Declared differences from the paper (A3): options, not shares; one trade per "
        "ticker-session, no reversal; the base-model exit; five tickers (the paper: SPY); "
        "quotes, not trade bars; exit 15:50; last entry 15:00.",
        "- Owner rulings of 2026-11-16 used by this run:",
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
        rows = pooled(synthetic_rows(cfg))
        n_total = cfg.study_options_day.n_trials_recorded + 3
        m = {**analyse(rows, cfg, n_total), "signals": signal_counts(rows, cfg)}
        write_report(args.dry_run_report, m, cfg, "dry-run", -1, -1, None, n_total)
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
        rows = pooled(real_rows(cfg, plan))
        HoldoutGuard(max(cfg.study_options_day.dev_end.values()), None).check(
            r["session_date"] for r in rows
        )
        OUT.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(rows, infer_schema_length=None).write_parquet(OUT)
        m = {**analyse(rows, cfg, n_after), "signals": signal_counts(rows, cfg)}
        complete_run(engine, run_id, {**m, "n_trials_before": n_before, "n_trials_after": n_after})
    except Exception as e:
        fail_run(engine, run_id, repr(e))
        raise
    finally:
        engine.dispose()
    write_report(REPORT, m, cfg, run_id, n_before, n_after, plan, n_after)
    print(f"outcome {m['outcome']}; trades {m['trades']}; wrote {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
