"""M11: mechanical diagnostic backtest (owner Q1). NOT a strategy.

Before calibration exists (M13) the decision engine must emit NO_TRADE (spec §4.1, rule 6), so
the backtester is exercised on real data with a mechanical signal instead: CALL at every
prediction timestamp, and separately PUT at every prediction timestamp, under the §4.7 position
limits and the conservative fill. Pre-holdout research sessions only.

Purpose: (1) reconcile the event-driven backtester with the independently written C labels (M6)
trade by trade; (2) record the unconditional-entry baseline (outcome mix, P&L, R, MFE/MAE,
holding time) for later comparison (gate 14). No profitability claim (rule 12).

Outputs: data/backtest/m11_diagnostic/<run_id>/{decisions,candidates,trades}.parquet,
reports/backtest/m11_diagnostic.md. One `validation_runs` row (run_kind "diagnostic").

    uv run python scripts/m11_diagnostic.py [--workers 7]
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from dotenv import load_dotenv
from sqlalchemy import create_engine

from qqq1dte.backtesting.bootstrap import session_bootstrap_ci
from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import code_commit, dataset_id
from qqq1dte.backtesting.registry import complete_run, fail_run, register_run
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.execution_sim.engine import Candidate, Decision, Signal, Trade, run_session
from qqq1dte.features.inputs import chain_table
from qqq1dte.labels.option import option_records
from qqq1dte.validation.records import build_definitions

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean" / "cleaned"
REJECTED = ROOT / "data" / "clean" / "rejected"
END = date(2026, 10, 2)
REPORT = ROOT / "reports" / "backtest" / "m11_diagnostic.md"
DT = pl.Datetime("us", "UTC")
TOL = 1e-9  # float tolerance for price / P&L equality
SCHEMAS: dict[type, dict[str, pl.DataType]] = {
    Decision: {
        "prediction_ts": DT,
        "side": pl.String(),
        "decision": pl.String(),
        "reason": pl.String(),
    },
    Candidate: {
        "prediction_ts": DT,
        "side": pl.String(),
        "symbol": pl.String(),
        "strike": pl.Float64(),
        "expiration": pl.Date(),
        "quote_ts": DT,
        "bid": pl.Float64(),
        "ask": pl.Float64(),
        "bid_size": pl.Int64(),
        "ask_size": pl.Int64(),
        "latency_s": pl.Int64(),
        "passed_gates": pl.Boolean(),
        "gate_failures": pl.List(pl.String()),
        "selected": pl.Boolean(),
        "selection_rule_version": pl.String(),
    },
    Trade: {
        f.name: (
            DT
            if f.name.endswith("_ts") or f.name == "t_end"
            else pl.List(pl.String())
            if f.name == "flags"
            else pl.Int64()
            if f.name == "holding_seconds"
            else pl.String()
            if f.name in ("side", "symbol", "fill_model", "outcome", "exit_reason")
            else pl.Float64()
        )
        for f in dataclasses.fields(Trade)
    },
}


def _frame(items: list[Any], cls: type, d: date) -> pl.DataFrame:
    rows = []
    for it in items:
        r = dataclasses.asdict(it)
        rows.append({k: list(v) if isinstance(v, tuple) else v for k, v in r.items()})
    return pl.DataFrame(rows, schema=SCHEMAS[cls]).with_columns(session_date=pl.lit(d))


def session_job(args: tuple[date, dict[str, pl.DataFrame]]) -> dict[str, pl.DataFrame]:
    d, t = args
    cfg = load_config()
    cal = TradingCalendar(cfg)
    out: dict[str, list[pl.DataFrame]] = {"decisions": [], "candidates": [], "trades": []}
    for side in ("C", "P"):
        sig = [Signal(ts, side) for ts in cal.prediction_timestamps(d)]
        res = run_session(d, sig, t["und"], t["chain"], t["records"], cal, cfg)
        out["decisions"].append(_frame(res.decisions, Decision, d))
        out["candidates"].append(_frame(res.candidates, Candidate, d))
        out["trades"].append(_frame(res.trades, Trade, d))
    return {k: pl.concat(v) for k, v in out.items()}


def reconcile(trades: pl.DataFrame, label_dir: Path) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Join every simulated trade to the C label trade at the same (side, T)."""
    labs = pl.concat(
        [
            pl.read_parquet(label_dir / f"session={d}.parquet")
            for d in trades["session_date"].unique().sort().to_list()
        ]
    ).select(
        "side",
        pl.col("prediction_ts").cast(DT),
        pl.col("entry_price").alias("l_entry"),
        pl.col("exit_ts").cast(DT).alias("l_exit_ts"),
        pl.col("exit_price").alias("l_exit"),
        pl.col("net_pnl").alias("l_net"),
        pl.col("outcome_class").alias("l_outcome"),
        pl.col("reason").alias("l_reason"),
        pl.col("contract").alias("l_symbol"),
    )
    j = trades.join(labs, on=["side", "prediction_ts"], how="left")
    trig = pl.col("outcome").is_in(["WIN", "LOSS"])
    j = j.with_columns(
        m_symbol=pl.col("symbol") == pl.col("l_symbol"),
        m_outcome=pl.col("outcome") == pl.col("l_outcome"),
        m_entry=(pl.col("entry_price") - pl.col("l_entry")).abs() < TOL,
        m_exit=((pl.col("exit_price") - pl.col("l_exit")).abs() < TOL)
        | (pl.col("exit_price").is_null() & pl.col("l_exit").is_null()),
        m_net=((pl.col("net_pnl") - pl.col("l_net")).abs() < TOL)
        | (pl.col("net_pnl").is_null() & pl.col("l_net").is_null()),
        # trigger exits share a timestamp; time exits differ by the 5 s latency by convention
        m_exit_ts=pl.when(trig).then(pl.col("exit_ts") == pl.col("l_exit_ts")).otherwise(True),
    ).with_columns(
        match=pl.all_horizontal(
            "m_symbol", "m_outcome", "m_entry", "m_exit", "m_net", "m_exit_ts"
        ).fill_null(False)
    )
    summary = {
        k: int(j[k].fill_null(False).sum())
        for k in ("m_symbol", "m_outcome", "m_entry", "m_exit", "m_net", "m_exit_ts", "match")
    }
    summary["n"] = j.height
    return j, summary


