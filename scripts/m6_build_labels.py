"""M6: build labels (label_version L1) for every research session; write reports/labels/.

A/B/D from cleaned QQQ bars; C_call/C_put from the frozen selection rule, conservative fills
and the bid path (labels/option.py). Per-session worker processes. Outputs:
  data/labels/<version>/session=<D>.parquet          long label rows
  data/labels/<version>_option/session=<D>.parquet   C trade details (entry/exit/MFE/MAE/P&L)
  reports/labels/summary.md, reports/labels/d_stop_check.md

    uv run python scripts/m6_build_labels.py [--workers 7] [--limit-sessions N]
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import subprocess
import sys
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
from dotenv import load_dotenv
from sqlalchemy import create_engine

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import config_hash, load_config
from qqq1dte.core.timeutil import ET
from qqq1dte.features.inputs import chain_table, qqq_reference
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.ingestion.databento_raw import compute_dataset_id
from qqq1dte.labels.option import OUTCOME_SCHEMA, option_label, option_records
from qqq1dte.labels.underlying import underlying_labels
from qqq1dte.validation.records import build_definitions

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean" / "cleaned"
REJECTED = ROOT / "data" / "clean" / "rejected"
END = date(2026, 10, 2)
LABEL_SCHEMA = {
    "session_date": pl.Date(),
    "prediction_ts": pl.Datetime("ns", "UTC"),
    "label_id": pl.String(),
    "variant": pl.String(),
    "value": pl.Int8(),
    "outcome_class": pl.String(),
    "reason": pl.String(),
    "t_end": pl.Datetime("ns", "UTC"),
    "ambiguous_bar": pl.Boolean(),
    "flags": pl.List(pl.String()),
    "label_version": pl.String(),
}


def session_job(args: tuple[date, dict[str, pl.DataFrame]]) -> tuple[pl.DataFrame, pl.DataFrame]:
    d, t = args
    cfg = load_config()
    cal = TradingCalendar(cfg)
    rows, trades = [], []
    for ts in cal.prediction_timestamps(d):
        labs = underlying_labels(t["bars"], d, ts, cal, cfg)
        for side in ("C", "P"):
            lab, oc = option_label(side, ts, d, t["und"], t["chain"], t["records"], cal, cfg)
            labs.append(lab)
            trades.append(dataclasses.asdict(oc))
        for r in labs:
            rows.append(
                {
                    "session_date": d,
                    "prediction_ts": ts,
                    "label_id": r.label_id,
                    "variant": r.variant,
                    "value": r.value,
                    "outcome_class": r.outcome_class,
                    "reason": r.reason,
                    "t_end": r.t_end,
                    "ambiguous_bar": r.ambiguous_bar,
                    "flags": list(r.flags),
                    "label_version": cfg.labels.version,
                }
            )
    # Explicit schemas: type inference from the first rows breaks when early rows are all null.
    return pl.DataFrame(rows, schema=LABEL_SCHEMA), pl.DataFrame(
        trades, schema=OUTCOME_SCHEMA
    ).with_columns(session_date=pl.lit(d))


def main() -> int:  # noqa: PLR0915 (linear pipeline)
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--limit-sessions", type=int, default=0)
    ap.add_argument("--reports-only", action="store_true", help="skip computing labels")
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    cal = TradingCalendar(cfg)
    sessions = cal.research_sessions(cfg.history.option_era_start, END)
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
    chain = chain_table(build_definitions(raw_defs, cal), cfg)

    def jobs() -> Iterator[tuple[date, dict[str, pl.DataFrame]]]:
        for d in sessions:
            nxt = cal.next_session(d)
            ch = chain.filter((pl.col("session_date") == d) & (pl.col("expiration") == nxt))
            c, r = (
                CLEAN / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet",
                REJECTED / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet",
            )
            recs = option_records(pl.read_parquet(c), pl.read_parquet(r)) if c.exists() else None
            if recs is None:
                recs = pl.DataFrame(
                    schema={
                        "symbol": pl.String,
                        "available_at": pl.Datetime("ns", "UTC"),
                        "bid": pl.Float64,
                        "ask": pl.Float64,
                        "bid_sz": pl.Int64,
                        "ask_sz": pl.Int64,
                        "rejected": pl.Boolean,
                    }
                )
            recs = recs.filter(pl.col("symbol").is_in(ch["raw_symbol"].to_list()))
            yield (
                d,
                {
                    "bars": bars.filter(pl.col("session_date") == d),
                    "und": und.filter(pl.col("session_date") == d),
                    "chain": ch,
                    "records": recs,
                },
            )

    out = ROOT / "data" / "labels" / cfg.labels.version
    out_opt = ROOT / "data" / "labels" / f"{cfg.labels.version}_option"
    out.mkdir(parents=True, exist_ok=True)
    out_opt.mkdir(parents=True, exist_ok=True)
    total = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        if args.reports_only:
            pool.shutdown()
        work = [] if args.reports_only else pool.map(session_job, jobs(), chunksize=2)
        for i, (labels, trades) in enumerate(work, 1):
            d = labels["session_date"][0]
            labels.write_parquet(out / f"session={d}.parquet")
            trades.write_parquet(out_opt / f"session={d}.parquet")
            total += labels.height
            if i % 50 == 0:
                print(f"labels {i}/{len(sessions)}", flush=True)

    # Reports exclude the final holdout (spec §8, rule 5): nothing about label definitions may be
    # chosen by looking at it. The label data itself covers all sessions.
    holdout_after = cal.final_holdout_start(END)
    lab_all = pl.scan_parquet(out / "*.parquet")
    total = int(lab_all.select(pl.len()).collect().item())
    lab = lab_all.filter(pl.col("session_date") <= holdout_after).with_columns(
        year=pl.col("session_date").dt.year().cast(pl.String)
    )
    n_hidden = int(
        lab_all.filter(pl.col("session_date") > holdout_after).select(pl.len()).collect().item()
    )

    def table(keys: list[str]) -> pl.DataFrame:
        return (
            lab.group_by(keys)
            .agg(
                n=pl.len(),
                resolved=pl.col("value").is_not_null().sum(),
                positive=(pl.col("value") == 1).sum(),
                invalid=(pl.col("outcome_class") == "INVALID").sum(),
                unresolved=pl.col("outcome_class").is_in(["UNRESOLVED", "UNRESOLVED_DATA"]).sum(),
                ambiguous=pl.col("ambiguous_bar").sum(),
            )
            .sort(keys)
            .collect()
        )

    def fmt(t: pl.DataFrame, keys: list[str]) -> list[str]:
        hdr = " | ".join(keys)
        lines = [
            f"| {hdr} | n | positive rate | INVALID % | UNRESOLVED % | ambiguous-bar % |",
            "|" + "---|" * (len(keys) + 5),
        ]
        for r in t.to_dicts():
            pos = r["positive"] / r["resolved"] if r["resolved"] else float("nan")
            lines.append(
                "| "
                + " | ".join(str(r[k]) for k in keys)
                + f" | {r['n']:,} | {pos:.2%} | {r['invalid'] / r['n']:.2%} "
                f"| {r['unresolved'] / r['n']:.2%} | {r['ambiguous'] / r['n']:.2%} |"
            )
        return lines

    by_label = table(["label_id", "variant"])
    by_year = table(["label_id", "variant", "year"])
    classes = (
        lab.filter(pl.col("label_id").str.starts_with("C_"))
        .group_by(["label_id", "outcome_class"])
        .agg(n=pl.len())
        .sort(["label_id", "n"], descending=[False, True])
        .collect()
    )
    reasons = (
        lab.filter(pl.col("reason").is_not_null())
        .group_by(["label_id", "reason"])
        .agg(n=pl.len())
        .sort(["label_id", "n"], descending=[False, True])
        .collect()
    )
    flags = (
        lab.filter(pl.col("flags").list.len() > 0)
        .explode("flags", empty_as_null=False)
        .group_by(["label_id", "flags"])
        .agg(n=pl.len())
        .sort(["label_id", "flags"])
        .collect()
    )
    commit = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
        or "unknown"
    )
    lines = [
        f"# Labels {cfg.labels.version}: summary",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {commit[:12]}. Sessions "
        f"{len(sessions)} ({sessions[0]} → {sessions[-1]}), {total:,} label rows. Positive rate "
        "= share of value 1 among resolved rows (value not null). For D, 1 = stop first.",
        "",
        f"**Final holdout excluded from every table below:** sessions after {holdout_after} "
        f"({n_hidden:,} label rows) stay locked until M19 (spec §8, CLAUDE.md rule 5).",
        "",
        "## By label",
        "",
        *fmt(by_label, ["label_id", "variant"]),
        "",
        "## By label and year",
        "",
        *fmt(by_year, ["label_id", "variant", "year"]),
        "",
        "## C outcome classes",
        "",
        "| label | class | rows |",
        "|---|---|---|",
        *[f"| {r['label_id']} | {r['outcome_class']} | {r['n']:,} |" for r in classes.to_dicts()],
        "",
        "## INVALID / UNRESOLVED reasons",
        "",
        "| label | reason | rows |",
        "|---|---|---|",
        *[f"| {r['label_id']} | {r['reason']} | {r['n']:,} |" for r in reasons.to_dicts()],
        "",
        "## Flags",
        "",
        "| label | flag | rows |",
        "|---|---|---|",
        *[f"| {r['label_id']} | {r['flags']} | {r['n']:,} |" for r in flags.to_dicts()],
    ]
    rep = ROOT / "reports" / "labels"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # D-stop check: underlying move when the option hit its stop / target -----------------------
    trades = pl.concat(
        [pl.read_parquet(p) for p in out_opt.glob("*.parquet")], how="diagonal_relaxed"
    ).filter(
        pl.col("outcome_class").is_in(["WIN", "LOSS"]) & (pl.col("session_date") <= holdout_after)
    )
    moves = []
    for d, part in trades.partition_by("session_date", as_dict=True).items():
        b = bars.filter(pl.col("session_date") == d[0])
        for r in part.iter_rows(named=True):
            p0, _ = qqq_reference(
                b.filter(pl.col("available_at") <= r["prediction_ts"]),
                r["prediction_ts"],
                cal,
                d[0],
            )
            p1, _ = qqq_reference(
                b.filter(pl.col("available_at") <= r["exit_ts"]), r["exit_ts"], cal, d[0]
            )
            if p0 and p1:
                moves.append(
                    {"side": r["side"], "outcome": r["outcome_class"], "move": p1 / p0 - 1}
                )
    mv = pl.DataFrame(moves)
    q = (
        mv.group_by(["side", "outcome"])
        .agg(
            n=pl.len(),
            p10=pl.col("move").quantile(0.1, "linear"),
            p50=pl.col("move").quantile(0.5, "linear"),
            p90=pl.col("move").quantile(0.9, "linear"),
        )
        .sort(["side", "outcome"])
    )
    s_, m0 = cfg.labels.risk.stop, cfg.labels.risk.target
    d_lines = [
        "# D-label stop/target vs. the empirical option bracket",
        "",
        f"For C trades that hit the option stop (-{cfg.labels.option.stop_pct:.0%}) or target "
        f"(+{cfg.labels.option.target_pct:.0%}) on the bid, the QQQ move from P_T to the exit "
        "time. "
        f"D uses stop {s_:.2%} and target {m0:.2%} of the underlying.",
        "",
        f"Pre-holdout sessions only (through {holdout_after}); the final holdout is locked.",
        "",
        "| side | option outcome | trades | QQQ move p10 | p50 | p90 |",
        "|---|---|---|---|---|---|",
        *[
            f"| {'call' if r['side'] == 'C' else 'put'} | {r['outcome']} | {r['n']:,} "
            f"| {r['p10']:+.3%} | {r['p50']:+.3%} | {r['p90']:+.3%} |"
            for r in q.to_dicts()
        ],
        "",
        f"Reading: compare |p50| for LOSS with the D stop ({s_:.2%}) and for WIN with the D target "
        f"({m0:.2%}). A material gap means D does not mirror the option bracket. Changing D's "
        "defaults needs an ADR (M6 criterion 4).",
    ]
    (rep / "d_stop_check.md").write_text("\n".join(d_lines) + "\n", encoding="utf-8")

    url = os.environ.get("DATABASE_URL")
    if url and not args.limit_sessions:
        cfg_h = config_hash(cfg.model_dump(mode="json"))
        lid = compute_dataset_id("labels", "QQQ", cfg.labels.version, [cfg_h, commit])
        engine = create_engine(url)
        record_dataset(
            engine,
            DatasetVersion(
                dataset_id=lid,
                kind="labels",
                source="qqq1dte",
                coverage_start=sessions[0],
                coverage_end=sessions[-1],
                row_count=total,
                storage_uri=f"data/labels/{cfg.labels.version}",
                code_commit=commit,
                config_hash=cfg_h,
            ),
        )
        engine.dispose()
        print(f"registered labels dataset {lid[:16]}")
    print(f"wrote {total:,} label rows; reports in reports/labels/ ({ET})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
