"""ADR-0022 (M32): the evening instruction for paper trading the frozen ADR-0018 rule.

Pure functions. The signals come from `strategies.pullback.signals`, the frozen M27 code, on the
dividend-adjusted closes up to and including the data date. Nothing here places, sends or
routes an order (hard rule 1): the output is a line of text that the owner acts on by hand.

- **Flat:** an entry signal gives BUY floor(trade_usd / unadjusted close) shares (amendment A1
  R1), unless a loss limit has stopped trading (A1 R4).
- **In a position:** an exit signal gives SELL all held shares, also when stopped.
- Otherwise NO ACTION.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

import polars as pl

from qqq1dte.core.config import StudyPullback
from qqq1dte.strategies.pullback import rsi_wilder, signals, sma

NY = ZoneInfo("America/New_York")
_EPS = 1e-9
Action = Literal["BUY", "SELL", "NO_ACTION"]


class EveningRefusalError(RuntimeError):
    """The evening script must not issue an instruction; the message says why."""


@dataclass(frozen=True)
class Instruction:
    data_date: date
    action: Action
    shares: int
    close: float  # unadjusted, sizes the order (A1 R1)
    adj_close: float  # the signal series
    rsi: float | None
    sma_trend: float | None
    sma_exit: float | None
    entry_signal: bool
    exit_signal: bool
    position_before: int
    halted: bool


def share_count(trade_usd: float, close: float) -> int:
    n = math.floor(trade_usd / close + _EPS)
    if n <= 0:
        raise EveningRefusalError(f"${trade_usd:,.2f} buys 0 shares at {close}")
    return n


def evening_instruction(
    dates: Sequence[date],
    close: Sequence[float],
    adj_close: Sequence[float],
    position_shares: int,
    halted: bool,
    rule: StudyPullback,
    trade_usd: float,
) -> Instruction:
    if not (len(dates) == len(close) == len(adj_close)) or not dates:
        raise ValueError("dates, close and adj_close must be equal-length and non-empty")
    if position_shares < 0:
        raise ValueError("position cannot be negative")
    entry, exit_ = signals(
        adj_close, rule.rsi_period, rule.rsi_entry, rule.sma_trend, rule.sma_exit
    )
    action: Action = "NO_ACTION"
    shares = 0
    if position_shares > 0:
        if exit_[-1]:
            action, shares = "SELL", position_shares
    elif entry[-1] and not halted:
        action, shares = "BUY", share_count(trade_usd, close[-1])
    return Instruction(
        data_date=dates[-1],
        action=action,
        shares=shares,
        close=close[-1],
        adj_close=adj_close[-1],
        rsi=rsi_wilder(adj_close, rule.rsi_period)[-1],
        sma_trend=sma(adj_close, rule.sma_trend)[-1],
        sma_exit=sma(adj_close, rule.sma_exit)[-1],
        entry_signal=entry[-1],
        exit_signal=exit_[-1],
        position_before=position_shares,
        halted=halted,
    )


def instruction_text(ins: Instruction, ticker: str) -> str:
    if ins.action == "NO_ACTION":
        if ins.halted and ins.entry_signal and ins.position_before == 0:
            return "NO ACTION (loss-limit stop: the BUY signal is not issued; owner review)"
        return "NO ACTION"
    return f"{ins.action} {ins.shares} {ticker} market-on-open"


def paper_data_date(
    now: datetime, sessions: Sequence[date], cutoff: time, opens: Mapping[date, datetime]
) -> tuple[date, date]:
    """(data date, the session whose open the instruction is for) at `now`.

    The data date is the last session whose bar is past the cut-off (New York time). Its
    instruction is valid until the next session's open; after that it is missed, never placed
    late (rule 8)."""
    if now.tzinfo is None:
        raise ValueError("now must carry a timezone")
    local = now.astimezone(NY)
    done = [
        d for d in sessions if d < local.date() or (d == local.date() and local.time() >= cutoff)
    ]
    if not done:
        raise EveningRefusalError("no completed session before now")
    data_date = done[-1]
    later = [d for d in sessions if d > data_date]
    if not later:
        raise EveningRefusalError(f"the calendar has no session after {data_date}")
    nxt = later[0]
    if now >= opens[nxt]:
        raise EveningRefusalError(
            f"{data_date}'s instruction was for the {nxt} open, which has passed: missed"
            + (
                f"; {nxt}'s bar is not used before {cutoff:%H:%M} New York"
                if nxt == local.date()
                else ""
            )
        )
    return data_date, nxt


def revisions(old: pl.DataFrame, new: pl.DataFrame) -> list[tuple[date, str, float, float]]:
    """Changed open, close or adjusted close on dates present in both downloads (A1 R3)."""
    cols = ["open", "close", "adj_close"]
    j = old.select("date", *cols).join(new.select("date", *cols), on="date", suffix="_new")
    out = []
    for row in j.sort("date").iter_rows(named=True):
        for c in cols:
            if row[c] != row[f"{c}_new"]:
                out.append((row["date"], c, float(row[c]), float(row[f"{c}_new"])))
    return out
