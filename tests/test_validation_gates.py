"""Phase 1V gate evaluation (spec §11; M19): threshold functions, PBO (CSCV) and the deflated
Sharpe ratio, on synthetic evidence with known answers."""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pytest

from qqq1dte.core.config import load_config
from qqq1dte.validation.phase1_gates import (
    deflated_sharpe_probability,
    gate6,
    gate10,
    gate11,
    gate13,
    gate14,
    gate15,
    gate16,
    gate_from_checks,
    pbo_cscv,
)

CFG = load_config()
N = NormalDist()


def test_gate_from_checks_states() -> None:
    assert gate_from_checks(1, "x", "r", {"a": True, "b": True}, {}).status == "PASS"
    assert gate_from_checks(1, "x", "r", {"a": True, "b": False}, {}).status == "FAIL"
    assert gate_from_checks(1, "x", "r", {"a": True, "b": None}, {}).status == "NOT_EVALUABLE"
    assert gate_from_checks(1, "x", "r", {"a": False, "b": None}, {}).status == "FAIL"


def test_gate6_needs_ci_above_zero_and_fold_share_for_every_target() -> None:
    ok = {"bss": 0.02, "ci": (0.005, 0.03), "folds_better": 5, "n_folds": 7}
    assert gate6({"C_call": ok, "C_put": ok}, CFG).status == "PASS"
    low_share = {**ok, "folds_better": 4}  # 4/7 < 0.70
    assert gate6({"C_call": ok, "C_put": low_share}, CFG).status == "FAIL"
    ci0 = {**ok, "ci": (-0.001, 0.03)}
    assert gate6({"C_call": ci0, "C_put": ok}, CFG).status == "FAIL"


def test_trade_gates_not_evaluable_without_trades() -> None:
    assert gate10(None, None, CFG).status == "NOT_EVALUABLE"
    assert gate11(None, None).status == "NOT_EVALUABLE"
    assert gate13([], 0, CFG).status == "NOT_EVALUABLE"
    assert gate14(None, 0).status == "NOT_EVALUABLE"
    assert gate15(0, 0, CFG).status == "FAIL"


def test_trade_gate_thresholds() -> None:
    assert gate10((0.5, 9.0), 5 / 7, CFG).status == "PASS"
    assert gate10((-0.5, 9.0), 5 / 7, CFG).status == "FAIL"
    assert gate10((0.5, 9.0), 4 / 7, CFG).status == "FAIL"  # 0.571 < 0.60
    assert gate11(1.0, True).status == "PASS" and gate11(-1.0, True).status == "FAIL"
    assert gate11(1.0, False).status == "FAIL"
    cells = [
        {"cell": "A", "trades": 150, "ci_upper": 3.0},
        {"cell": "B", "trades": 90, "ci_upper": -1.0},
    ]
    assert gate13(cells, 240, CFG).status == "PASS"  # B has < 100 trades: not judged
    cells[0]["ci_upper"] = -0.1
    assert gate13(cells, 240, CFG).status == "FAIL"
    assert gate14((0.2, 5.0), 300).status == "PASS" and gate14((-0.2, 5.0), 300).status == "FAIL"
    assert gate15(300, 150, CFG).status == "PASS" and gate15(299, 200, CFG).status == "FAIL"
    assert gate15(400, 149, CFG).status == "FAIL"


def test_gate16() -> None:
    assert gate16(0.10, 0.97, CFG).status == "PASS"
    assert gate16(0.25, 0.97, CFG).status == "FAIL"
    assert gate16(0.10, 0.90, CFG).status == "FAIL"
    assert gate16(0.10, None, CFG).status == "NOT_EVALUABLE"


def test_pbo_noise_is_about_half_and_dominant_strategy_is_zero() -> None:
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 1, (480, 10))
    p, logits = pbo_cscv(noise, 16)
    assert 0.3 <= p <= 0.7 and len(logits) == math.comb(16, 8)
    dom = noise.copy()
    dom[:, 3] += 1.0  # one configuration is genuinely better everywhere
    assert pbo_cscv(dom, 16)[0] == pytest.approx(0.0)


def test_pbo_hand_case() -> None:
    """2 blocks, 2 configs: IS block 0 picks config 0 (better there), which is worse OOS ->
    logit < 0; IS block 1 picks config 1, worse OOS -> logit < 0. PBO = 1."""
    m = np.array([[1.0, 0.0], [0.0, 1.0]])
    p, logits = pbo_cscv(m, 2)
    assert p == pytest.approx(1.0) and len(logits) == 2


def test_deflated_sharpe_matches_formula_and_behaves() -> None:
    rng = np.random.default_rng(1)
    r = rng.normal(0.05, 1.0, 2000)
    sr = r.mean() / r.std(ddof=1)
    n_trials, var_sr = 20, 0.01
    g = 0.5772156649015329
    sr0 = math.sqrt(var_sr) * (
        (1 - g) * N.inv_cdf(1 - 1 / n_trials) + g * N.inv_cdf(1 - 1 / (n_trials * math.e))
    )
    m3 = float(((r - r.mean()) ** 3).mean() / r.std() ** 3)
    m4 = float(((r - r.mean()) ** 4).mean() / r.std() ** 4)
    expected = N.cdf(
        (sr - sr0) * math.sqrt(r.size - 1) / math.sqrt(1 - m3 * sr + (m4 - 1) / 4 * sr**2)
    )
    assert deflated_sharpe_probability(r, n_trials, var_sr) == pytest.approx(expected, rel=1e-9)
    # more trials -> harder to clear; better returns -> easier
    assert deflated_sharpe_probability(r, 200, var_sr) < deflated_sharpe_probability(r, 20, var_sr)
    assert deflated_sharpe_probability(r + 0.05, 20, var_sr) > deflated_sharpe_probability(
        r, 20, var_sr
    )
