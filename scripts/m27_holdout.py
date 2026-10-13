"""M27 gate 2 (ADR-0019): the ONE holdout confirmation of the frozen RSI(2) pullback rule on SPY,
2016-01 -> 2026-09. Order (H5), all inside one registered run:
1. Refuse if a `screen_pullback_holdout` run already exists (one access only).
2. Register the run with touches_final_holdout = true, then log the access through
   `HoldoutGuard` (adr_ref ADR-0019), and only then read rows after 2015-12-31.
3. Data checks on holdout rows (H2, amendment A1). Any failure: the run FAILS before any
   strategy statistic is computed.
4. The rule runs continuously from 1993; holdout trades are those with entry signal close >=
   2016-01-04 and sale open <= 2026-09-30 (H1). Statistic and outcome as H3.

    uv run python scripts/m27_holdout.py
    uv run python scripts/m27_holdout.py --dry-run-report FILE   # synthetic prices, no database
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import exchange_calendars as xcals
import numpy as np
import polars as pl
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text

from m25_verify_data import ADJ_TOL, DIV_TOL, JUMP, SHILLER_TOL, shiller_monthly
from m26_screen import daily_compare, dirty
from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import code_commit
from qqq1dte.backtesting.premium_screen import moving_block_weights, weighted_means
from qqq1dte.backtesting.registry import complete_run, fail_run, n_trials, register_run
from qqq1dte.core.config import Phase1Config, StudyPullback, config_hash, load_config
from qqq1dte.ingestion.etf_data import parse_fred, parse_tiingo, with_holdout
from qqq1dte.strategies.pullback import period_trades, signals, trade_indices
from qqq1dte.strategies.tom import TomTrade, tom_trade
from qqq1dte.strategies.trend import tbill_growth
from qqq1dte.validation.etf_checks import (
    adjustment_violations,
    completeness,
    dividend_counts,
    jump_scan,
    open_gaps,
    open_ratio_violations,
    shiller_violations,
)

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "research" / "m27_holdout.md"
ADR = "ADR-0020"  # the second and last access (ADR-0020); the first was ADR-0019
RUN_KIND = "screen_pullback_holdout"
HOLD_START = date(2016, 1, 1)  # ADR-0018 D3 / ADR-0019 H1
MIN_TRADES = 60  # ADR-0019 H3
SHILLER_P_END, SHILLER_D_END = "2023-09", "2023-06"  # ADR-0019 A1: the Yale file ends here
SHILLER_PARTIAL = "2023-09"  # ADR-0020 E1: the final month is one day's close, not an average
FULL_DIV_YEARS = range(2016, 2026)  # H2 (d)
DEV_REFERENCE = (175, 0.00541)  # ADR-0018 run screen_pullback-287844c815ca


def sessions_to(end: date) -> list[date]:
    cal = xcals.get_calendar("XNYS", start="1993-01-01", end=str(end + timedelta(days=400)))
    return [ts.date() for ts in cal.sessions if ts.date() <= end]


def synthetic(
    s: StudyPullback, sessions: list[date]
) -> tuple[pl.DataFrame, dict[date, float | None]]:
    days = [d for d in sessions if d >= s.data_start]
    rng = np.random.default_rng(54321)
    close = 45.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, len(days))))
    opn = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, 0.002, len(days)))
    df = pl.DataFrame({
        "date": days, "ticker": s.ticker, "open": opn, "close": close, "adj_open": opn,
        "adj_close": close, "div_cash": 0.0, "split_factor": 1.0,
    })  # fmt: skip
    d, rates = s.data_start, {}
    while d <= s.holdout_end:
        rates[d] = 2.0
        d += timedelta(days=1)
    return df, dict(rates)


def data_checks(
    s: StudyPullback, df: pl.DataFrame, hold_sessions: list[date], dry: bool
) -> tuple[list[str], list[str]]:
    """H2 on holdout rows (the last development row only as the previous close)."""
    fails, notes = [], []
    h = df.filter(pl.col("date") >= HOLD_START)
    edge = df.filter(pl.col("date") >= s.dev_end - timedelta(days=7))
    missing, extra = completeness(h["date"].to_list(), hold_sessions)
    if missing or extra:
        fails.append(f"(a) {len(missing)} missing {missing[:5]} / {len(extra)} extra {extra[:5]}")
    adj = [v for v in adjustment_violations(edge, ADJ_TOL) if v[0] >= HOLD_START]
    if adj:
        fails.append(f"(b) {len(adj)} adjustment violations, first {adj[:3]}")
    jumps = [j for j in jump_scan(edge, JUMP) if j["date"] >= HOLD_START and not j["split"]]
    if jumps:
        fails.append(f"(c) unexplained jumps {[(j['date'], round(j['move'], 3)) for j in jumps]}")
    ratio = open_ratio_violations(h, s.open_ratio_tol)
    gaps = [g for g in open_gaps(edge, s.open_gap) if g[0] >= HOLD_START]
    if ratio:
        fails.append(f"open ratio: {len(ratio)} violations, first {ratio[:3]}")
    if gaps:
        fails.append(f"open gaps over {s.open_gap:.0%}: {gaps[:5]}")
    notes.append(f"(a)-(c), opens: {h.height:,} holdout rows; {len(missing)} missing, "
                 f"{len(adj)} adjustment, {len(jumps)} jump, {len(ratio)} open-ratio, "
                 f"{len(gaps)} open-gap findings")  # fmt: skip
    if dry:
        notes.append("(d), (e) skipped in the dry run (synthetic prices have no dividends)")
        return fails, notes
    divs = dividend_counts(h)
    bad = {y: divs.get(y, 0) for y in FULL_DIV_YEARS if divs.get(y, 0) != 4}  # noqa: PLR2004
    if bad:
        fails.append(f"(d) dividend counts off-pattern {bad}")
    sh = shiller_monthly(ROOT / "data" / "raw" / "etf" / "shiller" / "ie_data.xls")
    spy = df.filter(pl.col("date") >= date(2015, 1, 1)).with_columns(
        month=pl.col("date").dt.strftime("%Y-%m")
    )
    avg = dict(spy.group_by("month").agg(pl.col("close").mean()).iter_rows())
    months = sorted(m for m in avg if "2016-01" <= m <= SHILLER_P_END and m != SHILLER_PARTIAL)
    p = dict(zip(sh["month"].to_list(), sh["P"].to_list(), strict=True))
    dd = dict(zip(sh["month"].to_list(), sh["D"].to_list(), strict=True))
    pv = shiller_violations(months, avg, p, scale=10.0, tol=SHILLER_TOL)
    div_m = dict(spy.group_by("month").agg(pl.col("div_cash").sum()).sort("month").iter_rows())
    allm = sorted(div_m)
    dv, checked = [], 0
    for i, m in enumerate(allm):
        if i < 11 or not ("2016-01" <= m <= SHILLER_D_END) or not dd.get(m):  # noqa: PLR2004
            continue
        checked += 1
        t12 = sum(div_m[x] for x in allm[i - 11 : i + 1]) * 10
        if abs(t12 / dd[m] - 1) > DIV_TOL:
            dv.append((m, round(t12 / dd[m] - 1, 3)))
    if pv:
        fails.append(f"(e) Shiller price: {len(pv)} months outside ±1%, e.g. {pv[:5]}")
    if dv:
        fails.append(f"(e) Shiller dividends: {len(dv)} months outside ±10%, e.g. {dv[:5]}")
    notes.append(f"(d) dividends per year 2016-2025: {[divs.get(y, 0) for y in FULL_DIV_YEARS]}")
    notes.append(f"(e) Shiller: {len(months)} price months (2016-01 → {SHILLER_P_END}, "
                 f"{SHILLER_PARTIAL} excluded by ADR-0020 E1), "
                 f"{len(pv)} outside ±1%; {checked} dividend months (→ {SHILLER_D_END}), "
                 f"{len(dv)} outside ±10%. After {SHILLER_P_END}: internal checks only "
                 "(A1).")  # fmt: skip
    return fails, notes


def run_trades(
    s: StudyPullback, df: pl.DataFrame, rates: dict[date, float | None],
    idx: Sequence[tuple[int, int]], mult: float, at_close: bool = False,
) -> list[TomTrade]:  # fmt: skip
    """As `m27_screen.py` (ADR-0018 D1, D4)."""
    dates = df["date"].to_list()
    adj_c, adj_o = df["adj_close"].to_list(), df["adj_open"].to_list()
    opn, cls = df["open"].to_list(), df["close"].to_list()
    out = []
    for i, j in idx:
        if at_close:
            a, b, price, path = i, j, cls[i], adj_c[i : j + 1]
        else:
            a, b = i + 1, j + 1
            price, path = opn[a], [adj_o[a], *adj_c[a : j + 1], adj_o[b]]
        out.append(
            tom_trade(
                s.account_usd, price, path, tbill_growth(rates, dates[a], dates[b]),
                s.commission_per_share, s.commission_min, s.commission_max_pct, s.slippage_bps,
                cost_mult=mult,
            )
        )  # fmt: skip
    return out


def dataset_of(s: StudyPullback) -> str:
    """The M26 raw-file dataset id (content hash; registered by the M26/M27 screens)."""
    h = hashlib.sha256()
    for f in (
        Path(s.raw_dir) / "tiingo" / f"{s.ticker}.json",
        Path(s.raw_dir) / "fred" / f"{s.fred_series}.csv",
    ):
        h.update((ROOT / f).read_bytes())
    return f"raw_tom_{h.hexdigest()[:16]}"


def already_run(engine: Engine) -> bool:
    """One access only: refuse if the access was ever logged under this ADR, or a holdout run
    completed. A run that failed before logging read nothing (H5)."""
    with engine.connect() as c:
        logged = c.execute(
            text("SELECT count(*) FROM final_test_access_log WHERE adr_ref = :a"), {"a": ADR}
        ).scalar_one()
        done = c.execute(
            text("SELECT count(*) FROM validation_runs WHERE run_kind = :k AND status <> 'FAILED'"),
            {"k": RUN_KIND},
        ).scalar_one()
    return bool(logged or done)


def main() -> int:  # noqa: PLR0912, PLR0915 (linear pipeline)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run-report", type=Path, default=None)
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    cfg: Phase1Config = load_config()
    s = cfg.study_pullback
    dry = args.dry_run_report is not None
    if dry and args.dry_run_report.resolve() == REPORT.resolve():
        print("--dry-run-report must not overwrite the real report")
        return 1
    if not dry and dirty():
        print("the holdout run is registered: commit src/scripts/configs first")
        return 1
    sessions = sessions_to(s.holdout_end)
    hold_sessions = [d for d in sessions if d >= HOLD_START]
    window = (HOLD_START, s.holdout_end)
    engine: Engine | None = None
    run_id, n_before, n_after = "dry-run", -1, -1
    if not dry:
        engine = create_engine(os.environ["DATABASE_URL"])
        if already_run(engine):
            print(f"a {RUN_KIND} run already exists: the holdout is opened once (ADR-0019)")
            return 1
        n_before = n_trials(engine, *window)
        run_id = register_run(
            engine, run_kind=RUN_KIND,
            config={"study_pullback": s.model_dump(mode="json"), "adr": ADR,
                    "bootstrap_reps": cfg.validation.bootstrap_reps,
                    "bootstrap_seed": cfg.models.metrics.bootstrap_seed,
                    "min_trades": MIN_TRADES, "hold_start": str(HOLD_START),
                    "phase1_config_hash": config_hash(cfg.model_dump(mode="json"))},
            data_window=window, dataset_id=dataset_of(s), code_commit=code_commit(ROOT),
            folds=[], touches_final_holdout=True,
        )  # fmt: skip
        n_after = n_trials(engine, *window)
        print(f"registered {run_id}; n_trials {n_before} -> {n_after}", flush=True)
    try:
        if engine is not None:
            HoldoutGuard(s.dev_end, engine).check(
                hold_sessions, run_id=run_id, adr_ref=ADR,
                justification="M27 gate 2 rerun under ADR-0020 (Shiller partial-month exception)",
            )  # fmt: skip
            raw = ROOT / s.raw_dir
            rows = json.loads((raw / "tiingo" / f"{s.ticker}.json").read_text("utf-8"))
            df = with_holdout(parse_tiingo(rows, s.ticker), s.holdout_end, ADR)
            fred = (raw / "fred" / f"{s.fred_series}.csv").read_text("utf-8")
            rates = dict(with_holdout(parse_fred(fred, s.fred_series), s.holdout_end, ADR)
                         .iter_rows())  # fmt: skip
        else:
            df, rates = synthetic(s, sessions)
        df = df.sort("date")
        fails, notes = data_checks(s, df, hold_sessions, dry)
        if fails:
            if engine is not None:
                fail_run(engine, run_id, "H2 data checks: " + "; ".join(fails))
            out = ["# M27 holdout (ADR-0019): **STOP — data checks failed**", "",
                   f"Run `{run_id}`. No strategy statistic was computed. The holdout counts as "
                   "opened. A new ADR is needed for any exception (H2).", "",
                   *[f"- {f}" for f in fails], "", *[f"- {n}" for n in notes], ""]  # fmt: skip
            stop_report: Path = args.dry_run_report if dry else REPORT
            stop_report.write_text("\n".join(out) + "\n", encoding="utf-8")
            print("STOP: data checks failed;", fails)
            return 1
        dates: list[date] = df["date"].to_list()
        if dates != [d for d in sessions if d >= s.data_start]:
            raise ValueError("SPY dates differ from the XNYS sessions")
        entry, exit_ = signals(df["adj_close"].to_list(), s.rsi_period, s.rsi_entry,
                               s.sma_trend, s.sma_exit)  # fmt: skip
        idx_all = trade_indices(entry, exit_)
        idx = period_trades(idx_all, dates, HOLD_START, s.holdout_end)
        dev_idx = period_trades(idx_all, dates, s.data_start, s.dev_end)
        dev_net = np.array([t.net_excess for t in run_trades(s, df, rates, dev_idx, 1.0)])
        crossing = [(dates[i], dates[j + 1]) for i, j in idx_all
                    if dates[i] <= s.dev_end < dates[j + 1]]  # fmt: skip
        tr = run_trades(s, df, rates, idx, 1.0)
        tr2 = run_trades(s, df, rates, idx, s.cost_sensitivity)
        trc = run_trades(s, df, rates, idx, 1.0, at_close=True)
        net = np.array([t.net_excess for t in tr])
        n = len(net)
        reps, seed = cfg.validation.bootstrap_reps, cfg.models.metrics.bootstrap_seed
        boot = weighted_means(net, moving_block_weights(n, s.block_trades, reps, seed))
        lb = float(np.nanquantile(boot, 1 - s.lower_bound_level))
        ub = float(np.nanquantile(boot, 1 - (1 - s.kill_level) / 2))
        lo95 = float(np.nanquantile(boot, (1 - s.kill_level) / 2))
        k = max(n_after, 1)
        lb_combined = float(np.nanquantile(boot, (1 - s.lower_bound_level) / k))
        few = n < MIN_TRADES
        outcome = "KILL" if ub < 0 else "PASS" if lb > 0 and not few else "NOT CONFIRMED"
        windows = [(dates[i + 1], dates[j + 1]) for i, j in idx]
        years = np.array([dates[i].year for i, _ in idx])
        gross = np.array([t.gross_excess for t in tr])
        net2 = np.array([t.net_excess for t in tr2])
        netc = np.array([t.net_excess for t in trc])
        worst_days = np.array([t.worst_day for t in tr])
        hold = np.array([j - i for i, j in idx])
        cmp_ = daily_compare(df, rates, windows, tr, s.account_usd)
        metrics: dict[str, Any] = {
            "outcome": outcome, "mean_net_excess": float(net.mean()), "lower_bound": lb,
            "upper_bound": ub, "trades": n, "few_trades": few, "lower_bound_combined": lb_combined,
            "combined_count": k, "mean_gross_excess": float(gross.mean()),
            "mean_net_2x": float(net2.mean()), "mean_net_at_signal_close": float(netc.mean()),
            "loss_limit_trades": int((worst_days < -s.loss_day_limit).sum()),
            "dev_recomputed": [len(dev_net), float(dev_net.mean())], "compare": cmp_,
            "n_trials_before": n_before, "n_trials_after": n_after,
        }  # fmt: skip
        if engine is not None:
            complete_run(engine, run_id, metrics)
    except Exception as e:
        if engine is not None:
            fail_run(engine, run_id, repr(e))
        raise
    if engine is not None:
        engine.dispose()

    def p(x: float, nd: int = 3) -> str:
        return "-" if math.isnan(x) else f"{x:.{nd}%}"

    costs = np.array([t.costs for t in tr])
    out = [
        "# M27 holdout confirmation: RSI(2) pullback on SPY (ADR-0019)"
        + (" — DRY RUN, SYNTHETIC PRICES" if dry else ""),
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m27_holdout.py`, code "
        f"{code_commit(ROOT)[:12]}. Registered run `{run_id}` (touches_final_holdout; access "
        f"logged with {ADR}; n_trials on the holdout window {n_before} → {n_after}). Holdout "
        f"trades: entry signal ≥ {HOLD_START}, sale ≤ {s.holdout_end}. **This is the only "
        "access.**",
        "",
        f"## Outcome: **{outcome}**",
        "",
        "**Process disclosure (ADR-0020):** the first access (run "
        "`screen_pullback_holdout-b47cc1560348`, ADR-0019) stopped at a data check on Shiller's "
        "partial final month 2023-09 before any strategy statistic was computed. ADR-0020 "
        "excluded that one month and, overriding ADR-0019 H2's descriptive-only clause, kept "
        "this result confirmatory. The decision was made blind to the result.",
        "",
        f"- Mean net excess return per trade (after costs, above T-bills): **{p(net.mean())}**",
        f"- One-sided {s.lower_bound_level:.0%} lower bound: **{p(lb)}** (PASS needs > 0)",
        f"- Two-sided {s.kill_level:.0%} interval: [{p(lo95)}, {p(ub)}] (KILL needs the upper "
        "bound < 0)",
        f"- Trades: {n} (guard ≥ {MIN_TRADES}{', NOT MET' if few else ', met'})",
        f"- Circular moving-block bootstrap over trades: block {s.block_trades}, {reps} reps, "
        f"seed {seed}.",
        f"- Descriptive (H4): lower bound at the combined count ({k} trials, one-sided "
        f"1 - 0.05/{k}): {p(lb_combined)}",
        "",
        "Evidence with its uncertainty, not a claim of profitability (hard rule 12).",
        "",
        "## Data checks (H2, amendment A1): PASS",
        "",
        *[f"- {x}" for x in notes],
        "",
        "## Development vs holdout",
        "",
        "| | development (ADR-0018 run) | development recomputed here | holdout |",
        "|---|---|---|---|",
        f"| trades | {DEV_REFERENCE[0]} | {len(dev_net)} | {n} |",
        f"| mean net excess | {p(DEV_REFERENCE[1])} | {p(float(dev_net.mean()))} "
        f"| {p(net.mean())} |",
        "",
        f"Trades crossing 2015/2016 (in neither period): {crossing or 'none'}.",
        "",
        "## Descriptive (never decisions)",
        "",
        f"- Same signals at the signal closes (published timing; not tradable): "
        f"{p(netc.mean())}",
        f"- Mean gross excess {p(gross.mean())}; costs ${costs.mean():.2f} per trade; "
        f"at {s.cost_sensitivity:g}x costs {p(net2.mean())}",
        f"- Winning trades {float((net > 0).mean()):.1%}; worst trade {p(float(net.min()))}; "
        f"best {p(float(net.max()))}; median hold {float(np.median(hold)):.0f} sessions",
        f"- Loss limit (ADR-0015 D3): **{int((worst_days < -s.loss_day_limit).sum())}** trades "
        f"contain a day below -{s.loss_day_limit:.0%}; worst day {p(float(worst_days.min()))}",
        "",
        "| | pullback + T-bills | SPY buy-and-hold |",
        "|---|---|---|",
        f"| CAGR (approximate) | {p(cmp_['tom']['cagr'], 1)} | {p(cmp_['spy']['cagr'], 1)} |",
        f"| Sharpe | {cmp_['tom']['sharpe']:.2f} | {cmp_['spy']['sharpe']:.2f} |",
        f"| maximum drawdown | {p(cmp_['tom']['mdd'], 1)} | {p(cmp_['spy']['mdd'], 1)} |",
        "",
        "## Per year",
        "",
        "| year | trades | mean net excess | worst trade |",
        "|---|---|---|---|",
        *[
            f"| {y} | {int((years == y).sum())} | {p(float(net[years == y].mean()))} "
            f"| {p(float(net[years == y].min()))} |"
            for y in sorted(set(years.tolist()))
        ],
        "",
        "## Per trade (for hand checks)",
        "",
        "| signal close | buy open | exit signal close | sell open | shares | costs $ "
        "| net excess | net at signal closes | worst day |",
        "|---|---|---|---|---|---|---|---|---|",
        *[
            f"| {dates[i]} | {dates[i + 1]} | {dates[j]} | {dates[j + 1]} | {t.shares} "
            f"| {t.costs:.2f} | {p(t.net_excess, 4)} | {p(c.net_excess, 4)} "
            f"| {p(t.worst_day, 2)} |"
            for (i, j), t, c in zip(idx, tr, trc, strict=True)
        ],
        "",
    ]  # fmt: skip
    report: Path = args.dry_run_report if dry else REPORT
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"outcome {outcome}; mean {net.mean():.5f} lower bound {lb:.5f}; wrote {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
