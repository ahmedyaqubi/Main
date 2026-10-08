"""Drift monitoring (spec Phase 1Q, gate 18; M18): PSI, calibration z-score, expectancy and
regime monitors, the alert state machine (DISABLED latches), the decision guard, and the
gate-18 replay on synthetic stationary data (right alert within 10 sessions, no false alarm)."""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from qqq1dte.core.config import load_config
from qqq1dte.execution_sim.decision import CalibratedProbability, SideInput, decide
from qqq1dte.monitoring.drift import (
    DriftMonitor,
    assess_window,
    build_reference,
    flip_wins,
    psi,
    psi_categorical,
    replay_detection,
    shift_features,
)

CFG = load_config()
FEATS = ["f1", "f2", "f3"]
TARGETS = ("C_call", "C_put")


def sessions_frame(n: int, seed: int, start: date = date(2024, 1, 1)) -> pl.DataFrame:
    """Stationary synthetic predictions: 30 per session, calibrated probabilities."""
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(n):
        d = start + timedelta(days=s)
        cell = ["LOW/TREND/NORMAL", "HIGH/CHOP/NORMAL"][s % 2]
        for _ in range(30):
            p = rng.uniform(0.15, 0.4, 2)
            y = (rng.random(2) < p).astype(float)
            rows.append(
                {
                    "session_date": d,
                    **{f: rng.normal() for f in FEATS},
                    "p_C_call": p[0],
                    "p_C_put": p[1],
                    "y_C_call": y[0],
                    "y_C_put": y[1],
                    "cell": cell,
                }
            )
    return pl.DataFrame(rows)


def test_psi_hand_computed_and_zero_for_identical() -> None:
    ref = np.arange(100, dtype=float)
    assert psi(ref, ref.copy(), 10, 1e-4) == pytest.approx(0.0, abs=1e-12)
    cur = np.arange(50, dtype=float)  # all in the lower half
    eps = 1e-4
    expected = (1.0 - 0.5) * math.log(1.0 / 0.5) + (eps - 0.5) * math.log(eps / 0.5)
    assert psi(ref, cur, 2, eps) == pytest.approx(expected, rel=1e-9)


def test_psi_categorical_hand_computed() -> None:
    ref = ["A"] * 50 + ["B"] * 50
    cur = ["A"] * 75 + ["B"] * 25
    expected = (0.75 - 0.5) * math.log(0.75 / 0.5) + (0.25 - 0.5) * math.log(0.25 / 0.5)
    assert psi_categorical(ref, cur, 1e-4) == pytest.approx(expected, rel=1e-9)


def test_reference_session_gap_sd() -> None:
    f = sessions_frame(40, 1)
    ref = build_reference(f, FEATS, CFG)
    g = f.group_by("session_date").agg(
        c=(pl.col("y_C_call") - pl.col("p_C_call")).mean(),
        p=(pl.col("y_C_put") - pl.col("p_C_put")).mean(),
    )
    assert ref.gap_sd["C_call"] == pytest.approx(g["c"].std())
    assert ref.gap_sd["combined"] == pytest.approx(((g["c"] + g["p"]) / 2).std())


def test_stationary_window_is_ok_and_each_injection_raises_its_alert() -> None:
    ref_f = sessions_frame(60, 2)
    ref = build_reference(ref_f, FEATS, CFG)
    win = sessions_frame(10, 3, start=date(2024, 6, 1))
    a = assess_window(win, ref, CFG)
    assert a.overall in ("OK", "WARN"), a.details
    shifted = shift_features(win, FEATS, ref, 1.0)
    assert assess_window(shifted, ref, CFG).levels["features"] == "PAPER_ONLY"
    flipped = flip_wins(win, TARGETS, 1.0, np.random.default_rng(0))
    b = assess_window(flipped, ref, CFG)
    assert b.levels["calibration"] == "DISABLED" and b.overall == "DISABLED"


def test_expectancy_monitor() -> None:
    ref = build_reference(sessions_frame(40, 4), FEATS, CFG)
    win = sessions_frame(10, 5, start=date(2024, 6, 1))
    days = win["session_date"].unique().sort().to_list()

    def trades(nets: list[float]) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "session_date": [days[i % 10] for i in range(len(nets))],
                "gross_pnl": [n + 1.4 for n in nets],
                "commissions": [1.3] * len(nets),
                "fees": [0.1] * len(nets),
                "net_pnl": nets,
            }
        )

    assert (
        assess_window(win, ref, CFG, trades(list(np.full(10, -5.0)))).levels["expectancy"] == "OK"
    )  # fewer than min_trades: not evaluable
    mixed = list(np.tile([12.0, -14.0], 15))
    assert assess_window(win, ref, CFG, trades(mixed)).levels["expectancy"] == "WARN"
    losing = list(-20.0 + np.random.default_rng(1).normal(0, 2, 30))
    assert assess_window(win, ref, CFG, trades(losing)).levels["expectancy"] == "DISABLED"


def test_regime_frequency_only_warns() -> None:
    ref = build_reference(sessions_frame(40, 6), FEATS, CFG)
    win = sessions_frame(10, 7, start=date(2024, 6, 1)).with_columns(
        cell=pl.lit("HIGH/TREND/MACRO")
    )
    a = assess_window(win, ref, CFG, regime_cells=["HIGH/TREND/MACRO"] * 20)
    assert a.levels["regimes"] == "WARN"


