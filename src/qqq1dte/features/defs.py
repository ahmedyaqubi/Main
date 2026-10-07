"""feature_version f1: the 28 features of docs/FEATURES.md.

Every function receives only an `AsOfReader` (data with available_at <= T) and a `Ctx`, and
returns a `FeatureValue` whose available_at is the latest available_at among the rows it used.
Missing inputs give value None plus a reason. Nothing is filled or imputed here.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import Any

import polars as pl

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config
from qqq1dte.core.pit import AsOfReader
from qqq1dte.features.inputs import qqq_reference, quote_reference

WINDOW_BEFORE_OPEN = "window_before_open"
INSUFFICIENT_HISTORY = "insufficient_history"
NO_VALID_QUOTE = "no_valid_quote"
NO_DATA = "no_data"
FLAT_RANGE = "flat_range"


@dataclass(frozen=True)
class Ctx:
    T: datetime
    session: date
    cal: TradingCalendar
    cfg: Phase1Config


@dataclass(frozen=True)
class FeatureValue:
    value: float | None
    available_at: datetime | None
    missing_reason: str | None = None


def _missing(reason: str) -> FeatureValue:
    return FeatureValue(None, None, reason)


def _latest(*stamps: datetime | None) -> datetime | None:
    present = [s for s in stamps if s is not None]
    return max(present) if present else None


FeatureFn = Callable[[AsOfReader, Ctx], FeatureValue]


def _col_max(df: pl.DataFrame, col: str = "available_at") -> datetime | None:
    v = df[col].max() if df.height else None
    return v if isinstance(v, datetime) else None


def _num(v: object) -> float:
    if not isinstance(v, (int, float)):
        raise TypeError(f"expected a number, got {v!r}")
    return float(v)


# helpers -----------------------------------------------------------------------------------
def _today_rth(
    r: AsOfReader, ctx: Ctx, table: str = "qqq_bars", symbol: str | None = None
) -> pl.DataFrame:
    df = r.get(table).filter((pl.col("session_date") == ctx.session) & pl.col("is_rth"))
    if symbol is not None:
        df = df.filter(pl.col("symbol") == symbol)
    return df.sort("ts")


def _bars(r: AsOfReader, table: str, symbol: str | None) -> pl.DataFrame:
    df = r.get(table)
    return df.filter(pl.col("symbol") == symbol) if symbol is not None else df


def _log_return(
    r: AsOfReader, ctx: Ctx, minutes: int, table: str = "qqq_bars", symbol: str | None = None
) -> FeatureValue:
    bars = _bars(r, table, symbol)
    now, a1 = qqq_reference(bars, ctx.T, ctx.cal, ctx.session)
    then, a0 = qqq_reference(bars, ctx.T - timedelta(minutes=minutes), ctx.cal, ctx.session)
    if then is None:
        return _missing(WINDOW_BEFORE_OPEN)
    if now is None:
        return _missing(NO_DATA)
    return FeatureValue(math.log(now / then), _latest(a0, a1))


def _quote_log_return(r: AsOfReader, ctx: Ctx, minutes: int, symbol: str) -> FeatureValue:
    """ln(mid at T / mid at T - k) from cross-market NBBO (f2)."""
    q = r.get("cross_quotes").filter(pl.col("symbol") == symbol)
    age = ctx.cfg.liquidity.max_quote_age_s
    then, a0, why0 = quote_reference(
        q, ctx.T - timedelta(minutes=minutes), ctx.cal, ctx.session, age
    )
    now, a1, why1 = quote_reference(q, ctx.T, ctx.cal, ctx.session, age)
    if then is None:
        return _missing(why0 or NO_VALID_QUOTE)
    if now is None:
        return _missing(why1 or NO_VALID_QUOTE)
    return FeatureValue(math.log(now / then), _latest(a0, a1))


def _prev_day(r: AsOfReader, ctx: Ctx) -> dict[str, Any] | None:
    daily = r.get("daily").filter(pl.col("session_date") < ctx.session).sort("session_date")
    return daily.row(-1, named=True) if daily.height else None


# price structure ---------------------------------------------------------------------------
def vwap_dist(r: AsOfReader, ctx: Ctx) -> FeatureValue:
    rth = _today_rth(r, ctx)
    if not rth.height:
        return _missing(NO_DATA)
    tp = (rth["high"] + rth["low"] + rth["close"]) / 3
    vol = rth["volume"].cast(pl.Float64)
    if float(vol.sum()) <= 0:
        return _missing(NO_DATA)
    vwap = float((tp * vol).sum()) / float(vol.sum())
    p, a = qqq_reference(r.get("qqq_bars"), ctx.T, ctx.cal, ctx.session)
    if p is None:
        return _missing(NO_DATA)
    return FeatureValue((p - vwap) / vwap, _latest(a, _col_max(rth)))


def _vs_prev(field: str) -> FeatureFn:
    def fn(r: AsOfReader, ctx: Ctx) -> FeatureValue:
        prev = _prev_day(r, ctx)
        p, a = qqq_reference(r.get("qqq_bars"), ctx.T, ctx.cal, ctx.session)
        if prev is None:
            return _missing(INSUFFICIENT_HISTORY)
        if p is None:
            return _missing(NO_DATA)
        ref = float(prev[field])
        return FeatureValue(p / ref - 1, _latest(a, prev["available_at"]))

    return fn


def or_position(r: AsOfReader, ctx: Ctx) -> FeatureValue:
    n = ctx.cfg.features.opening_range_minutes
    open_, _ = ctx.cal.open_close(ctx.session)
    rth = _today_rth(r, ctx).filter(pl.col("ts") < open_ + timedelta(minutes=n))
    if rth.height < n:
        return _missing(WINDOW_BEFORE_OPEN)
    hi, lo = _num(rth["high"].max()), _num(rth["low"].min())
    if hi == lo:
        return _missing(FLAT_RANGE)
    p, a = qqq_reference(r.get("qqq_bars"), ctx.T, ctx.cal, ctx.session)
    if p is None:
        return _missing(NO_DATA)
    return FeatureValue((p - lo) / (hi - lo), _latest(a, _col_max(rth)))


def overnight_gap(r: AsOfReader, ctx: Ctx) -> FeatureValue:
    rth, prev = _today_rth(r, ctx), _prev_day(r, ctx)
    if prev is None:
        return _missing(INSUFFICIENT_HISTORY)
    if not rth.height:
        return _missing(NO_DATA)
    first = rth.row(0, named=True)
    return FeatureValue(
        _num(first["open"]) / _num(prev["close"]) - 1,
        _latest(first["available_at"], prev["available_at"]),
    )


def range_atr(r: AsOfReader, ctx: Ctx) -> FeatureValue:
    n = ctx.cfg.features.atr_sessions
    daily = r.get("daily").filter(pl.col("session_date") < ctx.session).sort("session_date")
    if daily.height < n + 1:
        return _missing(INSUFFICIENT_HISTORY)
    last = daily.tail(n + 1)
    h, lo, c = last["high"].to_list(), last["low"].to_list(), last["close"].to_list()
    trs = [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, n + 1)]
    atr = sum(trs) / n
    rth = _today_rth(r, ctx)
    if not rth.height or atr <= 0:
        return _missing(NO_DATA)
    rng = _num(rth["high"].max()) - _num(rth["low"].min())
    return FeatureValue(rng / atr, _latest(_col_max(rth), _col_max(last)))


# momentum ----------------------------------------------------------------------------------
def _ret(minutes: int) -> FeatureFn:
    return lambda r, ctx: _log_return(r, ctx, minutes)


def mom_accel(r: AsOfReader, ctx: Ctx) -> FeatureValue:
    k = ctx.cfg.features.cross_short_minutes
    bars = r.get("qqq_bars")
    p0, a0 = qqq_reference(bars, ctx.T, ctx.cal, ctx.session)
    p1, a1 = qqq_reference(bars, ctx.T - timedelta(minutes=k), ctx.cal, ctx.session)
    p2, a2 = qqq_reference(bars, ctx.T - timedelta(minutes=2 * k), ctx.cal, ctx.session)
    if p2 is None or p1 is None:
        return _missing(WINDOW_BEFORE_OPEN)
    if p0 is None:
        return _missing(NO_DATA)
    return FeatureValue(math.log(p0 / p1) - math.log(p1 / p2), _latest(a0, a1, a2))


def rv_30m(r: AsOfReader, ctx: Ctx) -> FeatureValue:
    n = ctx.cfg.features.rv_minutes
    rth = _today_rth(r, ctx)
    if rth.height < n + 1:
        return _missing(WINDOW_BEFORE_OPEN)
    closes = rth["close"].tail(n + 1).to_list()
    rets = [math.log(b / a) for a, b in pairwise(closes)]
    vol = statistics.stdev(rets) * math.sqrt(ctx.cfg.features.annualization_minutes)
    return FeatureValue(vol, _col_max(rth))


# volume --------------------------------------------------------------------------------------
def rel_volume(r: AsOfReader, ctx: Ctx) -> FeatureValue:
    f = ctx.cfg.features
    rth = _today_rth(r, ctx)
    m = rth.height
    if m == 0:
        return _missing(NO_DATA)
    prof = (
        r.get("profile")
        .filter((pl.col("session_date") < ctx.session) & (pl.col("minute") == m))
        .sort("session_date")
        .tail(f.rel_volume_sessions)
    )
    if prof.height < f.rel_volume_min_sessions:
        return _missing(INSUFFICIENT_HISTORY)
    base = _num(prof["cum_volume"].median())
    if base <= 0:
        return _missing(NO_DATA)
    today = float(rth["volume"].sum())
    return FeatureValue(today / base, _latest(_col_max(rth), _col_max(prof)))


# cross-market ----------------------------------------------------------------------------------
def _cross_ret(symbol: str, minutes_attr: str) -> FeatureFn:
    def fn(r: AsOfReader, ctx: Ctx) -> FeatureValue:
        return _quote_log_return(r, ctx, getattr(ctx.cfg.features, minutes_attr), symbol)

    return fn


def spy_qqq_rel_15m(r: AsOfReader, ctx: Ctx) -> FeatureValue:
    k = ctx.cfg.features.cross_short_minutes
    spy, qqq = _quote_log_return(r, ctx, k, "SPY"), _log_return(r, ctx, k)
    if spy.value is None or qqq.value is None:
        return _missing(spy.missing_reason or qqq.missing_reason or NO_DATA)
    return FeatureValue(spy.value - qqq.value, _latest(spy.available_at, qqq.available_at))


def megacap_ret_15m(r: AsOfReader, ctx: Ctx) -> FeatureValue:
    f = ctx.cfg.features
    vals = [_quote_log_return(r, ctx, f.cross_short_minutes, s) for s in f.megacap_symbols]
    got = [v for v in vals if v.value is not None]
    if len(got) < f.megacap_min_symbols:
        reasons = {v.missing_reason for v in vals if v.value is None}
        return _missing(WINDOW_BEFORE_OPEN if WINDOW_BEFORE_OPEN in reasons else NO_DATA)
    rets = [v.value for v in got if v.value is not None]
    return FeatureValue(sum(rets) / len(rets), _latest(*(v.available_at for v in got)))


def vix_prev_close(r: AsOfReader, ctx: Ctx) -> FeatureValue:
    vix = r.get("vix").filter(pl.col("date") < ctx.session).sort("date")
    if not vix.height:
        return _missing(INSUFFICIENT_HISTORY)
    row = vix.row(-1, named=True)
    return FeatureValue(float(row["close"]), row["available_at"])


# options ---------------------------------------------------------------------------------------
def _frozen_rule_quotes(r: AsOfReader, ctx: Ctx) -> tuple[dict[str, Any] | None, str | None]:
    """Spec §5 contracts at T from point-in-time data: spot = latest valid QQQ NBBO mid (age-
    limited); call = lowest D+1 strike >= spot, put = highest D+1 strike <= spot; each quote =
    the latest record for the contract, which must be valid and fresh."""
    max_age = timedelta(seconds=ctx.cfg.liquidity.max_quote_age_s)
    und = (
        r.get("und_quotes")
        .filter(
            pl.col("bid").is_not_null()
            & pl.col("ask").is_not_null()
            & (pl.col("bid") > 0)
            & (pl.col("bid") <= pl.col("ask"))
        )
        .sort("available_at")
    )
    if not und.height:
        return None, NO_DATA
    u = und.row(-1, named=True)
    if ctx.T - u["available_at"] > max_age:
        return None, NO_VALID_QUOTE
    spot = (u["bid"] + u["ask"]) / 2
    nxt = ctx.cal.next_session(ctx.session)
    chain = r.get("chain").filter(
        (pl.col("session_date") == ctx.session) & (pl.col("expiration") == nxt)
    )
    calls = chain.filter((pl.col("right") == "C") & (pl.col("strike") >= spot)).sort("strike")
    puts = chain.filter((pl.col("right") == "P") & (pl.col("strike") <= spot)).sort("strike")
    if not calls.height or not puts.height:
        return None, NO_DATA
    call, put = calls.row(0, named=True), puts.row(-1, named=True)
    quotes = {}
    for side, contract in (("call", call), ("put", put)):
        q = r.get("options").filter(pl.col("symbol") == contract["raw_symbol"]).sort("available_at")
        if not q.height:
            return None, NO_VALID_QUOTE
        last = q.row(-1, named=True)
        if not last["valid"] or ctx.T - last["available_at"] > max_age:
            return None, NO_VALID_QUOTE
        quotes[side] = last
    return {
        "spot": spot,
        "call_mid": (quotes["call"]["bid"] + quotes["call"]["ask"]) / 2,
        "put_mid": (quotes["put"]["bid"] + quotes["put"]["ask"]) / 2,
        "call_spread": quotes["call"]["ask"] - quotes["call"]["bid"],
        "put_spread": quotes["put"]["ask"] - quotes["put"]["bid"],
        "available_at": _latest(
            u["available_at"],
            call["available_at"],
            put["available_at"],
            quotes["call"]["available_at"],
            quotes["put"]["available_at"],
        ),
    }, None


def _option_feature(fn: Callable[[dict[str, Any]], float]) -> FeatureFn:
    def feature(r: AsOfReader, ctx: Ctx) -> FeatureValue:
        q, reason = _frozen_rule_quotes(r, ctx)
        if q is None:
            return _missing(reason or NO_DATA)
        return FeatureValue(fn(q), q["available_at"])

    return feature


straddle_move = _option_feature(lambda q: (q["call_mid"] + q["put_mid"]) / q["spot"])
atm_spread_pct = _option_feature(
    lambda q: (q["call_spread"] / q["call_mid"] + q["put_spread"] / q["put_mid"]) / 2
)
put_call_imbalance = _option_feature(
    lambda q: (q["put_mid"] - q["call_mid"]) / (q["put_mid"] + q["call_mid"])
)


# time / events -----------------------------------------------------------------------------------
def minutes_since_open(r: AsOfReader, ctx: Ctx) -> FeatureValue:
    open_, _ = ctx.cal.open_close(ctx.session)
    return FeatureValue((ctx.T - open_).total_seconds() / 60, ctx.T)


def day_of_week(r: AsOfReader, ctx: Ctx) -> FeatureValue:
    return FeatureValue(float(ctx.session.weekday()), ctx.T)


def cal_days_to_expiry(r: AsOfReader, ctx: Ctx) -> FeatureValue:
    return FeatureValue(float((ctx.cal.next_session(ctx.session) - ctx.session).days), ctx.T)


def macro_event_today(r: AsOfReader, ctx: Ctx) -> FeatureValue:
    ev = r.get("macro").filter(pl.col("session_date") == ctx.session)
    if not ev.height:
        return FeatureValue(0.0, ctx.T)
    return FeatureValue(1.0, _col_max(ev))


def registry(cfg: Phase1Config) -> dict[str, FeatureFn]:
    """Ordered f1 feature set (docs/FEATURES.md)."""
    f = cfg.features
    reg: dict[str, FeatureFn] = {
        "vwap_dist": vwap_dist,
        "ret_since_prev_close": _vs_prev("close"),
        "dist_prev_high": _vs_prev("high"),
        "dist_prev_low": _vs_prev("low"),
        "or_position": or_position,
        "overnight_gap": overnight_gap,
        "range_atr": range_atr,
    }
    for k in f.momentum_minutes:
        reg[f"ret_{k}m"] = _ret(k)
    reg |= {
        "mom_accel": mom_accel,
        f"rv_{f.rv_minutes}m": rv_30m,
        "rel_volume": rel_volume,
        f"spy_qqq_rel_{f.cross_short_minutes}m": spy_qqq_rel_15m,
        f"soxx_ret_{f.cross_short_minutes}m": _cross_ret("SOXX", "cross_short_minutes"),
        f"megacap_ret_{f.cross_short_minutes}m": megacap_ret_15m,
        f"uup_ret_{f.cross_long_minutes}m": _cross_ret("UUP", "cross_long_minutes"),
        f"ief_ret_{f.cross_long_minutes}m": _cross_ret("IEF", "cross_long_minutes"),
        f"shy_ret_{f.cross_long_minutes}m": _cross_ret("SHY", "cross_long_minutes"),
        "vix_prev_close": vix_prev_close,
        "straddle_move": straddle_move,
        "atm_spread_pct": atm_spread_pct,
        "put_call_imbalance": put_call_imbalance,
        "minutes_since_open": minutes_since_open,
        "day_of_week": day_of_week,
        "cal_days_to_expiry": cal_days_to_expiry,
        "macro_event_today": macro_event_today,
    }
    return reg
