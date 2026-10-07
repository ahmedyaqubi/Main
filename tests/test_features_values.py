"""Exact expected value for every f1 feature on the synthetic session (M5 criterion 4).

Expected numbers are computed here with plain arithmetic from the fixture's definitions,
independently of the feature code. T = 11:00 ET on D: RTH bars 09:30..10:59 (i = 0..89) are
complete; the 11:00 bar is not.
"""

from __future__ import annotations

import math
import statistics
from itertools import pairwise

import pytest

from feature_fixtures import (
    CAL,
    CALL,
    CFG,
    PUT,
    SPOT_ASK,
    SPOT_BID,
    D,
    cross_close,
    et,
    qqq_close,
    qqq_open,
    tables,
)
from qqq1dte.core.pit import AsOfReader
from qqq1dte.features.engine import FEATURE_NAMES, Ctx, compute_at

T = et(D, 11, 0)
P_T = qqq_close(89)  # 101.90
PREV_CLOSE, PREV_HIGH, PREV_LOW = 100.5, 101.0, 99.0


@pytest.fixture(scope="module")
def feats() -> dict[str, float | None]:
    out = compute_at(AsOfReader(tables(), T), Ctx(T=T, session=D, cal=CAL, cfg=CFG))
    return {name: fv.value for name, fv in out.items()}


def test_registry_has_28_features_in_documented_order(feats: dict[str, float | None]) -> None:
    assert len(FEATURE_NAMES) == 28
    assert list(feats) == FEATURE_NAMES


def test_price_structure(feats: dict[str, float | None]) -> None:
    typical = [(2 * qqq_close(i) + qqq_open(i)) / 3 for i in range(90)]  # (H+L+C)/3, H-L cancel
    vwap = sum(typical) / 90  # equal volume weights
    assert feats["vwap_dist"] == pytest.approx((P_T - vwap) / vwap)
    assert feats["ret_since_prev_close"] == pytest.approx(P_T / PREV_CLOSE - 1)
    assert feats["dist_prev_high"] == pytest.approx((P_T - PREV_HIGH) / PREV_HIGH)
    assert feats["dist_prev_low"] == pytest.approx((P_T - PREV_LOW) / PREV_LOW)
    or_high = max(qqq_close(i) + 0.02 for i in range(15))
    or_low = min(qqq_open(i) - 0.02 for i in range(15))
    assert feats["or_position"] == pytest.approx((P_T - or_low) / (or_high - or_low))
    assert feats["overnight_gap"] == pytest.approx(qqq_open(0) / PREV_CLOSE - 1)
    day_high = max(qqq_close(i) + 0.02 for i in range(90))
    day_low = min(qqq_open(i) - 0.02 for i in range(90))
    atr = 2.0  # prior sessions: TR = max(101 - 99, |101 - 100.5|, |99 - 100.5|) = 2
    assert feats["range_atr"] == pytest.approx((day_high - day_low) / atr)


def test_momentum(feats: dict[str, float | None]) -> None:
    # ref(T - k) = close of the last bar complete by T - k: label T - k - 1 minute.
    def ref(minutes_after_open: int) -> float:
        return qqq_close(minutes_after_open - 1)

    for k, idx in ((5, 85), (15, 75), (30, 60), (60, 30)):
        assert feats[f"ret_{k}m"] == pytest.approx(math.log(P_T / ref(idx))), k
    ret15_now = math.log(P_T / ref(75))
    ret15_prev = math.log(ref(75) / ref(60))
    assert feats["mom_accel"] == pytest.approx(ret15_now - ret15_prev)
    closes = [qqq_close(i) for i in range(59, 90)]  # 31 closes -> 30 returns
    rets = [math.log(b / a) for a, b in pairwise(closes)]
    assert feats["rv_30m"] == pytest.approx(statistics.stdev(rets) * math.sqrt(252 * 390))


def test_volume(feats: dict[str, float | None]) -> None:
    # today 90 bars x 200; each prior session 90 bars x 100 at the same minute
    assert feats["rel_volume"] == pytest.approx(2.0)


