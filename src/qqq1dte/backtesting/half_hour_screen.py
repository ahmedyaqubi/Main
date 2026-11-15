"""M30 (ADR-0021 D6): the screen of setup S2 (D3), one ticker-session at a time. The pooled
statistics, the one-position rule and the risk rows are M29's (`orb_screen`). Every quote is
read as "the latest record with available_at <= T".

Owner rulings of 2026-11-15 ("Approve all") implemented here:
1. the previous close is the mid of the quote in force `prev_close_offset_minutes` before the
   previous session's close, at most max_quote_age_s old, two-sided, not crossed;
2. the 10:00 price is the quote in force at signal_time, same checks;
3. direction by `half_hour_signal`: non-overlapping quotes only, else FLAT_MOVE;
4. no previous session, or no usable quote there: NO_PREV_CLOSE;
5. a split session: CORPORATE_ACTION (dividends are not adjusted);
6. Step A is the signed return of the underlying mid from entry_time to exit_time, on every
   ticker-session with a direction, before any option gate;
7. M29's rulings 2-8 unchanged. S2 exits at the forced exit, so there is no later minute to
   sell at: no usable option quote at exit_time + latency is UNRESOLVED_DATA.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from qqq1dte.backtesting.cost_map import cost_share, outlay
from qqq1dte.backtesting.orb_screen import CANDIDATE, Candidate, exit_quote, trade_pnl
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import BrokerFees, Phase1Config
from qqq1dte.core.timeutil import ET, ensure_utc
from qqq1dte.execution_sim.fills import Conservative, Optimistic
from qqq1dte.execution_sim.selection import Contract, Quote, choose_contract, liquidity_failures
from qqq1dte.strategies.half_hour import half_hour_signal
from qqq1dte.validation.options_day_data import DATA_FAILURES, data_present, quote_at


@dataclass(frozen=True)
class S2Candidate(Candidate):
    """M29's row plus the two quotes the direction was read from."""

    prev_bid: float | None = None
    prev_ask: float | None = None
    sig_bid: float | None = None
    sig_ask: float | None = None


def _present(records: Sequence[Quote], t: datetime, cfg: Phase1Config) -> Quote | None:
    q = quote_at(records, t)
    return q if q is not None and data_present(q, t, cfg) else None


def _sides(q: Quote) -> tuple[float, float]:
    assert q.bid is not None and q.ask is not None  # `_present` guarantees a two-sided quote
    return float(q.bid), float(q.ask)


def _mid(q: Quote) -> float:
    bid, ask = _sides(q)
    return (bid + ask) / 2


def session_decision(  # noqa: PLR0911, PLR0912, PLR0913 (one linear decision path)
    ticker: str,
    d: date,
    underlying: Sequence[Quote],
    contracts: Sequence[Contract],
    quotes_for: Callable[[str], Sequence[Quote]],
    cfg: Phase1Config,
    cal: TradingCalendar,
    fees: BrokerFees,
    *,
    prev_session: date | None,
    excluded: bool = False,
    split: bool = False,
) -> S2Candidate:
    """S2 on one ticker-session. `underlying` holds the previous session's and this session's
    records, sorted by available_at; `prev_session` is the session whose close is "the previous
    close", or None when it is outside the data or excluded. `contracts` is the D2 expiry's
    chain. Nothing later than the time being decided is read."""
    s = cfg.study_options_day
    h = s.half_hour
    base = S2Candidate(ticker, d, CANDIDATE)
    if excluded:
        return replace(base, status="EARNINGS_WINDOW")
    t_sig = ensure_utc(datetime.combine(d, h.signal_time, tzinfo=ET))
    t_entry = ensure_utc(datetime.combine(d, h.entry_time, tzinfo=ET))
    t_exit = ensure_utc(datetime.combine(d, h.exit_time, tzinfo=ET))
    if t_entry >= cal.forced_exit_time(d):  # owner, 2026-11-14: S2's times are not moved
        return replace(base, status="EARLY_CLOSE")
    if split:
        return replace(base, status="CORPORATE_ACTION")
    if prev_session is None:
        return replace(base, status="NO_PREV_CLOSE", detail="no previous session")
    t_prev = cal.open_close(prev_session)[1] - timedelta(minutes=h.prev_close_offset_minutes)
    q_prev = _present(underlying, t_prev, cfg)
    if q_prev is None:
        return replace(base, status="NO_PREV_CLOSE", detail="no usable quote")
    base = replace(base, prev_bid=q_prev.bid, prev_ask=q_prev.ask)
    q_sig = _present(underlying, t_sig, cfg)
    if q_sig is None:
        return replace(base, status="NO_UNDERLYING_QUOTE", detail="signal")
    base = replace(base, sig_bid=q_sig.bid, sig_ask=q_sig.ask)
    side = half_hour_signal(*_sides(q_prev), *_sides(q_sig))
    if side is None:
        return replace(base, status="FLAT_MOVE")
    direction = 1 if side == "C" else -1
    base = replace(base, side=side)

    # the underlying leg (Step A): measured for every direction, whatever the option does
    q_in = _present(underlying, t_entry, cfg)
    if q_in is None:
        return replace(base, status="NO_UNDERLYING_QUOTE", detail="entry")
    und_entry = _mid(q_in)
    q_out = _present(underlying, t_exit, cfg)
    und_exit = None if q_out is None else _mid(q_out)
    base = replace(
        base, und_entry=und_entry, und_exit_time=t_exit, und_exit=und_exit,
        und_exit_reason="TIME" if und_exit is not None else "NO_EXIT_QUOTE",
        und_return=None if und_exit is None else direction * (und_exit / und_entry - 1),
        und_gap_minutes=int(und_exit is None),
    )  # fmt: skip

    # the option leg (D2), at T_e = entry + latency
    t_e = t_entry + timedelta(seconds=cfg.fills.latency_s)
    c = choose_contract(contracts, und_entry, side, t_e)
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
    entry_fill, entry_mid = cons.buy(q), opti.buy(q)
    out = outlay(entry_fill, fees)
    base = replace(base, cost_share=cost_share(bid, ask, fees), outlay=out, entry_fill=entry_fill,
                   entry_mid=entry_mid)  # fmt: skip
    if out > s.max_premium_usd:
        return replace(base, status="PREMIUM_OVER_CAP")
    xq = exit_quote(recs, t_exit, t_exit, cfg)
    if xq is None:
        return replace(base, exit_reason="UNRESOLVED_DATA")
    t_sell, quote = xq
    exit_fill, exit_mid = cons.sell(quote), opti.sell(quote)
    net, ret = trade_pnl(entry_fill, exit_fill, fees)
    net_mid, ret_mid = trade_pnl(entry_mid, exit_mid, fees)
    return replace(
        base, exit_time=t_sell, exit_reason="TIME",
        exit_delay_minutes=int((t_sell - t_exit).total_seconds() // 60),
        exit_no_bid=quote.bid is None, exit_fill=exit_fill, net_usd=net, ret=ret,
        exit_mid=exit_mid, net_usd_mid=net_mid, ret_mid=ret_mid,
    )  # fmt: skip
