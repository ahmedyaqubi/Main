"""Decision entry point (spec §4.1; rule 6). M13 delivers the calibration guard only: without a
calibration version, or without calibrated probabilities for both sides, the decision is
NO_TRADE (UNCALIBRATED, T-CAL-04). With them it is still NO_TRADE (DECISION_RULE_PENDING) until
M15 implements the §4.1 rule. CALL/PUT cannot be emitted from this module before M15.

`CalibratedProbability` is the only probability type the engine accepts: a raw model score is
a float and is rejected at runtime and by mypy (rule 6)."""

from __future__ import annotations

from dataclasses import dataclass

UNCALIBRATED = "UNCALIBRATED"
CALIBRATION_VERSION_MISMATCH = "CALIBRATION_VERSION_MISMATCH"
DECISION_RULE_PENDING = "DECISION_RULE_PENDING"  # §4.1 rule arrives in M15


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
class DecisionOutcome:
    decision: str  # CALL | PUT | NO_TRADE
    reasons: tuple[str, ...]


def decide(
    p_call: CalibratedProbability | None,
    p_put: CalibratedProbability | None,
    calibration_version_id: str | None,
) -> DecisionOutcome:
    for p in (p_call, p_put):
        if p is not None and not isinstance(p, CalibratedProbability):
            raise TypeError("decisions accept only CalibratedProbability, never raw scores")
    if calibration_version_id is None or p_call is None or p_put is None:
        return DecisionOutcome("NO_TRADE", (UNCALIBRATED,))
    if {p_call.calibration_version_id, p_put.calibration_version_id} != {calibration_version_id}:
        return DecisionOutcome("NO_TRADE", (CALIBRATION_VERSION_MISMATCH,))
    return DecisionOutcome("NO_TRADE", (DECISION_RULE_PENDING,))
