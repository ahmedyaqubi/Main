"""Regime engine R1 (spec §9, OD-9; M14). Session-level regime state at prediction time T, from
information known at T only (AsOfReader):

- volatility: latest VIX close available at T (the prior session's close; 18:00 ET), bucketed
  LOW / NORMAL / HIGH by tercile cuts fit on the training fold's sessions. EXTREME stays merged
  into HIGH; training sessions at or above `extreme_vix` are counted only;
- trend: efficiency ratio |net move| / sum |daily moves| over the last `er_window_sessions` daily
  moves up to the prior close, TREND above the training median, else CHOP. Missing history or a
  missing daily close inside the window gives UNKNOWN with a reason (rule 8: never filled);
- event: MACRO if a configured event (CPI / FOMC / NFP) on session D is known by T.

Thresholds are fit on training-fold states only (T-LEAK-12); `assign` never refits.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
import polars as pl

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config
from qqq1dte.core.pit import AsOfReader

VOL = ("LOW", "NORMAL", "HIGH")
AXES = ("volatility", "trend", "event")


@dataclass(frozen=True)
class RegimeInputs:
    daily: pl.DataFrame  # session_date, close, available_at (session close)
    vix: pl.DataFrame  # date, close, available_at
    macro: pl.DataFrame  # event, session_date, available_at


@dataclass(frozen=True)
class SessionState:
    session: date
    ts: datetime
    vix: float | None
    vix_available_at: datetime | None
    er: float | None
    er_reason: str | None
    er_available_at: datetime | None
    macro: bool
    macro_available_at: datetime | None


@dataclass(frozen=True)
class Thresholds:
    vix_cuts: tuple[float, ...]
    er_median: float
    n_train_sessions: int
    n_extreme: int


def efficiency_ratio(closes: Sequence[float]) -> float:
    c = np.asarray(closes, dtype=np.float64)
    path = float(np.abs(np.diff(c)).sum())
    return abs(float(c[-1] - c[0])) / path if path > 0 else 0.0


def session_state(
    inp: RegimeInputs, session: date, t: datetime, cal: TradingCalendar, cfg: Phase1Config
) -> SessionState:
    r = AsOfReader({"d": inp.daily, "v": inp.vix, "m": inp.macro}, t)
    vix = r.get("v").sort("available_at")
    v, v_at = (float(vix["close"][-1]), vix["available_at"][-1]) if vix.height else (None, None)
    w = cfg.regimes.er_window_sessions
    need = [d for d in cal.sessions(session - timedelta(days=3 * w + 30), session) if d < session]
    need = need[-(w + 1) :]
    known = r.get("d")
    daily = known.filter(pl.col("session_date").is_in(need)).sort("session_date")
    first_known = known["session_date"].min() if known.height else None
    er: float | None = None
    er_reason: str | None = None
    er_at: datetime | None = None
    if len(need) < w + 1 or first_known is None or first_known > need[0]:  # type: ignore[operator]
        er_reason = "INSUFFICIENT_HISTORY"  # the daily series starts after the window begins
    elif daily.height < w + 1:
        er_reason = "MISSING_DAILY_CLOSE"
    else:
        er = efficiency_ratio(daily["close"].to_list())
        er_at = daily["available_at"].to_list()[-1]  # the prior session's close time
    ev = r.get("m").filter(
        (pl.col("session_date") == session) & pl.col("event").is_in(cfg.regimes.macro_events)
    )
    m_at = ev["available_at"].min() if ev.height else None
    return SessionState(session, t, v, v_at, er, er_reason, er_at, ev.height > 0, m_at)  # type: ignore[arg-type]


def fit_thresholds(train: Sequence[SessionState], cfg: Phase1Config) -> Thresholds:
    """Cuts from training-fold session states only (one state per session)."""
    vix = [s.vix for s in train if s.vix is not None]
    ers = [s.er for s in train if s.er is not None]
    if not vix or not ers:
        raise ValueError("training states lack VIX or efficiency-ratio values")
    cuts = tuple(float(c) for c in np.quantile(vix, cfg.regimes.vix_quantiles))
    n_ext = sum(v >= cfg.regimes.extreme_vix for v in vix)
    return Thresholds(cuts, float(np.median(ers)), len({s.session for s in train}), n_ext)


def assign(s: SessionState, th: Thresholds) -> dict[str, tuple[str, datetime]]:
    """axis -> (value, available_at); available_at <= s.ts always."""
    if s.vix is None or s.vix_available_at is None:
        vol = ("UNKNOWN", s.ts)
    else:
        vol = (
            VOL[int(np.searchsorted(np.asarray(th.vix_cuts), s.vix, side="right"))],
            s.vix_available_at,
        )
    if s.er is None or s.er_available_at is None:
        trend = ("UNKNOWN", s.ts)
    else:
        trend = ("TREND" if s.er > th.er_median else "CHOP", s.er_available_at)
    event = (
        ("MACRO", s.macro_available_at) if s.macro and s.macro_available_at else ("NORMAL", s.ts)
    )
    return {"volatility": vol, "trend": trend, "event": event}
