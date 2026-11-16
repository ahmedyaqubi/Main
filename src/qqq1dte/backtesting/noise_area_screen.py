"""M33 (ADR-0021 D6): the screen of setup S3 (amendment A3), one ticker-session at a time, and
the one-position rule across times of day. The pooled statistics and the risk rows are M29's
(`orb_screen`). Every quote is read as "the latest record with available_at <= T".

Owner rulings of 2026-11-16 (plan approved) implemented here:
1. today's open is the mid of the quote in force `open_offset_minutes` after the open, at most
   max_quote_age_s old, two-sided, not crossed;
2. the previous close is the mid of the quote in force `prev_close_offset_minutes` before the
   previous session's close, same checks (M30 ruling 1);
3. check prices are the quotes in force at the checks; boundaries and sigma use mids; a signal
   and an exit need the whole quote beyond the boundary (`strategies.noise_area`); a check with
   no usable quote is skipped and counted;
4. sigma averages the `lookback_sessions` most recent usable sessions before today; a session
   is usable when it is not an early close and has the open quote and every check quote; fewer:
   NO_HISTORY; a split session: CORPORATE_ACTION;
5. one position at a time across times of day (`apply_one_position_timed`);
6. Step A is the signed return of the underlying mid from the entry check to the exit, on every
   ticker-session with a signal, before any option gate;
7. M29's rulings 3-8 unchanged.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Any

from qqq1dte.backtesting.cost_map import cost_share, outlay
from qqq1dte.backtesting.orb_screen import CANDIDATE, Candidate, exit_quote, pick_one, trade_pnl
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import BrokerFees, Phase1Config
from qqq1dte.core.timeutil import ET, ensure_utc
from qqq1dte.execution_sim.fills import Conservative, Optimistic
from qqq1dte.execution_sim.selection import Contract, Quote, choose_contract, liquidity_failures
from qqq1dte.strategies.noise_area import boundaries, noise_exit, noise_signal, sigma
from qqq1dte.validation.options_day_data import DATA_FAILURES, data_present, quote_at


@dataclass(frozen=True)
class SessionMoves:
    """One usable history session: |mid at each check / that session's open - 1|."""

    session_date: date
    moves: dict[time, float]


@dataclass(frozen=True)
class S3Candidate(Candidate):
    """M29's row plus what the signal was read from."""

    open_mid: float | None = None
    prev_close: float | None = None
    entry_time: datetime | None = None  # the check that gave the signal
    sigma: float | None = None  # at the entry check
    upper: float | None = None
    lower: float | None = None
    checks_skipped: int = 0  # checks up to the exit with no usable underlying quote
    history_dates: tuple[date, ...] = ()


def check_times(first: time, last: time, step_minutes: int) -> list[time]:
    """Every check from `first` to `last`, both included."""
    out, t = [], datetime.combine(date.min, first)
    end = datetime.combine(date.min, last)
    while t <= end:
        out.append(t.time())
        t += timedelta(minutes=step_minutes)
    return out


def _at(d: date, t: time) -> datetime:
    return ensure_utc(datetime.combine(d, t, tzinfo=ET))


def _present(records: Sequence[Quote], t: datetime, cfg: Phase1Config) -> Quote | None:
    q = quote_at(records, t)
    return q if q is not None and data_present(q, t, cfg) else None


def _sides(q: Quote) -> tuple[float, float]:
    assert q.bid is not None and q.ask is not None  # `_present` guarantees a two-sided quote
    return float(q.bid), float(q.ask)


def _mid(q: Quote) -> float:
    bid, ask = _sides(q)
    return (bid + ask) / 2


def _open_mid(
    d: date, underlying: Sequence[Quote], cfg: Phase1Config, cal: TradingCalendar
) -> float | None:
    na = cfg.study_options_day.noise_area
    q = _present(underlying, cal.open_close(d)[0] + timedelta(minutes=na.open_offset_minutes), cfg)
    return None if q is None else _mid(q)


