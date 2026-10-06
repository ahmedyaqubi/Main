"""§4.9 liquidity-gate study over frozen-rule quotes (M4 criterion 5)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl
import pytest

from qqq1dte.core.config import load_config
from qqq1dte.validation.liquidity import liquidity_study

CFG = load_config()


def table(rows: list[tuple[date, float, float, int, bool]]) -> pl.DataFrame:
    """rows: (session, call_bid, call_ask, call_ask_sz, call_ok); puts mirror calls."""
    n = len(rows)
    t = datetime(2025, 3, 10, 14, 0, tzinfo=UTC)
    data = {"session_date": [r[0] for r in rows], "T": [t] * n}
    for side in ("call", "put"):
        data |= {
            f"{side}_bid": [r[1] for r in rows],
            f"{side}_ask": [r[2] for r in rows],
            f"{side}_bid_sz": [10] * n,
            f"{side}_ask_sz": [r[3] for r in rows],
            f"{side}_ok": [r[4] for r in rows],
        }
    return pl.DataFrame(data)


def test_gate_pass_rates_by_year_and_side() -> None:
    d24, d25 = date(2024, 6, 3), date(2025, 6, 2)
    t = table(
        [
            (d24, 1.00, 1.02, 5, True),  # spread .02: passes all
            (d24, 1.00, 1.10, 5, True),  # spread .10 > max(.05, 5% of 1.05=.0525): fails spread
            (d24, 0.10, 0.12, 5, True),  # bid .10 < .20: fails min bid
            (d24, 2.00, 2.04, 0, True),  # ask size 0: fails size
            (d24, 9.99, 9.99, 9, False),  # not a valid quote: excluded
            (d25, 4.00, 4.15, 5, True),  # spread .15 <= 5% of 4.075=.20375: passes
        ]
    )
    out = liquidity_study(t, CFG)
    r24 = out.filter((pl.col("year") == "2024") & (pl.col("side") == "call")).row(0, named=True)
    assert r24["n"] == 4
    assert r24["pass_spread"] == pytest.approx(3 / 4)
    assert r24["pass_min_bid"] == pytest.approx(3 / 4)
    assert r24["pass_size"] == pytest.approx(3 / 4)
    assert r24["pass_all"] == pytest.approx(1 / 4)
    assert r24["spread_p50"] == pytest.approx(0.03, abs=1e-9)  # median of .02 .02 .04 .10
    r25 = out.filter((pl.col("year") == "2025") & (pl.col("side") == "put")).row(0, named=True)
    assert (r25["n"], r25["pass_all"]) == (1, 1.0)
    allrow = out.filter((pl.col("year") == "all") & (pl.col("side") == "both")).row(0, named=True)
    assert allrow["n"] == 10
    assert allrow["pass_all"] == pytest.approx(4 / 10)
