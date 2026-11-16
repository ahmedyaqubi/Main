"""M32 (ADR-0022): the evening instruction, its timing and data readiness. Synthetic data only."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, time, timedelta

import polars as pl
import pytest

from qqq1dte.core.config import load_config
from qqq1dte.ingestion.etf_data import HoldoutLockedError, paper_rows
from qqq1dte.strategies.pullback import signals, trade_indices
from qqq1dte.strategies.pullback_live import (
    EveningRefusalError,
    evening_instruction,
    instruction_text,
    paper_data_date,
    revisions,
    share_count,
)

RULE = load_config().study_pullback
CUTOFF = time(18, 0)


def _walk(n: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    x, out = 100.0, []
    for _ in range(n):
        x *= 1 + rng.gauss(0.0004, 0.012)
        out.append(x)
    return out


def _sessions(n: int) -> list[date]:
    d, out = date(2020, 1, 1), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


# --- share count (A1 R1) ------------------------------------------------------------------
@pytest.mark.parametrize(
    ("usd", "close", "n"),
    [
        (2500.0, 750.0, 3),
        (2500.0, 833.34, 2),
        (2500.0, 833.33, 3),
        (2500.0, 625.0, 4),
        (1500.0, 751.0, 1),
    ],
)
def test_share_count_is_floor_of_trade_over_signal_close(usd: float, close: float, n: int) -> None:
    assert share_count(usd, close) == n


def test_share_count_refuses_zero_shares() -> None:
    with pytest.raises(EveningRefusalError, match="0 shares"):
        share_count(2500.0, 2600.0)


# --- instruction per state ----------------------------------------------------------------
def _flat_then(last: list[float]) -> tuple[list[date], list[float]]:
    """210 closes rising to 204.5 (far above SMA200), then `last`."""
    close = [100.0 + 0.5 * i for i in range(210)] + last
    return _sessions(len(close)), close


def test_buy_when_flat_and_entry_signal() -> None:
    dates, close = _flat_then([200.0, 196.0])  # two sharp drops: RSI(2) < 10
    entry, _ = signals(close, RULE.rsi_period, RULE.rsi_entry, RULE.sma_trend, RULE.sma_exit)
    assert entry[-1]
    ins = evening_instruction(dates, close, close, 0, False, RULE, 2500.0)
    assert (ins.action, ins.shares) == ("BUY", 12)  # floor(2500 / 196)
    assert instruction_text(ins, "SPY") == "BUY 12 SPY market-on-open"
    assert ins.entry_signal and ins.data_date == dates[-1]


def test_no_buy_while_halted() -> None:
    dates, close = _flat_then([200.0, 196.0])
    ins = evening_instruction(dates, close, close, 0, True, RULE, 2500.0)
    assert (ins.action, ins.shares, ins.halted) == ("NO_ACTION", 0, True)
    assert "loss-limit stop" in instruction_text(ins, "SPY")


def test_sell_all_held_shares_on_exit_signal_even_when_halted() -> None:
    dates, close = _flat_then([200.0, 196.0, 215.0])  # close > SMA(5)
    for halted in (False, True):
        ins = evening_instruction(dates, close, close, 7, halted, RULE, 2500.0)
        assert (ins.action, ins.shares) == ("SELL", 7)
        assert instruction_text(ins, "SPY") == "SELL 7 SPY market-on-open"


def test_hold_when_in_position_and_no_exit() -> None:
    dates, close = _flat_then([200.0, 196.0])
    ins = evening_instruction(dates, close, close, 7, False, RULE, 2500.0)
    assert (ins.action, ins.shares) == ("NO_ACTION", 0)
    assert instruction_text(ins, "SPY") == "NO ACTION"


def test_signals_use_adjusted_close_and_shares_use_unadjusted_close() -> None:
    dates, adj = _flat_then([200.0, 196.0])
    unadj = [a * 2 for a in adj]
    ins = evening_instruction(dates, unadj, adj, 0, False, RULE, 2500.0)
    assert (ins.action, ins.shares) == ("BUY", 6)  # floor(2500 / 392)
    assert ins.adj_close == 196.0 and ins.close == 392.0


# --- replay: the live path equals the backtest state machine ------------------------------
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_replay_day_by_day_equals_trade_indices(seed: int) -> None:
    n = 700
    close = _walk(n, seed)
    dates = _sessions(n)
    entry, exit_ = signals(close, RULE.rsi_period, RULE.rsi_entry, RULE.sma_trend, RULE.sma_exit)
    expected = trade_indices(entry, exit_)
    assert len(expected) >= 5
    pos, buys, sells = 0, [], []
    for k in range(n):  # every order assumed filled at the next open
        ins = evening_instruction(
            dates[: k + 1], close[: k + 1], close[: k + 1], pos, False, RULE, 2500.0
        )
        if ins.action == "BUY":
            buys.append(k)
            pos = ins.shares
        elif ins.action == "SELL":
            sells.append(k)
            pos = 0
    got = [(b, s) for b, s in zip(buys, sells, strict=False) if s + 1 < n]
    assert got == expected


# --- timing (A1 R3) -----------------------------------------------------------------------
SESS = [date(2026, 11, 13), date(2026, 11, 16), date(2026, 11, 17)]  # Fri, Mon, Tue
OPENS = {d: datetime(d.year, d.month, d.day, 14, 30, tzinfo=UTC) for d in SESS}  # 09:30 EST


def _ny(d: date, h: int, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h + 5, m, tzinfo=UTC)  # EST = UTC-5 in November


def test_after_cutoff_uses_today() -> None:
    assert paper_data_date(_ny(SESS[1], 18), SESS, CUTOFF, OPENS) == (SESS[1], SESS[2])


def test_weekend_uses_friday_for_monday_open() -> None:
    sat = datetime(2026, 11, 14, 15, tzinfo=UTC)
    assert paper_data_date(sat, SESS, CUTOFF, OPENS) == (SESS[0], SESS[1])


def test_morning_before_open_uses_previous_evening() -> None:
    assert paper_data_date(_ny(SESS[2], 8), SESS, CUTOFF, OPENS) == (SESS[1], SESS[2])


def test_refuses_after_the_open_it_was_for() -> None:
    with pytest.raises(EveningRefusalError, match="missed"):
        paper_data_date(_ny(SESS[1], 10), SESS, CUTOFF, OPENS)


def test_refuses_one_minute_before_cutoff_after_open() -> None:
    with pytest.raises(EveningRefusalError):
        paper_data_date(_ny(SESS[1], 17, 59), SESS, CUTOFF, OPENS)


def test_naive_time_refused() -> None:
    with pytest.raises(ValueError, match="timezone"):
        paper_data_date(datetime(2026, 11, 16, 23), SESS, CUTOFF, OPENS)  # noqa: DTZ001


# --- the paper loader (A1 R2) -------------------------------------------------------------
def test_paper_rows_need_adr_0022() -> None:
    df = pl.DataFrame({"date": [date(2016, 1, 4), date(2026, 11, 13)]})
    for bad in ("", "ADR-0019", "ADR-0020"):
        with pytest.raises(HoldoutLockedError):
            paper_rows(df, bad)
    assert paper_rows(df, "ADR-0022").height == 2


# --- revisions (A1 R3) --------------------------------------------------------------------
def _rows(vals: dict[date, tuple[float, float, float]]) -> pl.DataFrame:
    ds = sorted(vals)
    return pl.DataFrame(
        {
            "date": ds,
            "open": [vals[d][0] for d in ds],
            "close": [vals[d][1] for d in ds],
            "adj_close": [vals[d][2] for d in ds],
        }
    )


def test_revisions_list_changed_fields_on_common_dates_only() -> None:
    d1, d2, d3 = SESS
    old = _rows({d1: (1.0, 2.0, 3.0), d2: (4.0, 5.0, 6.0)})
    new = _rows({d1: (1.0, 2.0, 3.0), d2: (4.0, 5.5, 6.0), d3: (7.0, 8.0, 9.0)})
    assert revisions(old, new) == [(d2, "close", 5.0, 5.5)]
    assert revisions(new, new) == []


# --- config -------------------------------------------------------------------------------
def test_paper_config_holds_no_rule_values() -> None:
    p = load_config().paper_pullback
    rule_keys = {"rsi_period", "rsi_entry", "sma_trend", "sma_exit", "ticker"}
    assert not rule_keys & set(type(p).model_fields)
    assert (p.trade_usd, p.account_usd, p.adr) == (2500.0, 5000.0, "ADR-0022")


def test_paper_config_refuses_trade_over_account() -> None:
    from qqq1dte.core.config import PaperPullback  # noqa: PLC0415

    raw = load_config().paper_pullback.model_dump()
    with pytest.raises(ValueError, match="trade_usd"):
        PaperPullback.model_validate({**raw, "trade_usd": 6000.0})
