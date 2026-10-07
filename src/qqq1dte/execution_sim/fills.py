"""Fill models (spec §6) and per-contract costs (§4.8). Fills round AGAINST the trader to the
tick: buys up, sells down. M11 implements the conservative model; moderate and optimistic come
in M12 behind the same interface. Triggers always use the bid; only fill prices differ."""

from __future__ import annotations

import math
from typing import Protocol

from qqq1dte.core.config import Phase1Config
from qqq1dte.execution_sim.selection import Quote


def ceil_tick(x: float, tick: float) -> float:
    return round(math.ceil(round(x / tick, 6)) * tick, 10)


def floor_tick(x: float, tick: float) -> float:
    return round(math.floor(round(x / tick, 6)) * tick, 10)


def round_trip_costs(cfg: Phase1Config) -> tuple[float, float]:
    """(commissions, fees) in dollars for opening and closing `trade.contracts`."""
    n = 2 * cfg.trade.contracts
    return n * cfg.costs.commission_per_contract, n * cfg.costs.fees_per_contract


class FillModel(Protocol):
    name: str

    def buy(self, quote: Quote) -> float: ...

    def sell(self, quote: Quote) -> float: ...


class Conservative:
    """Buy at the ask, sell at the bid. A missing bid sells at 0 (M6 Q3)."""

    name = "CONSERVATIVE"

    def __init__(self, cfg: Phase1Config) -> None:
        self.tick = cfg.fills.tick

    def buy(self, quote: Quote) -> float:
        if quote.ask is None:
            raise ValueError("cannot buy without an ask")
        return ceil_tick(quote.ask, self.tick)

    def sell(self, quote: Quote) -> float:
        return floor_tick(quote.bid, self.tick) if quote.bid is not None else 0.0
