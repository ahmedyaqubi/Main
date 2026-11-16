"""M32 (ADR-0022 P4): operational criteria, ledger and loss limits on synthetic journals whose
answers are known exactly."""

from __future__ import annotations

import random
from dataclasses import fields, replace
from datetime import UTC, date, datetime, timedelta

import pytest

from qqq1dte.core.config import load_config
from qqq1dte.monitoring.paper_review import (
    DayPrice,
    FillRecord,
    SignalRecord,
    daily_ledger,
    fill_problems,
    independent_flags,
    review,
)
from qqq1dte.strategies.pullback import signals

CFG = load_config()
RULE, PAPER = (
    CFG.study_pullback,
    CFG.paper_pullback.model_copy(
        update={"first_session": date(2026, 1, 5), "paper_models_cash_settlement": True}
    ),
)


def _walk(n: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    x, out = 100.0, []
    for _ in range(n):
        x *= 1 + rng.gauss(0.0003, 0.013)
        out.append(x)
    return out


@pytest.mark.parametrize("seed", [4, 5])
def test_independent_flags_equal_the_frozen_code(seed: int) -> None:
    c = _walk(900, seed)
    e1, x1 = signals(c, RULE.rsi_period, RULE.rsi_entry, RULE.sma_trend, RULE.sma_exit)
    e2, x2 = independent_flags(c, RULE.rsi_period, RULE.rsi_entry, RULE.sma_trend, RULE.sma_exit)
    assert (e1, x1) == (e2, x2)


# --- a hand-built 70-session journal with 5 round trips -----------------------------------
def _days(n: int) -> list[date]:
    d, out = date(2026, 1, 5), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = _days(70)
PRICE = 700.0


def _prices() -> dict[date, DayPrice]:
    return {d: DayPrice(open=PRICE, close=PRICE, adj_close=PRICE, div_cash=0.0) for d in DAYS}


def _signal(i: int, action: str, shares: int, pos: int) -> SignalRecord:
    return SignalRecord(
        data_date=DAYS[i],
        next_session=DAYS[i + 1],
        action=action,
        shares=shares,
        entry_signal=action == "BUY",
        exit_signal=action == "SELL",
        position_before=pos,
        halted=False,
    )


def _filled(s: SignalRecord, price: float = PRICE, commission: float = 1.0) -> FillRecord:
    t = datetime(s.next_session.year, s.next_session.month, s.next_session.day, 14, 31, tzinfo=UTC)
    return FillRecord(
        data_date=s.data_date,
        status="FILLED",
        price=price,
        quantity=s.shares,
        commission=commission,
        filled_at=t,
        reason=None,
    )


def _journal() -> tuple[list[SignalRecord], list[FillRecord]]:
    sig, fills = [], []
    for k in range(5):
        b, s = 10 * k, 10 * k + 3
        for i in range(10 * k, 10 * k + 10):
            if i == b:
                x = _signal(i, "BUY", 3, 0)
            elif i == s:
                x = _signal(i, "SELL", 3, 3)
            else:
                x = _signal(i, "NO_ACTION", 0, 3 if b < i < s else 0)
            sig.append(x)
            if x.action != "NO_ACTION":
                fills.append(_filled(x))
    for i in range(50, 69):
        sig.append(_signal(i, "NO_ACTION", 0, 0))
    return sig, fills


def _flags_consistent(sig: list[SignalRecord]) -> dict[date, tuple[bool, bool]]:
    return {s.data_date: (s.entry_signal, s.exit_signal) for s in sig}


def _review(sig: list[SignalRecord], fills: list[FillRecord], paper=PAPER):  # type: ignore[no-untyped-def]
    return review(sig, fills, _prices(), _flags_consistent(sig), paper, RULE)


def test_clean_journal_passes_all_five() -> None:
    r = _review(*_journal())
    assert [c.status for c in r.criteria] == ["PASS"] * 5
    assert (r.sessions, r.round_trips, r.overall) == (69, 5, "PASS")


def test_one_signal_mismatch_fails_criterion_1() -> None:
    sig, fills = _journal()
    flags = _flags_consistent(sig)
    flags[sig[20].data_date] = (False, False)  # the recomputation disagrees on a BUY evening
    r = review(sig, fills, _prices(), flags, PAPER, RULE)
    assert (r.criteria[0].status, r.overall) == ("FAIL", "FAIL")
    assert r.criteria[0].value == 1


def test_one_miss_in_ten_fails_discipline() -> None:
    sig, fills = _journal()
    fills[4] = FillRecord(fills[4].data_date, "MISSED", None, None, None, None, "away")
    r = _review(sig, fills)
    assert r.criteria[1].value == pytest.approx(0.9)
    assert r.criteria[1].status == "FAIL"


def test_fill_26_bps_away_fails_and_25_passes() -> None:
    sig, fills = _journal()
    fills[0] = replace(fills[0], price=PRICE * 1.0025)
    assert _review(sig, fills).criteria[2].status == "PASS"  # max 25 bps, mean 2.5 bps
    fills[0] = replace(fills[0], price=PRICE * 1.0026)
    assert _review(sig, fills).criteria[2].status == "FAIL"


def test_mean_fill_over_5_bps_fails() -> None:
    sig, fills = _journal()
    fills = [replace(f, price=PRICE * 1.0006) for f in fills]  # 6 bps each
    assert _review(sig, fills).criteria[2].status == "FAIL"


def test_commission_off_by_11_cents_fails_by_10_passes() -> None:
    sig, fills = _journal()
    fills[1] = replace(fills[1], commission=1.10)
    assert _review(sig, fills).criteria[3].status == "PASS"
    fills[1] = replace(fills[1], commission=1.11)
    assert _review(sig, fills).criteria[3].status == "FAIL"


def test_a_rejected_order_fails_settlement() -> None:
    sig, fills = _journal()
    fills[2] = FillRecord(fills[2].data_date, "REJECTED", None, None, None, None, "unsettled")
    assert _review(sig, fills).criteria[4].status == "FAIL"


def test_settlement_not_testable_when_paper_does_not_model_it() -> None:
    p = PAPER.model_copy(update={"paper_models_cash_settlement": False})
    r = _review(*_journal(), paper=p)
    assert r.criteria[4].status == "NOT_TESTABLE"
    assert r.overall == "NOT_ESTABLISHED"


def test_too_few_sessions_or_trips_is_in_progress() -> None:
    sig, fills = _journal()
    r = _review(sig[:42], [f for f in fills if f.data_date <= sig[41].data_date])
    assert (r.round_trips, r.overall) == (4, "IN_PROGRESS")


# --- ledger and loss limits ---------------------------------------------------------------
def test_daily_pnl_with_dividend_and_commissions() -> None:
    d = DAYS[:4]
    prices = {
        d[0]: DayPrice(100, 100, 100, 0.0),
        d[1]: DayPrice(101, 102, 102, 0.0),
        d[2]: DayPrice(103, 104, 104, 0.5),
        d[3]: DayPrice(105, 106, 106, 0.0),
    }
    buy = SignalRecord(d[0], d[1], "BUY", 10, True, False, 0, False)
    sell = SignalRecord(d[2], d[3], "SELL", 10, False, True, 10, False)
    fills = [
        FillRecord(d[0], "FILLED", 101.0, 10, 1.0, datetime(2026, 1, 6, 14, 31, tzinfo=UTC), None),
        FillRecord(d[2], "FILLED", 105.0, 10, 1.0, datetime(2026, 1, 8, 14, 31, tzinfo=UTC), None),
    ]
    led = daily_ledger([buy, sell], fills, prices, 5000.0, d)
    # d1: 10 x (102 - 101) - 1 = 9; d2: 10 x (104 - 102) + 10 x 0.5 = 25; d3: 10 x (105 - 104) - 1
    assert [x.pnl for x in led] == pytest.approx([0.0, 9.0, 25.0, 9.0])
    assert led[-1].value == pytest.approx(5043.0)
    assert led[-1].shares == 0


def _loss_case(close_d1: float) -> list[float]:
    d = DAYS[:2]
    prices = {d[0]: DayPrice(1000, 1000, 1000, 0.0), d[1]: DayPrice(1000, close_d1, close_d1, 0.0)}
    buy = SignalRecord(d[0], d[1], "BUY", 3, True, False, 0, False)
    f = FillRecord(d[0], "FILLED", 1000.0, 3, 0.0, datetime(2026, 1, 6, 14, 31, tzinfo=UTC), None)
    return [x.day_return for x in daily_ledger([buy], [f], prices, 5000.0, d)]


def test_loss_day_exactly_3_percent_triggers() -> None:
    sig, fills = _journal()
    p = PAPER
    # 3 shares fall $50 each: -150 / 5000 = -3.0% exactly
    assert _loss_case(950.0)[1] == pytest.approx(-0.03)
    from qqq1dte.monitoring.paper_review import loss_limit_breach  # noqa: PLC0415

    d = DAYS[:2]
    prices = {d[0]: DayPrice(1000, 1000, 1000, 0.0), d[1]: DayPrice(1000, 950, 950, 0.0)}
    buy = SignalRecord(d[0], d[1], "BUY", 3, True, False, 0, False)
    f = FillRecord(d[0], "FILLED", 1000.0, 3, 0.0, datetime(2026, 1, 6, 14, 31, tzinfo=UTC), None)
    led = daily_ledger([buy], [f], prices, 5000.0, d)
    assert loss_limit_breach(led, p.account_usd, p.loss_day_limit, p.loss_total_limit) == (
        d[1],
        "day",
    )
    prices[d[1]] = DayPrice(1000, 950.01, 950.01, 0.0)
    led = daily_ledger([buy], [f], prices, 5000.0, d)
    assert loss_limit_breach(led, p.account_usd, p.loss_day_limit, p.loss_total_limit) is None
    assert sig and fills


def test_total_loss_exactly_20_percent_triggers() -> None:
    from qqq1dte.monitoring.paper_review import LedgerDay, loss_limit_breach  # noqa: PLC0415

    led = [
        LedgerDay(DAYS[i], 0, 5000 - 200 * (i + 1), -200, -0.04 if i == 0 else -0.02)
        for i in range(5)
    ]
    led = [replace(x, day_return=-0.02) for x in led]
    assert loss_limit_breach(led, 5000.0, 0.03, 0.20) == (DAYS[4], "total")
    assert loss_limit_breach(led[:4], 5000.0, 0.03, 0.20) is None


def test_settlement_ledger_flags_buy_with_unsettled_cash() -> None:
    d = DAYS[:3]
    prices = {x: DayPrice(1000, 1000, 1000, 0.0) for x in d}
    sell_buy = [
        SignalRecord(d[0], d[1], "SELL", 4, False, True, 4, False),
        SignalRecord(d[1], d[2], "BUY", 4, True, False, 0, False),
    ]
    from qqq1dte.monitoring.paper_review import settlement_violations  # noqa: PLC0415

    t = datetime(2026, 1, 6, 14, 31, tzinfo=UTC)
    fills = [
        FillRecord(d[0], "FILLED", 1000.0, 4, 1.0, t, None),
        FillRecord(d[1], "FILLED", 1000.0, 4, 1.0, t + timedelta(days=1), None),
    ]
    # start: 1,000 settled cash and 4 shares. The sale (open d1) settles T+1 on d2; the buy is
    # at the open of d2, so the proceeds are settled: allowed.
    assert settlement_violations(sell_buy, fills, prices, 1000.0, 4, d, settle_sessions=1) == []
    # if sales took two sessions to settle, the same buy would use unsettled cash
    assert len(settlement_violations(sell_buy, fills, prices, 1000.0, 4, d, settle_sessions=2)) == 1
    # a buy larger than the settled cash at the start
    assert len(settlement_violations(sell_buy[1:], fills[1:], prices, 1000.0, 0, d)) == 1


# --- fill entry (P3, rule 8) --------------------------------------------------------------
def test_fill_record_keeps_only_the_listed_fields() -> None:
    assert [f.name for f in fields(FillRecord)] == [
        "data_date",
        "status",
        "price",
        "quantity",
        "commission",
        "filled_at",
        "reason",
    ]


def test_fill_problems() -> None:
    s = SignalRecord(DAYS[0], DAYS[1], "BUY", 3, True, False, 0, False)
    ok = _filled(s)
    assert fill_problems(s, ok, prev_close=PRICE, sanity=0.15) == []
    assert fill_problems(replace(s, action="NO_ACTION", shares=0), ok, PRICE, 0.15)
    assert fill_problems(s, replace(ok, price=PRICE * 1.2), PRICE, 0.15)
    wrong_day = replace(ok, filled_at=ok.filled_at + timedelta(days=1))  # type: ignore[operator]
    assert fill_problems(s, wrong_day, PRICE, 0.15)
    assert fill_problems(
        s,
        replace(
            ok,
            status="MISSED",
            price=None,
            quantity=None,
            commission=None,
            filled_at=None,
            reason="",
        ),
        PRICE,
        0.15,
    )
