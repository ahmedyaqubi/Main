"""ADR-0012 D2 screen (M19S Step 1): required accuracy a*, achievable accuracy A-hat,
coverage, paired bootstrap of delta = A-hat - a*, guards and the advance rule. Synthetic cases
with exact answers."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st

from qqq1dte.backtesting.bootstrap import session_bootstrap_ci
from qqq1dte.backtesting.screen import (
    Cell,
    a_star,
    advance,
    bootstrap_draws,
    coverage_mask,
    delta_lower_bound,
    direction,
    ev_at,
    max_drawdown,
    policy_trades,
    predicted_side,
    screen_stats,
)
from qqq1dte.core.config import load_config

CFG = load_config()


def test_a_star_hand_computed() -> None:
    # (-0.2·(-10)/0.8 + 50) / 150 = 52.5 / 150
    assert a_star(100.0, -50.0, -10.0, 0.2) == pytest.approx(0.35)
    assert a_star(100.0, -50.0, 0.0, 0.0) == pytest.approx(50 / 150)


def test_a_star_undefined_when_c_not_above_w() -> None:
    assert math.isnan(a_star(10.0, 10.0, 0.0, 0.1))
    assert math.isnan(a_star(-5.0, 10.0, 0.0, 0.1))
    assert math.isnan(a_star(10.0, -10.0, 0.0, 1.0))


@given(
    c=st.floats(1.0, 500.0),
    w=st.floats(-500.0, 0.0),
    d=st.floats(-100.0, 100.0),
    p_d=st.floats(0.0, 0.9),
)
def test_ev_is_zero_at_a_star(c: float, w: float, d: float, p_d: float) -> None:
    a = a_star(c, w, d, p_d)
    assert ev_at(a, c, w, d, p_d) == pytest.approx(0.0, abs=1e-6)


def test_direction_and_side_rules() -> None:
    ret = np.array([0.001, -0.001, 0.0004, -0.0005, np.nan])
    assert direction(ret, 0.0005).tolist()[:4] == [1, -1, 0, 0]  # strict, like the A labels
    assert direction(ret, 0.0003).tolist()[:4] == [1, -1, 1, -1]
    assert np.isnan(direction(ret, 0.0005)[4])
    side, s = predicted_side(np.array([0.6, 0.3, 0.4]), np.array([0.2, 0.5, 0.4]))
    assert side.tolist() == ["C", "P", "P"]  # tie -> PUT (ADR-0012 D2)
    assert s.tolist() == [0.6, 0.5, 0.4]


def test_coverage_is_top_c_within_each_fold() -> None:
    fold = np.array([1] * 10 + [2] * 10)
    s = np.concatenate([np.arange(10) / 10, np.arange(10)[::-1] / 100])
    m = coverage_mask(fold, s, 0.2)
    assert m.sum() == 4
    assert m[8] and m[9] and m[10] and m[11]
    assert coverage_mask(fold, s, 1.0).all()


def _frame(rows: list[tuple[int, str, int, float]]) -> pl.DataFrame:
    """rows: (session index, predicted side, direction, net P&L)."""
    t0 = datetime(2025, 1, 2, 15, tzinfo=UTC)
    return pl.DataFrame(
        {
            "session_date": [date(2025, 1, 2) + timedelta(days=k) for k, _, _, _ in rows],
            "prediction_ts": [t0 + timedelta(days=k, minutes=i) for i, (k, *_) in enumerate(rows)],
            "side": [r[1] for r in rows],
            "dir": [float(r[2]) for r in rows],
            "net": [r[3] for r in rows],
        }
    )


def test_screen_stats_hand_computed() -> None:
    # correct: CALL & up, PUT & down; wrong: the opposite; deadband: dir 0
    df = _frame(
        [
            (0, "C", 1, 100.0),
            (0, "P", -1, 80.0),
            (1, "C", -1, -50.0),
            (1, "P", 1, -30.0),
            (2, "C", 0, -10.0),
            (2, "C", 1, 120.0),
        ]
    )
    r = screen_stats(df, np.ones(df.height))
    assert r["C"] == pytest.approx(100.0)
    assert r["W"] == pytest.approx(-40.0)
    assert r["D"] == pytest.approx(-10.0)
    assert r["p_D"] == pytest.approx(1 / 6)
    assert r["a_hat"] == pytest.approx(3 / 5)
    assert r["a_star"] == pytest.approx(a_star(100.0, -40.0, -10.0, 1 / 6))
    assert r["delta"] == pytest.approx(r["a_hat"] - r["a_star"])
    assert r["mean_net"] == pytest.approx(210 / 6)


def test_weights_act_as_session_copies() -> None:
    df = _frame([(0, "C", 1, 100.0), (1, "C", -1, -50.0)])
    w = np.array([2.0, 1.0])
    doubled = pl.concat([df.head(1), df])
    assert screen_stats(df, w)["a_hat"] == pytest.approx(screen_stats(doubled, np.ones(3))["a_hat"])


def test_paired_bootstrap_exact_when_noise_free() -> None:
    # every session identical -> every resample gives the same delta
    rows = []
    for k in range(40):
        rows += [(k, "C", 1, 100.0), (k, "C", -1, -50.0), (k, "P", -1, 100.0)]
    df = _frame(rows)
    point = screen_stats(df, np.ones(df.height))["delta"]
    assert delta_lower_bound(df, CFG) == pytest.approx(point)


def test_paired_bootstrap_lower_bound_below_point_with_noise() -> None:
    rng = np.random.default_rng(1)
    rows = []
    for k in range(60):
        for _ in range(5):
            d = int(rng.choice([1, -1]))
            rows.append((k, "C", d, float(rng.normal(80 if d == 1 else -50, 30))))
    df = _frame(rows)
    point = screen_stats(df, np.ones(df.height))["delta"]
    assert delta_lower_bound(df, CFG) < point


def _cell(defn: str, cov: float, lb: float, sessions: int = 200, **kw: object) -> Cell:
    base: dict[str, object] = {
        "definition": defn,
        "coverage": cov,
        "delta_lb": lb,
        "n_trades": 1000,
        "n_sessions": sessions,
        "c_minus_w": 50.0,
        "cohort_ok": True,
    }
    base.update(kw)
    return Cell(**base)  # type: ignore[arg-type]


def test_guards_bar_cells() -> None:
    cells = [
        _cell("T0", 1.0, 0.05, c_minus_w=0.0),
        _cell("T1a", 1.0, 0.05, n_trades=299),
        _cell("T1b", 1.0, 0.05, sessions=149),
        _cell("T5", 1.0, 0.05, cohort_ok=False),
        _cell("T2", 1.0, 0.0),  # lower bound must be strictly > 0
    ]
    assert advance(cells, CFG) == []
    assert cells[0].barred(CFG) == ["C_NOT_ABOVE_W"]
    assert cells[1].barred(CFG) == ["FEW_TRADES"]
    assert cells[2].barred(CFG) == ["FEW_SESSIONS"]
    assert cells[3].barred(CFG) == ["COHORT_AFTER_CUTOFF"]


def test_advance_best_coverage_per_definition_and_max_two() -> None:
    cells = [
        _cell("T0", 1.0, 0.010),
        _cell("T0", 0.2, 0.030),
        _cell("T2", 0.05, 0.020),
        _cell("T3", 0.2, 0.012),
    ]
    out = advance(cells, CFG)
    assert [(c.definition, c.coverage) for c in out] == [("T0", 0.2), ("T2", 0.05)]


def test_advance_ties_by_sessions_then_order() -> None:
    # within 0.005 of the best: more sessions wins; equal sessions -> tie_order (T1b before T0)
    cells = [
        _cell("T0", 1.0, 0.030, sessions=300),
        _cell("T1b", 1.0, 0.027, sessions=300),
        _cell("T4", 1.0, 0.026, sessions=400),
    ]
    out = advance(cells, CFG)
    assert [c.definition for c in out] == ["T4", "T1b"]


def test_shared_draws_match_session_bootstrap_ci() -> None:
    rng = np.random.default_rng(3)
    rows = []
    for k in range(30):
        for _ in range(4):
            d = int(rng.choice([1, -1, 0]))
            rows.append((k, str(rng.choice(["C", "P"])), d, float(rng.normal(10 * d, 40))))
    df = _frame(rows)
    draws = bootstrap_draws(df, CFG)["mean_net"]
    lo, hi = session_bootstrap_ci(
        df["session_date"].to_numpy(),
        lambda w: screen_stats(df, w)["mean_net"],
        CFG.validation.bootstrap_reps,
        CFG.models.metrics.bootstrap_seed,
        0.9,
    )
    assert np.quantile(draws, [0.05, 0.95]).tolist() == pytest.approx([lo, hi])


def test_policy_max_entries_and_one_open_position() -> None:
    t0 = datetime(2025, 1, 2, 15, tzinfo=UTC)
    m = timedelta(minutes=1)
    df = pl.DataFrame(
        {
            "session_date": [date(2025, 1, 2)] * 6,
            "prediction_ts": [t0, t0 + 5 * m, t0 + 30 * m, t0 + 40 * m, t0 + 60 * m, t0 + 90 * m],
            "exit_ts": [
                t0 + 20 * m,
                t0 + 25 * m,
                t0 + 35 * m,
                t0 + 50 * m,
                t0 + 70 * m,
                t0 + 99 * m,
            ],
            "net": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        }
    )
    # 0 enters (exit +20); 5 overlaps; 30 enters (exit +35); 40 enters -> 3 entries, stop
    out = policy_trades(df, max_entries=3)
    assert out["net"].to_list() == [1.0, 3.0, 4.0]


def test_max_drawdown() -> None:
    assert max_drawdown(np.array([10.0, -5.0, -10.0, 20.0, -30.0])) == pytest.approx(30.0)
    assert max_drawdown(np.array([1.0, 2.0])) == 0.0
