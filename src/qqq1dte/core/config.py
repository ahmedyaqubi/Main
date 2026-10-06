"""Load and validate configs/phase1.yaml; hash configurations for the run registry."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import date, time
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "phase1.yaml"
CONFIG_ENV = "QQQ1DTE_CONFIG"


class _Section(BaseModel):
    # Unknown keys are errors: a typo in the YAML must not silently fall back to a default.
    model_config = ConfigDict(extra="forbid", frozen=True)


class History(_Section):
    option_era_start: date
    underlying_start: date


class Session(_Section):
    calendar: str
    timezone: str
    ignore_post_close_options: bool


class Schedule(_Section):
    cadence_minutes: int
    first: time
    last_new_entry: time
    early_close_last_entry_offset_min: int


class Trade(_Section):
    forced_exit_time: time
    early_close_forced_exit_offset_min: int
    max_holding_minutes: int
    allow_overnight: bool
    contracts: int
    max_open_positions: int
    max_entries_per_day: int
    breakeven_band: float


class Direction(_Section):
    deadband: float


class Magnitude(_Section):
    thresholds: list[float]


class OptionLabel(_Section):
    target_pct: float
    stop_pct: float


class Risk(_Section):
    stop: float


class Labels(_Section):
    horizon_minutes: int
    direction: Direction
    magnitude: Magnitude
    option: OptionLabel
    risk: Risk


class Decision(_Section):
    edge_margin: float


class Selection(_Section):
    rule: str
    rule_version: str


class Costs(_Section):
    commission_per_contract: float
    fees_per_contract: float


class Liquidity(_Section):
    max_quote_age_s: int
    max_spread_abs: float
    max_spread_pct: float
    min_bid: float
    require_size: bool


class Fills(_Section):
    latency_s: int
    moderate_alpha: float
    tick: float


class Pit(_Section):
    bar_publication_lag_s: int
    oi_available_time: time


class Validation(_Section):
    initial_train_months: int
    calibration_months: int
    test_months: int
    step_months: int
    embargo_sessions: int
    final_holdout_months: int
    bootstrap_reps: int


class Phase1Config(_Section):
    history: History
    session: Session
    schedule: Schedule
    trade: Trade
    labels: Labels
    decision: Decision
    selection: Selection
    costs: Costs
    liquidity: Liquidity
    fills: Fills
    pit: Pit
    validation: Validation


def load_config(path: Path | None = None) -> Phase1Config:
    """Load the Phase 1 config (default: configs/phase1.yaml, or $QQQ1DTE_CONFIG)."""
    path = path or Path(os.environ.get(CONFIG_ENV, DEFAULT_CONFIG))
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Phase1Config.model_validate(raw)


def config_hash(cfg: Mapping[str, Any]) -> str:
    """SHA-256 of canonical JSON: independent of key order, sensitive to any value change."""
    canonical = json.dumps(
        cfg, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
