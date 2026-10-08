"""Drift monitoring (spec Phase 1Q, gate 18; M18).

Monitors over a rolling window of the last `monitoring.window_sessions` sessions, against a
reference period (research out-of-sample predictions):
- features: max PSI over monitored features (reference-quantile bins) -> WARN / PAPER_ONLY;
- predictions: max PSI of the calibrated C_call / C_put probabilities -> WARN / PAPER_ONLY;
  PSI thresholds are calibrated to no-drift noise (owner, M18 option A): the `psi_warn_quantile`
  and `psi_paper_only_quantile` of the monitor's PSI over `psi_null_draws` random windows of
  `window_sessions` sessions drawn (seeded) from the reference period. Fixed rules of thumb do
  not work here: many features are constant within a session, so a 10-session window holds 10
  values and its PSI is large even without drift;
- calibration: mean(observed - predicted) per target and for the combined decision targets,
  in units of the reference session-clustered SE (sd of session gaps / sqrt(sessions));
  any |z| > calib_z_warn -> WARN; DISABLED only when the combined |z| > calib_z_disable.
  The combined gap is far less noisy than either side alone (their
  session gaps are negatively correlated), so a degradation hitting both sides is detected much
  faster than one hitting a single side;
- expectancy: with >= min_trades trades, mean net < 0 -> WARN, session-bootstrap CI upper
  bound < 0 -> DISABLED (net of costs, gate-9 helpers);
- regimes: categorical PSI of regime cells over the last `regime_window_sessions` -> WARN only
  (above the null `psi_warn_quantile` of random reference windows of that length).
The overall state is the most severe monitor; `DriftMonitor` latches DISABLED until a named
human re-enables the model. `decide(..., drift_state="DISABLED")` returns NO_TRADE.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import numpy.typing as npt
import polars as pl

from qqq1dte.backtesting.reporting import net_from_frame, summarize_net
from qqq1dte.core.config import Phase1Config

LEVELS = ("OK", "WARN", "PAPER_ONLY", "DISABLED")
RANK = {lv: i for i, lv in enumerate(LEVELS)}
TARGETS = ("C_call", "C_put")
Arr = npt.NDArray[np.float64]


def _worst(levels: Sequence[str]) -> str:
    return max(levels, key=lambda lv: RANK[lv]) if levels else "OK"


def psi(reference: npt.ArrayLike, current: npt.ArrayLike, bins: int, eps: float) -> float:
    """Population stability index with bins at reference quantiles (empty bins floored)."""
    r = np.asarray(reference, dtype=np.float64)
    c = np.asarray(current, dtype=np.float64)
    r, c = r[~np.isnan(r)], c[~np.isnan(c)]
    if r.size == 0 or c.size == 0:
        return 0.0
    edges = np.unique(np.quantile(r, np.linspace(0, 1, bins + 1)[1:-1]))
    rp = np.bincount(np.searchsorted(edges, r, side="right"), minlength=edges.size + 1) / r.size
    cp = np.bincount(np.searchsorted(edges, c, side="right"), minlength=edges.size + 1) / c.size
    rp, cp = np.maximum(rp, eps), np.maximum(cp, eps)
    return float(np.sum((cp - rp) * np.log(cp / rp)))


def psi_categorical(reference: Sequence[str], current: Sequence[str], eps: float) -> float:
    cats = sorted(set(reference) | set(current))
    r = np.array([sum(x == k for x in reference) for k in cats], dtype=np.float64) / len(reference)
    c = np.array([sum(x == k for x in current) for k in cats], dtype=np.float64) / len(current)
    r, c = np.maximum(r, eps), np.maximum(c, eps)
    return float(np.sum((c - r) * np.log(c / r)))


def _session_gaps(frame: pl.DataFrame) -> pl.DataFrame:
    """Per session: mean(y - p) per target (resolved rows) and their average ('combined')."""
    g = frame.group_by("session_date").agg(
        *[
            (pl.col(f"y_{t}") - pl.col(f"p_{t}"))
            .filter(pl.col(f"y_{t}").is_not_null())
            .mean()
            .alias(t)
            for t in TARGETS
        ]
    )
    return g.with_columns(combined=(pl.col("C_call") + pl.col("C_put")) / 2)


@dataclass(frozen=True)
class Reference:
    features: dict[str, Arr]
    predictions: dict[str, Arr]
    feature_sd: dict[str, float]
    gap_sd: dict[str, float]
    cells: list[str]
    null: dict[str, Arr] = field(default_factory=dict)  # monitor -> PSI over no-drift windows
    thresholds: dict[str, tuple[float, float]] = field(default_factory=dict)  # (warn, escalate)


def _max_psi(
    window: pl.DataFrame, ref: Reference, cfg: Phase1Config, key: str
) -> tuple[float, str]:
    m = cfg.monitoring
    if key == "features":
        vals = {
            f: psi(ref.features[f], window[f].cast(pl.Float64).to_numpy(), m.psi_bins, m.psi_eps)
            for f in ref.features
        }
    else:
        vals = {
            t: psi(ref.predictions[t], window[f"p_{t}"].to_numpy(), m.psi_bins, m.psi_eps)
            for t in TARGETS
        }
    k = max(vals, key=lambda x: vals[x])
    return vals[k], k


def _calibrate_null(ref: Reference, frame: pl.DataFrame, cfg: Phase1Config) -> Reference:
    """PSI of each monitor over random no-drift windows drawn from the reference period, each
    compared with the reference *without* the window's sessions (leave-window-out), so the null
    matches how a genuinely new window is compared."""
    m = cfg.monitoring
    rng = np.random.default_rng(m.psi_null_seed)
    days = sorted(set(frame["session_date"].to_list()))
    day_idx = {d: i for i, d in enumerate(days)}
    row_day = np.array([day_idx[d] for d in frame["session_date"].to_list()])
    cols = {f: frame[f].cast(pl.Float64).to_numpy() for f in ref.features}
    cols.update({f"p_{t}": frame[f"p_{t}"].to_numpy() for t in TARGETS})
    w = min(m.window_sessions, len(days) - 1)
    rw = min(m.regime_window_sessions, len(ref.cells) - 1)
    null: dict[str, list[float]] = {"features": [], "predictions": [], "regimes": []}
    for _ in range(m.psi_null_draws):
        in_win = np.isin(row_day, rng.choice(len(days), w, replace=False))
        null["features"].append(
            max(psi(cols[f][~in_win], cols[f][in_win], m.psi_bins, m.psi_eps) for f in ref.features)
        )
        null["predictions"].append(
            max(
                psi(cols[f"p_{t}"][~in_win], cols[f"p_{t}"][in_win], m.psi_bins, m.psi_eps)
                for t in TARGETS
            )
        )
        pick = rng.choice(len(ref.cells), rw, replace=False)
        rest = [c for i, c in enumerate(ref.cells) if i not in set(pick)]
        null["regimes"].append(psi_categorical(rest, [ref.cells[i] for i in pick], m.psi_eps))
    arrs = {k: np.asarray(v, dtype=np.float64) for k, v in null.items()}
    thr = {
        k: (
            float(np.quantile(a, m.psi_warn_quantile)),
            float(np.quantile(a, m.psi_paper_only_quantile)),
        )
        for k, a in arrs.items()
    }
    return Reference(
        ref.features, ref.predictions, ref.feature_sd, ref.gap_sd, ref.cells, arrs, thr
    )


def build_reference(frame: pl.DataFrame, features: Sequence[str], cfg: Phase1Config) -> Reference:
    gaps = _session_gaps(frame)
    sess = frame.unique("session_date", keep="first").sort("session_date")
    base = Reference(
        features={f: frame[f].cast(pl.Float64).to_numpy() for f in features},
        predictions={t: frame[f"p_{t}"].to_numpy() for t in TARGETS},
        feature_sd={f: float(np.nanstd(frame[f].cast(pl.Float64).to_numpy())) for f in features},
        gap_sd={
            k: float(np.std(gaps[k].drop_nulls().to_numpy(), ddof=1))
            for k in (*TARGETS, "combined")
        },
        cells=sess["cell"].to_list(),
    )
    return _calibrate_null(base, frame, cfg)


@dataclass(frozen=True)
class Assessment:
    levels: dict[str, str]
    details: dict[str, Any]

    @property
    def overall(self) -> str:
        return _worst(list(self.levels.values()))


def _psi_level(v: float, thresholds: tuple[float, float]) -> str:
    warn, escalate = thresholds
    return "PAPER_ONLY" if v > escalate else "WARN" if v > warn else "OK"


def assess_window(
    window: pl.DataFrame,
    ref: Reference,
    cfg: Phase1Config,
    trades: pl.DataFrame | None = None,
    regime_cells: Sequence[str] | None = None,
) -> Assessment:
    m = cfg.monitoring
    levels: dict[str, str] = {}
    details: dict[str, Any] = {}
    fmax, fname = _max_psi(window, ref, cfg, "features")
    levels["features"] = _psi_level(fmax, ref.thresholds["features"])
    details["features"] = {
        "max_psi": fmax,
        "feature": fname,
        "thresholds": ref.thresholds["features"],
    }
    pmax, pname = _max_psi(window, ref, cfg, "predictions")
    levels["predictions"] = _psi_level(pmax, ref.thresholds["predictions"])
    details["predictions"] = {
        "max_psi": pmax,
        "target": pname,
        "thresholds": ref.thresholds["predictions"],
    }
    gaps = _session_gaps(window)
    zs = {}
    for k in (*TARGETS, "combined"):
        g = gaps[k].drop_nulls().to_numpy()
        sd = ref.gap_sd[k]
        zs[k] = float(g.mean() / (sd / np.sqrt(g.size))) if g.size and sd > 0 else 0.0
    # DISABLED only from the combined decision-target gap; a single target beyond the disable
    # level is WARN (three z-scores would triple false disables; M18 replay, disclosed)
    zmax = max(abs(v) for v in zs.values())
    if abs(zs["combined"]) > m.calib_z_disable:
        levels["calibration"] = "DISABLED"
    else:
        levels["calibration"] = "WARN" if zmax > m.calib_z_warn else "OK"
    details["calibration"] = zs
    levels["expectancy"], details["expectancy"] = "OK", "not evaluable (too few trades)"
    if trades is not None and trades.height >= m.min_trades:
        s = summarize_net(net_from_frame(trades), trades["session_date"].to_list(), cfg)
        levels["expectancy"] = "DISABLED" if s.ci[1] < 0 else "WARN" if s.mean < 0 else "OK"
        details["expectancy"] = {"n": s.n, "mean": s.mean, "ci": list(s.ci)}
    levels["regimes"], details["regimes"] = "OK", None
    if regime_cells:
        v = psi_categorical(ref.cells, list(regime_cells), m.psi_eps)
        levels["regimes"] = "WARN" if v > ref.thresholds["regimes"][0] else "OK"
        details["regimes"] = v
    return Assessment(levels, details)


@dataclass
class DriftMonitor:
    """Alert state across sessions. DISABLED latches until a named human re-enables."""

    state: str = "OK"
    history: list[dict[str, Any]] = field(default_factory=list)

    def update(self, a: Assessment, when: date | None = None) -> str:
        self.state = "DISABLED" if self.state == "DISABLED" else a.overall
        self.history.append({"when": when, "state": self.state, "levels": dict(a.levels)})
        return self.state

    def reenable(self, approved_by: str) -> None:
        if not approved_by or not approved_by.strip():
            raise ValueError("a named human approver is required to re-enable a model")
        self.state = "OK"
        self.history.append({"when": None, "state": "OK", "event": f"REENABLED by {approved_by}"})


def shift_features(
    frame: pl.DataFrame, features: Sequence[str], ref: Reference, sds: float
) -> pl.DataFrame:
    return frame.with_columns(
        [(pl.col(f).cast(pl.Float64) + sds * ref.feature_sd[f]).alias(f) for f in features]
    )


def flip_wins(
    frame: pl.DataFrame, targets: Sequence[str], q: float, rng: np.random.Generator
) -> pl.DataFrame:
    out = frame
    for t in targets:
        draw = pl.Series(rng.random(out.height) < q)
        out = out.with_columns(  # nulls (unresolved outcomes) stay null
            pl.when((pl.col(f"y_{t}") == 1) & draw)
            .then(0.0)
            .otherwise(pl.col(f"y_{t}"))
            .alias(f"y_{t}")
        )
    return out


def replay_detection(
    sessions: pl.DataFrame,
    features: Sequence[str],
    cfg: Phase1Config,
    n_replays: int | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Gate-18 replay: the reference period replayed in random session orders (stationary by
    construction); from `inject_at_session` on, (a) features shifted by `feature_shift_sd`
    reference SDs, or (b) a share `win_loss_flip` of WIN outcomes turned into LOSS. Reports per
    replay the first session (1-based after injection) at which the expected alert appears, and
    whether PAPER_ONLY / DISABLED appeared before injection (false alarm)."""
    rc, m = cfg.monitoring.replay, cfg.monitoring
    n = n_replays or rc.n_replays
    rng = np.random.default_rng(seed if seed is not None else rc.seed)
    ref = build_reference(sessions, features, cfg)
    days = sessions["session_date"].unique().sort().to_list()
    by_day = {d: g for (d,), g in sessions.group_by("session_date")}
    horizon = rc.inject_at_session + rc.max_delay_sessions + 5
    if len(days) < horizon:
        raise ValueError(f"replay needs at least {horizon} sessions, got {len(days)}")
    out: dict[str, Any] = {}
    for kind, monitor, expected in (
        ("feature_shift", "features", "PAPER_ONLY"),
        ("calibration", "calibration", "DISABLED"),
    ):
        replays: list[dict[str, Any]] = []
        for _ in range(n):
            order = [days[i] for i in rng.permutation(len(days))[:horizon]]
            inj_rng = np.random.default_rng(int(rng.integers(1 << 31)))
            stream = []
            for i, d in enumerate(order):
                f = by_day[d]
                if i >= rc.inject_at_session:
                    f = (
                        shift_features(f, features, ref, rc.feature_shift_sd)
                        if kind == "feature_shift"
                        else flip_wins(f, TARGETS, rc.win_loss_flip, inj_rng)
                    )
                stream.append(f)
            false_alarm, alert = False, "OK"
            delay: int | None = None
            for i in range(m.window_sessions - 1, horizon):
                a = assess_window(pl.concat(stream[i - m.window_sessions + 1 : i + 1]), ref, cfg)
                if i < rc.inject_at_session:
                    false_alarm |= RANK[a.overall] >= RANK["PAPER_ONLY"]
                    continue
                lv = a.levels[monitor]
                if RANK[lv] > RANK[alert]:
                    alert = lv
                if lv == expected and delay is None:
                    delay = i - rc.inject_at_session + 1
                    break
            replays.append(
                {
                    "delay": delay if delay is not None else horizon,
                    "alert": alert,
                    "detected": delay is not None,
                    "false_alarm": false_alarm,
                }
            )
        n_false = sum(bool(r["false_alarm"]) for r in replays)
        out[kind] = {
            "expected": expected,
            "replays": replays,
            "false_alarm_replays": n_false,
            "max_delay": max(int(r["delay"]) for r in replays),
            "pass": all(
                r["detected"] and r["alert"] == expected and r["delay"] <= rc.max_delay_sessions
                for r in replays
            )
            and n_false <= rc.max_false_alarm_replays,
        }
    return out
