"""Event-driven single-session options backtester (spec Phase 1I; §2, §4, §5, §6; M11).

One shared monotonic clock. At each signal (a prediction timestamp T) the engine moves the clock
to T_e = T + latency, first releasing the open position's quotes up to T_e (exits before entries),
then decides:

- position still open at T_e        -> BLOCKED_POSITION_OPEN (§4.7);
- `max_entries_per_day` reached     -> NO_TRADE (MAX_ENTRIES_PER_DAY);
- no spot / no contract / illiquid  -> NO_TRADE with the §5 reason (candidate recorded);
- fill-time hard/age check fails    -> UNFILLED (spec §4.6);
- otherwise ENTERED at the fill model's buy price on the quote in force at T_e.

An open position is checked on the BID at every released quote (target first, then stop; a
single bid cannot be both) until T_end = min(T_e + max holding, forced flat). Path rules match
M6 Q3: rejected records are skipped and flagged, a missing bid is worth 0, a gap longer than
`labels.option.max_path_gap_minutes` or no usable quote within `max_quote_age_s` of T_end makes
the trade UNRESOLVED_DATA (it keeps the position slot until T_end). Overnight holds are
impossible: T_end never passes the forced flat time.

The engine never reads labels; it shares only the frozen selection rule with them.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import polars as pl

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.clock import SimClock
from qqq1dte.core.config import Phase1Config
from qqq1dte.core.pit import AsOfReader
from qqq1dte.execution_sim.accounting import account, classify_time_exit
from qqq1dte.execution_sim.cursor import QuoteCursor
from qqq1dte.execution_sim.fills import Conservative, FillModel, floor_tick
from qqq1dte.execution_sim.selection import (
    Contract,
    NoTrade,
    Quote,
    choose_contract,
    liquidity_failures,
    select_contract,
)

SELECTION_RULE_VERSION = "S1"  # spec §5 (ACCEPTED, OD-3)
FILL_TIME_HARD = {"NO_QUOTE", "REJECTED_QUOTE", "STALE_QUOTE", "NOT_TWO_SIDED", "CROSSED"}


@dataclass(frozen=True)
class Signal:
    ts: datetime  # prediction timestamp T
    side: str  # "C" or "P"


@dataclass(frozen=True)
class Decision:
    prediction_ts: datetime
    side: str
    decision: str  # ENTERED | NO_TRADE | BLOCKED_POSITION_OPEN | UNFILLED
    reason: str | None = None


@dataclass(frozen=True)
class Candidate:
    prediction_ts: datetime
    side: str
    symbol: str
    strike: float
    expiration: date
    quote_ts: datetime | None
    bid: float | None
    ask: float | None
    bid_size: int | None
    ask_size: int | None
    latency_s: int
    passed_gates: bool
    gate_failures: tuple[str, ...]
    selected: bool
    selection_rule_version: str = SELECTION_RULE_VERSION


@dataclass(frozen=True)
class Trade:
    prediction_ts: datetime
    side: str
    symbol: str
    strike: float
    fill_model: str
    outcome: str
    exit_reason: str | None
    entry_ts: datetime | None = None
    entry_price: float | None = None
    entry_bid: float | None = None
    entry_ask: float | None = None
    t_end: datetime | None = None
    target_price: float | None = None
    stop_price: float | None = None
    exit_ts: datetime | None = None
    exit_price: float | None = None
    exit_bid: float | None = None
    exit_ask: float | None = None
    mfe: float | None = None  # best bid over the path, relative to the entry fill
    mae: float | None = None  # worst bid over the path, relative to the entry fill
    gross_pnl: float | None = None
    commissions: float | None = None
    fees: float | None = None
    spread_cost: float | None = None
    net_pnl: float | None = None
    r_multiple: float | None = None
    holding_seconds: int | None = None
    slippage: float | None = None  # latency: entry fill at T_e minus the same fill on T's quote, $
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class SessionResult:
    decisions: list[Decision]
    candidates: list[Candidate]
    trades: list[Trade]


@dataclass
class _Open:
    side: str
    prediction_ts: datetime
    contract: Contract
    cursor: QuoteCursor
    entry_ts: datetime
    entry_price: float
    entry_quote: Quote
    t_end: datetime
    target: float
    stop: float
    last_ok: datetime
    last_quote: Quote
    slippage: float | None = None
    best: float | None = None
    worst: float | None = None
    gap: bool = False
    flags: list[str] = field(default_factory=list)


def _spot(und: pl.DataFrame, t_e: datetime, cfg: Phase1Config) -> float | None:
    """QQQ NBBO mid in force at t_e, if fresh (spec §5 step 2)."""
    q = (
        AsOfReader({"u": und}, t_e)
        .get("u")
        .filter(
            pl.col("bid").is_not_null()
            & pl.col("ask").is_not_null()
            & (pl.col("bid") > 0)
            & (pl.col("bid") <= pl.col("ask"))
        )
        .sort("available_at")
    )
    if not q.height:
        return None
    row = q.row(-1, named=True)
    if (t_e - row["available_at"]).total_seconds() > cfg.liquidity.max_quote_age_s:
        return None
    return float((row["bid"] + row["ask"]) / 2)


class _Session:
    def __init__(
        self,
        session: date,
        und: pl.DataFrame,
        chain: pl.DataFrame,
        records: pl.DataFrame,
        cal: TradingCalendar,
        cfg: Phase1Config,
        fill: FillModel,
    ) -> None:
        self.session, self.und, self.records, self.cal, self.cfg, self.fill = (
            session,
            und,
            records,
            cal,
            cfg,
            fill,
        )
        nxt = cal.next_session(session)
        self.chain = chain.filter(
            (pl.col("session_date") == session) & (pl.col("expiration") == nxt)
        )
        self.clock = SimClock(cal.open_close(session)[0])
        self.latency = timedelta(seconds=cfg.fills.latency_s)
        self.forced = cal.forced_exit_time(session)
        self.max_gap = timedelta(minutes=cfg.labels.option.max_path_gap_minutes)
        self.decisions: list[Decision] = []
        self.candidates: list[Candidate] = []
        self.trades: list[Trade] = []
        self.pos: _Open | None = None
        self.pos_busy_until: datetime | None = None  # unresolved trades hold the slot to T_end
        self.entries = 0

    # -- position --------------------------------------------------------------------------
    def _release(self, t: datetime) -> None:
        """Release the open position's quotes up to t; close it on a trigger or at T_end."""
        p = self.pos
        if p is None:
            return
        for q in p.cursor.advance_to(min(t, p.t_end)):
            if self._on_quote(p, q):
                return
        if t >= p.t_end:
            self._finish(p)

    def _on_quote(self, p: _Open, q: Quote) -> bool:
        if p.gap:
            return False
        if q.rejected:
            p.flags.append("PATH_GAP")
            return False
        if q.available_at - p.last_ok > self.max_gap:
            p.gap = True  # unresolved; resolved at T_end (keeps the slot)
            return False
        if q.available_at - p.last_ok > timedelta(minutes=1):
            p.flags.append("PATH_GAP")
        p.last_ok, p.last_quote = q.available_at, q
        if q.bid is None:
            p.flags.append("NO_BID_AS_ZERO")
        bid = floor_tick(q.bid, self.cfg.fills.tick) if q.bid is not None else 0.0
        p.best = bid if p.best is None else max(p.best, bid)
        p.worst = bid if p.worst is None else min(p.worst, bid)
        for outcome, reason, hit in (
            ("WIN", "TARGET", bid >= p.target - 1e-9),
            ("LOSS", "STOP", bid <= p.stop + 1e-9),
        ):
            if hit:
                self._close(p, outcome, reason, q.available_at, q)
                return True
        return False

    def _finish(self, p: _Open) -> None:
        """No trigger by T_end: time exit on the quote in force, or unresolved."""
        if p.gap or p.t_end - p.last_ok > self.max_gap:
            self._close(p, "UNRESOLVED_DATA", "PATH_GAP_TOO_LONG", None, None)
        elif (p.t_end - p.last_ok).total_seconds() > self.cfg.liquidity.max_quote_age_s:
            self._close(p, "UNRESOLVED_DATA", "NO_EXIT_QUOTE", None, None)
        else:
            self._close(p, "TIME_EXIT", "TIME_EXIT", p.t_end, p.last_quote)

    def _close(
        self, p: _Open, outcome: str, reason: str, exit_ts: datetime | None, q: Quote | None
    ) -> None:
        def rel(x: float | None) -> float | None:
            return None if x is None else (x - p.entry_price) / p.entry_price

        base = {
            "prediction_ts": p.prediction_ts,
            "side": p.side,
            "symbol": p.contract.symbol,
            "strike": p.contract.strike,
            "fill_model": self.fill.name,
            "entry_ts": p.entry_ts,
            "entry_price": p.entry_price,
            "entry_bid": p.entry_quote.bid,
            "entry_ask": p.entry_quote.ask,
            "t_end": p.t_end,
            "target_price": p.target,
            "stop_price": p.stop,
            "mfe": rel(p.best),
            "mae": rel(p.worst),
            "slippage": p.slippage,
            "flags": tuple(dict.fromkeys(p.flags)),
        }
        self.pos = None
        if exit_ts is None or q is None:
            self.pos_busy_until = p.t_end
            self.trades.append(Trade(outcome=outcome, exit_reason=reason, **base))  # type: ignore[arg-type]
            return
        exit_price = self.fill.sell(q)
        a = account(p.entry_price, exit_price, p.entry_quote, q, self.cfg)
        if outcome == "TIME_EXIT":
            outcome = classify_time_exit(a.net_pnl, p.entry_price, self.cfg)
        if outcome == "EXPIRED" or exit_ts > self.forced:  # intraday-only (§4.6, OD-2)
            raise AssertionError("position held past the forced flat time")
        self.trades.append(
            Trade(
                outcome=outcome,
                exit_reason=reason,
                exit_ts=exit_ts,
                exit_price=exit_price,
                exit_bid=q.bid,
                exit_ask=q.ask,
                gross_pnl=a.gross_pnl,
                commissions=a.commissions,
                fees=a.fees,
                spread_cost=a.spread_cost,
                net_pnl=a.net_pnl,
                r_multiple=a.r_multiple,
                holding_seconds=int((exit_ts - p.entry_ts).total_seconds()),
                **base,  # type: ignore[arg-type]
            )
        )

    # -- signals ---------------------------------------------------------------------------
    def _latency_slippage(self, symbol: str, t: datetime, entry: float) -> float | None:
        """Entry fill minus the same model's fill on the quote in force at T (dollars per
        position); None if that quote is not usable. Reads only data <= T <= clock."""
        hist = AsOfReader({"q": self.records}, t).get("q").filter(pl.col("symbol") == symbol)
        if not hist.height:
            return None
        r = hist.sort("available_at").row(-1, named=True)
        q = Quote(r["bid"], r["ask"], r["bid_sz"], r["ask_sz"], r["available_at"], r["rejected"])
        if liquidity_failures(q, t, self.cfg):
            return None
        return (entry - self.fill.buy(q)) * 100 * self.cfg.trade.contracts

    def on_signal(self, s: Signal) -> None:
        t_e = s.ts + self.latency
        self._release(t_e)
        self.clock.advance_to(t_e)
        if self.pos is not None or (self.pos_busy_until is not None and t_e < self.pos_busy_until):
            self.decisions.append(Decision(s.ts, s.side, "BLOCKED_POSITION_OPEN"))
            return
        if self.entries >= self.cfg.trade.max_entries_per_day:
            self.decisions.append(Decision(s.ts, s.side, "NO_TRADE", "MAX_ENTRIES_PER_DAY"))
            return
        spot = _spot(self.und, t_e, self.cfg)
        if spot is None:
            self.decisions.append(Decision(s.ts, s.side, "NO_TRADE", "NO_SPOT"))
            return
        known = AsOfReader({"c": self.chain}, t_e).get("c")
        contracts = [
            Contract(
                r["raw_symbol"], float(r["strike"]), r["right"], r["expiration"], r["available_at"]
            )
            for r in known.iter_rows(named=True)
        ]
        chosen = choose_contract(contracts, spot, s.side, t_e)
        if chosen is None:
            self.decisions.append(Decision(s.ts, s.side, "NO_TRADE", "NO_CONTRACT"))
            return
        cursor = QuoteCursor(
            self.records.filter(pl.col("symbol") == chosen.symbol).sort("available_at"),
            self.clock,
        )
        cursor.advance_to(t_e)
        quote = cursor.latest
        sel = select_contract(
            contracts, spot, s.side, {chosen.symbol: quote} if quote else {}, t_e, self.cfg
        )
        failures = sel.details if isinstance(sel, NoTrade) else ()
        self.candidates.append(
            Candidate(
                s.ts,
                s.side,
                chosen.symbol,
                chosen.strike,
                chosen.expiration,
                quote.available_at if quote else None,
                quote.bid if quote else None,
                quote.ask if quote else None,
                quote.bid_sz if quote else None,
                quote.ask_sz if quote else None,
                self.cfg.fills.latency_s,
                not failures,
                tuple(failures),
                not failures,
            )
        )
        if isinstance(sel, NoTrade) or quote is None:
            reason = sel.reason if isinstance(sel, NoTrade) else "NO_QUOTE"
            self.decisions.append(Decision(s.ts, s.side, "NO_TRADE", reason))
            return
        hard = [f for f in liquidity_failures(quote, t_e, self.cfg) if f in FILL_TIME_HARD]
        if hard:  # fill-time check (spec §4.6 UNFILLED)
            self.decisions.append(Decision(s.ts, s.side, "UNFILLED", hard[0]))
            self.trades.append(
                Trade(
                    s.ts, s.side, chosen.symbol, chosen.strike, self.fill.name, "UNFILLED", hard[0]
                )
            )
            return
        entry = self.fill.buy(quote)
        slippage = self._latency_slippage(chosen.symbol, s.ts, entry)
        opt = self.cfg.labels.option
        self.pos = _Open(
            side=s.side,
            prediction_ts=s.ts,
            contract=chosen,
            cursor=cursor,
            entry_ts=t_e,
            entry_price=entry,
            entry_quote=quote,
            t_end=min(t_e + timedelta(minutes=self.cfg.trade.max_holding_minutes), self.forced),
            target=entry * (1 + opt.target_pct),
            stop=entry * (1 - opt.stop_pct),
            last_ok=quote.available_at,
            last_quote=quote,
            slippage=slippage,
        )
        self.entries += 1
        self.decisions.append(Decision(s.ts, s.side, "ENTERED"))


def run_session(
    session: date,
    signals: Sequence[Signal],
    und: pl.DataFrame,
    chain: pl.DataFrame,
    records: pl.DataFrame,
    cal: TradingCalendar,
    cfg: Phase1Config,
    fill: FillModel | None = None,
) -> SessionResult:
    """Simulate one session. `records` = option quote records (cleaned + rejected), `chain` =
    contract definitions with `available_at`, `und` = QQQ NBBO with `available_at`."""
    allowed = set(cal.prediction_timestamps(session))
    for s in signals:
        if s.ts not in allowed:
            raise ValueError(f"signal at {s.ts} is not a prediction timestamp of {session}")
    if any(b.ts < a.ts for a, b in itertools.pairwise(signals)):
        raise ValueError("signals must be in time order")
    sim = _Session(session, und, chain, records, cal, cfg, fill or Conservative(cfg))
    for s in signals:
        sim.on_signal(s)
    if sim.pos is not None:
        sim._release(sim.pos.t_end)
    return SessionResult(sim.decisions, sim.candidates, sim.trades)
