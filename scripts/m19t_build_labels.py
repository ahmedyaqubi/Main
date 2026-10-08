"""M19T Step 1 inputs (ADR-0013 D1, R1-R5): credit-spread labels for cells S1-S6 on every
development session 2020-01-02 -> 2026-04-02. Labels are data, not a trial.

Per session D and cell, for every entry time T in the cell window (`schedule.cadence_minutes`,
capped at `last_new_entry`; T_e = T + latency):
- Entry chain:
  - 0DTE: contracts expiring D, from the Step-0 store (`ext` before 2023-03-28, `0dte` after).
  - 1DTE: contracts expiring next_session(D), from `ext` before 2023-03-28 and from the M4
    store after.
- Open, then close at the expiry session's forced exit. Hold gaps are measured over RTH:
  - 0DTE: [T_e, exit];
  - 1DTE: [T_e, close D] plus [open E, exit].
- Statuses:
  - OK / NO_TRADE / UNRESOLVED_DATA (`labels.spread`);
  - EXCLUDED: `EX_DIV_SPAN` (D1.d), `LABEL_CROSSES_BLOCK` (expiry after dev_end; the holdout is
    never read), `EXIT_SESSION_EXCLUDED` (ADR-0006).
- Sessions where the cell's expiry is not listed produce no rows; the screen counts them.

Outputs: data/labels/<study_1c.labels_dir>/<cell>/session=<D>.parquet. `--register` records the
dataset (committed code only).

    uv run python scripts/m19t_build_labels.py [--workers 6] [--limit-sessions N]
        [--from YYYY-MM-DD] [--register]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import polars as pl
from dotenv import load_dotenv
from sqlalchemy import create_engine

from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import code_commit
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config, config_hash, load_config
from qqq1dte.core.dividends import ExDividend, ex_dividend_dates
from qqq1dte.core.timeutil import ET, ensure_utc
from qqq1dte.execution_sim.selection import Contract
from qqq1dte.features.inputs import chain_table
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.ingestion.databento_raw import compute_dataset_id
from qqq1dte.labels.option import option_records
from qqq1dte.labels.spread import (
    FILLS,
    NoTrade,
    close_spread,
    ex_div_span,
    open_spread,
    quote_at,
)
from qqq1dte.validation.records import build_definitions
from qqq1dte.validation.spread_coverage import longest_gap_minutes

ROOT = Path(__file__).resolve().parents[1]
M19T = ROOT / "data" / "clean" / "m19t"
M4 = ROOT / "data" / "clean"
ZERO_START = date(2023, 3, 28)  # first session of the Step-0 0dte store / M4 option era
EXCLUDED = "EXCLUDED"


# inputs ------------------------------------------------------------------------------------------
def store_0dte(d: date) -> str:
    return "ext" if d < ZERO_START else "0dte"


def store_1dte(d: date) -> str:
    return "ext" if d < ZERO_START else "m4"


def records(src: str, d: date, dev_end: date) -> pl.DataFrame:
    if d > dev_end:
        raise RuntimeError(f"holdout session {d} requested: refused (ADR-0011)")
    if src == "m4":
        c = M4 / "cleaned" / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"
        r = M4 / "rejected" / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"
    else:
        c, r = M19T / "cleaned" / src / f"{d}.parquet", M19T / "rejected" / src / f"{d}.parquet"
    return option_records(pl.read_parquet(c), pl.read_parquet(r))


def load_chains(cfg: Phase1Config, cal: TradingCalendar) -> dict[str, pl.DataFrame]:
    dev_end = cfg.study_1c.dev_end
    out = {
        src: chain_table(pl.read_parquet(M19T / "definitions" / f"{src}.parquet"), cfg).filter(
            pl.col("session_date") <= dev_end
        )
        for src in ("0dte", "ext")
    }
    m4 = pl.concat(
        [
            pl.read_parquet(p)
            for p in (ROOT / "data" / "raw" / "parquet" / "OPRA.PILLAR" / "definition").rglob(
                "*.parquet"
            )
        ],
        how="diagonal_relaxed",
    )
    out["m4"] = chain_table(build_definitions(m4, cal), cfg).filter(
        pl.col("session_date") <= dev_end
    )
    return out


def window_times(
    cal: TradingCalendar, d: date, window: tuple[time, time], step: int
) -> list[datetime]:
    t = ensure_utc(datetime.combine(d, window[0], tzinfo=ET))
    end = min(ensure_utc(datetime.combine(d, window[1], tzinfo=ET)), cal.last_new_entry(d))
    out = []
    while t <= end:
        out.append(t)
        t += timedelta(minutes=step)
    return out


def usable_times(recs: pl.DataFrame, symbol: str) -> list[datetime]:
    r = recs.filter((pl.col("symbol") == symbol) & ~pl.col("rejected") & (pl.col("ask") > 0))
    return r["available_at"].to_list()


# one session -------------------------------------------------------------------------------------
def session_job(  # noqa: PLR0912, PLR0915 (one session, all cells)
    args: tuple[date, dict[str, pl.DataFrame], list[ExDividend]],
) -> dict[str, int]:
    d, chains, exdivs = args
    cfg = load_config()
    cal = TradingCalendar(cfg)
    s1c = cfg.study_1c
    sessions = cal.sessions(s1c.ext_start, s1c.dev_end + timedelta(days=10))
    latency = timedelta(seconds=cfg.fills.latency_s)
    cache: dict[tuple[str, date], pl.DataFrame] = {}

    def recs(src: str, day: date) -> pl.DataFrame:
        if (src, day) not in cache:
            cache[(src, day)] = records(src, day, s1c.dev_end)
        return cache[(src, day)]

    counts: dict[str, int] = {}
    for name, cell in s1c.cells.items():
        if cell.tenor == "0dte":
            src, exp = store_0dte(d), d
        else:
            src, exp = store_1dte(d), cal.next_session(d)
        ch = chains[src].filter((pl.col("session_date") == d) & (pl.col("expiration") == exp))
        if ch.height == 0:
            continue  # the cell's expiry is not listed on D
        times = window_times(cal, d, cell.window, cfg.schedule.cadence_minutes)
        rows: list[dict[str, Any]] = []
        base = {"session_date": d, "cell": name, "expiry": exp}
        if exp > s1c.dev_end or cal.exclusion_reason(exp) is not None:
            reason = "LABEL_CROSSES_BLOCK" if exp > s1c.dev_end else "EXIT_SESSION_EXCLUDED"
            rows = [
                {**base, "prediction_ts": t, "status": EXCLUDED, "reason": reason} for t in times
            ]
        else:
            contracts = [
                Contract(
                    r["raw_symbol"], r["strike"], r["right"], r["expiration"], r["available_at"]
                )
                for r in ch.iter_rows(named=True)
            ]
            entry_recs = recs(src, d).filter(pl.col("symbol").is_in(ch["raw_symbol"].to_list()))
            exit_src = store_0dte(exp)
            t_x = cal.forced_exit_time(exp) + latency
            for t in times:
                t_e = t + latency
                row: dict[str, Any] = {**base, "prediction_ts": t}
                o = open_spread(
                    contracts, quote_at(entry_recs, t_e), t_e, cell.structure, cell.x,
                    s1c.width, cfg,
                )  # fmt: skip
                if isinstance(o, NoTrade):
                    rows.append({**row, "status": "NO_TRADE", "reason": o.reason,
                                 "details": ",".join(o.details)})  # fmt: skip
                    continue
                legs = ";".join(f"{lg.role}:{lg.contract.symbol}" for lg in o.legs)
                row |= {"legs": legs, **{f"credit_{f}": o.credit[f] for f in FILLS}}
                if ex_div_span(d, exp, o.has_short_call, exdivs, sessions):
                    rows.append({**row, "status": EXCLUDED, "reason": "EX_DIV_SPAN"})
                    continue
                syms = [lg.contract.symbol for lg in o.legs]
                ex_recs = recs(exit_src, exp).filter(pl.col("symbol").is_in(syms))
                gaps = {}
                for s in syms:
                    if exp == d:
                        gaps[s] = longest_gap_minutes(usable_times(ex_recs, s), t_e, t_x)
                    else:
                        _, close_d = cal.open_close(d)
                        open_e, _ = cal.open_close(exp)
                        gaps[s] = max(
                            longest_gap_minutes(usable_times(entry_recs, s), t_e, close_d),
                            longest_gap_minutes(usable_times(ex_recs, s), open_e, t_x),
                        )
                q_x = quote_at(ex_recs, t_x)
                out = close_spread(o, {s: q_x.get(s) for s in syms}, t_x, gaps, cfg)
                rows.append(
                    {
                        **row,
                        "status": out.status,
                        "reason": out.reason,
                        "costs": out.costs,
                        "max_risk": out.max_risk,
                        "max_gap": max(gaps.values()),
                        **{f"net_{f}": out.net.get(f) for f in FILLS},
                    }
                )
        if rows:
            df = pl.DataFrame(rows, infer_schema_length=None)
            path = ROOT / "data" / "labels" / s1c.labels_dir / name / f"session={d}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            df.write_parquet(path)
            counts[name] = df.height
    return counts


# main -------------------------------------------------------------------------------------------
def dirty() -> bool:
    out = subprocess.run(
        ["git", "status", "--porcelain", "src", "scripts", "configs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return bool(out.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit-sessions", type=int, default=0)
    ap.add_argument("--from", dest="start", type=date.fromisoformat, default=None)
    ap.add_argument("--register", action="store_true")
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    if args.register and dirty():
        print("--register needs committed code (src/scripts/configs are dirty)")
        return 1
    cfg = load_config()
    cal = TradingCalendar(cfg)
    s1c = cfg.study_1c
    sessions = [d for d in cal.sessions(s1c.ext_start, s1c.dev_end) if not cal.exclusion_reason(d)]
    HoldoutGuard(s1c.dev_end, None).check(sessions)
    if args.start:
        sessions = [d for d in sessions if d >= args.start]
    if args.limit_sessions:
        sessions = sessions[: args.limit_sessions]
    if args.register and (args.start or args.limit_sessions):
        print("--register needs the full session range")
        return 1
    chains = load_chains(cfg, cal)
    exdivs = ex_dividend_dates(ROOT / s1c.ex_dividends)

    def jobs() -> Any:
        for d in sessions:
            nxt = cal.next_session(d)
            sub = {
                k: v.filter(pl.col("session_date") == d).filter(
                    pl.col("expiration").is_in([d, nxt])
                )
                for k, v in chains.items()
            }
            yield d, sub, exdivs

    total: dict[str, int] = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, counts in enumerate(pool.map(session_job, jobs(), chunksize=4), 1):
            for k, v in counts.items():
                total[k] = total.get(k, 0) + v
            if i % 100 == 0:
                print(f"labels {i}/{len(sessions)}", flush=True)
    print(f"label rows per cell: {dict(sorted(total.items()))}", flush=True)
    if args.register:
        commit = code_commit(ROOT)
        cfg_h = config_hash(cfg.model_dump(mode="json"))
        uri = f"data/labels/{s1c.labels_dir}"
        engine = create_engine(os.environ["DATABASE_URL"])
        new = record_dataset(
            engine,
            DatasetVersion(
                dataset_id=compute_dataset_id("labels", "QQQ", uri, [cfg_h, commit]),
                kind="labels",
                source="qqq1dte",
                coverage_start=sessions[0],
                coverage_end=sessions[-1],
                row_count=sum(total.values()),
                storage_uri=uri,
                code_commit=commit,
                config_hash=cfg_h,
            ),
        )
        engine.dispose()
        print(f"label dataset registered: {new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
