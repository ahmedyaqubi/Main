"""Check catalogue (docs/DATA_QUALITY.md): every check has a fixed name, action and severity."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# Bump whenever a check's logic changes: it is part of every cleaned dataset_id, so changed
# rules can never be confused with (or skip writing over) results from older rules.
# v1: initial M4; v2: ADR-0005 contract rules + NO_EVENT_TS + ZERO_QUOTE.
DQ_RULES_VERSION = "2"


class Action(StrEnum):
    REJECT = "REJECTED"
    FLAG = "FLAGGED"
    NONE = "NONE"


class Severity(StrEnum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class Check:
    name: str
    action: Action
    severity: Severity
    rule: str


_R, _F, _N = Action.REJECT, Action.FLAG, Action.NONE
_I, _W, _C = Severity.INFO, Severity.WARN, Severity.CRITICAL

CHECKS: dict[str, Check] = {
    c.name: c
    for c in (
        # record-level: rejected
        Check("TS_AFTER_INGEST", _R, _W, "record timestamp later than ingested_at"),
        Check("TS_EVENT_AFTER_RECV", _R, _W, "ts_event > ts_recv beyond allowed skew"),
        Check("DUP_EXACT", _R, _W, "identical row repeated; extra copies rejected"),
        Check("DUP_CONFLICT", _R, _W, "same key, different values; all copies rejected"),
        Check("PRICE_NONPOSITIVE", _R, _W, "bar O/H/L/C undefined or <= 0"),
        Check("OHLC_INCONSISTENT", _R, _W, "bar high/low inconsistent with open/close"),
        Check("NONPOSITIVE_PRICE", _R, _W, "defined bid < 0 or defined ask <= 0"),
        Check("BID_GT_ASK", _R, _W, "crossed quote"),
        Check("CONTRACT_UNKNOWN", _R, _W, "no definition for the contract"),
        Check("NOT_YET_LISTED", _R, _W, "quote before the contract first appears"),
        Check("SYMBOL_MISMATCH", _R, _W, "definition and symbol mapping disagree"),
        Check("INVALID_MULTIPLIER", _R, _W, "known contract multiplier != 100"),
        Check("NONSTANDARD_ROOT", _R, _W, "OCC root is not the standard series root"),
        Check("NONSTANDARD_STRIKE", _R, _W, "strike not a multiple of dq.strike_increment"),
        Check("EXPIRATION_MISMATCH", _R, _W, "definition expiration != OCC symbol date"),
        Check("EXPIRATION_NOT_SESSION", _R, _W, "expiration is not an exchange session"),
        # record-level: flagged (kept)
        Check("NO_BID", _F, _I, "bid side undefined"),
        Check("NO_ASK", _F, _I, "ask side undefined"),
        Check("EMPTY_BOOK", _F, _I, "both sides undefined"),
        Check("ZERO_BID", _F, _I, "defined bid equals 0"),
        Check("ZERO_QUOTE", _F, _I, "bid and ask both 0: no market"),
        Check("NO_EVENT_TS", _F, _I, "ts_event undefined: no update during the interval"),
        Check("MULTIPLIER_UNKNOWN", _F, _I, "vendor does not publish the multiplier (ADR-0005)"),
        Check("ADJUSTED_STRIKE", _F, _I, "strike matches a documented OCC adjustment (ADR-0005)"),
        Check("OUTSIDE_RTH", _F, _I, "outside regular trading hours"),
        Check("NON_SESSION", _F, _I, "date is not an exchange session"),
        # session-level
        Check("MISSING_BAR", _N, _W, "expected RTH bar labels absent"),
        Check("BAR_COVERAGE_LOW", _N, _C, "RTH bar coverage below dq.min_bar_coverage"),
        Check("NO_1DTE_EXPIRY", _N, _C, "next-session expiration not in definitions"),
        Check("CHAIN_COVERAGE_LOW", _N, _C, "valid frozen-rule chain share below threshold"),
        Check("INVALID_QUOTE_RATE_HIGH", _N, _W, "ATM rejected-quote rate above threshold"),
    )
}