def test_disabled_latches_until_a_named_human_reenables() -> None:
    m = DriftMonitor()
    ref = build_reference(sessions_frame(40, 8), FEATS, CFG)
    bad = flip_wins(
        sessions_frame(10, 9, start=date(2024, 6, 1)), TARGETS, 1.0, np.random.default_rng(0)
    )
    good = sessions_frame(10, 10, start=date(2024, 7, 1))
    assert m.update(assess_window(bad, ref, CFG)) == "DISABLED"
    assert m.update(assess_window(good, ref, CFG)) == "DISABLED"  # latched
    with pytest.raises(ValueError, match="approver"):
        m.reenable(" ")
    m.reenable("Ahmed")
    assert m.update(assess_window(good, ref, CFG)) in ("OK", "WARN")
    assert m.history[-2]["event"] == "REENABLED by Ahmed"


def _side(s: str, p: float) -> SideInput:
    return SideInput(s, CalibratedProbability(p, f"cal-{s}"), None, 1.5, 1_000)


def test_degraded_model_cannot_emit_call_or_put() -> None:
    ok = decide(_side("C", 0.9), _side("P", 0.1), CFG)
    assert ok.decision == "CALL" and ok.flags == ()
    d = decide(_side("C", 0.9), _side("P", 0.1), CFG, drift_state="DISABLED")
    assert (d.decision, d.reasons) == ("NO_TRADE", ("DRIFT_DISABLED",))
    p = decide(_side("C", 0.9), _side("P", 0.1), CFG, drift_state="PAPER_ONLY")
    assert p.decision == "CALL" and p.flags == ("DRIFT_PAPER_ONLY",)
    with pytest.raises(ValueError, match="drift state"):
        decide(_side("C", 0.9), _side("P", 0.1), CFG, drift_state="MAYBE")


def test_gate_18_replay_on_synthetic_stationary_data() -> None:
    sessions = sessions_frame(60, 11)
    res = replay_detection(sessions, FEATS, CFG, n_replays=5, seed=3)
    for kind, expected in (("feature_shift", "PAPER_ONLY"), ("calibration", "DISABLED")):
        r = res[kind]
        assert all(x["alert"] == expected for x in r["replays"]), r
        assert max(x["delay"] for x in r["replays"]) <= CFG.monitoring.replay.max_delay_sessions
        assert r["false_alarm_replays"] <= CFG.monitoring.replay.max_false_alarm_replays


def test_flip_wins_keeps_unresolved_outcomes_null() -> None:
    """Regression (M18 real-data run): nulls must stay null, not become NaN in the gap means."""
    f = sessions_frame(10, 12).with_columns(
        y_C_call=pl.when(pl.int_range(pl.len()) % 7 == 0).then(None).otherwise(pl.col("y_C_call"))
    )
    out = flip_wins(f, TARGETS, 0.5, np.random.default_rng(0))
    assert out["y_C_call"].null_count() == f["y_C_call"].null_count()
    assert not out["y_C_call"].is_nan().any()
    ref = build_reference(sessions_frame(40, 13), FEATS, CFG)
    z = assess_window(flip_wins(f, TARGETS, 1.0, np.random.default_rng(1)), ref, CFG).details[
        "calibration"
    ]
    assert all(np.isfinite(v) for v in z.values())


def test_psi_thresholds_are_null_quantiles_of_reference_windows() -> None:
    """Owner M18 option A: thresholds = quantiles of the monitor's PSI over random
    window_sessions windows drawn (seeded) from the reference period."""
    f = sessions_frame(60, 14)
    ref = build_reference(f, FEATS, CFG)
    m = CFG.monitoring
    for key in ("features", "predictions"):
        nd = ref.null[key]
        assert nd.size == m.psi_null_draws
        assert ref.thresholds[key] == pytest.approx(
            (
                float(np.quantile(nd, m.psi_warn_quantile)),
                float(np.quantile(nd, m.psi_paper_only_quantile)),
            )
        )
    assert build_reference(f, FEATS, CFG).thresholds == ref.thresholds  # seeded, reproducible
    # stationary windows from the same process rarely escalate
    escalated = sum(
        assess_window(sessions_frame(10, 100 + i, start=date(2024, 6, 1)), ref, CFG).levels[
            "features"
        ]
        == "PAPER_ONLY"
        for i in range(30)
    )
    assert escalated <= 1


def test_only_the_combined_calibration_z_disables() -> None:
    """Per-target |z| > disable gives WARN; DISABLED needs the combined decision-target z
    (multiplicity of three z-scores; a one-sided degradation is documented as WARN)."""
    ref = build_reference(sessions_frame(60, 15), FEATS, CFG)
    win = sessions_frame(10, 16, start=date(2024, 6, 1))
    # strong degradation on one side only, offset on the other: combined stays near 0
    one = flip_wins(win, ("C_call",), 1.0, np.random.default_rng(2))
    # C_put wins ~0.27 more often than predicted: the two gaps cancel in the combined gap
    u = pl.Series(np.random.default_rng(3).random(one.height))
    one = one.with_columns(y_C_put=(u < pl.col("p_C_put") + 0.2775).cast(pl.Float64))
    a = assess_window(one, ref, CFG)
    z = a.details["calibration"]
    assert abs(z["C_call"]) > CFG.monitoring.calib_z_disable
    assert abs(z["combined"]) <= CFG.monitoring.calib_z_disable
    assert a.levels["calibration"] == "WARN"
