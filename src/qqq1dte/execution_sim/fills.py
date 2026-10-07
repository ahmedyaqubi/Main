"""Fill models (spec §6) and per-contract costs (§4.8). Fills round AGAINST the trader to the
tick: buys up, sells down. Conservative = ask / bid; moderate = mid +/- alpha x half-spread;
optimistic = mid. Triggers always use the bid (engine); only fill prices differ. A missing bid
sells at 0 in every model (M6 Q3: no mid exists without a bid)."""

from __future__ import annotations

import math
from typing import Protocol

from qqq1dte.core.config import Phase1Config
from qqq1dte.execution_sim.selection import Quote


def ceil_tick(x: float, tick: float) -> float:
    return round(math.ceil(round(x / tick, 6)) * tick, 10)


def floor_tick(x: float, tick: float) -> float:
    return round(math.floor(round(x / tick, 6)) * tick, 10)


def scaled_costs(cfg: Phase1Config, multiplier: float) -> Phase1Config:
    """Config copy with commission and fees scaled (M12 sensitivity); spreads are in fills."""
    costs = cfg.costs.model_copy(
        update={
            "commission_per_contract": cfg.costs.commission_per_contract * multiplier,
            "fees_per_contract": cfg.costs.fees_per_contract * multiplier,
        }
    )
    return cfg.model_copy(update={"costs": costs})


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


class Moderate:
    """Buy mid + alpha (ask - mid), sell mid - alpha (mid - bid) (spec §6, OD-6)."""

    name = "MODERATE"

    def __init__(self, cfg: Phase1Config, alpha: float) -> None:
        if not 0.0 <= alpha <= 1.0:
            raise ValueError("alpha must be in [0, 1]")
        self.tick, self.alpha = cfg.fills.tick, alpha

    def buy(self, quote: Quote) -> float:
        if quote.ask is None or quote.bid is None:
            raise ValueError("cannot price a buy without a two-sided quote")
        mid = (quote.bid + quote.ask) / 2
        return ceil_tick(mid + self.alpha * (quote.ask - mid), self.tick)

    def sell(self, quote: Quote) -> float:
        if quote.bid is None or quote.ask is None:
            return 0.0 if quote.bid is None else floor_tick(quote.bid, self.tick)
        mid = (quote.bid + quote.ask) / 2
        return floor_tick(mid - self.alpha * (mid - quote.bid), self.tick)


class Optimistic(Moderate):
    """Buy and sell at the mid (alpha = 0)."""

    name = "OPTIMISTIC"

    def __init__(self, cfg: Phase1Config) -> None:
        super().__init__(cfg, 0.0)
