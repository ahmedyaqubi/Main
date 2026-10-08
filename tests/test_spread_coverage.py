"""M19T Step 0 (ADR-0013 D1.a/D1.c): data-coverage view of the credit-fraction strike rule.

Synthetic chains with exactly known answers. These functions only describe whether the stored data
can resolve the rule; they compute no P&L.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from qqq1dte.validation.spread_coverage import (
    AT_BAND_EDGE,
    NO_QUALIFYING,
    OK,
    LegQuote,
    credit_pick,
    grid_holes,
    longest_gap_minutes,
)


def puts(prices: dict[float, tuple[float | None, float | None]]) -> dict[float, LegQuote]:
    return {k: LegQuote(k, b, a, True) for k, (b, a) in prices.items()}


# strikes 95..100, put bids/asks decreasing as strikes move out of the money (down)
CHAIN = puts(
    {
        100.0: (1.50, 1.52),
        99.0: (0.90, 0.92),
        98.0: (0.50, 0.52),
        97.0: (0.25, 0.27),
        96.0: (0.10, 0.12),
        95.0: (0.03, 0.05),
    }
)


def test_put_furthest_otm_meeting_x() -> None:
    # credits (short bid - long ask): 100/99 0.58, 99/98 0.38, 98/97 0.23, 97/96 0.13, 96/95 0.05
    p = credit_pick(CHAIN, "P", 0.20)
    assert (p.status, p.short, p.long) == (OK, 98.0, 97.0)
    assert p.credit == 0.23
    assert p.beyond == 2  # stored strikes 96, 95 lie further out than the long leg
    p33 = credit_pick(CHAIN, "P", 0.33)
    assert (p33.status, p33.short, p33.long, p33.credit) == (OK, 99.0, 98.0, 0.38)


def test_threshold_is_inclusive() -> None:
    p = credit_pick(CHAIN, "P", 0.23)
    assert (p.short, p.credit) == (98.0, 0.23)


def test_call_side_moves_up() -> None:
    calls = {
        k: LegQuote(k, b, a, True)
        for k, (b, a) in {
            100.0: (1.50, 1.52),
            101.0: (0.90, 0.92),
            102.0: (0.45, 0.47),
            103.0: (0.20, 0.22),
        }.items()
    }
    # credits: 100/101 0.58, 101/102 0.43, 102/103 0.23
    p = credit_pick(calls, "C", 0.20)
    assert (p.status, p.short, p.long, p.beyond) == (AT_BAND_EDGE, 102.0, 103.0, 0)


def test_band_edge_when_outermost_pair_qualifies() -> None:
    chain = {k: v for k, v in CHAIN.items() if k >= 97.0}  # 98/97 is now the outermost pair
    p = credit_pick(chain, "P", 0.20)
    assert (p.status, p.short, p.beyond) == (AT_BAND_EDGE, 98.0, 0)


def test_no_qualifying_pair() -> None:
    p = credit_pick(CHAIN, "P", 0.60)
    assert (p.status, p.short, p.long, p.credit) == (NO_QUALIFYING, None, None, None)


def test_unusable_or_missing_legs_are_not_candidates() -> None:
    chain = dict(CHAIN)
    chain[97.0] = LegQuote(97.0, 0.25, 0.27, False)  # stale / rejected at T_e
    p = credit_pick(chain, "P", 0.20)
    # 98/97 and 97/96 drop out; 99/98 (0.38) is the furthest qualifying pair
    assert (p.short, p.long) == (99.0, 98.0)
    assert p.pairs == 3  # 100/99, 99/98, 96/95
    chain2 = {k: v for k, v in CHAIN.items() if k != 97.0}  # $1 grid hole at 97
    p2 = credit_pick(chain2, "P", 0.20)
    assert (p2.short, p2.long) == (99.0, 98.0)


def test_missing_bid_or_ask_side() -> None:
    chain = dict(CHAIN)
    chain[97.0] = LegQuote(97.0, 0.25, None, True)  # long leg needs an ask
    assert credit_pick(chain, "P", 0.20).short == 99.0
    chain = dict(CHAIN)
    chain[98.0] = LegQuote(98.0, None, 0.52, True)  # short leg needs a bid
    assert credit_pick(chain, "P", 0.20).short == 99.0


def test_grid_holes() -> None:
    assert grid_holes([95.0, 96.0, 97.0]) == []
    assert grid_holes([95.0, 98.0, 99.0, 101.0]) == [96.0, 97.0, 100.0]
    assert grid_holes([]) == []


T0 = datetime(2024, 6, 12, 14, 0, tzinfo=UTC)


def m(n: float) -> datetime:
    return T0 + timedelta(minutes=n)


def test_longest_gap_includes_window_edges() -> None:
    # usable records at +1, +3, +10 within window [0, 12]: gaps 1, 2, 7, 2 -> 7
    assert longest_gap_minutes([m(1), m(3), m(10)], m(0), m(12)) == 7.0
    # nothing usable in the window: the whole window is a gap
    assert longest_gap_minutes([], m(0), m(12)) == 12.0
    # the quote in force at the start may be older: its age counts (-2 -> 6 is 8 minutes)
    assert longest_gap_minutes([m(-2), m(6)], m(0), m(8)) == 8.0
    # records after the window end are ignored
    assert longest_gap_minutes([m(0), m(4), m(20)], m(0), m(8)) == 4.0
