"""Regime engine R1 (spec §9; M14): point-in-time session state, efficiency ratio, thresholds fit
on training sessions only (T-LEAK-12), assignment, and the analysis helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import numpy as np
import polars as pl
import pytest

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import ET
from qqq1dte.regimes.analysis import stratified_difference, summarize
from qqq1dte.regimes.engine import (
    RegimeInputs,
    assign,
    efficiency_ratio,
    fit_thresholds,
    session_state,
)

CFG = load_config()
CAL = TradingCalendar(CFG)
DT = pl.Datetime("us", "UTC")
SESSIONS = CAL.sessions(date(2024, 1, 2), date(2024, 3, 28))


def _et(d: date, hh: int, mm: int) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=ET).astimezone(UTC)


def inputs(
    closes: dict[date, float] | None = None,
    vix: dict[date, float] | None = None,
    macro: list[tuple[str, date, datetime]] | None = None,
) -> RegimeInputs:
    closes = closes or {d: 100.0 + i for i, d in enumerate(SESSIONS)}
    vix = vix or {d: 15.0 + (i % 7) for i, d in enumerate(SESSIONS)}
    daily = pl.DataFrame(
        {
            "session_date": list(closes),
            "close": list(closes.values()),
            "available_at": [_et(d, 16, 0) for d in closes],
        },
        schema={"session_date": pl.Date, "close": pl.Float64, "available_at": DT},
    )
    vt = pl.DataFrame(
        {
            "date": list(vix),
            "close": list(vix.values()),
            "available_at": [_et(d, 18, 0) for d in vix],
        },
        schema={"date": pl.Date, "close": pl.Float64, "available_at": DT},
    )
    mt = pl.DataFrame(
        [(e, d, a) for e, d, a in (macro or [])],
        schema={"event": pl.String, "session_date": pl.Date, "available_at": DT},
        orient="row",
    )
    return RegimeInputs(daily, vt, mt)


def test_efficiency_ratio_hand_computed() -> None:
    assert efficiency_ratio([100, 101, 102, 103]) == pytest.approx(1.0)  # straight line
    assert efficiency_ratio([100, 102, 100, 102]) == pytest.approx(2 / 6)
    assert efficiency_ratio([100, 101, 100]) == pytest.approx(0.0)


def test_session_state_uses_only_information_known_at_t() -> None:
    d = SESSIONS[30]
    t = _et(d, 10, 0)
    s = session_state(inputs(), d, t, CAL, CFG)
    prev = SESSIONS[29]
    assert s.vix == pytest.approx(15.0 + 29 % 7)  # prior session's VIX close (18:00 ET)
    closes = [100.0 + i for i in range(9, 30)]  # 21 closes up to the prior close
    assert s.er == pytest.approx(efficiency_ratio(closes))
    assert s.er_available_at == _et(prev, 16, 0) <= t
    # changing the session's own close (16:00) or anything later changes nothing at 10:00
    later = {
        k: (v if k < d else v * 3)
        for k, v in {x: 100.0 + i for i, x in enumerate(SESSIONS)}.items()
    }
    assert session_state(inputs(closes=later), d, t, CAL, CFG) == s


def test_missing_history_is_unknown_with_a_reason() -> None:
    d = SESSIONS[10]  # only 10 prior closes
    s = session_state(inputs(), d, _et(d, 10, 0), CAL, CFG)
    assert s.er is None and s.er_reason == "INSUFFICIENT_HISTORY"
    d2 = SESSIONS[40]
    gap = {x: 100.0 + i for i, x in enumerate(SESSIONS) if x != SESSIONS[35]}
    s2 = session_state(inputs(closes=gap), d2, _et(d2, 10, 0), CAL, CFG)
    assert s2.er is None and s2.er_reason == "MISSING_DAILY_CLOSE"


def test_macro_event_only_once_available() -> None:
    d = SESSIONS[30]
    ev = [("CPI", d, _et(d, 8, 30)), ("FOMC", SESSIONS[31], _et(date(2023, 12, 31), 0, 0))]
    assert session_state(inputs(macro=ev), d, _et(d, 9, 45), CAL, CFG).macro
    late = [("CPI", d, _et(d, 11, 0))]  # not yet known at 10:00
    assert not session_state(inputs(macro=late), d, _et(d, 10, 0), CAL, CFG).macro
    other = [("OTHER", d, _et(d, 8, 30))]  # not in regimes.macro_events
    assert not session_state(inputs(macro=other), d, _et(d, 10, 0), CAL, CFG).macro


def test_leak_12_thresholds_fit_on_training_states_only() -> None:
    inp = inputs()
    train = [session_state(inp, d, _et(d, 9, 45), CAL, CFG) for d in SESSIONS[21:45]]
    th = fit_thresholds(train, CFG)
    vix = [s.vix for s in train]
    assert th.vix_cuts == pytest.approx(tuple(np.quantile(vix, CFG.regimes.vix_quantiles)))
    assert th.er_median == pytest.approx(float(np.median([s.er for s in train])))
    assert th.n_train_sessions == 24 and th.n_extreme == 0
    # test-period states never enter the fit: assigning them leaves thresholds unchanged
    test = [session_state(inp, d, _et(d, 9, 45), CAL, CFG) for d in SESSIONS[45:]]
    _ = [assign(s, th) for s in test]
    assert fit_thresholds(train, CFG) == th


def test_assignment_buckets() -> None:
    inp = inputs()
    train = [session_state(inp, d, _et(d, 9, 45), CAL, CFG) for d in SESSIONS[21:45]]
    th = fit_thresholds(train, CFG)
    s = train[0]
    lo = assign(s.__class__(**{**s.__dict__, "vix": th.vix_cuts[0] - 1, "er": th.er_median}), th)
    hi = assign(
        s.__class__(**{**s.__dict__, "vix": th.vix_cuts[1] + 1, "er": th.er_median + 0.1}), th
    )
    assert (lo["volatility"][0], lo["trend"][0]) == ("LOW", "CHOP")  # ties go to CHOP
    assert (hi["volatility"][0], hi["trend"][0]) == ("HIGH", "TREND")
    unk = assign(s.__class__(**{**s.__dict__, "er": None, "er_reason": "INSUFFICIENT_HISTORY"}), th)
    assert unk["trend"][0] == "UNKNOWN"
    for axis, (_, avail) in assign(s, th).items():
        assert avail <= s.ts, axis


def test_summarize_flags_low_support() -> None:
    df = pl.DataFrame(
        {
            "session_date": [date(2024, 1, 1) + timedelta(days=i // 10) for i in range(400)],
            "bucket": ["A"] * 350 + ["B"] * 50,
            "value": [1.0] * 350 + [0.0] * 50,
        }
    )
    out = {r["bucket"]: r for r in summarize(df, ["bucket"], "value", CFG, trades=True)}
    assert out["A"]["n"] == 350 and out["A"]["sessions"] == 35 and not out["A"]["low_support"]
    assert out["B"]["low_support"]  # 5 sessions, 50 trades
    assert out["A"]["mean"] == pytest.approx(1.0)


def test_stratified_difference_known_answer() -> None:
    rng = np.random.default_rng(0)
    rows = []
    for s in range(400):
        d = date(2024, 1, 1) + timedelta(days=s)
        stratum = "A" if s % 2 else "B"
        trend = "TREND" if (s // 2) % 2 else "CHOP"
        base = (1.0 if trend == "TREND" else 0.0) if stratum == "A" else 3.0
        rows += [(d, stratum, trend, base + rng.normal(0, 0.1)) for _ in range(5)]
    df = pl.DataFrame(rows, schema=["session_date", "stratum", "trend", "value"], orient="row")
    r = stratified_difference(df, "value", ["stratum"], CFG)
    assert r["difference"] == pytest.approx(0.5, abs=0.02)  # (1 + 0) / 2, equal weights
    assert r["ci"][0] > 0.4 and r["ci"][1] < 0.6
