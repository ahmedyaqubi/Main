"""Option-outcome labels C_call / C_put (spec §3 C, §4.6, §5, §6; owner decisions M6 Q1-Q4).

Entry at T_e = T + latency with the conservative fill (ask of the quote in force at T_e) on
the contract chosen by the frozen rule (`execution_sim.selection`). The path after T_e is read
through a ForwardWindowReader up to T_end and checked on the BID at 1-minute resolution:
WIN if bid >= (1 + target) * entry first, LOSS if bid <= (1 - stop) * entry first, otherwise a
time exit at T_end classified by net P&L. Missing bid -> 0 (cannot sell). Rejected records are
skipped and flagged. A gap longer than max_path_gap_minutes, or no fresh quote at T_end, gives
UNRESOLVED_DATA. No contract or a failed §4.9 gate gives INVALID (excluded from training).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import polars as pl

from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config, StudyDefinition
from qqq1dte.core.pit import AsOfReader, ForwardWindowReader
from qqq1dte.execution_sim.selection import (
    Contract,
    NoTrade,
    Quote,
    Selected,
    choose_contract,
    select_contract,
)
from qqq1dte.labels.common import INVALID, LabelRow, label_t_end
from qqq1dte.labels.underlying import STOP_FIRST, und_bracket

UNRESOLVED_DATA = "UNRESOLVED_DATA"
UND_STOP, UND_TARGET = "UND_STOP", "UND_TARGET"
SIDE_ID = {"C": "C_call", "P": "C_put"}


@dataclass(frozen=True)
class ExitRule:
    """How a trade exits. The Phase 1 rule (spec §3 C: +30% / -20% on the bid, cap = label
    horizon) is the default; other rules exist only for the ADR-0012 study. A missing option
    target/stop disables that trigger; a QQQ bracket (und_stop/und_target, relative to P_T) exits
    at the option bid in force when the triggering bar is known."""

    cap_minutes: int
    option_target: float | None
    option_stop: float | None
    und_stop: float | None = None
    und_target: float | None = None
    strike_offset: int = 0

    @classmethod
    def phase1(cls, cfg: Phase1Config) -> ExitRule:
        o = cfg.labels.option
        return cls(cfg.labels.horizon_minutes, o.target_pct, o.stop_pct)

    @classmethod
    def from_study(cls, d: StudyDefinition) -> ExitRule:
        return cls(
            d.cap_minutes, d.option_target, d.option_stop, d.und_stop, d.und_target, d.strike_offset
        )


@dataclass(frozen=True)
class OptionOutcome:
    side: str
    prediction_ts: datetime
    spot: float | None
    contract: str | None
    strike: float | None
    entry_ts: datetime | None
    entry_price: float | None
    exit_ts: datetime | None
    exit_price: float | None
    exit_reason: str | None
    mfe: float | None  # best bid relative to entry over the path
    mae: float | None  # worst bid relative to entry over the path
    net_pnl: float | None  # per contract, after round-trip commissions and fees
    outcome_class: str
    reason: str | None


_DT = pl.Datetime("ns", "UTC")
OUTCOME_SCHEMA: dict[str, pl.DataType] = {
    "side": pl.String(),
    "prediction_ts": _DT,
    "spot": pl.Float64(),
    "contract": pl.String(),
    "strike": pl.Float64(),
    "entry_ts": _DT,
    "entry_price": pl.Float64(),
    "exit_ts": _DT,
    "exit_price": pl.Float64(),
    "exit_reason": pl.String(),
    "mfe": pl.Float64(),
    "mae": pl.Float64(),
    "net_pnl": pl.Float64(),
    "outcome_class": pl.String(),
    "reason": pl.String(),
}


def option_records(cleaned: pl.DataFrame, rejected: pl.DataFrame) -> pl.DataFrame:
    """Per-contract quote records (cleaned + rejected) for label paths."""
    good = cleaned.select(
        "symbol",
        "available_at",
        "bid",
        "ask",
        bid_sz=pl.col("bid_sz").cast(pl.Int64),
        ask_sz=pl.col("ask_sz").cast(pl.Int64),
        rejected=pl.lit(False),
    )
    bad = rejected.select(
        "symbol",
        available_at=pl.col("ts"),
        bid=pl.lit(None, pl.Float64),
        ask=pl.lit(None, pl.Float64),
        bid_sz=pl.lit(None, pl.Int64),
        ask_sz=pl.lit(None, pl.Int64),
        rejected=pl.lit(True),
    )
    return pl.concat([good, bad]).sort(["symbol", "available_at"])


def _floor_cent(x: float) -> float:
    return math.floor(round(x * 100, 6)) / 100


def _ceil_cent(x: float) -> float:
    return math.ceil(round(x * 100, 6)) / 100


def _spot(und: pl.DataFrame, t_e: datetime, cfg: Phase1Config) -> float | None:
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


@dataclass(frozen=True)
class _Path:
    outcome: str | None  # WIN / LOSS / GAP / None (no trigger)
    exit_ts: datetime | None
    exit_px: float | None
    last_ok: datetime
    last_bid: float | None
    best: float | None
    worst: float | None
    flags: tuple[str, ...]


def _walk(
    path: pl.DataFrame,
    start: datetime,
    entry: float,
    cfg: Phase1Config,
    target_pct: float | None,
    stop_pct: float | None,
) -> _Path:
    """Scan the post-entry path on the bid (M6 Q3); a None target/stop never triggers."""
    tgt = entry * (1 + target_pct) if target_pct is not None else math.inf
    stop = entry * (1 - stop_pct) if stop_pct is not None else -math.inf
    max_gap = timedelta(minutes=cfg.labels.option.max_path_gap_minutes)
    flags: list[str] = []
    last_ok, last_bid = start, None
    best: float | None = None
    worst: float | None = None
    for r in path.iter_rows(named=True):
        if r["rejected"]:
            flags.append("PATH_GAP")
            continue
        if r["available_at"] - last_ok > max_gap:
            return _Path(
                "GAP", None, None, last_ok, last_bid, best, worst, tuple(dict.fromkeys(flags))
            )
        if r["available_at"] - last_ok > timedelta(minutes=1):
            flags.append("PATH_GAP")
        last_ok = r["available_at"]
        if r["bid"] is None:
            flags.append("NO_BID_AS_ZERO")
        bid = _floor_cent(float(r["bid"])) if r["bid"] is not None else 0.0
        last_bid = bid
        best = bid if best is None else max(best, bid)
        worst = bid if worst is None else min(worst, bid)
        for name, hit in (("WIN", bid >= tgt - 1e-9), ("LOSS", bid <= stop + 1e-9)):
            if hit:
                return _Path(
                    name,
                    r["available_at"],
                    bid,
                    last_ok,
                    last_bid,
                    best,
                    worst,
                    tuple(dict.fromkeys(flags)),
                )
    return _Path(None, None, None, last_ok, last_bid, best, worst, tuple(dict.fromkeys(flags)))


def _entry_selection(  # noqa: PLR0913 (data tables + study strike offset)
    side: str,
    t_e: datetime,
    session: date,
    und: pl.DataFrame,
    chain: pl.DataFrame,
    records: pl.DataFrame,
    cal: TradingCalendar,
    cfg: Phase1Config,
    *,
    strike_offset: int = 0,
) -> tuple[float | None, Contract | None, Selected | NoTrade]:
    """Spot, chosen contract and the gated selection, all from data known at T_e."""
    spot = _spot(und, t_e, cfg)
    if spot is None:
        return None, None, NoTrade("NO_SPOT")
    nxt = cal.next_session(session)
    known = (
        AsOfReader({"c": chain}, t_e)
        .get("c")
        .filter((pl.col("session_date") == session) & (pl.col("expiration") == nxt))
    )
    contracts = [
        Contract(
            r["raw_symbol"], float(r["strike"]), r["right"], r["expiration"], r["available_at"]
        )
        for r in known.iter_rows(named=True)
    ]
    chosen = choose_contract(contracts, spot, side, t_e, strike_offset)
    quotes: dict[str, Quote] = {}
    if chosen is not None:
        hist = AsOfReader({"q": records}, t_e).get("q").filter(pl.col("symbol") == chosen.symbol)
        if hist.height:
            q = hist.sort("available_at").row(-1, named=True)
            quotes[chosen.symbol] = Quote(
                q["bid"], q["ask"], q["bid_sz"], q["ask_sz"], q["available_at"], bool(q["rejected"])
            )
    return spot, chosen, select_contract(contracts, spot, side, quotes, t_e, cfg, strike_offset)


def option_label(  # noqa: PLR0913 (data tables + optional study exit rule)
    side: str,
    t: datetime,
    session: date,
    und: pl.DataFrame,
    chain: pl.DataFrame,
    records: pl.DataFrame,
    cal: TradingCalendar,
    cfg: Phase1Config,
    *,
    rule: ExitRule | None = None,
    bars: pl.DataFrame | None = None,
) -> tuple[LabelRow, OptionOutcome]:
    """C label / trade outcome at T under `rule` (default: the Phase 1 rule). `bars` (QQQ 1-min
    bars) are needed only for a QQQ-bracket rule."""
    rule = rule or ExitRule.phase1(cfg)
    lid = SIDE_ID[side]
    t_end = label_t_end(t, session, cal, cfg, rule.cap_minutes)
    t_e = t + timedelta(seconds=cfg.fills.latency_s)
    spot, chosen, sel = _entry_selection(
        side, t_e, session, und, chain, records, cal, cfg, strike_offset=rule.strike_offset
    )
    if isinstance(sel, NoTrade):
        return (
            LabelRow(lid, "", None, INVALID, t_end, reason=sel.reason, flags=sel.details),
            OptionOutcome(
                side,
                t,
                spot,
                chosen.symbol if chosen else None,
                chosen.strike if chosen else None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                INVALID,
                sel.reason,
            ),
        )

    entry = _ceil_cent(_num(sel.quote.ask))  # conservative: pay the ask, rounded against us
    und_hit, ambiguous, reason = None, False, None
    exit_by = t_end  # end of the option path: T_end, or when a QQQ-bracket trigger is known
    if rule.und_stop is not None and rule.und_target is not None:
        if bars is None:
            raise ValueError("a QQQ-bracket exit rule needs the QQQ bars")
        und_hit, hit_at, ambiguous, reason = und_bracket(
            bars, session, t, t_end, cal, side, rule.und_stop, rule.und_target
        )
        exit_by = hit_at or t_end
    path = (
        ForwardWindowReader({"q": records}, start=t_e, end=exit_by)
        .get("q")
        .filter(pl.col("symbol") == sel.contract.symbol)
        .sort("available_at")
    )
    p = _walk(path, sel.quote.available_at, entry, cfg, rule.option_target, rule.option_stop)
    max_gap = timedelta(minutes=cfg.labels.option.max_path_gap_minutes)
    if reason is not None:
        pass  # QQQ window unusable (missing bar / no reference price): never filled
    elif p.outcome == "GAP" or (p.outcome is None and exit_by - p.last_ok > max_gap):
        reason = "PATH_GAP_TOO_LONG"
    elif (
        p.outcome is None and (exit_by - p.last_ok).total_seconds() > cfg.liquidity.max_quote_age_s
    ):
        reason = "NO_EXIT_QUOTE"
    if reason is not None:
        return (
            LabelRow(lid, "", None, UNRESOLVED_DATA, t_end, reason=reason, flags=p.flags),
            OptionOutcome(
                side,
                t,
                spot,
                sel.contract.symbol,
                sel.contract.strike,
                t_e,
                entry,
                None,
                None,
                None,
                _rel(p.best, entry),
                _rel(p.worst, entry),
                None,
                UNRESOLVED_DATA,
                reason,
            ),
        )
    costs = (
        2 * (cfg.costs.commission_per_contract + cfg.costs.fees_per_contract) * cfg.trade.contracts
    )
    if p.outcome is not None:
        outcome, exit_ts, exit_px = p.outcome, p.exit_ts, _num(p.exit_px)
    elif und_hit is not None:  # QQQ bracket: the option bid in force when the bar is known
        outcome = UND_STOP if und_hit == STOP_FIRST else UND_TARGET
        exit_ts, exit_px = exit_by, p.last_bid if p.last_bid is not None else 0.0
    else:  # time exit at T_end on the bid in force then (a missing bid counts as 0)
        exit_ts, exit_px = t_end, p.last_bid if p.last_bid is not None else 0.0
        net = (exit_px - entry) * 100 * cfg.trade.contracts - costs
        band = cfg.trade.breakeven_band * entry * 100 * cfg.trade.contracts
        outcome = (
            "BREAKEVEN" if abs(net) <= band else "TIME_EXIT_PROFIT" if net > 0 else "TIME_EXIT_LOSS"
        )
    net = (exit_px - entry) * 100 * cfg.trade.contracts - costs
    return (
        LabelRow(
            lid,
            "",
            1 if outcome == "WIN" else 0,
            outcome,
            t_end,
            ambiguous_bar=ambiguous,
            flags=p.flags,
        ),
        OptionOutcome(
            side,
            t,
            spot,
            sel.contract.symbol,
            sel.contract.strike,
            t_e,
            entry,
            exit_ts,
            exit_px,
            outcome,
            _rel(p.best, entry),
            _rel(p.worst, entry),
            net,
            outcome,
            None,
        ),
    )


def _num(x: float | None) -> float:
    if x is None:
        raise ValueError("expected a price")
    return float(x)


def _rel(x: float | None, entry: float) -> float | None:
    return None if x is None else x / entry - 1
