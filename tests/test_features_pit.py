"""Point-in-time / leakage tests for the feature engine: T-LEAK-03 ... T-LEAK-09."""

from __future__ import annotations

import csv
import math
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from feature_fixtures import CAL, CFG, D, et, tables
from qqq1dte.core.pit import AsOfReader
from qqq1dte.features.engine import Ctx, compute_at, compute_session
from qqq1dte.features.inputs import daily_stats, macro_table, open_interest_table, qqq_reference
from qqq1dte.features.writer import PitViolationError, assert_pit

ROOT = Path(__file__).resolve().parents[1]
TABLES = tables()


def values_at(tbls: dict[str, pl.DataFrame], t) -> list[float | None]:  # type: ignore[no-untyped-def]
    out = compute_at(AsOfReader(tbls, t), Ctx(T=t, session=D, cal=CAL, cfg=CFG))
    return [fv.value for fv in out.values()]


def perturb_after(tbls: dict[str, pl.DataFrame], t, factor: float) -> dict[str, pl.DataFrame]:  # type: ignore[no-untyped-def]
    """Scale every numeric value in every row that becomes available after t."""
    out = {}
    for name, df in tbls.items():
        num = [c for c, dt in df.schema.items() if dt.is_numeric()]
        future = pl.col("available_at") > t
        out[name] = df.with_columns(
            [pl.when(future).then(pl.col(c) * factor + 1).otherwise(pl.col(c)).alias(c)
             for c in num]
        )  # fmt: skip
    return out


def same(a: list[float | None], b: list[float | None]) -> bool:
    return all(
        (x is None and y is None)
        or (x is not None and y is not None and x == y)
        or (x is not None and y is not None and math.isnan(x) and math.isnan(y))
        for x, y in zip(a, b, strict=True)
    )


# T-LEAK-05: >= 1,000 random T, future rows mutated -> features bit-identical ----------------
@settings(max_examples=1000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    seconds=st.integers(min_value=15 * 60, max_value=int(6.5 * 3600) - 1),
    factor=st.sampled_from([-3.0, 0.0, 0.5, 7.0]),
)
def test_leak_05_future_perturbation_invariance(seconds: int, factor: float) -> None:
    t = et(D, 9, 30) + timedelta(seconds=seconds)
    assert same(values_at(TABLES, t), values_at(perturb_after(TABLES, t, factor), t))


# T-LEAK-04: planted future canary -------------------------------------------------------------
def test_leak_04_planted_future_canary() -> None:
    """The bar labelled T (complete at T + 1 min) encodes the 'answer': set its close to an
    absurd value. Nothing computed at T may change."""
    t = et(D, 11, 0)
    bars = TABLES["qqq_bars"]
    planted = bars.with_columns(
        close=pl.when(pl.col("ts") == t).then(pl.lit(1e9)).otherwise(pl.col("close"))
    )
    assert same(values_at(TABLES, t), values_at({**TABLES, "qqq_bars": planted}, t))


# T-LEAK-06: unfinished bar excluded ----------------------------------------------------------
def test_leak_06_unfinished_bar_excluded() -> None:
    t = et(D, 10, 2, 30)  # the 10:02 bar ends at 10:03
    reader = AsOfReader(TABLES, t)
    price, available_at = qqq_reference(reader.get("qqq_bars"), t, CAL, D)
    assert available_at == et(D, 10, 2)  # bar labelled 10:01
    assert price == pytest.approx(101 + 0.01 * 32)  # close of i = 31 (10:01)


# T-LEAK-03: available_at stamping and the writer refusal ---------------------------------------
def test_leak_03_feature_available_at_is_max_of_inputs_and_not_after_t() -> None:
    t = et(D, 11, 0)
    out = compute_at(AsOfReader(TABLES, t), Ctx(T=t, session=D, cal=CAL, cfg=CFG))
    assert out["ret_5m"].available_at == et(D, 11, 0)  # bar 10:59, complete at 11:00
    assert out["vix_prev_close"].available_at == et(date(2025, 3, 10), 18, 0)
    assert all(fv.available_at is None or fv.available_at <= t for fv in out.values())


