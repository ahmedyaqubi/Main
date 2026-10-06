"""M4: run data-quality validation over the full ingested history and write reports/dq/.

Inputs: data/raw/databento/history/ (scripts/m4_fetch_history.py). Steps: ingest into the raw
store (idempotent) -> clean underlying -> clean options per session -> session checks ->
register cleaned datasets + aggregated events in Postgres (if DATABASE_URL) -> gates 1-2 ->
reports. Re-running is safe: outputs are recomputed from the same content.

    uv run python scripts/m4_run_dq.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
from dotenv import load_dotenv
from sqlalchemy import create_engine

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import config_hash, load_config
from qqq1dte.ingestion.catalog import DatasetVersion, record_dataset
from qqq1dte.ingestion.databento_raw import IngestResult, RawStore, compute_dataset_id, ingest_file
from qqq1dte.validation.events import (
    DQEvent,
    open_critical,
    record_events,
    resolved_from_config,
    session_events,
    write_events,
)
from qqq1dte.validation.gates import gate1, gate2
from qqq1dte.validation.liquidity import liquidity_study
from qqq1dte.validation.records import (
    CleanResult,
    build_definitions,
    clean_bars,
    clean_option_quotes,
    clean_quotes,
)
from qqq1dte.validation.report import DatasetCounts, merge_counts, render_report, summarize_dataset
from qqq1dte.validation.rules import DQ_RULES_VERSION
from qqq1dte.validation.sessions import (
    bar_coverage,
    frozen_rule_table,
    invalid_quote_rate,
    one_dte_presence,
)

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "data" / "raw" / "databento" / "history"
STORE = RawStore(ROOT / "data" / "raw")
CLEAN = ROOT / "data" / "clean"
REPORTS = ROOT / "reports" / "dq"
END = date(2026, 10, 2)


def code_commit() -> str:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "src", "scripts"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return head + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def ingest_all() -> dict[tuple[str, str], list[IngestResult]]:
    groups: dict[tuple[str, str], list[IngestResult]] = defaultdict(list)
    files = sorted(HIST.rglob("*.dbn.zst"))
    now = datetime.now(UTC)
    for i, f in enumerate(files, 1):
        r = ingest_file(f, STORE, now=now)
        groups[(r.vendor_dataset, r.schema)].append(r)
        if i % 200 == 0:
            print(f"ingested {i}/{len(files)}", flush=True)
    return groups


def read_raw(results: list[IngestResult]) -> pl.DataFrame:
    frames = [pl.read_parquet(r.parquet_path) for r in results if r.rows]
    return pl.concat(frames, how="vertical_relaxed") if frames else pl.DataFrame()


def write_clean(kind: str, schema: str, res: CleanResult, part: str) -> None:
    for name, df in (("cleaned", res.cleaned), ("rejected", res.rejected)):
        out = CLEAN / name / kind / schema / f"{part}.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(out)


def main() -> int:  # noqa: PLR0915 (linear pipeline)
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    cal = TradingCalendar(cfg)
    sessions = cal.sessions(cfg.history.option_era_start, END)
    groups = ingest_all()
    print("ingest done:", {k: len(v) for k, v in groups.items()}, flush=True)

    # Underlying ------------------------------------------------------------------------------
    raw_bars = read_raw(groups[("EQUS.MINI", "ohlcv-1m")])
    bars = clean_bars(raw_bars, cal, cfg)
    write_clean("cleaned_market_data", "ohlcv-1m", bars, "QQQ")
    raw_bbo = read_raw(groups[("EQUS.MINI", "bbo-1m")])
    bbo = clean_quotes(raw_bbo, cal, cfg)
    write_clean("cleaned_market_data", "bbo-1m", bbo, "QQQ")
    counts: list[DatasetCounts] = [
        summarize_dataset("QQQ ohlcv-1m", raw_bars, bars),
        summarize_dataset("QQQ bbo-1m", raw_bbo, bbo),
    ]
    events: list[DQEvent] = record_events(bars.cleaned, bars.rejected, "QQQ")
    events += record_events(bbo.cleaned, bbo.rejected, "QQQ")
    print("underlying cleaned", flush=True)

    # Options -----------------------------------------------------------------------------
    raw_defs = read_raw(groups[("OPRA.PILLAR", "definition")])
    defs = build_definitions(raw_defs, cal)
    # A session can have several files: the main pull plus OCC-adjusted strikes (ADR-0005).
    cbbo_by_day: dict[date, list[IngestResult]] = defaultdict(list)
    for r in groups[("OPRA.PILLAR", "cbbo-1m")]:
        cbbo_by_day[r.partition_date].append(r)
    opt_counts: list[DatasetCounts] = []
    tables, rates = [], []
    und_q = bbo.cleaned
    for i, d in enumerate(sessions, 1):
        day_files = [r for r in cbbo_by_day.get(d, []) if r.rows]
        if not day_files:
            continue  # no options data: surfaces as NO_1DTE_EXPIRY / CHAIN_COVERAGE_LOW
        raw = read_raw(day_files)
        res = clean_option_quotes(raw, defs, cal, cfg)
        write_clean("cleaned_options_data", "cbbo-1m", res, d.isoformat())
        opt_counts.append(summarize_dataset(f"QQQ options cbbo-1m {d}", raw, res))
        events += record_events(res.cleaned, res.rejected, "QQQ options")
        und_day = und_q.filter(pl.col("session_date") == d)
        tables.append(frozen_rule_table(res.cleaned, res.rejected, und_day, defs, cal, cfg, [d]))
        rates.append(invalid_quote_rate(res.cleaned, res.rejected, und_day, cal, cfg, [d]))
        if i % 50 == 0:
            print(f"options {i}/{len(sessions)}", flush=True)
    counts.append(merge_counts("QQQ options cbbo-1m", opt_counts))

    # Session checks ------------------------------------------------------------------------
    bar_cov = bar_coverage(bars.cleaned, cal, sessions)
    one = one_dte_presence(defs, cal, sessions)
    table = pl.concat(tables)
    covered = (
        table.group_by("session_date")
        .agg(
            n_timestamps=pl.len(),
            n_valid=(pl.col("spot").is_not_null() & pl.col("call_ok") & pl.col("put_ok")).sum(),
            no_spot=pl.col("spot").is_null().sum(),
            call_invalid=(pl.col("spot").is_not_null() & ~pl.col("call_ok")).sum(),
            put_invalid=(pl.col("spot").is_not_null() & ~pl.col("put_ok")).sum(),
        )
        .with_columns(share=pl.col("n_valid") / pl.col("n_timestamps"))
    )
    # Sessions with no options data at all count as zero coverage, never as missing rows.
    expected_ts = pl.DataFrame(
        {"session_date": sessions, "n_ts": [len(cal.prediction_timestamps(d)) for d in sessions]},
        schema={"session_date": pl.Date, "n_ts": pl.Int64},
    )
    chain_cov = (
        expected_ts.join(covered, on="session_date", how="left")
        .with_columns(
            n_timestamps=pl.col("n_ts"),
            n_valid=pl.col("n_valid").fill_null(0),
            no_spot=pl.col("no_spot").fill_null(0),
            call_invalid=pl.col("call_invalid").fill_null(pl.col("n_ts")),
            put_invalid=pl.col("put_invalid").fill_null(pl.col("n_ts")),
        )
        .with_columns(share=pl.col("n_valid") / pl.col("n_timestamps"))
        .drop("n_ts")
        .sort("session_date")
    )
    rate = pl.concat(rates) if rates else pl.DataFrame()
    events += session_events(bar_cov, one, chain_cov, rate, cfg)
    n_total = int(rate["n_total"].sum()) if rate.height else 0
    n_rej = int(rate["n_rejected"].sum()) if rate.height else 0
    overall_rate = n_rej / n_total if n_total else 1.0
    resolved = resolved_from_config(cfg)
    crit = open_critical(events, resolved)
    # Gate 1 population: research sessions (ADR-excluded sessions are reported, not scored).
    in_window = pl.col("session_date").is_in(cal.research_sessions(sessions[0], sessions[-1]))
    gates = [
        gate1(bar_cov.filter(in_window), chain_cov.filter(in_window), cfg),
        gate2(crit, overall_rate, cfg),
    ]

    # Catalogue + events ------------------------------------------------------------------------
    commit, cfg_h = code_commit(), config_hash(cfg.model_dump(mode="json"))
    raw_ids = {k: [r.raw_file_id for r in v] for k, v in groups.items()}
    db_note = "DATABASE_URL not set: datasets/events not written to Postgres."
    url = os.environ.get("DATABASE_URL")
    if url:
        engine = create_engine(url)
        clean_ids = {}
        for (vds, schema), ids in raw_ids.items():
            kind = "raw_options_data" if vds == "OPRA.PILLAR" else "raw_market_data"
            res_list = groups[(vds, schema)]
            raw_id = compute_dataset_id(kind, vds, schema, ids)
            record_dataset(
                engine,
                DatasetVersion(
                    dataset_id=raw_id,
                    kind=kind,
                    source="databento",
                    coverage_start=min(r.partition_date for r in res_list),
                    coverage_end=max(r.partition_date for r in res_list),
                    row_count=sum(r.rows for r in res_list),
                    storage_uri=f"data/raw/parquet/{vds}/{schema}",
                    code_commit=commit,
                    config_hash=cfg_h,
                ),
            )
            ckind = kind.replace("raw_", "cleaned_")
            cid = compute_dataset_id(ckind, vds, schema, [raw_id, cfg_h, f"dq-v{DQ_RULES_VERSION}"])
            clean_ids[(vds, schema)] = cid
            record_dataset(
                engine,
                DatasetVersion(
                    dataset_id=cid,
                    kind=ckind,
                    source="databento",
                    parent_ids=[raw_id],
                    coverage_start=min(r.partition_date for r in res_list),
                    coverage_end=max(r.partition_date for r in res_list),
                    row_count=sum(r.rows for r in res_list),
                    storage_uri=f"data/clean/cleaned/{ckind}/{schema}",
                    code_commit=commit,
                    config_hash=cfg_h,
                ),
            )
        n_ev = write_events(engine, clean_ids[("OPRA.PILLAR", "cbbo-1m")], events, resolved)
        engine.dispose()
        db_note = (
            f"Registered raw + cleaned datasets in `dataset_versions`; wrote {n_ev} "
            f"aggregated `data_quality_events` (0 = already written for this dataset)."
        )

    # Reports --------------------------------------------------------------------------------
    REPORTS.mkdir(parents=True, exist_ok=True)
    monthly = (
        bar_cov.join(chain_cov, on="session_date")
        .join(rate.select("session_date", "n_total", "n_rejected"), on="session_date", how="left")
        .group_by(pl.col("session_date").dt.strftime("%Y-%m").alias("month"))
        .agg(
            sessions=pl.len(),
            bar_cov_min=pl.col("coverage").min(),
            chain_share_mean=pl.col("share").mean(),
            chain_share_min=pl.col("share").min(),
            atm_records=pl.col("n_total").sum(),
            atm_rejected=pl.col("n_rejected").sum(),
        )
        .sort("month")
    )
    crit_rows = [e for e in events if e.severity == "CRITICAL"]

    def closed_by(e: DQEvent) -> str:
        if e.session_date is None:
            return "**open**"
        return resolved.get((e.check_name, e.session_date), "**open**")

    extra = [
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {commit[:12]}, config "
        f"{cfg_h[:12]}. Window {sessions[0]} → {sessions[-1]} ({len(sessions)} sessions).",
        "",
        "## Coverage by month",
        "",
        "| month | sessions | min bar coverage | mean chain share | min chain share "
        "| ATM records | ATM rejected |",
        "|---|---|---|---|---|---|---|",
        *[
            f"| {m['month']} | {m['sessions']} | {m['bar_cov_min']:.4f} "
            f"| {m['chain_share_mean']:.4f} | {m['chain_share_min']:.4f} "
            f"| {m['atm_records'] or 0:,} | {m['atm_rejected'] or 0:,} |"
            for m in monthly.to_dicts()
        ],
        "",
        f"## CRITICAL events ({len(crit_rows)}; open: {crit})",
        "",
        "| check | session | reason | closed by |",
        "|---|---|---|---|",
        *[
            f"| {e.check_name} | {e.session_date} | {e.reason} | {closed_by(e)} |"
            for e in crit_rows
        ],
        "",
        "## Excluded sessions (history.excluded_sessions)",
        "",
        *[f"- {x.date}: {x.adr}: {x.reason}" for x in cfg.history.excluded_sessions],
        "",
        "## Catalogue",
        "",
        db_note,
    ]
    (REPORTS / "full_history.md").write_text(
        render_report(
            counts,
            bar_cov,
            chain_cov,
            gates,
            "M4 data-quality report: full history",
            extra=extra,
            min_bar_coverage=cfg.dq.min_bar_coverage,
        ),
        encoding="utf-8",
    )
    g_lines = [
        "# M4 gate evaluation (spec §11 gates 1-2)",
        "",
        "| gate | result | numbers | rule |",
        "|---|---|---|---|",
    ]
    for g in gates:
        nums = "; ".join(
            f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in g.numbers.items()
        )
        g_lines.append(
            f"| {g.gate} {g.name} | {'PASS' if g.passed else '**FAIL**'} | {nums} | {g.rule} |"
        )
    g_lines += [
        "",
        f"Overall ATM invalid-quote rate: {n_rej:,}/{n_total:,} = {overall_rate:.4%}.",
        f"Open CRITICAL events: {crit} (see reports/dq/full_history.md).",
    ]
    (REPORTS / "gates.md").write_text("\n".join(g_lines) + "\n", encoding="utf-8")
    liq = liquidity_study(table, cfg)
    l_lines = [
        "# §4.9 liquidity gates vs. empirical frozen-rule quotes",
        "",
        "Population: spec §5 call and put (D+1, ATM / first OTM) at every prediction "
        "timestamp where the quote is valid (two-sided, fresh, not rejected).",
        "",
        "| year | side | n | spread p50 | p90 | p99 | mid p50 | pass spread | pass min bid "
        "| pass size | pass all |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in liq.to_dicts():
        l_lines.append(
            f"| {row['year']} | {row['side']} | {row['n']:,} | {row['spread_p50']:.3f} "
            f"| {row['spread_p90']:.3f} | {row['spread_p99']:.3f} | {row['mid_p50']:.2f} "
            f"| {row['pass_spread']:.2%} | {row['pass_min_bid']:.2%} | {row['pass_size']:.2%} "
            f"| {row['pass_all']:.2%} |"
        )
    (REPORTS / "liquidity_spreads.md").write_text("\n".join(l_lines) + "\n", encoding="utf-8")
    for g in gates:
        print(f"gate {g.gate}: {'PASS' if g.passed else 'FAIL'} {g.numbers}")
    print("reports written to reports/dq/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