def session_moves(
    d: date, underlying: Sequence[Quote], cfg: Phase1Config, cal: TradingCalendar
) -> SessionMoves | None:
    """The moves of session d for later sessions' sigma, or None when d is not usable history:
    an early close, no usable open quote, or no usable quote at one of the checks."""
    na = cfg.study_options_day.noise_area
    if cal.is_early_close(d):
        return None
    open_ = _open_mid(d, underlying, cfg, cal)
    if open_ is None:
        return None
    moves: dict[time, float] = {}
    for t in check_times(na.first_check, na.last_exit_check, na.check_interval_minutes):
        q = _present(underlying, _at(d, t), cfg)
        if q is None:
            return None
        moves[t] = abs(_mid(q) / open_ - 1)
    return SessionMoves(d, moves)


def session_decision(  # noqa: PLR0911, PLR0912, PLR0913, PLR0915 (one linear decision path)
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
    history: Sequence[SessionMoves],
    excluded: bool = False,
    split: bool = False,
) -> S3Candidate:
    """S3 on one ticker-session. `underlying` holds the previous session's and this session's
    records, sorted by available_at; `prev_session` is the session whose close is "the previous
    close", or None when it is outside the data or excluded; `history` holds usable sessions
    before d (any later one is refused). `contracts` is the D2 expiry's chain. Nothing later
    than the time being decided is read."""
    s = cfg.study_options_day
    na = s.noise_area
    if any(h.session_date >= d for h in history):
        raise ValueError("history must hold sessions before the session being decided")
    base = S3Candidate(ticker, d, CANDIDATE)
    if excluded:
        return replace(base, status="EARNINGS_WINDOW")
    if cal.is_early_close(d):
        return replace(base, status="EARLY_CLOSE")
    if split:
        return replace(base, status="CORPORATE_ACTION")
    hist = sorted(history, key=lambda h: h.session_date)[-na.lookback_sessions :]
    if len(hist) < na.lookback_sessions:
        return replace(base, status="NO_HISTORY", detail=f"{len(hist)} usable sessions")
    base = replace(base, history_dates=tuple(h.session_date for h in hist))
    if prev_session is None:
        return replace(base, status="NO_PREV_CLOSE", detail="no previous session")
    t_prev = cal.open_close(prev_session)[1] - timedelta(minutes=na.prev_close_offset_minutes)
    q_prev = _present(underlying, t_prev, cfg)
    if q_prev is None:
        return replace(base, status="NO_PREV_CLOSE", detail="no usable quote")
    prev_close = _mid(q_prev)
    open_ = _open_mid(d, underlying, cfg, cal)
    if open_ is None:
        return replace(base, prev_close=prev_close, status="NO_UNDERLYING_QUOTE", detail="open")
    base = replace(base, prev_close=prev_close, open_mid=open_)

    def bounds(t: time) -> tuple[float, float, float]:
        sig = sigma([h.moves[t] for h in hist])
        return (sig, *boundaries(open_, prev_close, sig))

    # the signal: the first entry check whose quote is wholly outside the noise area
    checks = check_times(na.first_check, na.last_exit_check, na.check_interval_minutes)
    skipped = 0
    side: str | None = None
    entry_check: time | None = None
    und_entry = 0.0
    for t in checks:
        if t > na.last_entry_check:
            break
        q = _present(underlying, _at(d, t), cfg)
        if q is None:
            skipped += 1
            continue
        sig, upper, lower = bounds(t)
        side = noise_signal(*_sides(q), upper, lower)
        if side is not None:
            entry_check, und_entry = t, _mid(q)
            base = replace(base, side=side, sigma=sig, upper=upper, lower=lower)
            break
    if side is None or entry_check is None:
        return replace(base, status="NO_SIGNAL", checks_skipped=skipped)
    direction = 1 if side == "C" else -1
    t_entry = _at(d, entry_check)
    forced = min(_at(d, na.exit_time), cal.forced_exit_time(d))

    # the underlying leg (Step A): measured for every signal, whatever the option does
    t_x, reason = forced, "NO_EXIT_QUOTE"
    m_x: float | None = None
    for t in checks:
        if t <= entry_check:
            continue
        q = _present(underlying, _at(d, t), cfg)
        if q is None:
            skipped += 1
            continue
        _, upper, lower = bounds(t)
        if noise_exit(side, *_sides(q), upper, lower):
            t_x, reason, m_x = _at(d, t), "OPPOSITE", _mid(q)
            break
    if reason != "OPPOSITE":
        q_out = _present(underlying, forced, cfg)
        if q_out is not None:
            reason, m_x = "TIME", _mid(q_out)
    base = replace(
        base, entry_time=t_entry, und_entry=und_entry, und_exit_time=t_x,
        und_exit_reason=reason, und_exit=m_x,
        und_return=None if m_x is None else direction * (m_x / und_entry - 1),
        checks_skipped=skipped,
    )  # fmt: skip

    # the option leg (D2), at T_e = entry check + latency
    t_e = t_entry + timedelta(seconds=cfg.fills.latency_s)
    c = choose_contract(contracts, und_entry, side, t_e)
    if c is None:
        return replace(base, status="NO_CONTRACT")
    base = replace(base, symbol=c.symbol, strike=c.strike, expiry=c.expiration)
    recs = quotes_for(c.symbol)
    q_opt = quote_at(recs, t_e)
    fails = liquidity_failures(q_opt, t_e, cfg)
    if q_opt is None or set(fails) & DATA_FAILURES:
        return replace(base, status="NO_OPTION_QUOTE", detail=";".join(sorted(fails)))
    bid, ask = float(q_opt.bid), float(q_opt.ask)  # type: ignore[arg-type]
    base = replace(base, bid=bid, ask=ask)
    if fails:
        return replace(base, status="SELECTED_CONTRACT_ILLIQUID", detail=";".join(sorted(fails)))
    cons, opti = Conservative(cfg), Optimistic(cfg)
    entry_fill, entry_mid = cons.buy(q_opt), opti.buy(q_opt)
    out = outlay(entry_fill, fees)
    base = replace(base, cost_share=cost_share(bid, ask, fees), outlay=out, entry_fill=entry_fill,
                   entry_mid=entry_mid)  # fmt: skip
    if out > s.max_premium_usd:
        return replace(base, status="PREMIUM_OVER_CAP")
    xq = exit_quote(recs, t_x, forced, cfg)
    if xq is None:
        return replace(base, exit_reason="UNRESOLVED_DATA")
    t_sell, quote = xq
    exit_fill, exit_mid = cons.sell(quote), opti.sell(quote)
    net, ret = trade_pnl(entry_fill, exit_fill, fees)
    net_mid, ret_mid = trade_pnl(entry_mid, exit_mid, fees)
    return replace(
        base, exit_time=t_sell, exit_reason=reason if reason != "NO_EXIT_QUOTE" else "TIME",
        exit_delay_minutes=int((t_sell - t_x).total_seconds() // 60),
        exit_no_bid=quote.bid is None, exit_fill=exit_fill, net_usd=net, ret=ret,
        exit_mid=exit_mid, net_usd_mid=net_mid, ret_mid=ret_mid,
    )  # fmt: skip


# the one-position rule across times of day (ruling 5) ---------------------------------------
_OPTION_PNL = ("exit_time", "exit_reason", "exit_delay_minutes", "exit_no_bid", "exit_fill",
               "net_usd", "ret", "exit_mid", "net_usd_mid", "ret_mid")  # fmt: skip


def apply_one_position_timed(rows: list[dict[str, Any]], order: list[str]) -> list[dict[str, Any]]:
    """D3 with entries at different checks. Per session, candidates are taken in the order of
    their entry check. A position is open from its entry until its option is sold (to the end
    of the session when the sale is unresolved). A candidate whose check is at or before that
    sale is POSITION_OPEN and its option exit is blanked (it was never a trade). Candidates at
    the same check compete: the lowest cost share, ties to the earlier name in `order`."""
    by_day: dict[date, list[dict[str, Any]]] = {}
    for r in rows:
        if r["status"] == CANDIDATE:
            by_day.setdefault(r["session_date"], []).append(r)
    for cands in by_day.values():
        busy_until: datetime | None = None  # the open position's sale minute
        busy_all_day = False
        for t in sorted({r["entry_time"] for r in cands}):
            group = sorted(
                (r for r in cands if r["entry_time"] == t), key=lambda r: order.index(r["ticker"])
            )
            free = not busy_all_day and (busy_until is None or t > busy_until)
            keep = pick_one([(r["ticker"], r["cost_share"]) for r in group]) if free else None
            for r in group:
                if r["ticker"] == keep:
                    r["status"] = "TRADE"
                    busy_until = r["exit_time"]
                    busy_all_day = r["exit_time"] is None
                else:
                    r["status"] = "POSITION_OPEN"
                    for k in _OPTION_PNL:
                        r[k] = None
    return rows
