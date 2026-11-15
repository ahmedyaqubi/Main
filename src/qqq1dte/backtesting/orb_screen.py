"""M29 (ADR-0021 D6): the screen of setup S1 (amendment A1). One ticker-session at a time, then
the pooled statistics. Every quote is read as "the latest record with available_at <= T".

Owner rulings of 2026-11-15 implemented here:
- Step A is measured on every ticker-session with a signal, before any option gate (2);
- only contracts that pass every gate compete for the one position (3);
- returns are net dollars over entry fill x 100 (5);
- the mid-fill (KILL) row reprices the same trades (6);
- with no usable option quote at the exit minute, the sale is at the first later minute that
  has one; none by the forced exit = UNRESOLVED_DATA, counted and left out (7).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

import numpy as np
import numpy.typing as npt

from qqq1dte.backtesting.bootstrap import session_bootstrap_ci
from qqq1dte.backtesting.cost_map import MULT, cost_share, outlay
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import BrokerFees, Phase1Config
from qqq1dte.core.timeutil import ET, ensure_utc
from qqq1dte.execution_sim.fills import Conservative, Optimistic
from qqq1dte.execution_sim.selection import Contract, Quote, choose_contract, liquidity_failures
from qqq1dte.strategies.orb import orb_exit, orb_signal
from qqq1dte.validation.options_day_data import DATA_FAILURES, data_present, minute_grid, quote_at

CANDIDATE = "CANDIDATE"
_EXIT_BLOCKERS = frozenset({"NO_QUOTE", "REJECTED_QUOTE", "STALE_QUOTE", "CROSSED"})


@dataclass(frozen=True)
class Candidate:
    """One ticker-session: a NO_TRADE reason, or a contract that may take the one position."""

    ticker: str
    session_date: date
    status: str
    detail: str = ""
    side: str | None = None
    und_entry: float | None = None
    stop: float | None = None
    target: float | None = None
    und_exit_time: datetime | None = None
    und_exit_reason: str | None = None  # STOP / TARGET / TIME / NO_EXIT_QUOTE
    und_exit: float | None = None
    und_return: float | None = None  # signed by the trade's direction (Step A)
    und_gap_minutes: int = 0  # path minutes with no usable underlying quote (not checked)
    symbol: str | None = None
    strike: float | None = None
    expiry: date | None = None
    bid: float | None = None
    ask: float | None = None
    cost_share: float | None = None
    outlay: float | None = None
    entry_fill: float | None = None
    exit_time: datetime | None = None
    exit_reason: str | None = None  # the underlying's reason, or UNRESOLVED_DATA
    exit_delay_minutes: int | None = None
    exit_no_bid: bool | None = None
    exit_fill: float | None = None
    net_usd: float | None = None
    ret: float | None = None
    entry_mid: float | None = None
    exit_mid: float | None = None
    net_usd_mid: float | None = None
    ret_mid: float | None = None


def trade_pnl(entry_fill: float, exit_fill: float, fees: BrokerFees) -> tuple[float, float]:
    """(net dollars, net dollars / premium paid) for one contract; premium = entry x 100."""
    net = (
        (exit_fill - entry_fill) * MULT
        - fees.order_cost(1, entry_fill, sell=False)
        - fees.order_cost(1, exit_fill, sell=True)
    )
    return net, net / (entry_fill * MULT)


def pick_one(candidates: Sequence[tuple[str, float]]) -> str | None:
    """D3: the name with the lowest round-trip cost share; ties go to the earlier entry."""
    if not candidates:
        return None
    return min(enumerate(candidates), key=lambda ic: (ic[1][1], ic[0]))[1][0]


def exit_quote(
    records: Sequence[Quote], t_from: datetime, t_last: datetime, cfg: Phase1Config
) -> tuple[datetime, Quote] | None:
    """The first minute t in t_from..t_last whose quote in force at t + latency can be sold
    into: not missing, rejected, stale or crossed. A quote with no bid is usable and is returned
    with bid None (it sells at 0, M6 Q3)."""
    lat = timedelta(seconds=cfg.fills.latency_s)
    for t in minute_grid(t_from, t_last):
        q = quote_at(records, t + lat)
        fails = set(liquidity_failures(q, t + lat, cfg))
        if q is None or fails & _EXIT_BLOCKERS:
            continue
        if "NOT_TWO_SIDED" in fails:
            if q.ask is None or q.ask <= 0:
                continue
            return t, replace(q, bid=None)
        return t, q
    return None


def _mid(q: Quote | None, t: datetime, cfg: Phase1Config) -> float | None:
    if q is None or not data_present(q, t, cfg):
        return None
    return (float(q.bid) + float(q.ask)) / 2  # type: ignore[arg-type]


def session_decision(  # noqa: PLR0911, PLR0913 (one linear decision path)
    ticker: str,
    d: date,
    underlying: Sequence[Quote],
    contracts: Sequence[Contract],
    quotes_for: Callable[[str], Sequence[Quote]],
    cfg: Phase1Config,
    cal: TradingCalendar,
    fees: BrokerFees,
    *,
    excluded: bool = False,
) -> Candidate:
    """S1 on one ticker-session. `underlying` and each `quotes_for(symbol)` are sorted by
    available_at; `contracts` is the D2 expiry's chain. Nothing later than the time being
    decided is read: every lookup is `quote_at(records, T)`."""
    s = cfg.study_options_day
    base = Candidate(ticker, d, CANDIDATE)
    if excluded:
        return replace(base, status="EARNINGS_WINDOW")
    t0 = ensure_utc(datetime.combine(d, s.orb.candle_start, tzinfo=ET))
    t5 = ensure_utc(datetime.combine(d, s.orb.candle_end, tzinfo=ET))
    t_entry = ensure_utc(datetime.combine(d, s.orb.entry_time, tzinfo=ET))
    t_exit = ensure_utc(datetime.combine(d, s.orb.exit_time, tzinfo=ET))
    forced = min(t_exit, cal.forced_exit_time(d))
    candle = [_mid(quote_at(underlying, t), t, cfg) for t in minute_grid(t0, t5)]
    if candle[0] is None or candle[-1] is None:
        return replace(base, status="NO_UNDERLYING_QUOTE")
    sig = orb_signal([m for m in candle if m is not None], s.orb.target_r_multiple)
    if sig is None:
        return replace(base, status="FLAT_FIRST_CANDLE")

    # the underlying leg (Step A): measured for every signal, whatever the option does
    grid = minute_grid(t_entry + timedelta(minutes=1), forced)
    mids = [(t, _mid(quote_at(underlying, t), t, cfg)) for t in grid]
    path = [(t, m) for t, m in mids if m is not None]
    hit = orb_exit(sig, path)
    t_x, reason = forced, "NO_EXIT_QUOTE"
    m_x: float | None = None
    if hit is not None:
        t_x, reason, m_x = hit
    elif path and path[-1][0] == forced:
        reason, m_x = "TIME", path[-1][1]
    base = replace(
        base, side=sig.side, und_entry=sig.entry, stop=sig.stop, target=sig.target,
        und_exit_time=t_x, und_exit_reason=reason, und_exit=m_x,
        und_return=None if m_x is None else sig.direction * (m_x / sig.entry - 1),
        und_gap_minutes=sum(1 for t, m in mids if m is None and t <= t_x),
    )  # fmt: skip

    # the option leg (D2), at T_e = entry + latency
    t_e = t_entry + timedelta(seconds=cfg.fills.latency_s)
    c = choose_contract(contracts, sig.entry, sig.side, t_e)
    if c is None:
        return replace(base, status="NO_CONTRACT")
    base = replace(base, symbol=c.symbol, strike=c.strike, expiry=c.expiration)
    recs = quotes_for(c.symbol)
    q = quote_at(recs, t_e)
    fails = liquidity_failures(q, t_e, cfg)
    if q is None or set(fails) & DATA_FAILURES:
        return replace(base, status="NO_OPTION_QUOTE", detail=";".join(sorted(fails)))
    bid, ask = float(q.bid), float(q.ask)  # type: ignore[arg-type]
    base = replace(base, bid=bid, ask=ask)
    if fails:
        return replace(base, status="SELECTED_CONTRACT_ILLIQUID", detail=";".join(sorted(fails)))
    cons, opti = Conservative(cfg), Optimistic(cfg)
    entry_fill = cons.buy(q)
    out = outlay(entry_fill, fees)
    base = replace(base, cost_share=cost_share(bid, ask, fees), outlay=out, entry_fill=entry_fill,
                   entry_mid=opti.buy(q))  # fmt: skip
    if out > s.max_premium_usd:
        return replace(base, status="PREMIUM_OVER_CAP")
    xq = exit_quote(recs, t_x, forced, cfg)
    if xq is None:
        return replace(base, exit_reason="UNRESOLVED_DATA")
    t_sell, quote = xq
    exit_fill, exit_mid = cons.sell(quote), opti.sell(quote)
    net, ret = trade_pnl(entry_fill, exit_fill, fees)
    assert base.entry_mid is not None
    net_mid, ret_mid = trade_pnl(base.entry_mid, exit_mid, fees)
    return replace(
        base, exit_time=t_sell, exit_reason=reason if reason != "NO_EXIT_QUOTE" else "TIME",
        exit_delay_minutes=int((t_sell - t_x).total_seconds() // 60),
        exit_no_bid=quote.bid is None, exit_fill=exit_fill, net_usd=net, ret=ret,
        exit_mid=exit_mid, net_usd_mid=net_mid, ret_mid=ret_mid,
    )  # fmt: skip


# statistics ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class Bounds:
    mean: float
    lower: float  # one-sided, at lower_level
    two_sided_low: float
    two_sided_high: float
    n: int
    sessions: int


def mean_bounds(
    session_ids: npt.ArrayLike,
    values: npt.ArrayLike,
    *,
    reps: int,
    seed: int,
    lower_level: float,
    two_sided_level: float = 0.95,
) -> Bounds:
    """Mean of `values` with session-bootstrap bounds (D6): whole sessions are resampled, so
    rows of one session stay together. The same seed gives the same resamples for both bounds."""
    v = np.asarray(values, dtype=np.float64)
    sid = np.asarray(session_ids)

    def stat(w: npt.NDArray[np.float64]) -> float:
        return float((w * v).sum() / w.sum())

    lower, _ = session_bootstrap_ci(sid, stat, reps, seed, 1 - 2 * (1 - lower_level))
    lo, hi = session_bootstrap_ci(sid, stat, reps, seed, two_sided_level)
    return Bounds(float(v.mean()), lower, lo, hi, int(v.size), int(np.unique(sid).size))


def screen_outcome(
    *, step_a_lower: float, b_lower: float, trades: int, min_trades: int, kill_upper: float
) -> str:
    """D6. KILL: the mid-fill two-sided upper bound is below 0. ADVANCE: Step A's lower bound
    and Step B's lower bound are above 0 with enough trades. Otherwise AMBIGUOUS."""
    if kill_upper < 0:
        return "KILL"
    if step_a_lower > 0 and b_lower > 0 and trades >= min_trades:
        return "ADVANCE"
    return "AMBIGUOUS"


def longest_losing_run(pnl: Sequence[float]) -> int:
    best = run = 0
    for x in pnl:
        run = run + 1 if x < 0 else 0
        best = max(best, run)
    return best


def max_drawdown(pnl: Sequence[float]) -> float:
    """Largest fall of the running total from an earlier high (the start counts as a high)."""
    total = peak = worst = 0.0
    for x in pnl:
        total += x
        peak = max(peak, total)
        worst = max(worst, peak - total)
    return worst


def cap_hit_index(pnl: Sequence[float], cap: float) -> int | None:
    """Index of the first trade after which total losses since the start reach `cap`."""
    total = 0.0
    for i, x in enumerate(pnl):
        total += x
        if total <= -cap:
            return i
    return None
