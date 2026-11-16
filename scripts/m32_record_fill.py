"""M32 (ADR-0022 P3, amendment A1 R5): record the outcome of one paper order, typed by the owner.

The evening date names the instruction; the time is the fill time in New York on the session the
order was for. A refused entry is logged with its reasons and nothing is stored (rule 8). Only
price, quantity, commission and time are kept, or a reason for a missed or rejected order: never
an account number.

    uv run python scripts/m32_record_fill.py --date 2026-11-16 --filled --price 712.31 \
        --quantity 3 --commission 1.00 --time 09:30:02
    uv run python scripts/m32_record_fill.py --date 2026-11-16 --missed --reason "away"
    uv run python scripts/m32_record_fill.py --date 2026-11-16 --rejected --reason "..."
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, time
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from qqq1dte.core.config import load_config
from qqq1dte.journal.paper_store import read_fills, read_signals, write_event, write_fill
from qqq1dte.monitoring.paper_review import FillRecord, fill_problems
from qqq1dte.strategies.pullback_live import NY

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=date.fromisoformat, required=True, help="the evening's date")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--filled", action="store_true")
    g.add_argument("--missed", action="store_true")
    g.add_argument("--rejected", action="store_true")
    ap.add_argument("--price", type=float)
    ap.add_argument("--quantity", type=int)
    ap.add_argument("--commission", type=float)
    ap.add_argument("--time", type=time.fromisoformat, help="fill time, New York")
    ap.add_argument("--reason")
    a = ap.parse_args()
    load_dotenv(ROOT / ".env")
    p = load_config().paper_pullback
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as c:
        sig = {s.data_date: s for s in read_signals(c)}
        done = {f.data_date for f in read_fills(c)}
        row = c.execute(
            text("SELECT close FROM paper_signals WHERE data_date = :d"), {"d": a.date}
        ).first()
    s = sig.get(a.date)
    status = "FILLED" if a.filled else "MISSED" if a.missed else "REJECTED"
    filled_at = None
    if a.filled and s is not None and a.time is not None:
        filled_at = datetime.combine(s.next_session, a.time, tzinfo=NY)
    f = FillRecord(a.date, status, a.price, a.quantity, a.commission, filled_at, a.reason)
    if s is None or row is None:
        problems = [f"no instruction on {a.date}"]
    else:
        problems = fill_problems(s, f, prev_close=float(row[0]), sanity=p.fill_sanity)
        if a.filled and a.time is None:
            problems.append("a fill needs --time")
    if a.date in done:
        problems.append(f"{a.date} already has a recorded outcome (the journal is append-only)")
    with engine.begin() as c:
        if problems:
            write_event(c, "FILL_REFUSED", a.date, {"problems": problems})
            print("REFUSED: " + "; ".join(problems))
            return 1
        assert s is not None
        write_fill(c, f)
        if status == "FILLED" and f.quantity != s.shares:
            write_event(c, "QTY_DIFFERS", a.date, {"instructed": s.shares, "filled": f.quantity})
            print(f"NOTE: filled {f.quantity}, instructed {s.shares}; logged")
    print(f"recorded {status} for {a.date} ({s.action} {s.shares}, {s.next_session} open)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