def test_cross_market(feats: dict[str, float | None]) -> None:
    def r(sym: str, k: int) -> float:
        return math.log(cross_close(sym, 89) / cross_close(sym, 89 - k))

    assert feats["spy_qqq_rel_15m"] == pytest.approx(r("SPY", 15) - math.log(P_T / qqq_close(74)))
    assert feats["soxx_ret_15m"] == pytest.approx(r("SOXX", 15))
    mega = [r(s, 15) for s in ("NVDA", "AMD", "AVGO", "TSM")]
    assert feats["megacap_ret_15m"] == pytest.approx(sum(mega) / 4)
    assert feats["uup_ret_60m"] == pytest.approx(r("UUP", 60))
    assert feats["ief_ret_60m"] == pytest.approx(r("IEF", 60))
    assert feats["shy_ret_60m"] == pytest.approx(r("SHY", 60))
    assert feats["vix_prev_close"] == pytest.approx(15.5)  # D's 99.0 is published after 18:00


def test_options(feats: dict[str, float | None]) -> None:
    spot = (SPOT_BID + SPOT_ASK) / 2  # 101.90 -> call 102 (first >=), put 101 (last <=)
    call_mid, put_mid = 0.51, 0.41
    assert CALL.endswith("C00102000") and PUT.endswith("P00101000")
    assert feats["straddle_move"] == pytest.approx((call_mid + put_mid) / spot)
    assert feats["atm_spread_pct"] == pytest.approx((0.02 / call_mid + 0.02 / put_mid) / 2)
    assert feats["put_call_imbalance"] == pytest.approx((put_mid - call_mid) / (put_mid + call_mid))


def test_time_and_events(feats: dict[str, float | None]) -> None:
    assert feats["minutes_since_open"] == 90
    assert feats["day_of_week"] == 1  # Tuesday
    assert feats["cal_days_to_expiry"] == 1
    assert feats["macro_event_today"] == 1  # CPI at 08:30 on D


def test_missing_values_are_null_with_reason() -> None:
    t = et(D, 9, 45)
    out = compute_at(AsOfReader(tables(), t), Ctx(T=t, session=D, cal=CAL, cfg=CFG))
    assert out["ret_15m"].value is not None  # 09:30 reference = the open
    for name in ("ret_30m", "ret_60m", "mom_accel", "rv_30m", "uup_ret_60m"):
        assert out[name].value is None, name
        assert out[name].missing_reason == "window_before_open", name


def test_cross_market_prices_come_from_quotes_not_bars() -> None:
    """f2 (ADR-0004 amendment): cross-market features read NBBO mids; no bar table needed."""
    tbl = tables()
    assert "cross_bars" not in tbl
    out = compute_at(AsOfReader(tbl, T), Ctx(T=T, session=D, cal=CAL, cfg=CFG))
    assert out["soxx_ret_15m"].available_at == T  # quote stamped 11:00 (interval end)


def test_invalid_or_stale_latest_cross_quote_gives_missing_not_fallback() -> None:
    import polars as pl  # noqa: PLC0415

    tbl = tables()
    q = tbl["cross_quotes"]
    one_sided = q.with_columns(
        bid=pl.when((pl.col("symbol") == "SOXX") & (pl.col("ts") == T))
        .then(None).otherwise(pl.col("bid"))
    )  # fmt: skip
    out = compute_at(AsOfReader({**tbl, "cross_quotes": one_sided}, T),
                     Ctx(T=T, session=D, cal=CAL, cfg=CFG))  # fmt: skip
    assert out["soxx_ret_15m"].value is None
    assert out["soxx_ret_15m"].missing_reason == "no_valid_quote"
    gap = q.filter(~((pl.col("symbol") == "SOXX") & (pl.col("ts") > et(D, 10, 58))
                     & (pl.col("ts") <= T)))  # fmt: skip
    out = compute_at(AsOfReader({**tbl, "cross_quotes": gap}, T),
                     Ctx(T=T, session=D, cal=CAL, cfg=CFG))  # fmt: skip
    assert out["soxx_ret_15m"].missing_reason == "no_valid_quote"  # newest quote 2 min old
