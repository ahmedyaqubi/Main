"""ADR-0014 (M23): longer-dated SPX trade-definition helpers. Pure, point-in-time.

- R2: the spread width W is a fixed share of the previous session's close, rounded to the
  strike grid, with a minimum.
- D2: the expiry is the listed session whose calendar DTE is closest to the target; ties go to
  the earlier one. The exit is 15:45 ET on the session before the expiry.
- R5: the minimum detectable effect is an outcome-free upper bound. It uses sigma <= range / 2
  (Popoviciu) and an effective sample size of independent holding periods.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import date
from statistics import NormalDist


def width_from_close(prev_close: float, share: float, grid: float, minimum: float) -> float:
    w = round(prev_close * share / grid) * grid
    return max(minimum, float(w))


def choose_expiry(
    listed: Iterable[date], d: date, target_dte: int, sessions: set[date]
) -> date | None:
    """Listed expiries are those known at T_e (the caller filters by definition availability)."""
    ok = [e for e in listed if e > d and e in sessions]
    if not ok:
        return None
    return min(ok, key=lambda e: (abs((e - d).days - target_dte), e))


def exit_session(expiry: date, sessions: Sequence[date]) -> date | None:
    before = [s for s in sessions if s < expiry]
    return before[-1] if before else None


def mde_upper_bound(
    pnl_range: float, n_eff: float, alpha: float = 0.05, power: float = 0.8
) -> float:
    """Smallest true mean (same units as `pnl_range`) a one-sided level-alpha test detects with
    the given power. The variance is bounded by (range / 2)^2, so this is conservative."""
    if n_eff <= 0:
        return math.inf
    z = NormalDist().inv_cdf(1 - alpha) + NormalDist().inv_cdf(power)
    return z * (pnl_range / 2) / math.sqrt(n_eff)


def select_stored_expiry(
    listed_before: set[date],
    known_today: set[date],
    stored: set[date],
    d: date,
    target_dte: int,
    sessions: set[date],
) -> tuple[str, date | None]:
    """D2 point-in-time expiry choice (M23 leakage review). The candidates are expiries listed
    on an earlier day plus those whose definitions are known at T_e today. The chosen expiry
    is never replaced: if its contracts were not stored, the result is EXPIRY_NOT_STORED."""
    e = choose_expiry(listed_before | known_today, d, target_dte, sessions)
    if e is None:
        return "NO_EXPIRY", None
    return ("OK", e) if e in stored else ("EXPIRY_NOT_STORED", e)
