"""ADR-0021 (M28 step 1): the `study_options_day` block holds every frozen parameter of D1-D8,
and the config refuses values that contradict the ADR or the Phase 1 spec."""

from __future__ import annotations

import copy
from datetime import date, time
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from qqq1dte.core.config import DEFAULT_CONFIG, Phase1Config, load_config

CFG = load_config()
S = CFG.study_options_day
RAW: dict[str, Any] = yaml.safe_load(Path(DEFAULT_CONFIG).read_text(encoding="utf-8"))


def _with(**changes: Any) -> dict[str, Any]:
    raw = copy.deepcopy(RAW)
    raw["study_options_day"].update(changes)
    return raw


def test_tickers_are_the_owners_six() -> None:
    assert S.tickers == ["QQQ", "SPY", "IWM", "NVDA", "TSLA", "AAPL"]
    assert S.single_stocks == ["NVDA", "TSLA", "AAPL"]
    assert S.earnings_exclusion_sessions == 1


def test_development_ends_before_each_tickers_locked_holdout() -> None:
    assert S.dev_end["QQQ"] == date(2026, 4, 2)  # ADR-0011
    assert {S.dev_end[t] for t in S.tickers if t != "QQQ"} == {date(2025, 10, 2)}
    assert S.holdout_end == date(2026, 10, 2)


def test_contract_and_account_limits() -> None:
    assert (S.min_sessions_to_expiry, S.max_sessions_to_expiry) == (1, 5)  # never 0DTE
    assert S.account_usd == 5000.0
    assert S.max_premium_usd == 500.0
    assert S.total_loss_cap == 0.20
    assert S.decision_fill == "CONSERVATIVE"
    assert S.kill_fill == "OPTIMISTIC"
    assert CFG.trade.contracts == 1 and CFG.trade.max_open_positions == 1


def test_setups_are_frozen_as_in_d3() -> None:
    o, h = S.orb, S.half_hour
    assert (o.range_start, o.range_end) == (time(9, 30), time(10, 0))
    assert (o.signal_from, o.signal_until, o.exit_time) == (time(10, 0), time(12, 0), time(15, 45))
    assert (h.signal_time, h.entry_time, h.exit_time) == (time(10, 0), time(15, 30), time(15, 50))


def test_statistics_and_budget() -> None:
    assert S.max_tests == 3
    assert S.advance_level == pytest.approx(1 - 0.05 / 3)  # Bonferroni over this ADR's tests
    assert S.advance_level == pytest.approx(0.9833, abs=1e-4)
    assert (S.step_a_level, S.kill_level) == (0.95, 0.95)
    assert (S.min_trades, S.holdout_min_trades, S.max_advance) == (60, 40, 2)
    assert S.bootstrap_reps == 20_000
    assert S.breakeven_move_percentile == 0.75
    assert S.n_trials_recorded == 42
    assert S.data_budget_usd == 71.49


@pytest.mark.parametrize(
    "changes",
    [
        {"single_stocks": ["NVDA", "MSFT"]},  # not one of the tickers
        {"dev_end": {"QQQ": "2026-04-02"}},  # a ticker without a development end
        {"min_sessions_to_expiry": 0},  # 0DTE is excluded (D2)
        {"max_premium_usd": 6000.0},  # above the account
        {"holdout_end": "2025-01-01"},  # before a development end
        {"decision_fill": "MID"},  # not a spec fill model
        {"family_alpha": 0.0},
    ],
)
def test_contradictory_values_are_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Phase1Config.model_validate(_with(**changes))


def test_setup_times_must_be_ordered_and_inside_the_session_rules() -> None:
    late = copy.deepcopy(RAW)
    late["study_options_day"]["half_hour"]["exit_time"] = "15:55"  # after trade.forced_exit_time
    with pytest.raises(ValidationError, match="forced_exit_time"):
        Phase1Config.model_validate(late)
    backwards = copy.deepcopy(RAW)
    backwards["study_options_day"]["orb"]["signal_until"] = "09:45"
    with pytest.raises(ValidationError):
        Phase1Config.model_validate(backwards)


def test_unknown_keys_are_errors() -> None:
    with pytest.raises(ValidationError):
        Phase1Config.model_validate(_with(profit_target=0.5))


def test_broker_fees_one_contract_round_trip() -> None:
    """IBKR Canada: the $1.00 order minimum binds for one contract, so a side costs more than
    the Phase 1 `costs` block's $0.70. Exactly: 1.00 + 0.025 + 0.0003, plus the SEC fee on sells."""
    ibkr, wb = S.broker_fees["ibkr_canada"], S.broker_fees["webull_canada"]
    assert ibkr.order_cost(1, 3.00, sell=False) == pytest.approx(1.0253)
    assert ibkr.order_cost(1, 3.00, sell=True) == pytest.approx(1.0253 + 0.0000206 * 300)
    assert ibkr.order_cost(2, 3.00, sell=False) == pytest.approx(1.30 + 2 * 0.0253)
    assert wb.order_cost(1, 3.00, sell=False) == pytest.approx(0.99 + 0.0253)
    with pytest.raises(ValueError):
        ibkr.order_cost(0, 3.00, sell=False)


def test_both_brokers_are_required() -> None:
    raw = copy.deepcopy(RAW)
    del raw["study_options_day"]["broker_fees"]["webull_canada"]
    with pytest.raises(ValidationError):
        Phase1Config.model_validate(raw)
