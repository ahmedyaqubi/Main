"""M32 (ADR-0022 P6): replay the live evening path day by day over the stored SPY history and
compare it with the backtest state machine (`strategies.pullback.trade_indices`).

Every order is assumed filled at the next open. Only dates and counts are compared; no return
or other statistic is computed (amendment A1 R2: reading the 2016-2026 rows to compute the frozen
rule's signals is not a holdout access).

    uv run python scripts/m32_replay_check.py --data-file data/raw/tom/tiingo/SPY.json
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from m32_evening import load_download
from qqq1dte.backtesting.oos import code_commit
from qqq1dte.core.config import load_config
from qqq1dte.ingestion.etf_data import paper_rows
from qqq1dte.strategies.pullback import signals, trade_indices
from qqq1dte.strategies.pullback_live import evening_instruction

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "research" / "m32_replay_check.md"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-file", type=Path, required=True)
    a = ap.parse_args()
    cfg = load_config()
    s, p = cfg.study_pullback, cfg.paper_pullback
    df, sha = load_download(a.data_file, s.ticker)
    df = paper_rows(df, p.adr)
    dates, close, adj = df["date"].to_list(), df["close"].to_list(), df["adj_close"].to_list()
    n = len(dates)
    entry, exit_ = signals(adj, s.rsi_period, s.rsi_entry, s.sma_trend, s.sma_exit)
    expected = trade_indices(entry, exit_)
    pos, buys, sells = 0, [], []
    for k in range(n):
        ins = evening_instruction(
            dates[: k + 1], close[: k + 1], adj[: k + 1], pos, False, s, p.trade_usd
        )
        if ins.action == "BUY":
            buys.append(k)
            pos = ins.shares
        elif ins.action == "SELL":
            sells.append(k)
            pos = 0
        if k % 1000 == 0:
            print(f"{k}/{n}", flush=True)
    got = [(b, x) for b, x in zip(buys, sells, strict=False) if x + 1 < n]
    bad = [i for i, (g, e) in enumerate(zip(got, expected, strict=False)) if g != e]
    ok = got == expected
    lines = [
        "# M32: live evening path replayed against the backtest state machine (ADR-0022 P6)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `scripts/m32_replay_check.py`, code "
        f"{code_commit(ROOT)[:12]}. Data: `{a.data_file.name}` (sha256 {sha[:16]}), {n:,} sessions "
        f"{dates[0]} → {dates[-1]}, read under {p.adr} amendment A1 R2. Dates and counts only.",
        "",
        f"## Result: **{'MATCH' if ok else 'MISMATCH'}**",
        "",
        f"- Completed trades, backtest `trade_indices`: {len(expected)}",
        f"- Completed trades, live path replayed day by day: {len(got)}",
        f"- Mismatched trades: {len(bad) + abs(len(got) - len(expected))}"
        + (
            f", first at index {bad[0]}: live {got[bad[0]]} vs backtest {expected[bad[0]]}"
            if bad
            else ""
        ),
        f"- First trade: buy signal {dates[expected[0][0]]}, sell signal {dates[expected[0][1]]}; "
        f"last: buy signal {dates[expected[-1][0]]}, sell signal {dates[expected[-1][1]]}",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(("MATCH" if ok else "MISMATCH") + f": {len(got)} vs {len(expected)} -> {REPORT}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
