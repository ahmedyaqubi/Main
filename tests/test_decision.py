"""Decision engine (spec §4.1; M15): breakeven / EV (binary-conservative, owner Q1), per-side
checks with reason codes, side choice by EV, regime blocking hook (gate 13 mechanism, Q4), the
calibration guard (T-CAL-04) and the selection-at-T_e helper.

Costs $1.40 round trip; target +30%, stop -20%; edge margin 0.03. Entry 1.50 per share:
win W = 45, loss L = 30, p_breakeven = (30 + 1.4) / 75 = 0.418667.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from mypy import api

from qqq1dte.core.config import load_config
from qqq1dte.execution_sim.decision import (
    CalibratedProbability,
    SideInput,
    breakeven_probability,
    decide,
    expected_value,
)

CFG = load_config()
ROOT = Path(__file__).resolve().parents[1]


def side(
    s: str,
    p: float | None,
    entry: float | None = 1.50,
    reason: str | None = None,
    support: int = 1_000,
) -> SideInput:
    cp = None if p is None else CalibratedProbability(p, f"cal-{s}")
    return SideInput(s, cp, reason, entry, support)


def test_breakeven_and_ev_hand_computed() -> None:
    assert breakeven_probability(1.50, CFG) == pytest.approx(31.4 / 75)
    assert expected_value(0.5, 1.50, CFG) == pytest.approx(0.5 * 45 - 0.5 * 30 - 1.4)
    assert expected_value(31.4 / 75, 1.50, CFG) == pytest.approx(0.0, abs=1e-12)
    assert breakeven_probability(0.50, CFG) == pytest.approx((10 + 1.4) / 25)  # costs bite more


def test_call_when_margin_and_ev_pass() -> None:
    d = decide(side("C", 0.50), side("P", 0.30), CFG)
    assert d.decision == "CALL" and d.reasons == ()
    assert d.ev_call == pytest.approx(6.1) and d.margin_call == pytest.approx(0.5 - 31.4 / 75)


def test_margin_must_exceed_edge_margin() -> None:
    p = 31.4 / 75 + 0.03  # exactly at the margin: not strictly greater
    d = decide(side("C", p), side("P", 0.10), CFG)
    assert d.decision == "NO_TRADE"
    assert d.reasons == ("CALL:BELOW_BREAKEVEN_MARGIN", "PUT:BELOW_BREAKEVEN_MARGIN")
    assert decide(side("C", p + 1e-6), side("P", 0.10), CFG).decision == "CALL"


def test_higher_ev_side_wins_and_exact_tie_is_no_trade() -> None:
    d = decide(side("C", 0.55), side("P", 0.60), CFG)
    assert d.decision == "PUT"
    tie = decide(side("C", 0.55), side("P", 0.55), CFG)
    assert (tie.decision, tie.reasons) == ("NO_TRADE", ("SIDE_TIE",))


def test_selection_failure_is_a_side_reason() -> None:
    d = decide(side("C", 0.9, None, "SELECTED_CONTRACT_ILLIQUID"), side("P", 0.2), CFG)
    assert d.decision == "NO_TRADE"
    assert d.reasons == ("CALL:SELECTED_CONTRACT_ILLIQUID", "PUT:BELOW_BREAKEVEN_MARGIN")
    assert d.ev_call is None
    ok = decide(side("C", 0.9, None, "NO_CONTRACT"), side("P", 0.6), CFG)
    assert ok.decision == "PUT"


def test_regime_blocked_cell_is_no_trade() -> None:
    cfg = CFG.model_copy(
        update={
            "decision": CFG.decision.model_copy(
                update={"blocked_regime_cells": ["HIGH/CHOP/MACRO"]}
            )
        }
    )
    d = decide(side("C", 0.9), side("P", 0.1), cfg, regime_cell="HIGH/CHOP/MACRO")
    assert (d.decision, d.reasons) == ("NO_TRADE", ("REGIME_BLOCKED",))
    assert (
        decide(side("C", 0.9), side("P", 0.1), cfg, regime_cell="LOW/TREND/NORMAL").decision
        == "CALL"
    )


def test_cal_04_uncalibrated_forces_no_trade() -> None:
    d = decide(side("C", None), side("P", 0.9), CFG)
    assert (d.decision, d.reasons) == ("NO_TRADE", ("UNCALIBRATED",))
    with pytest.raises(TypeError, match="CalibratedProbability"):
        decide(SideInput("C", 0.9, None, 1.5, 1_000), side("P", 0.1), CFG)  # type: ignore[arg-type]


def test_mypy_rejects_a_raw_score_in_a_side_input(tmp_path: Path) -> None:
    snippet = tmp_path / "bad_side.py"
    snippet.write_text(
        textwrap.dedent("""
        from qqq1dte.execution_sim.decision import SideInput
        SideInput("C", 0.7, None, 1.5, 1_000)
    """),
        encoding="utf-8",
    )
    out, _, status = api.run(
        [str(snippet), "--config-file", str(ROOT / "pyproject.toml"), "--no-incremental"]
    )
    assert status != 0 and "CalibratedProbability" in out


def test_adr_0010_minimum_calibration_support() -> None:
    """ADR-0010: a side needs >= decision.min_calibration_support calibration-block rows whose raw
    score is >= its raw score; the boundary is inclusive."""
    need = CFG.decision.min_calibration_support
    assert need == 200
    d = decide(side("C", 0.9, support=need - 1), side("P", 0.1), CFG)
    assert d.decision == "NO_TRADE"
    assert d.reasons == ("CALL:INSUFFICIENT_CALIBRATION_SUPPORT", "PUT:BELOW_BREAKEVEN_MARGIN")
    assert d.ev_call is not None  # EV and margin still reported for analysis
    assert decide(side("C", 0.9, support=need), side("P", 0.1), CFG).decision == "CALL"
    # support is checked after selection: a selection failure keeps its own reason
    sel = decide(side("C", 0.9, None, "NO_CONTRACT", support=0), side("P", 0.1), CFG)
    assert sel.reasons[0] == "CALL:NO_CONTRACT"
