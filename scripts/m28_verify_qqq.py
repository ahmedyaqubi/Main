"""M28 step 4 (ADR-0021 D5, D8; rule 9): are the QQQ quotes the cost map needs present on every
development session, and has the QQQ holdout ever been accessed?

Development sessions only: history.option_era_start -> study_options_day.dev_end.QQQ. No holdout
file is opened (option and definition files are chosen by their date before reading), and the
single underlying file is filtered on session_date before any row is loaded.
No signal or return is computed: calls and puts are checked alike at each setup's entry time.

Per session (thresholds are the spec's gate-1 values in `dq`, fixed before this ran):
  U  underlying 1-minute quotes present on >= dq.min_bar_coverage of RTH minutes
  E  the expiration on the next session is listed (D2; QQQ lists daily)
  Q  at each entry time (S1 09:35, S2 15:30), the frozen ATM call and put (spec §5) have a
     present quote, and keep one on >= dq.min_chain_timestamp_share of minutes to the exit
Overall "complete": the share of sessions passing >= dq.min_chain_session_share. Any failing
session is listed as a gap (owner: stop and ask).

    uv run python scripts/m28_verify_qqq.py
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import ET, ensure_utc
from qqq1dte.execution_sim.selection import Contract, Quote, choose_contract, liquidity_failures
from qqq1dte.features.inputs import chain_table
from qqq1dte.labels.option import option_records
from qqq1dte.validation.options_day_data import (
    bar_coverage,
    data_present,
    dev_partitions,
    held_coverage,
    quote_at,
)
from qqq1dte.validation.records import build_definitions

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean" / "cleaned"
REJECTED = ROOT / "data" / "clean" / "rejected"
DEFS = ROOT / "data" / "raw" / "parquet" / "OPRA.PILLAR" / "definition"
OUT = ROOT / "data" / "research" / "m28" / "qqq_step4_sessions.parquet"
REPORT = ROOT / "reports" / "research" / "m28_step4_qqq_data.md"


def quotes(df: pl.DataFrame) -> list[Quote]:
    return [
        Quote(
            r["bid"],
            r["ask"],
            r.get("bid_sz"),
            r.get("ask_sz"),
            r["available_at"],
            bool(r.get("rejected", False)),
        )
        for r in df.sort("available_at").iter_rows(named=True)
    ]


def holdout_log() -> list[dict[str, object]]:
    load_dotenv(ROOT / ".env")
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as c:
        return [
            dict(r)
            for r in c.execute(
                text(
                    "SELECT access_id, run_id, justification, adr_ref, accessed_at "
                    "FROM final_test_access_log ORDER BY access_id"
                )
            ).mappings()
        ]


def main() -> int:  # noqa: PLR0912, PLR0915 (linear check)
    cfg = load_config()
    s = cfg.study_options_day
    cal = TradingCalendar(cfg)
    dev_end = s.dev_end["QQQ"]
    sessions = cal.research_sessions(cfg.history.option_era_start, dev_end)

    und = (
        pl.scan_parquet(CLEAN / "cleaned_market_data" / "bbo-1m" / "QQQ.parquet")
        .filter(pl.col("session_date") <= dev_end)
        .select("session_date", "ts", "available_at", "bid", "ask", "bid_sz", "ask_sz", "is_rth")
        .collect()
    )
    assert und["session_date"].max() <= dev_end  # type: ignore[operator]
    def_dirs = dev_partitions([p.name for p in DEFS.iterdir()], dev_end)
    raw_defs = pl.concat(
        [pl.read_parquet(f) for d in def_dirs for f in (DEFS / d).glob("*.parquet")],
        how="diagonal_relaxed",
    )
    chain = chain_table(build_definitions(raw_defs, cal), cfg)
    opt_files = set(
        dev_partitions(
            [p.name for p in (CLEAN / "cleaned_options_data" / "cbbo-1m").glob("*.parquet")],
            dev_end,
        )
    )

    rows: list[dict[str, object]] = []
    for d in sessions:
        open_, close = cal.open_close(d)
        forced = cal.forced_exit_time(d)
        reasons: list[str] = []
        u = und.filter(pl.col("session_date") == d)
        ok_u = u.filter(pl.col("is_rth") & (pl.col("bid") > 0) & (pl.col("ask") >= pl.col("bid")))
        cov_u = bar_coverage(ok_u["ts"].to_list(), open_, close)
        if cov_u < cfg.dq.min_bar_coverage:
            reasons.append(f"UNDERLYING_COVERAGE {cov_u:.3f}")
        nxt = cal.next_session(d)
        ch = chain.filter((pl.col("session_date") == d) & (pl.col("expiration") == nxt))
        row: dict[str, object] = {
            "session_date": d,
            "underlying_coverage": cov_u,
            "expiry": nxt,
            "listed_contracts": ch.height,
        }
        fname = f"{d}.parquet"
        if ch.height == 0:
            reasons.append("NO_1DTE_EXPIRY")
        if fname not in opt_files:
            reasons.append("NO_OPTION_FILE")
        if not reasons or reasons == [f"UNDERLYING_COVERAGE {cov_u:.3f}"]:
            recs = option_records(
                pl.read_parquet(CLEAN / "cleaned_options_data" / "cbbo-1m" / fname),
                pl.read_parquet(REJECTED / "cleaned_options_data" / "cbbo-1m" / fname),
            ).filter(pl.col("symbol").is_in(ch["raw_symbol"].to_list()))
            by_sym = {k[0]: quotes(g) for k, g in recs.group_by("symbol")}
            contracts = [
                Contract(
                    r["raw_symbol"], r["strike"], r["right"], r["expiration"], r["available_at"]
                )
                for r in ch.iter_rows(named=True)
            ]
            uq = quotes(u.with_columns(rejected=pl.lit(False)))
            for setup, entry_t, exit_t in (
                ("S1", s.orb.entry_time, s.orb.exit_time),
                ("S2", s.half_hour.entry_time, s.half_hour.exit_time),
            ):
                t_e = ensure_utc(datetime.combine(d, entry_t, tzinfo=ET))
                t_x = min(ensure_utc(datetime.combine(d, exit_t, tzinfo=ET)), forced)
                if t_e >= t_x:
                    row[f"{setup}_status"] = "NO_ENTRY_EARLY_CLOSE"
                    continue
                sq = quote_at(uq, t_e)
                if not data_present(sq, t_e, cfg) or sq is None:
                    reasons.append(f"{setup}_NO_SPOT")
                    continue
                spot = (float(sq.bid) + float(sq.ask)) / 2  # type: ignore[arg-type]
                for side in ("C", "P"):
                    c = choose_contract(contracts, spot, side, t_e)
                    if c is None:
                        reasons.append(f"{setup}_{side}_NO_CONTRACT")
                        continue
                    recs_c = by_sym.get(c.symbol, [])
                    q = quote_at(recs_c, t_e)
                    if not data_present(q, t_e, cfg):
                        reasons.append(f"{setup}_{side}_NO_ENTRY_QUOTE")
                    hc = held_coverage(recs_c, t_e, t_x, cfg)
                    row[f"{setup}_{side}_held_coverage"] = hc
                    row[f"{setup}_{side}_liquid_at_entry"] = not liquidity_failures(q, t_e, cfg)
                    if hc < cfg.dq.min_chain_timestamp_share:
                        reasons.append(f"{setup}_{side}_HELD_COVERAGE {hc:.3f}")
                row[f"{setup}_status"] = "CHECKED"
        row["reasons"] = "; ".join(reasons)
        row["passes"] = not reasons
        rows.append(row)

    df = pl.DataFrame(rows, infer_schema_length=None)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(OUT)
    n = df.height
    n_pass = int(df["passes"].sum())
    share = n_pass / n
    complete = share >= cfg.dq.min_chain_session_share
    resolved = {str(r.session) for r in cfg.dq.resolved_critical}
    gaps = df.filter(~pl.col("passes"))
    log = holdout_log()
    qqq_access = [r for r in log if "QQQ" in str(r).upper() or "1DTE" in str(r).upper()]
    reason_counts = Counter(
        x.split(" ")[0] for r in gaps["reasons"].to_list() for x in str(r).split("; ") if x
    )
    early = df.filter(pl.col("S2_status") == "NO_ENTRY_EARLY_CLOSE").height

    def mean(col: str) -> str:
        return f"{df[col].mean():.4f}" if col in df.columns else "n/a"

    def liq(col: str) -> str:
        return f"{df[col].drop_nulls().mean():.1%}" if col in df.columns else "n/a"

    lines = [
        "# M28 step 4: QQQ data check (ADR-0021 D5, D8; rule 9)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m28_verify_qqq.py`. "
        f"Development sessions {sessions[0]} → {sessions[-1]} only; no holdout file was opened. "
        "No signal or return was computed: calls and puts were checked alike.",
        "",
        "## Holdout access log",
        "",
        f"`final_test_access_log` has **{len(log)}** entries:",
        "",
        "| id | run | ADR | accessed at | justification |",
        "|---|---|---|---|---|",
        *[
            f"| {r['access_id']} | `{r['run_id']}` | {r['adr_ref']} | {r['accessed_at']} | "
            f"{r['justification']} |"
            for r in log
        ],
        "",
        f"QQQ accesses: **{len(qqq_access)}**.",
        "",
        "## Coverage",
        "",
        f"- Sessions checked: **{n}**; passing every check: **{n_pass}** ({share:.2%}). "
        f"Line: {cfg.dq.min_chain_session_share:.0%} → "
        f"**{'COMPLETE' if complete else 'NOT COMPLETE'}**.",
        f"- Mean underlying coverage: {mean('underlying_coverage')}.",
        f"- Mean held-contract coverage, entry → exit: S1 call {mean('S1_C_held_coverage')}, "
        f"S1 put {mean('S1_P_held_coverage')}, S2 call {mean('S2_C_held_coverage')}, "
        f"S2 put {mean('S2_P_held_coverage')}.",
        f"- S2 has no entry on {early} early-close sessions (15:30 is after the forced exit).",
        "- Descriptive, not a data check: share of sessions where the ATM contract passes the "
        f"§4.9 liquidity gates at entry: S1 call {liq('S1_C_liquid_at_entry')}, put "
        f"{liq('S1_P_liquid_at_entry')}; S2 call {liq('S2_C_liquid_at_entry')}, put "
        f"{liq('S2_P_liquid_at_entry')}.",
        "",
        "## Gaps",
        "",
        *([f"- {k}: {v} sessions" for k, v in sorted(reason_counts.items())] or ["None."]),
        "",
        "| session | ADR-resolved (dq.resolved_critical) | reasons |",
        "|---|---|---|",
        *[
            f"| {r['session_date']} | {'yes' if str(r['session_date']) in resolved else 'no'} | "
            f"{r['reasons']} |"
            for r in gaps.iter_rows(named=True)
        ],
        "",
        f"Per-session table: `{OUT.relative_to(ROOT).as_posix()}` (not committed; `data/`).",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"sessions {n}, passing {n_pass} ({share:.2%}), complete={complete}, "
        f"holdout log {len(log)} entries, QQQ {len(qqq_access)}"
    )
    for k, v in sorted(reason_counts.items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
