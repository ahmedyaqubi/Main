"""ADR-0022 P4 (M32): the paper period's operational criteria, its ledger and its loss limits.

Pure functions on the journal (signals and owner-entered fills) and daily prices. Paper P&L is
computed and reported, never a criterion (hard rule 12).

Criterion 1 recomputes the signals with `independent_flags`, written here without importing the
frozen `strategies.pullback` code, so a fault in either one shows as a mismatch.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

import numpy as np

from qqq1dte.core.config import PaperPullback, StudyPullback
from qqq1dte.strategies.pullback_live import NY
from qqq1dte.strategies.trend import commission

_EPS = 1e-9
_BPS = 10_000


@dataclass(frozen=True)
class SignalRecord:
    data_date: date
    next_session: date
    action: str  # BUY | SELL | NO_ACTION
    shares: int
    entry_signal: bool
    exit_signal: bool
    position_before: int
    halted: bool


@dataclass(frozen=True)
class FillRecord:
    """Exactly the fields ADR-0022 P3 lists, plus the status and a reason for a non-fill. No
    account number or other broker field is ever kept."""

    data_date: date  # the signal evening the order belongs to
    status: str  # FILLED | MISSED | REJECTED
    price: float | None
    quantity: int | None
    commission: float | None
    filled_at: datetime | None
    reason: str | None


@dataclass(frozen=True)
class DayPrice:
    open: float
    close: float
    adj_close: float
    div_cash: float


@dataclass(frozen=True)
class LedgerDay:
    day: date
    shares: int
    value: float  # cash + shares x close
    pnl: float
    day_return: float  # pnl / account


@dataclass(frozen=True)
class Criterion:
    name: str
    status: str  # PASS | FAIL | NO_DATA | NOT_TESTABLE
    value: float
    detail: str


@dataclass(frozen=True)
class Review:
    criteria: list[Criterion]
    sessions: int
    round_trips: int
    overall: str  # PASS | FAIL | NOT_ESTABLISHED | IN_PROGRESS
    ledger: list[LedgerDay]
    loss_limit: tuple[date, str] | None
    trades: list[dict[str, float | str]]


# --- criterion 1: independent recomputation -----------------------------------------------
def independent_flags(
    adj_close: Sequence[float], rsi_period: int, rsi_entry: float, sma_trend: int, sma_exit: int
) -> tuple[list[bool], list[bool]]:
    """Entry (RSI < rsi_entry and close > SMA(sma_trend)) and exit (close > SMA(sma_exit))
    flags per day, written independently of `strategies.pullback`: numpy cumulative sums and a
    Wilder recursion over arrays."""
    x = np.asarray(adj_close, dtype=float)
    n = x.size
    csum = np.concatenate([[0.0], np.cumsum(x)])

    def mean_last(k: int) -> np.ndarray:
        out = np.full(n, np.nan)
        if n >= k:
            out[k - 1 :] = (csum[k:] - csum[:-k]) / k
        return out

    trend, ex = mean_last(sma_trend), mean_last(sma_exit)
    rsi = np.full(n, np.nan)
    if n > rsi_period:
        d = np.diff(x)
        up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
        g, lo = up[:rsi_period].mean(), dn[:rsi_period].mean()
        for k in range(rsi_period, n):
            if k > rsi_period:
                g = (g * (rsi_period - 1) + up[k - 1]) / rsi_period
                lo = (lo * (rsi_period - 1) + dn[k - 1]) / rsi_period
            rsi[k] = (100.0 if g > 0 else 50.0) if lo == 0 else 100.0 - 100.0 / (1.0 + g / lo)
    with np.errstate(invalid="ignore"):
        entry = (~np.isnan(rsi)) & (~np.isnan(trend)) & (rsi < rsi_entry) & (x > trend)
        exit_ = (~np.isnan(ex)) & (x > ex)
    return [bool(v) for v in entry], [bool(v) for v in exit_]


# --- fills ----------------------------------------------------------------------------------
def fill_problems(  # noqa: PLR0912 (one check per field)
    signal: SignalRecord, fill: FillRecord, prev_close: float, sanity: float
) -> list[str]:
    """Reasons to refuse an owner-entered fill (rule 8: refused, logged, never adjusted)."""
    out = []
    if signal.action not in ("BUY", "SELL"):
        out.append(f"{signal.data_date} has no order ({signal.action})")
    if fill.data_date != signal.data_date:
        out.append("the fill belongs to another evening")
    if fill.status == "FILLED":
        if fill.price is None or fill.price <= 0:
            out.append("a fill needs a positive price")
        elif abs(fill.price / prev_close - 1) > sanity:
            out.append(f"price {fill.price} is more than {sanity:.0%} from the close {prev_close}")
        if fill.quantity is None or fill.quantity <= 0:
            out.append("a fill needs a positive quantity")
        if fill.commission is None or fill.commission < 0:
            out.append("a fill needs a commission of 0 or more")
        if fill.filled_at is None or fill.filled_at.tzinfo is None:
            out.append("a fill needs a time with a timezone")
        elif fill.filled_at.astimezone(NY).date() != signal.next_session:
            out.append(f"the fill time is not on {signal.next_session}, the session it was for")
    elif fill.status in ("MISSED", "REJECTED"):
        if not (fill.reason or "").strip():
            out.append(f"a {fill.status} record needs a reason")
        if fill.price is not None or fill.quantity is not None:
            out.append(f"a {fill.status} record has no price or quantity")
    else:
        out.append(f"unknown status {fill.status!r}")
    return out


def model_commission(fill: FillRecord, rule: StudyPullback) -> float:
    assert fill.price is not None and fill.quantity is not None
    value = fill.price * fill.quantity
    return commission(
        value, fill.price, rule.commission_per_share, rule.commission_min, rule.commission_max_pct
    )


# --- ledger -----------------------------------------------------------------------------------
def _executions(
    signals: Sequence[SignalRecord], fills: Sequence[FillRecord]
) -> dict[date, list[tuple[str, FillRecord]]]:
    by_date = {s.data_date: s for s in signals}
    out: dict[date, list[tuple[str, FillRecord]]] = {}
    for f in fills:
        if f.status != "FILLED":
            continue
        s = by_date[f.data_date]
        out.setdefault(s.next_session, []).append((s.action, f))
    return out


def daily_ledger(
    signals: Sequence[SignalRecord],
    fills: Sequence[FillRecord],
    prices: Mapping[date, DayPrice],
    account: float,
    days: Sequence[date],
) -> list[LedgerDay]:
    """Account value each session on a notional `account` (OQ5): a dividend is credited when
    shares were held at the previous close; sales then buys execute at their fill price."""
    ex = _executions(signals, fills)
    cash, shares, prev_close = account, 0, None
    out = []
    for d in days:
        p = prices[d]
        start = cash + shares * (prev_close if prev_close is not None else p.close)
        if shares > 0:
            cash += shares * p.div_cash
        for action, f in sorted(ex.get(d, []), key=lambda t: t[0] != "SELL"):
            assert f.price is not None and f.quantity is not None
            fee = f.commission or 0.0
            if action == "SELL":
                cash += f.quantity * f.price - fee
                shares -= f.quantity
            else:
                cash -= f.quantity * f.price + fee
                shares += f.quantity
        value = cash + shares * p.close
        pnl = value - start
        out.append(LedgerDay(d, shares, value, pnl, pnl / account))
        prev_close = p.close
    return out


def loss_limit_breach(
    ledger: Sequence[LedgerDay], account: float, day_limit: float, total_limit: float
) -> tuple[date, str] | None:
    """The first session whose loss reaches the daily or the total limit (ADR-0015 D3)."""
    for x in ledger:
        if x.day_return <= -day_limit + _EPS:
            return x.day, "day"
        if x.value / account - 1 <= -total_limit + _EPS:
            return x.day, "total"
    return None


def settlement_violations(
    signals: Sequence[SignalRecord],
    fills: Sequence[FillRecord],
    prices: Mapping[date, DayPrice],
    start_cash: float,
    start_shares: int,
    days: Sequence[date],
    *,
    settle_sessions: int = 1,
) -> list[str]:
    """Buys that would use unsettled cash: sale proceeds settle `settle_sessions` sessions after
    the sale (T+1 assumed; not verified at IBKR, ADR-0022 P1)."""
    ex = _executions(signals, fills)
    pos = {d: i for i, d in enumerate(days)}
    settled, out = start_cash, []
    pending: list[tuple[int, float]] = []
    shares = start_shares
    for d in days:
        i = pos[d]
        settled += sum(a for k, a in pending if k <= i)
        pending = [(k, a) for k, a in pending if k > i]
        for action, f in sorted(ex.get(d, []), key=lambda t: t[0] != "SELL"):
            assert f.price is not None and f.quantity is not None
            fee = f.commission or 0.0
            if action == "SELL":
                pending.append((i + settle_sessions, f.quantity * f.price - fee))
                shares -= f.quantity
            else:
                cost = f.quantity * f.price + fee
                if cost > settled + _EPS:
                    out.append(f"{d}: buy of ${cost:,.2f} with ${settled:,.2f} settled cash")
                settled -= cost
                shares += f.quantity
    return out


# --- the review -------------------------------------------------------------------------------
def _trades(
    signals: Sequence[SignalRecord], fills: Sequence[FillRecord]
) -> list[dict[str, float | str]]:
    by_date = {s.data_date: s for s in signals}
    done = sorted(
        ((by_date[f.data_date], f) for f in fills if f.status == "FILLED"),
        key=lambda t: t[0].data_date,
    )
    out: list[dict[str, float | str]] = []
    buy: tuple[SignalRecord, FillRecord] | None = None
    for s, f in done:
        if s.action == "BUY":
            buy = (s, f)
        elif buy is not None:
            bs, bf = buy
            assert bf.price and bf.quantity and f.price and f.quantity
            cost = bf.price * bf.quantity + (bf.commission or 0.0)
            proceeds = f.price * f.quantity - (f.commission or 0.0)
            out.append(
                {
                    "buy": str(bs.next_session),
                    "sell": str(s.next_session),
                    "pnl_usd": proceeds - cost,
                    "pnl_pct": proceeds / cost - 1,
                }
            )
            buy = None
    return out


def review(
    signals: Sequence[SignalRecord],
    fills: Sequence[FillRecord],
    prices: Mapping[date, DayPrice],
    recomputed: Mapping[date, tuple[bool, bool]],
    paper: PaperPullback,
    rule: StudyPullback,
) -> Review:
    """`recomputed`: (entry, exit) per data date from `independent_flags` on the same data."""
    sig = sorted(signals, key=lambda s: s.data_date)
    fill_by = {f.data_date: f for f in fills}
    start = paper.first_session
    last = sig[-1].data_date if sig else start
    days = sorted(
        d for d in prices if start is not None and last is not None and start <= d <= last
    )
    crit = []

    # 1. signal fidelity
    mism = [
        s.data_date for s in sig if recomputed.get(s.data_date) != (s.entry_signal, s.exit_signal)
    ]
    crit.append(
        Criterion(
            "signal fidelity",
            "FAIL" if mism else "PASS" if sig else "NO_DATA",
            len(mism),
            f"{len(sig)} evenings, mismatches {mism[:5]}",
        )
    )

    # 2. execution discipline
    orders = [s for s in sig if s.action in ("BUY", "SELL")]
    placed = [s for s in orders if (f := fill_by.get(s.data_date)) and f.status != "MISSED"]
    share = len(placed) / len(orders) if orders else math.nan
    crit.append(
        Criterion(
            "execution discipline",
            "NO_DATA" if not orders else "PASS" if share >= paper.discipline_min - _EPS else "FAIL",
            share,
            f"{len(placed)} of {len(orders)} orders placed",
        )
    )

    # 3. fill quality vs the official open
    by_sig = {s.data_date: s for s in sig}
    filled = [f for f in fills if f.status == "FILLED"]
    bps = [
        abs(f.price / prices[by_sig[f.data_date].next_session].open - 1) * _BPS
        for f in filled
        if f.price is not None
    ]
    ok3 = (
        bool(bps)
        and np.mean(bps) <= paper.fill_mean_bps_max + _EPS
        and max(bps) <= paper.fill_max_bps + _EPS
    )
    crit.append(
        Criterion(
            "fill quality",
            "NO_DATA" if not bps else "PASS" if ok3 else "FAIL",
            float(np.mean(bps)) if bps else math.nan,
            f"mean {np.mean(bps) if bps else math.nan:.2f} bps, "
            f"max {max(bps, default=math.nan):.2f} bps over {len(bps)} fills",
        )
    )

    # 4. commissions vs the IBKR Fixed model
    gaps = [abs((f.commission or 0.0) - model_commission(f, rule)) for f in filled]
    ok4 = bool(gaps) and max(gaps) <= paper.commission_tol_usd + _EPS
    crit.append(
        Criterion(
            "costs",
            "NO_DATA" if not gaps else "PASS" if ok4 else "FAIL",
            max(gaps, default=math.nan),
            f"largest gap ${max(gaps, default=math.nan):.2f} over {len(gaps)} orders",
        )
    )

    # 5. settlement
    rejected = [f for f in fills if f.status == "REJECTED"]
    viol = settlement_violations(sig, fills, prices, paper.account_usd, 0, days) if days else []
    if rejected or viol:
        st5 = "FAIL"
    elif paper.paper_models_cash_settlement is not True:
        st5 = "NOT_TESTABLE"
    else:
        st5 = "PASS" if orders else "NO_DATA"
    crit.append(
        Criterion(
            "settlement",
            st5,
            len(rejected) + len(viol),
            f"{len(rejected)} rejected orders; own ledger: {viol[:3] or 'none'}; "
            f"paper models cash settlement: {paper.paper_models_cash_settlement}",
        )
    )

    ledger = daily_ledger(sig, fills, prices, paper.account_usd, days) if days else []
    breach = loss_limit_breach(
        ledger, paper.account_usd, paper.loss_day_limit, paper.loss_total_limit
    )
    trades = _trades(sig, fills)
    statuses = [c.status for c in crit]
    if "FAIL" in statuses:
        overall = "FAIL"
    elif len(days) < paper.min_sessions or len(trades) < paper.min_round_trips:
        overall = "IN_PROGRESS"
    elif "NOT_TESTABLE" in statuses or "NO_DATA" in statuses:
        overall = "NOT_ESTABLISHED"
    else:
        overall = "PASS"
    return Review(crit, len(days), len(trades), overall, ledger, breach, trades)
