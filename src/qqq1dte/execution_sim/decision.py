"""Decision engine (spec §4.1, Phase 1N; M15). NO_TRADE is a first-class output (rule 10).

Per side (CALL = C_call, PUT = C_put), at prediction time T with selection at T_e:
1. a calibrated probability must exist (else NO_TRADE UNCALIBRATED, T-CAL-04; rule 6);
2. the frozen selection rule and §4.9 gates must pass (else the selection reason);
3. calibrated_p - p_breakeven > decision.edge_margin (else BELOW_BREAKEVEN_MARGIN);
4. EV after costs at the moderate entry fill > 0 (else NEGATIVE_EV).
A listed regime cell is NO_TRADE REGIME_BLOCKED (gate 13 mechanism). If both sides qualify the
higher EV wins; an exact tie is NO_TRADE SIDE_TIE. Position limits (BLOCKED_POSITION_OPEN) are
applied by the backtest engine, separately from these reasons.

EV model `binary_conservative` (owner, M15 Q1): the calibrated probability is P(WIN); every
non-WIN outcome is treated as the full stop. With entry E per share and size = contracts x 100:
EV = p * target_pct * E * size - (1 - p) * stop_pct * E * size - round-trip costs, and
p_breakeven = (stop_pct * E * size + costs) / ((target_pct + stop_pct) * E * size).

`CalibratedProbability` is the only probability type accepted: a raw score is rejected at
runtime and by mypy."""

from __future__ import annotations

from dataclasses import dataclass

from qqq1dte.core.config import Phase1Config

UNCALIBRATED = "UNCALIBRATED"
REGIME_BLOCKED = "REGIME_BLOCKED"
BELOW_BREAKEVEN_MARGIN = "BELOW_BREAKEVEN_MARGIN"
NEGATIVE_EV = "NEGATIVE_EV"
SIDE_TIE = "SIDE_TIE"
SIDE_NAME = {"C": "CALL", "P": "PUT"}
MULTIPLIER = 100


class CalibratedProbability(float):
    """A probability produced by a fitted calibrator, tagged with its calibration version."""

    calibration_version_id: str

    def __new__(cls, value: float, calibration_version_id: str) -> CalibratedProbability:
        if not calibration_version_id:
            raise ValueError("a calibrated probability needs a calibration version id")
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"probability {value} outside [0, 1]")
        obj = super().__new__(cls, value)
        obj.calibration_version_id = calibration_version_id
        return obj


@dataclass(frozen=True)
class SideInput:
    side: str  # "C" or "P"
    p: CalibratedProbability | None  # None: no calibrated probability
    selection_reason: str | None  # None: contract selected and §4.9 gates passed at T_e
    entry_price: float | None  # entry fill (decision.ev_fill_model) on the quote at T_e


@dataclass(frozen=True)
class DecisionOutcome:
    decision: str  # CALL | PUT | NO_TRADE
    reasons: tuple[str, ...]
    ev_call: float | None = None
    ev_put: float | None = None
    margin_call: float | None = None
    margin_put: float | None = None


def _size(cfg: Phase1Config) -> float:
    return float(cfg.trade.contracts * MULTIPLIER)


def _costs(cfg: Phase1Config) -> float:
    n = 2 * cfg.trade.contracts
    return n * (cfg.costs.commission_per_contract + cfg.costs.fees_per_contract)


def breakeven_probability(entry: float, cfg: Phase1Config) -> float:
    o = cfg.labels.option
    loss = o.stop_pct * entry * _size(cfg)
    return (loss + _costs(cfg)) / ((o.target_pct + o.stop_pct) * entry * _size(cfg))


def expected_value(p: float, entry: float, cfg: Phase1Config) -> float:
    o = cfg.labels.option
    win, loss = o.target_pct * entry * _size(cfg), o.stop_pct * entry * _size(cfg)
    return p * win - (1 - p) * loss - _costs(cfg)


def _side(s: SideInput, cfg: Phase1Config) -> tuple[float | None, float | None, str | None]:
    """(EV, margin, failure reason) for one side; reason None = qualifies."""
    if s.selection_reason is not None or s.entry_price is None or s.p is None:
        return None, None, s.selection_reason or "NO_ENTRY_PRICE"
    margin = float(s.p) - breakeven_probability(s.entry_price, cfg)
    ev = expected_value(float(s.p), s.entry_price, cfg)
    if margin <= cfg.decision.edge_margin:
        return ev, margin, BELOW_BREAKEVEN_MARGIN
    if ev <= 0:
        return ev, margin, NEGATIVE_EV
    return ev, margin, None


def decide(
    call: SideInput, put: SideInput, cfg: Phase1Config, regime_cell: str | None = None
) -> DecisionOutcome:
    for s in (call, put):
        if s.p is not None and not isinstance(s.p, CalibratedProbability):
            raise TypeError("decisions accept only CalibratedProbability, never raw scores")
    if call.p is None or put.p is None:
        return DecisionOutcome("NO_TRADE", (UNCALIBRATED,))
    if regime_cell is not None and regime_cell in cfg.decision.blocked_regime_cells:
        return DecisionOutcome("NO_TRADE", (REGIME_BLOCKED,))
    ev_c, m_c, r_c = _side(call, cfg)
    ev_p, m_p, r_p = _side(put, cfg)
    base = {"ev_call": ev_c, "ev_put": ev_p, "margin_call": m_c, "margin_put": m_p}
    if r_c is not None and r_p is not None:
        return DecisionOutcome("NO_TRADE", (f"CALL:{r_c}", f"PUT:{r_p}"), **base)
    if r_c is None and r_p is None:
        assert ev_c is not None and ev_p is not None
        if ev_c == ev_p:
            return DecisionOutcome("NO_TRADE", (SIDE_TIE,), **base)
        return DecisionOutcome("CALL" if ev_c > ev_p else "PUT", (), **base)
    return DecisionOutcome("CALL" if r_c is None else "PUT", (), **base)
