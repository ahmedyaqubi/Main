"""Per-regime summaries (spec §9; M14): bucket statistics with session-block bootstrap CIs and
LOW_SUPPORT flags, and the OD-9 trend-separation statistic (TREND minus CHOP, stratified)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import polars as pl

from qqq1dte.backtesting.bootstrap import session_bootstrap_ci
from qqq1dte.core.config import Phase1Config

TREND_VALUES = ("TREND", "CHOP")


def _ci(sid: np.ndarray, v: np.ndarray, cfg: Phase1Config) -> tuple[float, float]:
    m = cfg.models.metrics
    return session_bootstrap_ci(
        sid,
        lambda w: float(np.average(v, weights=w)) if w.sum() > 0 else float("nan"),
        cfg.validation.bootstrap_reps,
        m.bootstrap_seed,
        m.ci_level,
    )


def summarize(
    df: pl.DataFrame, by: Sequence[str], value: str, cfg: Phase1Config, trades: bool = False
) -> list[dict[str, Any]]:
    """Per group: n, sessions, mean of `value` with CI, LOW_SUPPORT (< low_support_sessions
    sessions, or < low_support_trades rows when the rows are trades)."""
    rc = cfg.regimes
    out = []
    for key, g in df.group_by(list(by), maintain_order=True):
        v = g[value].cast(pl.Float64).to_numpy()
        sid = g["session_date"].to_numpy()
        n_s = g["session_date"].n_unique()
        lo, hi = _ci(sid, v, cfg)
        low = n_s < rc.low_support_sessions or (trades and g.height < rc.low_support_trades)
        out.append(
            {
                **dict(zip(by, key, strict=True)),
                "n": g.height,
                "sessions": n_s,
                "mean": float(v.mean()),
                "ci": [lo, hi],
                "low_support": low,
            }
        )
    return out


def stratified_difference(
    df: pl.DataFrame, value: str, strata: Sequence[str], cfg: Phase1Config
) -> dict[str, Any]:
    """Mean(TREND) - mean(CHOP) within each stratum, averaged with weights = stratum rows, over
    strata that contain both trend values. CI by session-block bootstrap (rows reweighted by
    their session's draw count). Expects a `trend` column with TREND / CHOP."""
    d = df.filter(pl.col("trend").is_in(list(TREND_VALUES)))
    keys = d.select(list(strata)).unique()
    both = [
        k
        for k in keys.iter_rows(named=True)
        if d.filter(pl.all_horizontal([pl.col(c) == v for c, v in k.items()]))["trend"].n_unique()
        == len(TREND_VALUES)
    ]
    if not both:
        return {"difference": float("nan"), "ci": [float("nan"), float("nan")], "strata": 0}
    d = d.with_columns(_s=pl.concat_str([pl.col(c).cast(pl.String) for c in strata], separator="|"))
    ok = {"|".join(str(k[c]) for c in strata) for k in both}
    d = d.filter(pl.col("_s").is_in(list(ok)))
    s_idx = d["_s"].to_numpy()
    is_t = (d["trend"] == "TREND").to_numpy()
    v = d[value].cast(pl.Float64).to_numpy()
    groups = [(s_idx == s) for s in sorted(ok)]

    def stat(w: np.ndarray) -> float:
        diffs, weights = [], []
        for m in groups:
            wt, wc = w * (m & is_t), w * (m & ~is_t)
            if wt.sum() == 0 or wc.sum() == 0:
                continue
            diffs.append(np.average(v, weights=wt) - np.average(v, weights=wc))
            weights.append((w * m).sum())
        return float(np.average(diffs, weights=weights)) if diffs else float("nan")

    m = cfg.models.metrics
    lo, hi = session_bootstrap_ci(
        d["session_date"].to_numpy(),
        stat,
        cfg.validation.bootstrap_reps,
        m.bootstrap_seed,
        m.ci_level,
    )
    return {"difference": stat(np.ones(d.height)), "ci": [lo, hi], "strata": len(groups)}
