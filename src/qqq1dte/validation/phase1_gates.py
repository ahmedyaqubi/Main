"""Phase 1V gate evaluation (spec §11; M19). Each gate returns PASS / FAIL / NOT_EVALUABLE with
its numbers; NOT_EVALUABLE (missing evidence, e.g. no trades) is never a pass. Also the
statistics gate 16 needs: the probability of backtest overfitting by combinatorially
symmetric cross-validation (CSCV) and the deflated Sharpe ratio (Bailey & López de Prado)."""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any

import numpy as np
import numpy.typing as npt

from qqq1dte.core.config import Phase1Config

PASS, FAIL, NOT_EVALUABLE = "PASS", "FAIL", "NOT_EVALUABLE"
EULER_GAMMA = 0.5772156649015329
MIN_RETURNS, MIN_TRIALS = 3, 2
_N = NormalDist()


@dataclass(frozen=True)
class GateResult:
    number: int
    name: str
    status: str
    rule: str
    numbers: dict[str, Any] = field(default_factory=dict)


def gate_from_checks(
    number: int, name: str, rule: str, checks: dict[str, bool | None], numbers: dict[str, Any]
) -> GateResult:
    """All checks True -> PASS; any False -> FAIL; otherwise (a missing check) NOT_EVALUABLE."""
    if any(v is False for v in checks.values()):
        status = FAIL
    elif any(v is None for v in checks.values()):
        status = NOT_EVALUABLE
    else:
        status = PASS
    return GateResult(number, name, status, rule, {**numbers, "checks": checks})


def gate6(per_target: dict[str, dict[str, Any]], cfg: Phase1Config) -> GateResult:
    """Beats baseline: per decision target, BSS vs Model 0 CI lower bound > 0 (pooled OOS) and
    better in >= min_folds_better_share of folds."""
    v = cfg.validation_gates
    checks: dict[str, bool | None] = {}
    for t, e in per_target.items():
        checks[f"{t} CI lower > 0"] = e["ci"][0] > 0
        checks[f"{t} folds better >= {v.min_folds_better_share:.0%}"] = (
            e["folds_better"] / e["n_folds"] >= v.min_folds_better_share
        )
    return gate_from_checks(
        6,
        "Beats baseline",
        "BSS vs Model 0 CI lower bound > 0, pooled OOS; "
        f"better in >= {v.min_folds_better_share:.0%} of folds",
        checks,
        {"per_target": per_target},
    )


def gate10(
    mean_net_ci: tuple[float, float] | None, folds_positive_share: float | None, cfg: Phase1Config
) -> GateResult:
    v = cfg.validation_gates
    checks = {
        "pooled CI lower > 0": None if mean_net_ci is None else mean_net_ci[0] > 0,
        f"positive in >= {v.min_folds_positive_share:.0%} of folds": (
            None
            if folds_positive_share is None
            else folds_positive_share >= v.min_folds_positive_share
        ),
    }
    return gate_from_checks(
        10,
        "Walk-forward positive",
        "pooled OOS expectancy (moderate, net) CI lower bound > 0; positive in >= 60% of folds",
        checks,
        {"mean_net_ci": mean_net_ci, "folds_positive_share": folds_positive_share},
    )


def gate11(conservative_mean: float | None, alpha_sign_consistent: bool | None) -> GateResult:
    checks = {
        "conservative point estimate > 0": None
        if conservative_mean is None
        else conservative_mean > 0,
        "sign stable for alpha in [0.25, 0.75]": alpha_sign_consistent,
    }
    return gate_from_checks(
        11,
        "Execution robustness",
        "conservative expectancy > 0; sign independent of alpha in [0.25, 0.75]",
        checks,
        {"conservative_mean": conservative_mean},
    )


def gate13(cells: Sequence[dict[str, Any]], n_trades: int, cfg: Phase1Config) -> GateResult:
    """Every traded regime cell with >= regime_min_trades trades has expectancy CI upper > 0."""
    v = cfg.validation_gates
    judged = [c for c in cells if c["trades"] >= v.regime_min_trades]
    checks: dict[str, bool | None]
    if n_trades == 0:
        checks = {"traded regime cells": None}
    else:
        checks = {f"cell {c['cell']} CI upper > 0": c["ci_upper"] > 0 for c in judged}
        if not judged:
            checks = {f"a cell with >= {v.regime_min_trades} trades": None}
    return gate_from_checks(
        13,
        "Regime behaviour",
        "every traded cell with >= 100 trades has expectancy CI upper bound > 0",
        checks,
        {"cells": list(cells), "n_trades": n_trades},
    )