def test_leak_03_writer_refuses_rows_after_prediction_time() -> None:
    t = et(D, 11, 0)
    df = compute_session(TABLES, D, CAL, CFG, timestamps=[t])
    assert_pit(df)  # passes
    bad = df.with_columns(available_at=pl.col("prediction_ts") + pl.duration(seconds=1))
    with pytest.raises(PitViolationError):
        assert_pit(bad)


# T-LEAK-07: open interest visible only from 09:30 on the next session ----------------------------
def test_leak_07_oi_prior_day_only() -> None:
    stats = pl.DataFrame(
        {"ts_recv": [et(D, 6, 30)], "symbol": ["QQQ   250312C00102000"], "quantity": [1234],
         "stat_type": [9]},
        schema={"ts_recv": pl.Datetime("ns", "UTC"), "symbol": pl.String,
                "quantity": pl.Int64, "stat_type": pl.Int64},
    )  # fmt: skip
    oi = open_interest_table(stats, CAL, CFG)
    assert oi["as_of_session"].to_list() == [date(2025, 3, 10)]  # reflects the prior close
    assert AsOfReader({"oi": oi}, et(D, 9, 29)).get("oi").height == 0
    assert AsOfReader({"oi": oi}, et(D, 9, 30)).get("oi").height == 1


# T-LEAK-08: a session's daily bar is never visible during that session ---------------------------
def test_leak_08_daily_bar_not_intraday() -> None:
    daily = daily_stats(TABLES["qqq_bars"])
    assert daily.filter(pl.col("session_date") == D)["available_at"].to_list() == [et(D, 16, 0)]
    during = AsOfReader({"daily": daily}, et(D, 15, 59)).get("daily")
    assert D not in during["session_date"].to_list()
    next_day = AsOfReader({"daily": daily}, et(date(2025, 3, 12), 9, 45)).get("daily")
    assert D in next_day["session_date"].to_list()


# T-LEAK-09: macro events -----------------------------------------------------------------------
def test_leak_09_macro_release_visible_only_from_release_time() -> None:
    m = TABLES["macro"]
    assert AsOfReader({"macro": m}, et(D, 8, 29)).get("macro")["event"].to_list() == ["FOMC"]
    assert sorted(AsOfReader({"macro": m}, et(D, 9, 45)).get("macro")["event"].to_list()) == [
        "CPI", "FOMC"]  # fmt: skip


def test_macro_calendar_file_is_pit_and_on_sessions() -> None:
    path = ROOT / "configs" / "reference" / "macro_calendar.csv"
    m = macro_table(path)
    with path.open(encoding="utf-8") as f:
        n = sum(1 for _ in csv.DictReader(f))
    assert m.height == n == 119
    # BLS publishes on market holidays: the March 2023 and March 2026 jobs reports came out on
    # Good Friday. Such releases never fire macro_event_today (no session, no predictions);
    # their information reaches the next session through price (overnight gap etc.).
    off = {(e, d) for e, d in zip(m["event"], m["session_date"], strict=True)
           if not CAL.is_session(d)}  # fmt: skip
    assert off == {("NFP", date(2023, 4, 7)), ("NFP", date(2026, 4, 3))}
    cpi_nfp = m.filter(pl.col("event") != "FOMC")
    assert (cpi_nfp["available_at"].dt.convert_time_zone("America/New_York").dt.hour() == 8).all()
    # shutdown: no NFP on its original 2025-10-03 date; September report came 2025-11-20
    nfp = m.filter(pl.col("event") == "NFP")["session_date"].to_list()
    assert date(2025, 10, 3) not in nfp and date(2025, 11, 20) in nfp


# T-LEAK-10 ---------------------------------------------------------------------------------------
def test_leak_10_import_contract_kept() -> None:
    import shutil  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    exe = shutil.which("lint-imports")
    if exe is None:
        pytest.skip("import-linter not installed")
    # explicit UTF-8: lint-imports may print UTF-8 (e.g. under PYTHONIOENCODING=utf-8), which the
    # Windows locale codec cannot decode (stdout would silently become None)
    res = subprocess.run(
        [exe], cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", check=False
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "1 kept, 0 broken" in res.stdout
