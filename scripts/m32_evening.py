"""M32 (ADR-0022 P3): the evening instruction for paper trading the frozen RSI(2) rule on SPY.

Run each evening after the US close. It downloads SPY daily prices from Tiingo (token from .env,
sent in a header only), checks them, computes the frozen signals and prints ONE line:
"BUY n SPY market-on-open", "SELL n SPY market-on-open" or "NO ACTION". The owner places any
order by hand in the IBKR paper account. This script opens no broker connection of any kind
(hard rule 1); it writes the journal only.

It refuses (and logs why) when: the P1 rows are not confirmed (`first_session` unset); the code
is not committed; it is before the cut-off or past the open the instruction is for; the data
are stale or fail a check; or an earlier order's outcome is not recorded yet.

    uv run python scripts/m32_evening.py
    uv run python scripts/m32_evening.py --dry-run --data-file FILE --now 2026-09-30T23:00:00Z
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import exchange_calendars as xcals
import polars as pl
import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine

from m25_fetch import TIMEOUT, save
from m26_screen import dirty
from qqq1dte.backtesting.oos import code_commit
from qqq1dte.core.config import Phase1Config, config_hash, load_config
from qqq1dte.ingestion.etf_data import TIINGO_URL, paper_rows, parse_tiingo
from qqq1dte.journal.paper_store import (
    position_after,
    read_events,
    read_fills,
    read_signals,
    unrecorded_orders,
    write_event,
    write_signal,
)
from qqq1dte.monitoring.paper_review import DayPrice, daily_ledger, loss_limit_breach
from qqq1dte.strategies.pullback import signals
from qqq1dte.strategies.pullback_live import (
    EveningRefusalError,
    evening_instruction,
    instruction_text,
    paper_data_date,
    revisions,
)
from qqq1dte.validation.etf_checks import paper_problems

ROOT = Path(__file__).resolve().parents[1]


def xnys(start: date, end: date) -> tuple[list[date], dict[date, datetime]]:
    """XNYS sessions and their opens (UTC)."""
    cal = xcals.get_calendar("XNYS", start=str(start), end=str(end))
    sessions = [ts.date() for ts in cal.sessions]
    opens = {ts.date(): cal.session_open(ts).to_pydatetime() for ts in cal.sessions}
    return sessions, opens


def load_download(path: Path, ticker: str) -> tuple[pl.DataFrame, str]:
    raw = path.read_bytes()
    return parse_tiingo(json.loads(raw), ticker), hashlib.sha256(raw).hexdigest()


def prices_from(df: pl.DataFrame) -> dict[date, DayPrice]:
    return {
        d: DayPrice(o, c, a, v)
        for d, o, c, a, v in df.select("date", "open", "close", "adj_close", "div_cash").iter_rows()
    }


def previous_download(raw_dir: Path, before: date, ticker: str) -> Path | None:
    dirs = sorted(p for p in raw_dir.glob("*") if p.is_dir() and p.name < before.isoformat())
    return next(
        (d / f"{ticker}.json" for d in reversed(dirs) if (d / f"{ticker}.json").exists()), None
    )


def fetch(cfg: Phase1Config, data_date: date) -> tuple[Path, datetime]:
    s, p = cfg.study_pullback, cfg.paper_pullback
    token = os.environ.get("TIINGO_API_KEY")
    if not token:
        raise EveningRefusalError("TIINGO_API_KEY is not set in .env")
    url = TIINGO_URL.format(ticker=s.ticker.lower(), start=s.data_start, end=data_date)
    r = requests.get(url, headers={"Authorization": f"Token {token}"}, timeout=TIMEOUT)
    if r.status_code != 200:  # noqa: PLR2004
        raise EveningRefusalError(f"Tiingo {s.ticker}: HTTP {r.status_code}")
    available_at = datetime.now(UTC)
    path = ROOT / p.raw_dir / data_date.isoformat() / f"{s.ticker}.json"
    save(path, r.content, url)
    return path, available_at


def main() -> int:  # noqa: PLR0911, PLR0912, PLR0915 (one linear evening)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="no download, no journal")
    ap.add_argument("--data-file", type=Path, default=None)
    ap.add_argument("--now", type=datetime.fromisoformat, default=None)
    args = ap.parse_args()
    if args.dry_run != (args.data_file is not None) or (args.now is not None and not args.dry_run):
        print("--data-file and --now go with --dry-run only")
        return 2
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    s, p = cfg.study_pullback, cfg.paper_pullback
    now = args.now or datetime.now(UTC)
    engine = None if args.dry_run else create_engine(os.environ["DATABASE_URL"])

    def refuse(kind: str, why: str, d: date | None = None) -> int:
        print(f"REFUSED: {why}")
        if engine is not None:
            with engine.begin() as c:
                write_event(c, kind, d, {"reason": why, "at": now.isoformat()})
        return 1

    if not args.dry_run:
        if p.first_session is None:
            return refuse(
                "REFUSED",
                "paper_pullback.first_session is not set: ADR-0022 P1 rows "
                "are not all confirmed (amendment A1 R6)",
            )
        if dirty():
            return refuse("REFUSED", "src, scripts or configs have uncommitted changes")
    today = now.astimezone(UTC).date()
    sessions, opens = xnys(s.data_start, today + timedelta(days=30))
    try:
        data_date, nxt = paper_data_date(now, sessions, p.evening_not_before_et, opens)
    except EveningRefusalError as e:
        return refuse("MISSED_EVENING" if "missed" in str(e) else "REFUSED", str(e))
    if p.first_session is not None and not args.dry_run and data_date < p.first_session:
        return refuse("REFUSED", f"{data_date} is before the first session {p.first_session}")

    try:
        if args.dry_run:
            path, available_at = args.data_file, now
        else:
            path, available_at = fetch(cfg, data_date)
        df, sha = load_download(path, s.ticker)
    except EveningRefusalError as e:
        return refuse("REFUSED", str(e), data_date)
    df = paper_rows(df, p.adr).filter(pl.col("date") <= data_date)
    if engine is not None:
        with engine.begin() as c:
            write_event(
                c,
                "DATA_READ",
                data_date,
                {
                    "file": str(path.relative_to(ROOT)),
                    "sha256": sha,
                    "rows": df.height,
                    "first": df["date"][0],
                    "last": df["date"][-1],
                    "adr": p.adr,
                },
            )
    if df.is_empty() or df["date"][-1] != data_date:
        last = None if df.is_empty() else df["date"][-1]
        return refuse("REFUSED", f"the download ends {last}, not {data_date}: stale", data_date)
    want = [d for d in sessions if s.data_start <= d <= data_date]
    problems = paper_problems(df, want, p.adj_tol, p.jump, s.open_ratio_tol, s.open_gap)
    if problems:
        return refuse("REFUSED", "data checks failed: " + "; ".join(problems), data_date)

    dates: list[date] = df["date"].to_list()
    close, adj = df["close"].to_list(), df["adj_close"].to_list()
    if engine is None:
        position, halted, journal = 0, False, []
    else:
        with engine.connect() as c:
            journal, fills = read_signals(c), read_fills(c)
            stopped = read_events(c, "LOSS_LIMIT")
        if any(j.data_date == data_date for j in journal):
            print(f"{data_date} already has an instruction; see the journal")
            return 0
        pending = unrecorded_orders(journal, fills)
        if pending:
            return refuse(
                "REFUSED",
                f"record the outcome of the order(s) from {pending} first "
                "(scripts/m32_record_fill.py)",
                data_date,
            )
        position = position_after(journal, fills)
        assert p.first_session is not None
        days = [d for d in dates if d >= p.first_session]
        breach = loss_limit_breach(
            daily_ledger(journal, fills, prices_from(df), p.account_usd, days),
            p.account_usd,
            p.loss_day_limit,
            p.loss_total_limit,
        )
        halted = bool(stopped) or breach is not None
        prev = previous_download(ROOT / p.raw_dir, data_date, s.ticker)
        with engine.begin() as c:
            if breach is not None and not stopped:
                write_event(c, "LOSS_LIMIT", breach[0], {"limit": breach[1]})
                print(f"LOSS LIMIT ({breach[1]}) reached on {breach[0]}: no new BUY until review")
            if prev is not None:
                old, _ = load_download(prev, s.ticker)
                for d, col, a, b in revisions(old, df):
                    write_event(c, "REVISION", d, {"field": col, "old": a, "new": b})
            entry, exit_ = signals(adj, s.rsi_period, s.rsi_entry, s.sma_trend, s.sma_exit)
            flags = dict(zip(dates, zip(entry, exit_, strict=True), strict=True))
            for j in journal:
                if flags.get(j.data_date) != (j.entry_signal, j.exit_signal):
                    write_event(
                        c,
                        "REVISION_FLIPS_SIGNAL",
                        j.data_date,
                        {"journal": [j.entry_signal, j.exit_signal], "now": flags.get(j.data_date)},
                    )
                    print(f"WARNING: revised data change the {j.data_date} signal; tell the owner")

    ins = evening_instruction(dates, close, adj, position, halted, s, p.trade_usd)
    text = instruction_text(ins, s.ticker)
    run_at = max(datetime.now(UTC), available_at) if engine is not None else now
    if engine is not None:
        with engine.begin() as c:
            write_signal(
                c,
                ins,
                next_session=nxt,
                ticker=s.ticker,
                instruction=text,
                run_at=run_at,
                available_at=available_at,
                code_commit=code_commit(ROOT),
                data_sha256=sha,
                config_hash=config_hash(cfg.model_dump(mode="json")),
            )
    print(
        f"data {data_date} | close {ins.close:.2f} | RSI({s.rsi_period}) {ins.rsi:.2f} | "
        f"SMA{s.sma_trend} {ins.sma_trend:.2f} | SMA{s.sma_exit} {ins.sma_exit:.2f} | "
        f"held {position}" + (" | STOPPED" if halted else "")
    )
    print(f"\n  {text}   (for the {nxt} open)\n")
    if args.dry_run:
        print("DRY RUN: nothing downloaded, nothing journalled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
