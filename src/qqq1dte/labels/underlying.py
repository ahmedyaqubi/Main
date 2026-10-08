"""Underlying labels A (direction), B (magnitude touch), D (stop before target), spec §3.

P_T comes from bars available at T (AsOfReader). The window W = (T, T_end] comes from a
ForwardWindowReader: bars whose whole interval lies inside W, i.e. labels T .. T_end - 1 min
(available T + 1 min .. T_end). Missing bars in W -> INVALID (never interpolated).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import polars as pl

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config
from qqq1dte.core.pit import AsOfReader, ForwardWindowReader
from qqq1dte.features.inputs import qqq_reference
from qqq1dte.labels.common import INVALID, UNRESOLVED, LabelRow, label_t_end

STOP_FIRST, TARGET_FIRST = "STOP_FIRST", "TARGET_FIRST"
POSITIVE, NEGATIVE = "POSITIVE", "NEGATIVE"
NO_REFERENCE_PRICE, MISSING_BAR = "NO_REFERENCE_PRICE", "MISSING_BAR"


def _variant(m: float) -> str:
    return f"m={m:g}"


def _ids(cfg: Phase1Config) -> list[tuple[str, str]]:
    ids = [("A_up", ""), ("A_dn", "")]
    for m in cfg.labels.magnitude.thresholds:
        ids += [("B_up", _variant(m)), ("B_dn", _variant(m))]
    return [*ids, ("D_call", ""), ("D_put", "")]


def _binary(label_id: str, variant: str, hit: bool, t_end: datetime) -> LabelRow:
    return LabelRow(label_id, variant, int(hit), POSITIVE if hit else NEGATIVE, t_end)


def _risk(
    label_id: str, w: pl.DataFrame, stop_hit: pl.Expr, target_hit: pl.Expr, t_end: datetime
) -> LabelRow:
    """First bar touching stop or target; both in one bar -> stop first (conservative)."""
    flags = w.select(s=stop_hit, t=target_hit)
    for s, t in flags.iter_rows():
        if s:
            return LabelRow(label_id, "", 1, STOP_FIRST, t_end, ambiguous_bar=bool(t))
        if t:
            return LabelRow(label_id, "", 0, TARGET_FIRST, t_end)
    return LabelRow(label_id, "", None, UNRESOLVED, t_end)


def _window(
    bars: pl.DataFrame, session: date, t: datetime, t_end: datetime, cal: TradingCalendar
) -> tuple[float | None, pl.DataFrame, str | None]:
    """P_T from bars known at t, the bars of W = (t, t_end], and a missing reason (if any)."""
    p_t, _ = qqq_reference(AsOfReader({"bars": bars}, t).get("bars"), t, cal, session)
    if p_t is None:
        return None, bars.clear(), NO_REFERENCE_PRICE
    w = (
        ForwardWindowReader({"bars": bars}, start=t, end=t_end)
        .get("bars")
        .filter((pl.col("session_date") == session) & pl.col("is_rth"))
        .filter(pl.col("ts") >= t)  # interval [ts, ts + 1m) entirely inside (t, t_end]
        .sort("ts")
    )
    expected = int((t_end - t) / timedelta(minutes=1))
    if w.height != expected:
        return p_t, w, MISSING_BAR
    return p_t, w, None


def underlying_move(
    bars: pl.DataFrame,
    session: date,
    t: datetime,
    cal: TradingCalendar,
    cfg: Phase1Config,
    horizon_minutes: int,
) -> tuple[float | None, datetime, str | None]:
    """(last close in W / P_T - 1, T_end, missing reason) for a study horizon (ADR-0012); the
    A-label direction at h is this move against the deadband."""
    t_end = label_t_end(t, session, cal, cfg, horizon_minutes)
    p_t, w, why = _window(bars, session, t, t_end, cal)
    if why is not None or p_t is None:
        return None, t_end, why
    return float(w["close"][-1]) / p_t - 1, t_end, None


def und_bracket(
    bars: pl.DataFrame,
    session: date,
    t: datetime,
    t_end: datetime,
    cal: TradingCalendar,
    side: str,
    stop: float,
    target: float,
) -> tuple[str | None, datetime | None, bool, str | None]:
    """ADR-0012 T2 exit trigger on QQQ bars: (STOP_FIRST / TARGET_FIRST / None, time the
    triggering bar is known, ambiguous bar, missing reason). Both in one bar -> stop first."""
    p_t, w, why = _window(bars, session, t, t_end, cal)
    if why is not None or p_t is None:
        return None, None, False, why
    if side == "C":
        s_hit, t_hit = pl.col("low") <= p_t * (1 - stop), pl.col("high") >= p_t * (1 + target)
    else:
        s_hit, t_hit = pl.col("high") >= p_t * (1 + stop), pl.col("low") <= p_t * (1 - target)
    for s, tg, at in w.select(s_hit, t_hit, "available_at").iter_rows():
        if s:
            return STOP_FIRST, at, bool(tg), None
        if tg:
            return TARGET_FIRST, at, False, None
    return None, None, False, None


def underlying_labels(
    bars: pl.DataFrame, session: date, t: datetime, cal: TradingCalendar, cfg: Phase1Config
) -> list[LabelRow]:
    """A_up/A_dn, B_up/B_dn per magnitude threshold, D_call/D_put at prediction time t."""
    t_end = label_t_end(t, session, cal, cfg)
    lab = cfg.labels
    p_t, w, why = _window(bars, session, t, t_end, cal)
    if why is not None or p_t is None:
        return [LabelRow(i, v, None, INVALID, t_end, reason=why) for i, v in _ids(cfg)]
    d = lab.direction.deadband
    last = float(w["close"][-1])
    out = [
        _binary("A_up", "", last > p_t * (1 + d), t_end),
        _binary("A_dn", "", last < p_t * (1 - d), t_end),
    ]
    hi, lo = float(w["high"].max()), float(w["low"].min())  # type: ignore[arg-type]
    for m in lab.magnitude.thresholds:
        out += [
            _binary("B_up", _variant(m), hi >= p_t * (1 + m), t_end),
            _binary("B_dn", _variant(m), lo <= p_t * (1 - m), t_end),
        ]
    m0, s = lab.risk.target, lab.risk.stop  # ADR-0007: D has its own target
    out.append(
        _risk("D_call", w, pl.col("low") <= p_t * (1 - s), pl.col("high") >= p_t * (1 + m0), t_end)
    )
    out.append(
        _risk("D_put", w, pl.col("high") >= p_t * (1 + s), pl.col("low") <= p_t * (1 - m0), t_end)
    )
    return out
