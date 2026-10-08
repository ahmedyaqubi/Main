"""f3 extra features (M19R Stage 2, E1): option quote dynamics, size imbalances and QQQ NBBO
imbalance. Exact values on a synthetic fixture, point-in-time invariance, missing reasons.

Fixture: D = 2025-03-11, T = 11:00 ET. QQQ NBBO 500.39 / 500.41 (sizes 30 / 10) every minute ->
spot 500.40 -> call 501, put 500 (D+1). Option quotes every minute from 10:00: call mid
1.00 + 0.01 m, put mid 2.00 - 0.01 m (m = minutes after 10:00), spread 0.02; call sizes
20 bid / 5 ask, put sizes 5 / 15.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, time, timedelta

import polars as pl
import pytest

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import ET
from qqq1dte.features.defs import NO_VALID_QUOTE
from qqq1dte.features.defs_f3 import registry_f3_extra
from qqq1dte.features.engine import compute_session

CFG = load_config()
CAL = TradingCalendar(CFG)
D, NEXT = date(2025, 3, 11), date(2025, 3, 12)
CALL, PUT = "QQQ   250312C00501000", "QQQ   250312P00500000"
DT = pl.Datetime("ns", "UTC")


def et(hh: int, mm: int) -> datetime:
    return datetime.combine(D, time(hh, mm), tzinfo=ET).astimezone(UTC)


T = et(11, 0)


def und(scale: float = 1.0) -> pl.DataFrame:
    rows = [
        {
            "available_at": et(9, 31) + timedelta(minutes=k),
            "bid": 500.39,
            "ask": 500.41,
            "bid_sz": 30,
            "ask_sz": 10,
        }
        for k in range(390)
    ]
    df = pl.DataFrame(
        rows,
        schema={
            "available_at": DT,
            "bid": pl.Float64,
            "ask": pl.Float64,
            "bid_sz": pl.Int64,
            "ask_sz": pl.Int64,
        },
    )
    return df.with_columns(
        pl.when(pl.col("available_at") > T)
        .then(pl.col("bid") * scale)
        .otherwise(pl.col("bid"))
        .alias("bid"),
        pl.when(pl.col("available_at") > T)
        .then(pl.col("ask") * scale)
        .otherwise(pl.col("ask"))
        .alias("ask"),
    )


def chain() -> pl.DataFrame:
    rows = [
        {
            "session_date": D,
            "raw_symbol": f"QQQ   250312{r}{k * 1000:08d}",
            "expiration": NEXT,
            "strike": float(k),
            "right": r,
            "available_at": et(6, 30),
        }
        for k in (499, 500, 501, 502)
        for r in "CP"
    ]
    return pl.DataFrame(
        rows,
        schema={
            "session_date": pl.Date,
            "raw_symbol": pl.String,
            "expiration": pl.Date,
            "strike": pl.Float64,
            "right": pl.String,
            "available_at": DT,
        },
    )


def options(skip: set[int] | None = None, scale_after_t: float = 1.0) -> pl.DataFrame:
    rows = []
    for m in range(0, 360):
        if skip and m in skip:
            continue
        ts = et(10, 0) + timedelta(minutes=m)
        f = scale_after_t if ts > T else 1.0
        for sym, raw_mid, bsz, asz in (
            (CALL, 1.00 + 0.01 * m, 20, 5),
            (PUT, 2.00 - 0.01 * m, 5, 15),
        ):
            mid = max(raw_mid, 0.05) * f
            rows.append(
                {
                    "symbol": sym,
                    "available_at": ts,
                    "bid": mid - 0.01,
                    "ask": mid + 0.01,
                    "bid_sz": bsz,
                    "ask_sz": asz,
                    "valid": True,
                }
            )
    return pl.DataFrame(
        rows,
        schema={
            "symbol": pl.String,
            "available_at": DT,
            "bid": pl.Float64,
            "ask": pl.Float64,
            "bid_sz": pl.Int64,
            "ask_sz": pl.Int64,
            "valid": pl.Boolean,
        },
    )


def compute(
    tables: dict[str, pl.DataFrame],
) -> dict[str, tuple[float | None, str | None, datetime | None]]:
    df = compute_session(tables, D, CAL, CFG, timestamps=[T], features=registry_f3_extra(CFG))
    return {
        r["feature_name"]: (r["value"], r["missing_reason"], r["available_at"])
        for r in df.to_dicts()
    }


def base() -> dict[str, pl.DataFrame]:
    return {"und_quotes": und(), "chain": chain(), "options": options()}


def test_values_hand_computed() -> None:
    v = compute(base())
    assert v["opt_call_mom_5m"][0] == pytest.approx(math.log(1.60 / 1.55))
    assert v["opt_call_mom_15m"][0] == pytest.approx(math.log(1.60 / 1.45))
    assert v["opt_put_mom_5m"][0] == pytest.approx(math.log(1.40 / 1.45))
    assert v["opt_put_mom_15m"][0] == pytest.approx(math.log(1.40 / 1.55))
    imb_t, imb_15 = (1.40 - 1.60) / 3.00, (1.55 - 1.45) / 3.00
    assert v["pc_imbalance_chg_15m"][0] == pytest.approx(imb_t - imb_15)
    assert v["opt_call_size_imb"][0] == pytest.approx(15 / 25)
    assert v["opt_put_size_imb"][0] == pytest.approx(-10 / 20)
    assert v["qqq_book_imb"][0] == pytest.approx(20 / 40)
    assert all(a is not None and a <= T for _, _, a in v.values())
    assert set(v) == set(CFG.features_f3.extra_features)


def test_point_in_time_invariance() -> None:
    """Changing every quote after T changes nothing at T."""
    perturbed = {
        "und_quotes": und(scale=2.0),
        "chain": chain(),
        "options": options(scale_after_t=3.0),
    }
    assert compute(perturbed) == compute(base())


def test_missing_past_quote_is_reported_not_filled() -> None:
    v = compute({**base(), "options": options(skip=set(range(42, 46)))})  # no quotes 10:42-10:45
    assert v["opt_call_mom_15m"][0] is None and v["opt_call_mom_15m"][1] == NO_VALID_QUOTE
    assert v["opt_call_mom_5m"][0] == pytest.approx(math.log(1.60 / 1.55))  # unaffected
