"""Guarded Databento downloads: price first (free), cap the spend, retry, write atomically.

Network access only through a client object with `metadata.get_cost` and
`timeseries.get_range` (the databento SDK's `Historical`), so tests use a fake. Market data
only: this module never touches order APIs.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from functools import partial
from pathlib import Path
from typing import Any

MAX_SYMBOLS_PER_REQUEST = 1000


# The client is duck-typed: anything with `metadata.get_cost(**kw)` and
# `timeseries.get_range(**kw, path=...)`, i.e. databento.Historical or a test fake.
Client = Any


@dataclass(frozen=True)
class RetryPolicy:
    """Which errors are transient (e.g. 504 gateway timeouts) and how to back off."""

    retry_on: tuple[type[BaseException], ...] = ()
    tries: int = 6
    backoff_s: float = 5.0


NO_RETRY = RetryPolicy()


class CostCapExceededError(RuntimeError):
    """The priced total is above the approved cap; nothing was downloaded."""


@dataclass(frozen=True)
class FetchRequest:
    dataset: str
    schema: str
    start: date
    end: date  # exclusive
    symbols: tuple[str, ...]
    stype_in: str
    path: Path

    def kwargs(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "schema": self.schema,
            "stype_in": self.stype_in,
            "symbols": list(self.symbols),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }


@dataclass
class PricedPlan:
    priced: list[FetchRequest] = field(default_factory=list)
    costs: list[float] = field(default_factory=list)
    unresolved: list[FetchRequest] = field(default_factory=list)
    already_present: list[FetchRequest] = field(default_factory=list)

    @property
    def total_usd(self) -> float:
        return float(sum(self.costs))


# planning -------------------------------------------------------------------------------------
def occ_symbol(root: str, expiration: date, right: str, strike: float) -> str:
    """OCC/OPRA 21-character symbol, as Databento's raw_symbol."""
    return f"{root:<6}{expiration:%y%m%d}{right}{round(strike * 1000):08d}"


def strike_band(low: float, high: float, pad: float) -> list[int]:
    """Whole-dollar strikes from (1 - pad) * low to (1 + pad) * high, inclusive.

    Used only to decide which contracts to *store*: a superset of anything the
    point-in-time selection rule can choose, so it cannot introduce look-ahead.
    """
    return list(range(math.floor(low * (1 - pad)), math.ceil(high * (1 + pad)) + 1))


def option_symbols_for_day(
    root: str,
    day: date,
    sessions: Sequence[date],
    strikes: Sequence[float],
    expiry_offsets: Sequence[int],
) -> tuple[str, ...]:
    i = list(sessions).index(day)
    return tuple(
        occ_symbol(root, sessions[i + k], right, s)
        for k in expiry_offsets
        for right in "CP"
        for s in strikes
    )


# pricing / download -----------------------------------------------------------------------------
def _with_retry[T](call: Callable[[], T], policy: RetryPolicy) -> T:
    for attempt in range(policy.tries - 1):
        try:
            return call()
        except policy.retry_on:
            time.sleep(policy.backoff_s * 2**attempt)
    return call()


def price(
    client: Client,
    requests: Sequence[FetchRequest],
    *,
    unresolved_errors: tuple[type[BaseException], ...],
    retry: RetryPolicy = NO_RETRY,
) -> PricedPlan:
    """Price every request not already on disk. Requests whose symbols don't resolve are
    collected (they are evidence, e.g. no listed contracts), not treated as errors."""
    plan = PricedPlan()
    for r in requests:
        if len(r.symbols) > MAX_SYMBOLS_PER_REQUEST:
            raise ValueError(f"split requests to <= {MAX_SYMBOLS_PER_REQUEST} symbols: {r}")
        if r.path.exists():
            plan.already_present.append(r)
            continue
        try:
            cost = _with_retry(partial(client.metadata.get_cost, **r.kwargs()), retry)
        except unresolved_errors as e:
            if "symbology_invalid_request" not in str(e):
                raise
            plan.unresolved.append(r)
            continue
        plan.priced.append(r)
        plan.costs.append(float(cost))
    return plan


def download(
    client: Client,
    plan: PricedPlan,
    *,
    max_usd: float,
    retry: RetryPolicy = NO_RETRY,
    on_saved: Callable[[FetchRequest], None] | None = None,
) -> list[Path]:
    """Download every priced request if the total is within the cap; atomic per file."""
    if plan.total_usd > max_usd:
        raise CostCapExceededError(f"priced ${plan.total_usd:.2f} > cap ${max_usd:.2f}")
    saved: list[Path] = []
    for r in plan.priced:
        r.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = r.path.with_name(r.path.name + ".partial")
        if tmp.exists():  # leftover from an interrupted run: incomplete by construction
            tmp.unlink()

        def fetch(r: FetchRequest = r, tmp: Path = tmp) -> None:
            if tmp.exists():
                tmp.unlink()
            client.timeseries.get_range(**r.kwargs(), path=tmp)

        _with_retry(fetch, retry)
        tmp.replace(r.path)
        saved.append(r.path)
        if on_saved is not None:
            on_saved(r)
    return saved
