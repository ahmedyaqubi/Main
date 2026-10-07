"""Per-trade accounting (spec §4.6-4.8, Phase 1I): gross and net P&L, costs, spread cost vs mid,
R multiple, and the time-exit outcome class. All dollar figures are per position
(`trade.contracts` contracts x 100 multiplier)."""

from __future__ import annotations

from dataclasses import dataclass

from qqq1dte.core.config import Phase1Config
from qqq1dte.execution_sim.fills import round_trip_costs
from qqq1dte.execution_sim.selection import Quote

MULTIPLIER = 100


@dataclass(frozen=True)
class Accounting:
    gross_pnl: float
    commissions: float
    fees: float
    net_pnl: float
    spread_cost: float | None  # (fill vs mid) at entry + exit, dollars; None if a mid is unknown
    one_r: float
    r_multiple: float


def _mid(q: Quote) -> float | None:
    if q.bid is None or q.ask is None or q.bid <= 0 or q.ask <= 0:
        return None
    return (q.bid + q.ask) / 2


def account(
    entry_fill: float, exit_fill: float, entry_quote: Quote, exit_quote: Quote, cfg: Phase1Config
) -> Accounting:
    size = cfg.trade.contracts * MULTIPLIER
    commissions, fees = round_trip_costs(cfg)
    gross = (exit_fill - entry_fill) * size
    net = gross - commissions - fees
    em, xm = _mid(entry_quote), _mid(exit_quote)
    spread = None if em is None or xm is None else ((entry_fill - em) + (xm - exit_fill)) * size
    one_r = cfg.labels.option.stop_pct * entry_fill * size + commissions + fees  # §4.7
    return Accounting(gross, commissions, fees, net, spread, one_r, net / one_r)


def classify_time_exit(net_pnl: float, entry_fill: float, cfg: Phase1Config) -> str:
    """§4.6: neither target nor stop touched; classified by net P&L, breakeven band first."""
    band = cfg.trade.breakeven_band * entry_fill * cfg.trade.contracts * MULTIPLIER
    if abs(net_pnl) <= band:
        return "BREAKEVEN"
    return "TIME_EXIT_PROFIT" if net_pnl > 0 else "TIME_EXIT_LOSS"
