"""M30 (ADR-0021 D6): the one registered screen of setup S2 (D3: direction = the underlying's
move from the previous close to 10:00; enter 15:30; exit 15:50), pooled over the tickers. It is
a trial (test 2 of the 3 ADR-0021 D7 allows): registered BEFORE any signal or statistic is
computed, from committed code, with n_trials recorded before and after.

Development sessions only (study_options_day.dev_end per ticker). Files are chosen by the date
in their name; no holdout file is opened. AAPL is out (D1: unverified earnings dates).

- Step A: mean signed return of the underlying mid, 15:30 -> 15:50, over every ticker-session
  with a direction; one-sided lower bound at step_a_level. <= 0: the setup stops.
- Step B: mean net P&L / premium paid over the trades taken under the one-position rule, buy at
  the ask and sell at the bid, the decision broker's fees. ADVANCE: lower bound > 0 at the D7
  level with >= min_trades. KILL: two-sided upper bound < 0 at the mid fill. Else AMBIGUOUS.
- Session bootstrap, study_options_day.bootstrap_reps, seed models.metrics.bootstrap_seed.

The plan, the one-position pooling and the statistics are M29's (`m29_screen`).

    uv run python scripts/m30_screen.py
    uv run python scripts/m30_screen.py --dry-run-report FILE   # synthetic prices, no database
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import sys
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
from m28_cost_map import _quotes, load_ticker, option_day
from m29_screen import (
    DECISION_BROKER,
    EARNINGS,
    OTHER_BROKER,
    TICKERS,
    WORKERS,
    analyse,
    apply_one_position,
    d2_contracts,
    dev_files,
    pc,
    session_plan,
)
from qqq1dte.backtesting.cost_map import bs_price
from qqq1dte.backtesting.half_hour_screen import session_decision
from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import code_commit
from qqq1dte.backtesting.registry import complete_run, fail_run, n_trials, register_run
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config, config_hash, load_config
from qqq1dte.execution_sim.selection import Contract, Quote
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.validation.earnings_calendar import earnings_exclusions, earnings_table
from qqq1dte.validation.options_day_data import ticker_config

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "research" / "m30_s2_screen.md"
OUT = ROOT / "data" / "research" / "m30" / "s2_rows.parquet"
RULINGS = {  # owner, 2026-11-15 ("Approve all"); recorded in the registered config
    "1_previous_close": "mid of the quote in force prev_close_offset_minutes before the "
    "previous session's close; at most max_quote_age_s old, two-sided, not crossed",
    "2_signal_price": "the quote in force at signal_time, same checks",
    "3_direction": "up only if the signal bid > previous-close ask; down only if the signal "
    "ask < previous-close bid; otherwise FLAT_MOVE",
    "4_no_previous_close": "first session, a previous session excluded by an ADR, or no usable "
    "quote there: NO_PREV_CLOSE",
    "5_corporate_actions": "split_sessions are CORPORATE_ACTION; dividends are not adjusted",
    "6_step_a": "signed mid(exit_time) / mid(entry_time) - 1 on every ticker-session with a "
    "direction, before option gates; no entry quote = NO_UNDERLYING_QUOTE; no exit quote = "
    "left out and counted",
    "7_m29_rulings_2_to_8": "unchanged; the exit is the forced exit, so no usable option quote "
    "at exit_time + latency = UNRESOLVED_DATA",
    "8_full_count": "the descriptive bound uses the registry's n_trials after registration",
    "early_close": "EARLY_CLOSE (owner, 2026-11-14)",
}


# one ticker-session (worker) ---------------------------------------------------------------
def work(
    args: tuple[str, date, date | None, pl.DataFrame, pl.DataFrame, bool, bool],
) -> dict[str, Any]:
    ticker, d, prev, u, ch, excluded, split = args
    cfg = ticker_config(load_config(), ticker)
    cal = TradingCalendar(cfg)
    fees = cfg.study_options_day.broker_fees[DECISION_BROKER]  # type: ignore[index]
    uq = _quotes(u.with_columns(rejected=pl.lit(False)))
    contracts = d2_contracts(ch, d, cal, cfg)
    c = session_decision(
        ticker, d, uq, contracts, lambda sym: _quotes(option_day(ticker, d, [sym])),
        cfg, cal, fees, prev_session=prev, excluded=excluded, split=split,
    )  # fmt: skip
    row = asdict(c)
    if c.status == "NO_CONTRACT" and not contracts:
        row["status"] = "NO_D2_EXPIRY"
    return row


def previous_sessions(
    cfg: Phase1Config, start: date, sessions: list[date]
) -> dict[date, date | None]:
    """For each research session, the calendar's previous session, or None when that session
    is before the data or is not a research session (excluded by an ADR)."""
    every = TradingCalendar(cfg).sessions(start, sessions[-1])
    research = set(sessions)
    return {
        d: every[i - 1] if i > 0 and every[i - 1] in research else None
        for i, d in enumerate(every)
        if d in research
    }


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
        args = [
            (t, d, prev[d],
             u.filter(pl.col("session_date").is_in([x for x in (prev[d], d) if x is not None])),
             ch.filter(pl.col("session_date") == d), d in excl, d in splits)
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
    fees = cfg0.study_options_day.broker_fees[DECISION_BROKER]  # type: ignore[index]
    cal = TradingCalendar(cfg0)
    sessions = cal.sessions(date(2024, 1, 2), date(2024, 4, 30))
    rows = []
    for ticker, s0 in (("QQQ", 420.0), ("SPY", 480.0), ("IWM", 200.0)):
        cfg = ticker_config(cfg0, ticker)
        prev_d: date | None = None
        prev_uq: list[Quote] = []
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
            )))  # fmt: skip
            prev_d, prev_uq = d, uq
    return rows


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
    ds_id = f"options_day_dev_s2_{h.hexdigest()[:16]}"
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
        run_kind="screen_half_hour",
        config={
            "study_options_day": s.model_dump(mode="json"),
            "setup": "S2 (ADR-0021 D3)",
            "tickers": list(plan),
            "sessions_per_ticker": {t: len(v) for t, v in plan.items()},
            "decision_broker": DECISION_BROKER,
            "bootstrap_seed": cfg.models.metrics.bootstrap_seed,
            "owner_rulings_2026_11_15": RULINGS,
            "phase1_config_hash": config_hash(cfg.model_dump(mode="json")),
            "adr": "ADR-0021 D6, test 2 of 3",
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
def signal_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sig = [r for r in rows if r["side"] is not None]
    return {
        "directions": len(sig),
        "up": sum(r["side"] == "C" for r in sig),
        "no_exit_quote": sum(r["und_exit_reason"] == "NO_EXIT_QUOTE" for r in sig),
    }


def write_report(
    path: Path, m: dict[str, Any], cfg: Phase1Config, run_id: str, n_before: int, n_after: int,
    plan: dict[str, list[date]] | None, n_total: int,
) -> None:  # fmt: skip
    s = cfg.study_options_day
    a, b, k, sc = m["step_a"], m["step_b"], m["mid_fill"], m["signals"]
    dry = plan is None
    a_text = "above 0: Step A passes" if m["step_a_passes"] else "not above 0: the setup stops here"
    cap_text = "never reached" if m["loss_cap_hit"] is None else f"reached on {m['loss_cap_hit']}"
    over_cap = sum(v.get("PREMIUM_OVER_CAP", 0) for v in m["statuses"].values())
    pos_open = sum(v.get("POSITION_OPEN", 0) for v in m["statuses"].values())
    out = [
        "# M30: D6 screen of setup S2, the first half-hour predicts the last (ADR-0021 D3)"
        + (" — DRY RUN, SYNTHETIC PRICES" if dry else ""),
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m30_screen.py`, code "
        f"{code_commit(ROOT)[:12]}. Registered run `{run_id}` (n_trials {n_before} → {n_after}). "
        "Test 2 of the 3 that ADR-0021 D7 allows. Development sessions only; no holdout file "
        "was opened.",
        "",
        f"## Outcome: **{m['outcome']}**",
        "",
        "### Step A: the underlying",
        f"- Mean signed return, 15:30 → 15:50, over {a['n']:,} ticker-sessions with a direction "
        f"({a['sessions']:,} sessions): **{pc(a['mean'], 4)}**",
        f"- One-sided {s.step_a_level:.0%} lower bound: **{pc(a['lower'], 4)}** ({a_text})",
        f"- Two-sided {s.kill_level:.0%} interval: [{pc(a['two_sided_low'], 4)}, "
        f"{pc(a['two_sided_high'], 4)}]",
        f"- Directions: {sc['directions']:,}, of which up {sc['up']:,}; left out of Step A for "
        f"want of an underlying quote at 15:50: {sc['no_exit_quote']}",
        "",
        "### Step B: the option trades"
        + ("" if m["step_a_passes"] else " (descriptive only: Step A did not pass)"),
        f"- Trades: **{m['trades']:,}** (guard ≥ {s.min_trades}"
        f"{', NOT MET' if m['few_trades'] else ', met'}); one position at a time; buy at the ask "
        f"at 15:30, sell at the bid at 15:50; `{DECISION_BROKER}` fees",
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
        f"{cfg.models.metrics.bootstrap_seed}.",
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
        f"- Trades with no usable option quote at 15:50 (`UNRESOLVED_DATA`, left out): "
        f"{m['unresolved']}; mean with those counted as a total loss: "
        f"{pc(m['mean_ret_unresolved_as_total_loss'])}",
        f"- Exits with no bid (sold at 0): {m['no_bid_exits']}",
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
    out += ["", "## How it was run", ""]
    if plan is not None:
        out += [f"- {t}: {len(v)} development sessions, {v[0]} → {v[-1]}" for t, v in plan.items()]
    out += [
        "- AAPL is out (D1: five earnings dates not verified in advance). NVDA and TSLA earnings "
        "sessions, and the session on each side, are `EARNINGS_WINDOW`.",
        "- After 2025-10-02 only QQQ has development data, so the pooled sample is uneven in time.",
        "- The underlying is read from 1-minute quotes. The previous close is the quote in force "
        f"{s.half_hour.prev_close_offset_minutes} minute before the previous session's close, "
        "not the official closing trade price (which this project does not hold for four of the "
        "five tickers). The quote stamped at the close itself is wide on NVDA and TSLA "
        "(`reports/research/m30_quote_survey.md`, measured before the run).",
        "- A direction needs the two quotes not to overlap, so small moves and wide quotes are "
        "`FLAT_MOVE`. The paper goes short on a move that is not positive; here that is NO_TRADE.",
        "- Dividends are not adjusted: on an ex-dividend session the move from the previous "
        "close is lower by the dividend. Split sessions are `CORPORATE_ACTION`: "
        + ", ".join(f"{t} {d}" for t, v in s.split_sessions.items() for d in v)
        + ".",
        "- Declared differences from the paper (D3): exit 15:50, not 16:00; options, not ETF "
        "shares; NVDA and TSLA are single stocks, outside the paper.",
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
        n_total = cfg.study_options_day.n_trials_recorded + 2
        m = {**analyse(rows, cfg, n_total), "signals": signal_counts(rows)}
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
        rows = apply_one_position(real_rows(cfg, plan), TICKERS)
        HoldoutGuard(max(cfg.study_options_day.dev_end.values()), None).check(
            r["session_date"] for r in rows
        )
        OUT.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(rows, infer_schema_length=None).write_parquet(OUT)
        m = {**analyse(rows, cfg, n_after), "signals": signal_counts(rows)}
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