def gate14(diff_ci: tuple[float, float] | None, n_traded: int) -> GateResult:
    checks = {
        "traded - counterfactual CI lower > 0": None
        if diff_ci is None or n_traded == 0
        else diff_ci[0] > 0
    }
    return gate_from_checks(
        14,
        "NO_TRADE validated",
        "counterfactual NO_TRADE expectancy < traded expectancy, CI on the difference excluding 0",
        checks,
        {"diff_ci": diff_ci, "n_traded": n_traded},
    )


def gate15(n_trades: int, n_sessions: int, cfg: Phase1Config) -> GateResult:
    v = cfg.validation_gates
    checks: dict[str, bool | None] = {
        f">= {v.min_trades} OOS trades": n_trades >= v.min_trades,
        f">= {v.min_sessions} OOS sessions with a trade": n_sessions >= v.min_sessions,
    }
    return gate_from_checks(
        15,
        "Sample size",
        ">= 300 OOS trades and >= 150 sessions with a trade",
        checks,
        {"n_trades": n_trades, "n_sessions": n_sessions},
    )


def gate16(pbo: float | None, dsr_probability: float | None, cfg: Phase1Config) -> GateResult:
    v = cfg.validation_gates
    checks = {
        f"PBO <= {v.max_pbo}": None if pbo is None else pbo <= v.max_pbo,
        f"DSR probability >= {v.min_dsr_probability}": (
            None if dsr_probability is None else dsr_probability >= v.min_dsr_probability
        ),
    }
    return gate_from_checks(
        16,
        "No overfitting",
        "PBO <= 0.20; deflated Sharpe probability >= 0.95 with the logged n_trials",
        checks,
        {"pbo": pbo, "dsr_probability": dsr_probability},
    )


def pbo_cscv(performance: npt.ArrayLike, n_blocks: int) -> tuple[float, list[float]]:
    """Probability of backtest overfitting (CSCV). `performance` is T x N (rows = time-ordered
    periods, columns = configurations; higher = better). Rows are cut into `n_blocks` equal
    blocks (remainder rows dropped); for every split into n_blocks/2 in-sample blocks, the best
    in-sample configuration's out-of-sample relative rank w = rank / (N + 1) gives
    logit(w); PBO = share of logits <= 0."""
    m = np.asarray(performance, dtype=np.float64)
    t, n = m.shape
    size = t // n_blocks
    if size == 0 or n < MIN_TRIALS or n_blocks % 2:
        raise ValueError("need >= n_blocks rows, >= 2 configurations and an even n_blocks")
    blocks = m[: size * n_blocks].reshape(n_blocks, size, n).mean(axis=1)  # block means
    logits = []
    for is_idx in itertools.combinations(range(n_blocks), n_blocks // 2):
        oos_idx = [b for b in range(n_blocks) if b not in is_idx]
        is_perf, oos_perf = blocks[list(is_idx)].mean(axis=0), blocks[oos_idx].mean(axis=0)
        best = int(np.argmax(is_perf))
        rank = 1 + int(np.sum(oos_perf < oos_perf[best]))  # 1 = worst out of sample
        w = rank / (n + 1)
        logits.append(math.log(w / (1 - w)))
    return float(np.mean(np.asarray(logits) <= 0)), logits


def deflated_sharpe_probability(
    returns: npt.ArrayLike, n_trials: int, sharpe_variance: float
) -> float:
    """P(true Sharpe > SR0) with SR0 the expected maximum Sharpe of `n_trials` unskilled trials
    whose Sharpe ratios have variance `sharpe_variance` (per-period, non-annualised)."""
    r = np.asarray(returns, dtype=np.float64)
    if r.size < MIN_RETURNS or n_trials < MIN_TRIALS:
        raise ValueError("need >= 3 returns and >= 2 trials")
    sr = float(r.mean() / r.std(ddof=1))
    sr0 = math.sqrt(sharpe_variance) * (
        (1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n_trials)
        + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n_trials * math.e))
    )
    z = (r - r.mean()) / r.std()
    skew, kurt = float((z**3).mean()), float((z**4).mean())
    return _N.cdf(
        (sr - sr0) * math.sqrt(r.size - 1) / math.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr**2)
    )
