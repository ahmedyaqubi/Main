"""M23 Step 1 inputs (ADR-0014 D2, R1-R12): SPX longer-dated credit-spread labels for cells L1-L4
on every development session (`study_2a.start` -> `study_2a.dev_end`). Labels are data, not a
trial.

Per session D and cell, at T_e = `entry_time` + latency:
- W from the previous Cboe close (R2), and the expiry closest to the target DTE among expiries
  listed on an earlier day (symbology universe) or whose definitions are known at T_e (D2).
  If that expiry was not stored, the row is UNRESOLVED_DATA `EXPIRY_NOT_STORED`. It is never
  replaced by another expiry (M23 leakage review).
- Open with `labels.longspread.open_long_spread`. Close at `exit_time` (close - 15 min on early
  closes) + latency on the session before expiry, with `close_long_spread`.
- Statuses:
  - OK / NO_TRADE / UNRESOLVED_DATA;
  - EXCLUDED: `NO_EXPIRY`, or `CROSSES_HOLDOUT` when the exit session is after dev_end. That
    exit is never read.

Output: data/labels/<study_2a.labels_dir>/<cell>/session=<D>.parquet. `--register` records the
dataset (committed code and the full range only).

    uv run python scripts/m23_build_labels.py [--workers 6] [--limit-sessions N] [--from YYYY-MM-DD]
        [--register]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
from dotenv import load_dotenv
from sqlalchemy import create_engine

from m23_build_data import spx_config
from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import code_commit
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config, config_hash, load_config
from qqq1dte.core.timeutil import ET
from qqq1dte.execution_sim.longdated import exit_session, select_stored_expiry, width_from_close
from qqq1dte.execution_sim.selection import Contract
from qqq1dte.features.inputs import chain_table
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.ingestion.databento_raw import compute_dataset_id
from qqq1dte.labels.longspread import LongOpened, close_long_spread, open_long_spread
from qqq1dte.labels.option import option_records
from qqq1dte.labels.spread import quote_at

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean" / "m23"
FILLS = ("conservative", "moderate", "mid")
EXCLUDED = "EXCLUDED"


def records(d: date, dev_end: date) -> pl.DataFrame:
    if d > dev_end:
        raise RuntimeError(f"holdout session {d} requested: refused (ADR-0014 D3)")
    c, r = CLEAN / "cleaned" / f"{d}.parquet", CLEAN / "rejected" / f"{d}.parquet"
    if not c.exists():
        return pl.DataFrame()
    rej = (
        pl.read_parquet(r)
        if r.exists()
        else pl.DataFrame(schema={"symbol": pl.String, "ts": pl.Datetime("ns", "UTC")})
    )
    return option_records(pl.read_parquet(c), rej)


def spx_closes(cfg: Phase1Config) -> dict[date, float]:
    df = pl.read_csv(ROOT / cfg.study_2a.spx_close_csv).select(
        d=pl.col("DATE").str.strptime(pl.Date, "%m/%d/%Y"), c=pl.col("SPX").cast(pl.Float64)
    )
    return dict(zip(df["d"].to_list(), df["c"].to_list(), strict=True))


def load_chain(base: Phase1Config) -> pl.DataFrame:
    defs = pl.read_parquet(CLEAN / "definitions.parquet").filter(
        pl.col("session_date") <= base.study_2a.dev_end
    )
    return pl.concat([chain_table(defs, spx_config(base, r)) for r in ("SPX", "SPXW")])


def first_listing() -> dict[date, date]:
    """Per SPX/SPXW expiry: the first day any of its contracts was listed (free symbology
    universe from Step 0; day-level, so only days before D count as known at T_e)."""
    uni = pl.concat(
        [
            pl.read_parquet(f)
            for f in sorted((ROOT / "data/raw/databento/m23/universe").glob("*.parquet"))
        ]
    ).with_columns(
        d0=pl.col("d0").str.to_date(),
        expiry=pl.col("raw_symbol").str.slice(6, 6).str.to_date("%y%m%d"),
    )
    f = uni.group_by("expiry").agg(pl.col("d0").min())
    return dict(zip(f["expiry"].to_list(), f["d0"].to_list(), strict=True))


def exit_time(cal: TradingCalendar, d: date, cfg: Phase1Config) -> datetime:
    s = cfg.study_2a
    _, close = cal.open_close(d)
    if cal.is_early_close(d):
        return close - timedelta(minutes=s.early_exit_offset_min)
    return datetime.combine(d, s.exit_time, ET).astimezone(UTC)


def session_job(args: tuple[date, float, pl.DataFrame, set[date]]) -> dict[str, int]:
    d, prev_close, chain, listed_before = args
    base = load_config()
    cfg = spx_config(base, "SPXW")
    cal = TradingCalendar(cfg)
    s = cfg.study_2a
    sessions = cal.sessions(s.start, s.dev_end + timedelta(days=90))
    sset = set(sessions)
    latency = timedelta(seconds=cfg.fills.latency_s)
    t = datetime.combine(d, s.entry_time, ET).astimezone(UTC)
    t_e = t + latency
    w = width_from_close(prev_close, s.width_share, s.width_grid, s.width_min)
    known = chain.filter(pl.col("available_at") <= t_e)
    known_today = set(known["expiration"].to_list())
    stored = set(chain["expiration"].to_list())
    recs = records(d, s.dev_end)
    q = quote_at(recs, t_e) if recs.height else {}
    counts: dict[str, int] = {}
    for name, cell in s.cells.items():
        pick, exp = select_stored_expiry(
            listed_before, known_today, stored, d, cell.target_dte, sset
        )
        row: dict[str, Any] = {"session_date": d, "cell": name, "prediction_ts": t,
                               "W": w, "prev_close": prev_close, "expiry": exp}  # fmt: skip
        if exp is None:
            row |= {"status": EXCLUDED, "reason": "NO_EXPIRY"}
        elif pick != "OK":  # chosen point-in-time but not stored: never substituted
            row |= {"status": "UNRESOLVED_DATA", "reason": pick, "dte": (exp - d).days}
        else:
            ex = exit_session(exp, sessions)
            hold = len([x for x in sessions if ex is not None and d < x <= ex])
            row |= {"dte": (exp - d).days, "exit_session": ex, "hold": hold}
            contracts = [
                Contract(
                    r["raw_symbol"], r["strike"], r["right"], r["expiration"], r["available_at"]
                )
                for r in known.filter(pl.col("expiration") == exp).iter_rows(named=True)
            ]
            o = open_long_spread(contracts, q, t_e, cell.structure, cell.x, w, cfg)
            if not isinstance(o, LongOpened):
                row |= {"status": "NO_TRADE", "reason": o.reason, "details": ",".join(o.details)}
            else:
                row |= {
                    "legs": ";".join(f"{lg.role}:{lg.contract.symbol}" for lg in o.legs),
                    **{f"credit_{f}": o.credit[f] for f in FILLS},
                }
                if ex is None or ex > s.dev_end:
                    row |= {"status": EXCLUDED, "reason": "CROSSES_HOLDOUT"}
                else:
                    xr = records(ex, s.dev_end)
                    t_x = exit_time(cal, ex, cfg) + latency
                    qx = quote_at(xr, t_x) if xr.height else {}
                    out = close_long_spread(
                        o, {lg.contract.symbol: qx.get(lg.contract.symbol) for lg in o.legs},
                        t_x, cfg,
                    )  # fmt: skip
                    row |= {
                        "status": out.status,
                        "reason": out.reason,
                        "max_risk": out.max_risk,
                        **{f"net_{f}": out.net.get(f) for f in FILLS},
                        **{f"costs_{f}": out.costs.get(f) for f in FILLS},
                    }
        df = pl.DataFrame([row], infer_schema_length=None)
        path = ROOT / "data" / "labels" / s.labels_dir / name / f"session={d}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(path)
        counts[name] = counts.get(name, 0) + 1
    return counts


def dirty() -> bool:
    out = subprocess.run(
        ["git", "status", "--porcelain", "src", "scripts", "configs"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return bool(out.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit-sessions", type=int, default=0)
    ap.add_argument("--from", dest="start", type=date.fromisoformat, default=None)
    ap.add_argument("--register", action="store_true")
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    if args.register and (dirty() or args.start or args.limit_sessions):
        print("--register needs committed code and the full session range")
        return 1
    base = load_config()
    cal = TradingCalendar(spx_config(base, "SPXW"))
    s = base.study_2a
    sessions = cal.sessions(s.start, s.dev_end)
    HoldoutGuard(s.dev_end, None).check(sessions)
    if args.start:
        sessions = [d for d in sessions if d >= args.start]
    if args.limit_sessions:
        sessions = sessions[: args.limit_sessions]
    chain = load_chain(base)
    closes = spx_closes(base)
    first = first_listing()
    jobs = []
    for d in sessions:
        prev = max(x for x in closes if x < d)
        before = {e for e, d0 in first.items() if d0 < d < e}
        jobs.append((d, closes[prev], chain.filter(pl.col("session_date") == d), before))
    total: dict[str, int] = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, c in enumerate(pool.map(session_job, jobs, chunksize=4), 1):
            for k, v in c.items():
                total[k] = total.get(k, 0) + v
            if i % 250 == 0:
                print(f"labels {i}/{len(jobs)}", flush=True)
    print(f"label rows per cell: {dict(sorted(total.items()))}", flush=True)
    if args.register:
        commit = code_commit(ROOT)
        cfg_h = config_hash(base.model_dump(mode="json"))
        uri = f"data/labels/{s.labels_dir}"
        engine = create_engine(os.environ["DATABASE_URL"])
        new = record_dataset(
            engine,
            DatasetVersion(
                dataset_id=compute_dataset_id("labels", "SPX", uri, [cfg_h, commit]),
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