def _num(x: object) -> float:
    return float(x) if isinstance(x, int | float) else float("nan")


def _ci(df: pl.DataFrame, col: str, reps: int, seed: int, level: float) -> tuple[float, float]:
    v = df[col].to_numpy().astype(np.float64)
    return session_bootstrap_ci(
        df["session_date"].to_numpy(), lambda w: float(np.average(v, weights=w)), reps, seed, level
    )


def write_report(
    dec: pl.DataFrame,
    trades: pl.DataFrame,
    rec: pl.DataFrame,
    summ: dict[str, dict[str, Any]],
    meta: dict[str, Any],
) -> None:
    lines = [
        "# M11 mechanical diagnostic backtest (NOT a strategy)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {meta['commit'][:12]}, run "
        f"`{meta['run_id']}`. Sessions {meta['n_sessions']} ({meta['first']} → {meta['last']}, "
        f"pre-holdout research sessions; holdout after {meta['hold']} not opened).",
        "",
        "**What this is.** Until calibration exists (M13) the decision engine must output NO_TRADE "
        "(spec §4.1, rule 6). To exercise the backtester on real data, a mechanical signal "
        "requests a CALL (separately a PUT) at every prediction timestamp; the §4.7 limits (one "
        "open position, at most 3 entries per session), the frozen selection rule (§5), the §4.9 "
        "gates and the conservative fill (§6: buy the ask, sell the bid, both rounded against the "
        "trader) apply. The P&L below is an **unconditional-entry baseline** for later comparison "
        "(gate 14), not evidence of an edge, and not a claim of profitability (rule 12).",
        "",
        "## Decisions per signal",
        "",
        "| side | signals | ENTERED | BLOCKED_POSITION_OPEN | NO_TRADE (by reason) | UNFILLED |",
        "|---|---|---|---|---|---|",
    ]
    for side in ("C", "P"):
        d = dec.filter(pl.col("side") == side)
        nt = (
            d.filter(pl.col("decision") == "NO_TRADE")
            .group_by("reason")
            .len()
            .sort("len", descending=True)
        )
        cnt = {r["decision"]: r["len"] for r in d.group_by("decision").len().to_dicts()}
        lines.append(
            f"| {side} | {d.height:,} | {cnt.get('ENTERED', 0):,} "
            f"| {cnt.get('BLOCKED_POSITION_OPEN', 0):,} | "
            + ", ".join(f"{r['reason']} {r['len']:,}" for r in nt.to_dicts())
            + f" | {cnt.get('UNFILLED', 0):,} |"
        )
    lines += [
        "",
        "## Reconciliation with the C labels (M6, independent implementation)",
        "",
        "Each simulated trade is matched to the C label at the same side and prediction time. "
        "Exit timestamps are compared for target/stop exits only: a time exit happens at "
        "T_e + 90 min in the backtester (spec §2: entry + max holding) and at T + 90 min in the "
        "label (§3), the same 1-minute quote either way.",
        "",
        "| side | trades | symbol | outcome | entry | exit price | net P&L | exit ts "
        "| all fields |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for side, s in summ.items():
        lines.append(
            f"| {side} | {s['n']:,} | {s['m_symbol']:,} | {s['m_outcome']:,} | {s['m_entry']:,} "
            f"| {s['m_exit']:,} | {s['m_net']:,} | {s['m_exit_ts']:,} | {s['match']:,} |"
        )
    mism = rec.filter(~pl.col("match"))
    lines += ["", f"Mismatches: {mism.height:,}."]
    if mism.height:
        lines += [
            "",
            "| session | T | side | outcome / label | entry / label | exit / label | net / label |",
            "|---|---|---|---|---|---|---|",
            *[
                f"| {r['session_date']} | {r['prediction_ts']:%H:%M} | {r['side']} "
                f"| {r['outcome']} / {r['l_outcome']} ({r['l_reason']}) "
                f"| {r['entry_price']} / {r['l_entry']} | {r['exit_price']} / {r['l_exit']} "
                f"| {r['net_pnl']} / {r['l_net']} |"
                for r in mism.head(50).to_dicts()
            ],
        ]
    lines += [
        "",
        "## Unconditional-entry baseline (conservative fill, net of §4.8 costs, per contract)",
        "",
        f"Mean net P&L CI: session-block bootstrap, {meta['reps']} reps, {meta['level']:.0%}. "
        "UNRESOLVED_DATA and UNFILLED trades have no P&L and are counted separately.",
        "",
        "| side | trades | WIN | LOSS | BREAKEVEN | TIME_EXIT_PROFIT | TIME_EXIT_LOSS "
        "| UNRESOLVED | mean net $ [CI] | median net $ | mean R | median hold (min) "
        "| median MFE | median MAE | mean spread cost $ |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for side in ("C", "P"):
        t = trades.filter(pl.col("side") == side)
        done = t.filter(pl.col("net_pnl").is_not_null())
        oc = {r["outcome"]: r["len"] for r in t.group_by("outcome").len().to_dicts()}
        lo, hi = _ci(done, "net_pnl", meta["reps"], meta["seed"], meta["level"])
        lines.append(
            f"| {side} | {t.height:,} | {oc.get('WIN', 0):,} | {oc.get('LOSS', 0):,} "
            f"| {oc.get('BREAKEVEN', 0):,} | {oc.get('TIME_EXIT_PROFIT', 0):,} "
            f"| {oc.get('TIME_EXIT_LOSS', 0):,} | {oc.get('UNRESOLVED_DATA', 0):,} "
            f"| {_num(done['net_pnl'].mean()):+.2f} [{lo:+.2f}, {hi:+.2f}] "
            f"| {_num(done['net_pnl'].median()):+.2f} | {_num(done['r_multiple'].mean()):+.3f} "
            f"| {_num(done['holding_seconds'].median()) / 60:.1f} "
            f"| {_num(done['mfe'].median()):+.3f} | {_num(done['mae'].median()):+.3f} "
            f"| {_num(done['spread_cost'].mean()):.2f} |"
        )
    flags = (
        trades.explode("flags", empty_as_null=True)
        .drop_nulls("flags")
        .group_by("side", "flags")
        .len()
        .sort("side", "len", descending=[False, True])
    )
    lines += [
        "",
        "## Path flags",
        "",
        "| side | flag | trades |",
        "|---|---|---|",
        *[f"| {r['side']} | {r['flags']} | {r['len']:,} |" for r in flags.to_dicts()],
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:  # noqa: PLR0915 (linear pipeline)
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    cal = TradingCalendar(cfg)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set: every run must be registered in validation_runs")
        return 2
    engine = create_engine(url)
    hold = cal.final_holdout_start(END)
    sessions = cal.research_sessions(cfg.history.option_era_start, hold)
    HoldoutGuard(hold, engine).check(sessions)
    commit = code_commit(ROOT)
    features_id = dataset_id(engine, f"data/features/{cfg.features.version}")
    run_cfg = {
        "model": "mechanical_diagnostic",
        "signal": "every prediction timestamp, CALL and PUT run separately",
        "fill_model": "CONSERVATIVE",
        "trade": cfg.trade.model_dump(mode="json"),
        "fills": cfg.fills.model_dump(mode="json"),
        "costs": cfg.costs.model_dump(mode="json"),
        "liquidity": cfg.liquidity.model_dump(mode="json"),
        "labels_option": cfg.labels.option.model_dump(mode="json"),
    }
    run_id = register_run(
        engine,
        run_kind="diagnostic",
        config=run_cfg,
        data_window=(sessions[0], sessions[-1]),
        dataset_id=features_id,
        code_commit=commit,
        folds=[],
    )
    print(f"registered run {run_id}")
    try:
        und = pl.read_parquet(CLEAN / "cleaned_market_data" / "bbo-1m" / "QQQ.parquet").select(
            "session_date", "available_at", "bid", "ask"
        )
        raw_defs = pl.concat(
            [
                pl.read_parquet(p)
                for p in (ROOT / "data" / "raw" / "parquet" / "OPRA.PILLAR" / "definition").rglob(
                    "*.parquet"
                )
            ],
            how="diagonal_relaxed",
        )
        chain = chain_table(build_definitions(raw_defs, cal), cfg)

        def jobs() -> Iterator[tuple[date, dict[str, pl.DataFrame]]]:
            for d in sessions:
                nxt = cal.next_session(d)
                ch = chain.filter((pl.col("session_date") == d) & (pl.col("expiration") == nxt))
                c = CLEAN / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"
                r = REJECTED / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"
                recs = option_records(pl.read_parquet(c), pl.read_parquet(r))
                recs = recs.filter(pl.col("symbol").is_in(ch["raw_symbol"].to_list()))
                yield (
                    d,
                    {"und": und.filter(pl.col("session_date") == d), "chain": ch, "records": recs},
                )

        parts: dict[str, list[pl.DataFrame]] = {"decisions": [], "candidates": [], "trades": []}
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for i, res in enumerate(pool.map(session_job, jobs(), chunksize=2), 1):
                for k, v in res.items():
                    parts[k].append(v)
                if i % 100 == 0:
                    print(f"sessions {i}/{len(sessions)}", flush=True)
        out = {k: pl.concat(v) for k, v in parts.items()}
        odir = ROOT / "data" / "backtest" / "m11_diagnostic" / run_id
        odir.mkdir(parents=True, exist_ok=True)
        for k, v in out.items():
            v.write_parquet(odir / f"{k}.parquet")
        trades = out["trades"].filter(pl.col("outcome") != "UNFILLED")
        rec, summ = pl.DataFrame(), {}
        recs = []
        for side in ("C", "P"):
            j, s = reconcile(
                trades.filter(pl.col("side") == side),
                ROOT / "data" / "labels" / f"{cfg.labels.version}_option",
            )
            recs.append(j)
            summ[side] = s
        rec = pl.concat(recs)
        metrics = {
            "reconciliation": summ,
            "decisions": out["decisions"].group_by("side", "decision").len().to_dicts(),
            "outcomes": out["trades"].group_by("side", "outcome").len().to_dicts(),
        }
    except Exception as e:
        fail_run(engine, run_id, repr(e))
        raise
    complete_run(engine, run_id, metrics)
    write_report(
        out["decisions"],
        out["trades"],
        rec,
        summ,
        {
            "commit": commit,
            "run_id": run_id,
            "n_sessions": len(sessions),
            "first": sessions[0],
            "last": sessions[-1],
            "hold": hold,
            "reps": cfg.validation.bootstrap_reps,
            "seed": cfg.models.metrics.bootstrap_seed,
            "level": cfg.models.metrics.ci_level,
        },
    )
    engine.dispose()
    print(f"completed run {run_id}; report {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
