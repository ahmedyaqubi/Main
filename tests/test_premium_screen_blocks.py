"""M23 Step 1 (ADR-0014 D5): moving-block bootstrap, independent holding periods, D5 guards."""

from __future__ import annotations

import numpy as np

from qqq1dte.backtesting.premium_screen import (
    ADVANCE,
    CellResult,
    family_outcome,
    guards_2a,
    independent_periods,
    moving_block_weights,
    weighted_means,
)
from qqq1dte.core.config import load_config

CFG = load_config()


def test_block_weights_sum_and_reproducible() -> None:
    w = moving_block_weights(10, block=3, reps=50, seed=7)
    assert w.shape == (50, 10) and (w.sum(axis=1) == 10).all()
    assert np.array_equal(w, moving_block_weights(10, block=3, reps=50, seed=7))


def test_block_of_full_length_covers_every_session_once() -> None:
    # one circular block of length n starting anywhere visits each session exactly once
    w = moving_block_weights(6, block=6, reps=5, seed=1)
    assert (w == 1).all()


def test_blocks_are_contiguous_circular_runs() -> None:
    w = moving_block_weights(4, block=2, reps=200, seed=3)
    for row in w:
        # two blocks of two adjacent sessions (circular): every row is a sum of such pairs
        pairs = [np.roll(np.array([1, 1, 0, 0]), k) for k in range(4)]
        assert any(np.array_equal(row, a + b) for a in pairs for b in pairs)
    vals = np.array([1.0, 2.0, 3.0, 4.0])
    assert np.allclose(weighted_means(vals, w[:1]), (w[0] * vals).sum() / 4)


def test_independent_periods_greedy() -> None:
    # entries on sessions 0..9 with a 3-session hold: 0, 3, 6, 9 -> 4 independent periods
    assert independent_periods(np.arange(10), 3) == 4
    assert independent_periods(np.array([0, 1, 2, 7, 8]), 5) == 2
    assert independent_periods(np.array([], dtype=int), 3) == 0


def test_guards_2a() -> None:
    assert guards_2a(300, 24, 3.0, CFG) == []
    assert guards_2a(299, 23, 2.9, CFG) == ["FEW_ENTRIES", "FEW_INDEPENDENT_PERIODS", "FEW_YEARS"]


def test_family_outcome_respects_study_2a_max_advance() -> None:
    adv = [
        CellResult(c, ADVANCE, lb, 1.0, 400, 400, 200, [], False)
        for c, lb in (("L1", 1.0), ("L3", 2.0))
    ]
    assert family_outcome(adv, CFG, CFG.study_2a.max_advance) == (ADVANCE, ["L3"])
    assert family_outcome(adv, CFG) == (ADVANCE, ["L3", "L1"])  # ADR-0013 default unchanged
