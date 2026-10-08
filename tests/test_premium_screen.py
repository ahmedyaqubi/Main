"""M19T Step 1 (ADR-0013 D3-D4): screen statistics and decision rules, exact synthetic cases."""

from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl
import pytest

from qqq1dte.backtesting.premium_screen import (
    ADVANCE,
    AMBIGUOUS,
    KILL,
    CellResult,
    breakeven_loss_freq,
    cell_outcome,
    draw_weights,
    era_driven,
    family_outcome,
    guards,
    max_consecutive_losses,
    session_means,
    weighted_means,
)
from qqq1dte.core.config import load_config

CFG = load_config()
D1, D2, D3 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)


def test_session_means_use_resolved_trades_only() -> None:
    df = pl.DataFrame(
        {
            "session_date": [D1, D1, D1, D2, D3],
            "status": ["OK", "OK", "UNRESOLVED_DATA", "NO_TRADE", "OK"],
            "net_conservative": [10.0, -20.0, None, None, 4.0],
            "net_moderate": [12.0, -18.0, None, None, 5.0],
            "net_mid": [14.0, -16.0, None, None, 6.0],
            "max_risk": [80.0, 90.0, None, None, 70.0],
        }
    )
    s = session_means(df)
    assert s["session_date"].to_list() == [D1, D3]  # D2 has no resolved trade: dropped
    assert s["conservative"].to_list() == [-5.0, 4.0]
    assert s["mid"].to_list() == [-1.0, 6.0]
    assert s["n_trades"].to_list() == [2, 1]
    assert s["max_risk"].to_list() == [85.0, 70.0]


def test_weighted_means_and_shared_draws() -> None:
    w = draw_weights(4, reps=3, seed=1)
    assert w.shape == (3, 4) and (w.sum(axis=1) == 4).all()
    assert np.array_equal(w, draw_weights(4, reps=3, seed=1))  # reproducible
    vals = np.array([1.0, 2.0, 3.0, 6.0])
    idx = np.array([0, 3])  # a cell observing sessions 0 and 3 only
    m = weighted_means(vals[idx], np.array([[1, 0, 0, 3], [0, 4, 0, 0]])[:, idx])
    assert m[0] == pytest.approx((1 * 1 + 3 * 6) / 4)
    assert np.isnan(m[1])  # the cell's sessions were not drawn


def test_guards() -> None:
    assert guards(300, 300, 150, CFG) == []
    assert guards(299, 300, 150, CFG) == ["FEW_TRADES"]
    assert guards(300, 299, 149, CFG) == ["FEW_SESSIONS", "FEW_RECENT_SESSIONS"]


def test_cell_outcome() -> None:
    assert cell_outcome(0.5, 3.0, []) == ADVANCE
    assert cell_outcome(0.5, 3.0, ["FEW_TRADES"]) == AMBIGUOUS
    assert cell_outcome(-4.0, -0.1, []) == KILL
    assert cell_outcome(-4.0, -0.1, ["FEW_TRADES"]) == KILL  # guards only bar advancing
    assert cell_outcome(-1.0, 2.0, []) == AMBIGUOUS
    assert cell_outcome(0.0, 2.0, []) == AMBIGUOUS  # the lower bound must exceed 0


def res(cell: str, outcome: str, lb: float, recent: int) -> CellResult:
    return CellResult(cell, outcome, lb, 0.0, 400, 400, recent, [], False)


def test_family_outcome() -> None:
    kills = [res(f"S{i}", KILL, -1.0, 200) for i in range(1, 7)]
    assert family_outcome(kills, CFG) == (KILL, [])
    mixed = [*kills[:5], res("S6", AMBIGUOUS, -0.5, 200)]
    assert family_outcome(mixed, CFG) == (AMBIGUOUS, [])
    adv = [
        res("S1", ADVANCE, 1.0, 200),
        res("S2", ADVANCE, 2.0, 200),
        res("S3", ADVANCE, 2.0, 300),
        res("S4", KILL, -1.0, 200),
    ]
    # at most 2, largest lower bound first; the tie at 2.0 goes to more recent sessions
    assert family_outcome(adv, CFG) == (ADVANCE, ["S3", "S2"])


def test_breakeven_loss_frequency() -> None:
    # mean win 15, mean loss 30: break-even loss share = 15 / (15 + 30)
    assert breakeven_loss_freq(np.array([10.0, 20.0, -30.0])) == pytest.approx(1 / 3)
    assert np.isnan(breakeven_loss_freq(np.array([10.0, 20.0])))


def test_max_consecutive_losses() -> None:
    assert max_consecutive_losses(np.array([1.0, -1.0, -2.0, 3.0, -1.0, -1.0, -1.0])) == 3
    assert max_consecutive_losses(np.array([1.0, 0.0])) == 0


def test_era_driven_flag() -> None:
    # pooled mean (+40 - 5 x 2) / 6 = +5 > 0; without era A it is -2: driven by one era
    era = np.array(["A", "B", "B", "B", "B", "B"])
    net = np.array([40.0, -2.0, -2.0, -2.0, -2.0, -2.0])
    assert era_driven(net, era)
    assert not era_driven(np.array([3.0, 1.0, 1.0, 2.0, 1.0, 1.0]), era)
