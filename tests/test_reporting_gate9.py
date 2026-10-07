"""Gate 9: every P&L figure in reports is net of costs, enforced by type (M12 Q6).

Report helpers accept only `NetPnl`, which can only be built from gross P&L and costs. Parquet
round trips lose the type, so frames are converted with `net_from_frame`, which requires the
gross and cost columns and checks them against the stored net."""

from __future__ import annotations

import textwrap
import typing
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from mypy import api

from qqq1dte.backtesting.reporting import net_from_frame, summarize_net
from qqq1dte.core.config import load_config
from qqq1dte.execution_sim.accounting import NetPnl

CFG = load_config()
ROOT = Path(__file__).resolve().parents[1]


def _frame(net_override: float | None = None) -> pl.DataFrame:
    gross = [31.0, -50.0, 1.0, 20.0]
    net = [g - 1.4 for g in gross]
    if net_override is not None:
        net[0] = net_override
    return pl.DataFrame(
        {
            "session_date": [date(2025, 3, d) for d in (10, 10, 11, 12)],
            "gross_pnl": gross,
            "commissions": [1.3] * 4,
            "fees": [0.1] * 4,
            "net_pnl": net,
        }
    )


def test_net_from_frame_rebuilds_net_from_gross_and_costs() -> None:
    nets = net_from_frame(_frame())
    assert all(isinstance(n, NetPnl) for n in nets)
    assert [float(n) for n in nets] == pytest.approx([29.6, -51.4, -0.4, 18.6])


def test_net_from_frame_rejects_inconsistent_or_missing_costs() -> None:
    with pytest.raises(ValueError, match="net_pnl"):
        net_from_frame(_frame(net_override=31.0))  # gross reported as net
    with pytest.raises(ValueError, match="fees"):
        net_from_frame(_frame().drop("fees"))


def test_summary_accepts_only_net_pnl() -> None:
    df = _frame()
    s = summarize_net(net_from_frame(df), df["session_date"].to_list(), CFG)
    assert s.n == 4 and s.mean == pytest.approx((29.6 - 51.4 - 0.4 + 18.6) / 4)
    assert s.ci[0] <= s.mean <= s.ci[1] and s.median == pytest.approx((18.6 - 0.4) / 2)
    with pytest.raises(TypeError, match="NetPnl"):
        summarize_net([29.6, -51.4], [date(2025, 3, 10)] * 2, CFG)  # type: ignore[list-item]


def test_summary_signature_requires_net_pnl() -> None:
    hints = typing.get_type_hints(summarize_net)
    assert hints["pnl"] == Sequence[NetPnl]


def test_mypy_rejects_a_float_pnl_in_reports(tmp_path: Path) -> None:
    snippet = tmp_path / "bad_report.py"
    snippet.write_text(
        textwrap.dedent("""
        from datetime import date
        from qqq1dte.backtesting.reporting import summarize_net
        from qqq1dte.core.config import load_config
        summarize_net([29.6], [date(2025, 3, 10)], load_config())
    """),
        encoding="utf-8",
    )
    out, _, status = api.run(
        [str(snippet), "--config-file", str(ROOT / "pyproject.toml"), "--no-incremental"]
    )
    assert status != 0 and "NetPnl" in out
