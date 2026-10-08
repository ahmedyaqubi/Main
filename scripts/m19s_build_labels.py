"""M19S (ADR-0012) Step 1 inputs: study trade labels for T1a-T5 and the QQQ move at each study
horizon, for every pre-holdout research session (the holdout is never read, ADR-0011).

T0 is the Phase 1 C label and is not rebuilt: `--verify-t0 K` recomputes it with the default
exit rule on every K-th session and requires an exact match with the stored L2 option labels;
the same sessions' ret_90 must reproduce the stored A_up / A_dn labels.

Outputs (data/labels/<study_1b.labels_dir>/):
  <definition>/session=<D>.parquet   one trade per (prediction_ts, side): OUTCOME_SCHEMA +
                                      ambiguous_bar + session_date
  moves/session=<D>.parquet          prediction_ts, ret_<h>, reason_<h> for h in 45 / 90 / 150
Registered as label datasets. Labels are data, not trials (no model is fit).

    uv run python scripts/m19s_build_labels.py [--workers 7] [--limit-sessions N] [--verify-t0 K]
        [--no-register]
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import polars as pl
from dotenv import load_dotenv
from sqlalchemy import create_engine

from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import code_commit
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import config_hash, load_config
from qqq1dte.features.inputs import chain_table
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.ingestion.databento_raw import compute_dataset_id
from qqq1dte.labels.option import OUTCOME_SCHEMA, ExitRule, option_label, option_records
from qqq1dte.labels.underlying import underlying_move
from qqq1dte.validation.records import build_definitions

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean" / "cleaned"
REJECTED = ROOT / "data" / "clean" / "rejected"
END = date(2026, 10, 2)
CFG = load_config()
OUT = ROOT / "data" / "labels" / CFG.study_1b.labels_dir
STORED_T0 = ROOT / "data" / "labels" / f"{CFG.labels.version}_option"
STORED_A = ROOT / "data" / "labels" / CFG.labels.version
BUILD = [d for d in CFG.study_1b.definitions if d != "T0"]
HORIZONS = sorted({90, *CFG.study_1b.refit_horizons})
TRADE_SCHEMA = {**OUTCOME_SCHEMA, "ambiguous_bar": pl.Boolean(), "session_date": pl.Date()}


def trades(
    d: date, t: dict[str, pl.DataFrame], rule: ExitRule, cal: TradingCalendar
) -> pl.DataFrame:
    rows = []
    for ts in cal.prediction_timestamps(d):
        for side in ("C", "P"):
            lab, oc = option_label(
                side,
                ts,
                d,
                t["und"],
                t["chain"],
                t["records"],
                cal,
                CFG,
                rule=rule,
                bars=t["bars"],
            )
            rows.append({**dataclasses.asdict(oc), "ambiguous_bar": lab.ambiguous_bar})
    return pl.DataFrame(rows, schema=OUTCOME_SCHEMA | {"ambiguous_bar": pl.Boolean()}).with_columns(
        session_date=pl.lit(d)
    )


def moves(d: date, bars: pl.DataFrame, cal: TradingCalendar) -> pl.DataFrame:
    rows = []
    for ts in cal.prediction_timestamps(d):
        r: dict[str, object] = {"session_date": d, "prediction_ts": ts}
        for h in HORIZONS:
            ret, _, why = underlying_move(bars, d, ts, cal, CFG, h)
            r[f"ret_{h}"], r[f"reason_{h}"] = ret, why
        rows.append(r)
    schema: dict[str, pl.DataType] = {
        "session_date": pl.Date(),
        "prediction_ts": pl.Datetime("ns", "UTC"),
    }
    for h in HORIZONS:
        schema |= {f"ret_{h}": pl.Float64(), f"reason_{h}": pl.String()}
    return pl.DataFrame(rows, schema=schema)


def session_job(args: tuple[date, dict[str, pl.DataFrame], bool]) -> tuple[date, int, str | None]:
    d, t, verify = args
    cal = TradingCalendar(CFG)
    n = 0
    for name in BUILD:
        df = trades(d, t, ExitRule.from_study(CFG.study_1b.definitions[name]), cal)
        df.write_parquet(OUT / name / f"session={d}.parquet")
        n += df.height
    mv = moves(d, t["bars"], cal)
    mv.write_parquet(OUT / "moves" / f"session={d}.parquet")
    mismatch = None
    if verify:  # T0 = the Phase 1 rule must reproduce the stored labels exactly
        new = trades(d, t, ExitRule.phase1(CFG), cal).drop("ambiguous_bar")
        old = pl.read_parquet(STORED_T0 / f"session={d}.parquet").select(new.columns)
        if not new.equals(old):
            mismatch = f"{d} T0"
        # ret_90 against the deadband must reproduce the stored A_up / A_dn labels
        a = (
            pl.read_parquet(STORED_A / f"session={d}.parquet")
            .filter(pl.col("label_id").is_in(["A_up", "A_dn"]))
            .pivot(on="label_id", index="prediction_ts", values="value")
            .join(mv, on="prediction_ts", how="full", coalesce=True)
        )
        db = CFG.labels.direction.deadband
        up = (pl.col("ret_90") > db).cast(pl.Int8)
        dn = (pl.col("ret_90") < -db).cast(pl.Int8)
        if not a.select(
            (up.eq_missing(pl.col("A_up")) & dn.eq_missing(pl.col("A_dn"))).all()
        ).item():
            mismatch = f"{d} A"
    return d, n, mismatch


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--limit-sessions", type=int, default=0)
    ap.add_argument("--verify-t0", type=int, default=10, help="verify T0 on every K-th session")
    ap.add_argument("--no-register", action="store_true", help="smoke run: no dataset rows")
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    url = os.environ["DATABASE_URL"]
    engine = create_engine(url)
    cal = TradingCalendar(CFG)
    hold = cal.final_holdout_start(END)
    sessions = cal.research_sessions(CFG.history.option_era_start, hold)
    HoldoutGuard(hold, engine).check(sessions)
    if args.limit_sessions:
        sessions = sessions[: args.limit_sessions]
    bars = pl.read_parquet(CLEAN / "cleaned_market_data" / "ohlcv-1m" / "QQQ.parquet")
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
    chain = chain_table(build_definitions(raw_defs, cal), CFG)

    def jobs() -> Iterator[tuple[date, dict[str, pl.DataFrame], bool]]:
        for i, d in enumerate(sessions):
            ch = chain.filter(
                (pl.col("session_date") == d) & (pl.col("expiration") == cal.next_session(d))
            )
            c = CLEAN / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"
            r = REJECTED / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"
            if not c.exists():  # rule 9: never assume data exists
                raise FileNotFoundError(f"no cleaned OPRA quotes for research session {d}")
            recs = option_records(pl.read_parquet(c), pl.read_parquet(r)).filter(
                pl.col("symbol").is_in(ch["raw_symbol"].to_list())
            )
            yield (
                d,
                {
                    "bars": bars.filter(pl.col("session_date") == d),
                    "und": und.filter(pl.col("session_date") == d),
                    "chain": ch,
                    "records": recs,
                },
                bool(args.verify_t0) and i % args.verify_t0 == 0,
            )

    for name in [*BUILD, "moves"]:
        (OUT / name).mkdir(parents=True, exist_ok=True)
    total, verified, mismatches = 0, 0, []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, (d, n, bad) in enumerate(pool.map(session_job, jobs(), chunksize=1), 1):
            total += n
            verified += bool(args.verify_t0) and (i - 1) % args.verify_t0 == 0
            if bad:
                mismatches.append(bad)
            if i % 25 == 0:
                print(f"study labels {i}/{len(sessions)} (last {d})", flush=True)
    print(f"T0 + A verification: {verified} sessions, mismatches: {mismatches or 'none'}")
    if mismatches:
        print("stored labels not reproduced: stopping before registration")
        return 1
    if args.no_register:
        engine.dispose()
        print(f"smoke run: {total:,} study trades over {len(sessions)} sessions, not registered")
        return 0
    commit = code_commit(ROOT)
    cfg_h = config_hash(CFG.model_dump(mode="json"))
    for name in [*BUILD, "moves"]:
        uri = f"data/labels/{CFG.study_1b.labels_dir}/{name}"
        fid = compute_dataset_id("labels", "QQQ", uri, [cfg_h, commit])
        record_dataset(
            engine,
            DatasetVersion(
                dataset_id=fid,
                kind="labels",
                source="qqq1dte",
                coverage_start=sessions[0],
                coverage_end=sessions[-1],
                row_count=pl.scan_parquet(ROOT / uri / "*.parquet")
                .select(pl.len())
                .collect()
                .item(),
                storage_uri=uri,
                code_commit=commit,
                config_hash=cfg_h,
            ),
        )
    engine.dispose()
    print(f"wrote {total:,} study trades over {len(sessions)} sessions to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
