"""M32 (ADR-0022 P4): the paper period's operational review -> reports/research/m32_paper.md.

Reads the journal and the latest evening download (no new download). Signal fidelity uses the
independent recomputation in `monitoring.paper_review`. Paper P&L is reported as context and is
never a criterion (hard rule 12).

    uv run python scripts/m32_review.py
    uv run python scripts/m32_review.py --synthetic FILE   # a synthetic journal, no database
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

from m32_evening import load_download, prices_from
from qqq1dte.backtesting.oos import code_commit
from qqq1dte.core.config import PaperPullback, StudyPullback, load_config
from qqq1dte.journal.paper_store import read_events, read_fills, read_signals
from qqq1dte.monitoring.paper_review import (
    DayPrice,
    FillRecord,
    Review,
    SignalRecord,
    independent_flags,
    review,
)
from qqq1dte.strategies.pullback_live import evening_instruction

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "research" / "m32_paper.md"


def render(
    r: Review, title_note: str, events: Sequence[dict[str, object]], paper: PaperPullback
) -> str:
    out = [
        "# M32: paper trading of the RSI(2) pullback rule on SPY (ADR-0022)" + title_note,
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m32_review.py`, code "
        f"{code_commit(ROOT)[:12]}. First session {paper.first_session}; ${paper.trade_usd:,.0f} "
        f"per trade on a notional ${paper.account_usd:,.0f} account.",
        "",
        f"## Status: **{r.overall}**",
        "",
        f"- Sessions: {r.sessions} (needs ≥ {paper.min_sessions}); completed round trips: "
        f"{r.round_trips} (needs ≥ {paper.min_round_trips})",
        f"- Loss limit: {'reached ' + str(r.loss_limit) if r.loss_limit else 'not reached'}",
        "",
        "## Operational criteria (ADR-0022 P4; all required)",
        "",
        "| # | criterion | status | detail |",
        "|---|---|---|---|",
        *(f"| {i} | {c.name} | {c.status} | {c.detail} |" for i, c in enumerate(r.criteria, 1)),
        "",
        "## Paper P&L (context only, never a criterion)",
        "",
        "Paper fills are IBKR's simulation, not real auction fills. At about 8 trades a year this "
        "says nothing about the edge (ADR-0022, 'What paper trading can and cannot show').",
        "",
        "| buy open | sell open | P&L $ | P&L % of cost |",
        "|---|---|---|---|",
        *(
            f"| {t['buy']} | {t['sell']} | {float(t['pnl_usd']):.2f} | {float(t['pnl_pct']):.3%} |"
            for t in r.trades
        ),
        "",
        f"## Events ({len(events)})",
        "",
        *(f"- {e['at']}: {e['kind']} {e['data_date'] or ''} {e['detail']}" for e in events[-30:]),
        "",
    ]
    return "\n".join(out)


def synthetic(
    rule: StudyPullback, paper: PaperPullback
) -> tuple[list[SignalRecord], list[FillRecord], dict[date, DayPrice], list[date]]:
    """A seeded random walk run through the live path, every order filled at the open + 1 bp."""
    rng = random.Random(20261115)
    days: list[date] = []
    d = date(2025, 1, 2)
    while len(days) < 520:  # noqa: PLR2004
        if d.weekday() < 5:  # noqa: PLR2004
            days.append(d)
        d += timedelta(days=1)
    px, close = 600.0, []
    for _ in days:
        px *= 1 + rng.gauss(0.0003, 0.012)
        close.append(px)
    prices = {x: DayPrice(c, c, c, 0.0) for x, c in zip(days, close, strict=True)}
    start = days.index(paper.first_session) if paper.first_session in days else 300
    sig, fills, pos = [], [], 0
    for k in range(start, len(days) - 1):
        ins = evening_instruction(
            days[: k + 1], close[: k + 1], close[: k + 1], pos, False, rule, paper.trade_usd
        )
        sig.append(
            SignalRecord(
                days[k],
                days[k + 1],
                ins.action,
                ins.shares,
                ins.entry_signal,
                ins.exit_signal,
                pos,
                False,
            )
        )
        if ins.action != "NO_ACTION":
            o = close[k + 1] * 1.0001
            t = datetime(days[k + 1].year, days[k + 1].month, days[k + 1].day, 14, 31, tzinfo=UTC)
            fills.append(FillRecord(days[k], "FILLED", o, ins.shares, 1.0, t, None))
            pos = ins.shares if ins.action == "BUY" else 0
    return sig, fills, prices, days


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", type=Path, default=None)
    a = ap.parse_args()
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    s, p = cfg.study_pullback, cfg.paper_pullback
    if a.synthetic is not None:
        if a.synthetic.resolve() == REPORT.resolve():
            print("--synthetic must not overwrite the real report")
            return 2
        sig, fills, prices, days = synthetic(s, p)
        p = p.model_copy(
            update={"first_session": sig[0].data_date, "paper_models_cash_settlement": True}
        )
        adj = [prices[d].adj_close for d in days]
        events: list[dict[str, object]] = []
        out, note = a.synthetic, " — SYNTHETIC JOURNAL, NOT PAPER RESULTS"
    else:
        engine = create_engine(os.environ["DATABASE_URL"])
        with engine.connect() as c:
            sig, fills, events = read_signals(c), read_fills(c), read_events(c)
        if not sig:
            print("the journal is empty")
            return 1
        last = max(x.data_date for x in sig)
        files = sorted((ROOT / p.raw_dir).glob(f"*/{s.ticker}.json"))
        if not files:
            print("no evening download found")
            return 1
        df, _ = load_download(files[-1], s.ticker)
        prices, days = prices_from(df), df["date"].to_list()
        adj = df["adj_close"].to_list()
        if last not in prices:
            print(f"the latest download does not cover {last}")
            return 1
        out, note = REPORT, ""
    e, x = independent_flags(adj, s.rsi_period, s.rsi_entry, s.sma_trend, s.sma_exit)
    recomputed = dict(zip(days, zip(e, x, strict=True), strict=True))
    r = review(sig, fills, prices, recomputed, p, s)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(r, note, events, p), encoding="utf-8")
    print(f"{r.overall}: {[c.status for c in r.criteria]} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
