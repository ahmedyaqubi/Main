"""Walk-forward splitter (spec §8): T-WF-01, T-WF-02, T-WF-04 and the full-block rule (M7 Q1)."""

from __future__ import annotations

import inspect
import itertools
from datetime import date
from pathlib import Path

import pytest

from qqq1dte.backtesting import splits
from qqq1dte.backtesting.splits import walk_forward_folds
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config

CFG = load_config()
CAL = TradingCalendar(CFG)
HOLD = CAL.final_holdout_start(date(2026, 10, 2))
SESSIONS = CAL.research_sessions(CFG.history.option_era_start, HOLD)  # pre-holdout only
FOLDS = walk_forward_folds(SESSIONS, HOLD, CFG)


def test_fold_layout_matches_spec_section_8() -> None:
    assert len(FOLDS) == 7  # the partial 8th test block is dropped (M7 Q1)
    f1 = FOLDS[0]
    assert (f1.train[0], f1.train[-1], len(f1.train)) == (date(2023, 3, 28), date(2024, 3, 27), 251)
    assert f1.embargo == (date(2024, 3, 28),)
    assert (f1.calib[0], f1.calib[-1]) == (date(2024, 4, 1), date(2024, 5, 24))
    assert (f1.test[0], f1.test[-1], len(f1.test)) == (date(2024, 5, 28), date(2024, 8, 27), 64)
    assert FOLDS[-1].test[-1] == date(2026, 2, 27)


def test_wf_01_chronological_and_disjoint() -> None:
    for f in FOLDS:
        assert max(f.train) < min(f.embargo) <= max(f.embargo) < min(f.calib)
        assert max(f.calib) < min(f.test)
        blocks = [set(f.train), set(f.embargo), set(f.calib), set(f.test)]
        assert sum(len(b) for b in blocks) == len(set().union(*blocks))
    for a, b in itertools.pairwise(FOLDS):
        assert b.train[0] == a.train[0] and len(b.train) > len(a.train)  # expanding window
        assert set(a.test) & set(b.test) == set()  # test blocks never overlap


def test_wf_02_embargo_is_one_full_session_after_training() -> None:
    for f in FOLDS:
        assert len(f.embargo) == CFG.validation.embargo_sessions
        nxt = SESSIONS[SESSIONS.index(f.train[-1]) + 1]
        assert f.embargo[0] == nxt  # the very next session is embargoed


def test_folds_never_touch_the_final_holdout() -> None:
    assert all(d <= HOLD for f in FOLDS for block in (f.train, f.calib, f.test) for d in block)


def test_holdout_sessions_in_input_are_rejected() -> None:
    with pytest.raises(ValueError, match="holdout"):
        walk_forward_folds([*SESSIONS, date(2026, 4, 6)], HOLD, CFG)


def test_wf_04_no_random_split_possible() -> None:
    params = inspect.signature(walk_forward_folds).parameters
    assert not any(k in params for k in ("shuffle", "random_state", "seed"))
    src = Path(splits.__file__).read_text(encoding="utf-8")
    assert "random" not in src and "shuffle" not in src
