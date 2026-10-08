"""f3 extra features (M19R Stage 2, E1): direction-oriented option and order-book information,
computed point-in-time through the AsOfReader at T and stored next to the f2 snapshots.

At T the frozen-rule contracts are found as in f2 (spot = latest fresh QQQ NBBO mid; call =
lowest D+1 strike >= spot, put = highest D+1 strike <= spot). Then:
- opt_{call,put}_mom_{k}m = log(mid at T / mid at T - k) of that same contract;
- pc_imbalance_chg_{k}m = put/call imbalance at T minus at T - k (same two contracts);
- opt_{call,put}_size_imb = (bid size - ask size) / (bid size + ask size) at T;
- qqq_book_imb = the same for the latest fresh QQQ NBBO.
A quote "at t" is the latest record with available_at <= t; it must be valid and no older than
`liquidity.max_quote_age_s` relative to t, otherwise the feature is missing (never filled).
Not built from OPRA open interest: only 5 sessions of it are on disk (M19R E1 scope note).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

import polars as pl

from qqq1dte.core.config import Phase1Config
from qqq1dte.core.pit import AsOfReader
from qqq1dte.features.defs import (
    NO_DATA,
    NO_VALID_QUOTE,
    Ctx,
    FeatureFn,
    FeatureValue,
    _latest,
    _missing,
)


def _valid(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter(
        pl.col("bid").is_not_null()
        & pl.col("ask").is_not_null()
        & (pl.col("bid") > 0)
        & (pl.col("bid") <= pl.col("ask"))
    )


def _spot_quote(r: AsOfReader, ctx: Ctx) -> dict[str, Any] | None:
    und = _valid(r.get("und_quotes")).sort("available_at")
    if not und.height:
        return None
    u = und.row(-1, named=True)
    if ctx.T - u["available_at"] > timedelta(seconds=ctx.cfg.liquidity.max_quote_age_s):
        return None
    return u


def _contracts(r: AsOfReader, ctx: Ctx) -> tuple[str, str] | str:
    """(call symbol, put symbol) at T, or a missing reason."""
    u = _spot_quote(r, ctx)
    if u is None:
        return NO_VALID_QUOTE
    spot = (u["bid"] + u["ask"]) / 2
    nxt = ctx.cal.next_session(ctx.session)
    chain = r.get("chain").filter(
        (pl.col("session_date") == ctx.session) & (pl.col("expiration") == nxt)
    )
    calls = chain.filter((pl.col("right") == "C") & (pl.col("strike") >= spot)).sort("strike")
    puts = chain.filter((pl.col("right") == "P") & (pl.col("strike") <= spot)).sort("strike")
    if not calls.height or not puts.height:
        return NO_DATA
    return calls["raw_symbol"][0], puts["raw_symbol"][-1]


def _quote_at(r: AsOfReader, ctx: Ctx, symbol: str, t: datetime) -> dict[str, Any] | None:
    q = (
        r.get("options")
        .filter((pl.col("symbol") == symbol) & (pl.col("available_at") <= t))
        .sort("available_at")
    )
    if not q.height:
        return None
    last = q.row(-1, named=True)
    if not last["valid"] or t - last["available_at"] > timedelta(
        seconds=ctx.cfg.liquidity.max_quote_age_s
    ):
        return None
    return last


def _mid(q: dict[str, Any]) -> float:
    return float((q["bid"] + q["ask"]) / 2)


def _mom(side: int, minutes: int) -> FeatureFn:
    def feature(r: AsOfReader, ctx: Ctx) -> FeatureValue:
        c = _contracts(r, ctx)
        if isinstance(c, str):
            return _missing(c)
        now = _quote_at(r, ctx, c[side], ctx.T)
        then = _quote_at(r, ctx, c[side], ctx.T - timedelta(minutes=minutes))
        if now is None or then is None:
            return _missing(NO_VALID_QUOTE)
        return FeatureValue(
            math.log(_mid(now) / _mid(then)), _latest(now["available_at"], then["available_at"])
        )

    return feature


def _imbalance(call: dict[str, Any], put: dict[str, Any]) -> float:
    cm, pm = _mid(call), _mid(put)
    return (pm - cm) / (pm + cm)


def _pc_change(minutes: int) -> FeatureFn:
    def feature(r: AsOfReader, ctx: Ctx) -> FeatureValue:
        c = _contracts(r, ctx)
        if isinstance(c, str):
            return _missing(c)
        past = ctx.T - timedelta(minutes=minutes)
        q = [
            _quote_at(r, ctx, c[0], ctx.T),
            _quote_at(r, ctx, c[1], ctx.T),
            _quote_at(r, ctx, c[0], past),
            _quote_at(r, ctx, c[1], past),
        ]
        if any(x is None for x in q):
            return _missing(NO_VALID_QUOTE)
        a, b, cc, d = (x for x in q if x is not None)
        return FeatureValue(
            _imbalance(a, b) - _imbalance(cc, d),
            _latest(*(x["available_at"] for x in (a, b, cc, d))),
        )

    return feature


def _size_imb(q: dict[str, Any]) -> float | None:
    b, a = q.get("bid_sz"), q.get("ask_sz")
    if b is None or a is None or b + a <= 0:
        return None
    return float((b - a) / (b + a))


def _opt_size(side: int) -> FeatureFn:
    def feature(r: AsOfReader, ctx: Ctx) -> FeatureValue:
        c = _contracts(r, ctx)
        if isinstance(c, str):
            return _missing(c)
        q = _quote_at(r, ctx, c[side], ctx.T)
        v = None if q is None else _size_imb(q)
        if q is None or v is None:
            return _missing(NO_VALID_QUOTE)
        return FeatureValue(v, q["available_at"])

    return feature


def qqq_book_imb(r: AsOfReader, ctx: Ctx) -> FeatureValue:
    u = _spot_quote(r, ctx)
    v = None if u is None else _size_imb(u)
    if u is None or v is None:
        return _missing(NO_VALID_QUOTE)
    return FeatureValue(v, u["available_at"])


def registry_f3_extra(cfg: Phase1Config) -> dict[str, FeatureFn]:
    f = cfg.features_f3
    reg: dict[str, FeatureFn] = {}
    for k in f.option_mom_minutes:
        reg[f"opt_call_mom_{k}m"] = _mom(0, k)
        reg[f"opt_put_mom_{k}m"] = _mom(1, k)
    reg[f"pc_imbalance_chg_{f.pc_change_minutes}m"] = _pc_change(f.pc_change_minutes)
    reg["opt_call_size_imb"] = _opt_size(0)
    reg["opt_put_size_imb"] = _opt_size(1)
    reg["qqq_book_imb"] = qqq_book_imb
    if sorted(reg) != sorted(f.extra_features):
        raise ValueError(f"features_f3.extra_features {f.extra_features} != built {list(reg)}")
    return {k: reg[k] for k in f.extra_features}
