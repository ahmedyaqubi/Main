"""Calibration maps from raw model scores to probabilities (spec Phase 1L): identity ("none"),
temperature (sigmoid(logit(p) / T)), Platt (sigmoid(a logit(p) + b)) and isotonic (monotone
step fit, linear interpolation between thresholds, clamped at the ends). Outputs are clipped to
[prob_clip, 1 - prob_clip]. Calibrators are stored as JSON with a sha256."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.optimize import minimize_scalar
from sklearn.isotonic import IsotonicRegression

from qqq1dte.core.config import Phase1Config
from qqq1dte.execution_sim.decision import CalibratedProbability
from qqq1dte.models.metrics import log_loss

Arr = npt.NDArray[np.float64]
LOGIT_EPS = 1e-6
CONST_EPS = 1e-12  # range below which x is treated as constant; also the minimum step
FORMAT = "qqq1dte.calibrator.v1"


def logit(p: npt.ArrayLike) -> Arr:
    q = np.clip(np.asarray(p, dtype=np.float64), LOGIT_EPS, 1 - LOGIT_EPS)
    return np.asarray(np.log(q / (1 - q)), dtype=np.float64)


def sigmoid(z: npt.ArrayLike) -> Arr:
    zc = np.clip(np.asarray(z, dtype=np.float64), -500.0, 500.0)  # exp overflow guard
    return np.asarray(1.0 / (1.0 + np.exp(-zc)), dtype=np.float64)


def _nll(a: float, b: float, x: Arr, y: Arr) -> float:
    z = a * x + b
    return float(np.sum(np.logaddexp(0.0, z) - y * z))


def logistic_fit(x: Arr, y: Arr, max_iter: int = 200, tol: float = 1e-10) -> tuple[float, float]:
    """Unregularised 1-D logistic regression y ~ sigmoid(a x + b): Newton steps with
    step-halving on the negative log-likelihood (monotone; plain Newton can oscillate and
    diverge when extreme x values disagree with their outcomes). A constant x has no slope:
    returns (nan, logit(mean y))."""
    if np.ptp(x) < CONST_EPS:
        return float("nan"), float(logit([float(np.mean(y))])[0])
    a, b = 0.0, float(logit([float(np.mean(y))])[0])
    loss = _nll(a, b, x, y)
    for _ in range(max_iter):
        p = sigmoid(a * x + b)
        w = p * (1 - p)
        g = np.array([np.sum((p - y) * x), np.sum(p - y)])
        h = np.array([[np.sum(w * x * x), np.sum(w * x)], [np.sum(w * x), np.sum(w)]])
        step = np.linalg.lstsq(h, g, rcond=None)[0]
        t = 1.0
        while t > CONST_EPS:
            na, nb = a - t * float(step[0]), b - t * float(step[1])
            new = _nll(na, nb, x, y)
            if new <= loss:
                break
            t /= 2
        else:
            break  # no descent possible: at the optimum to numerical precision
        a, b, loss = na, nb, new
        if t * float(np.max(np.abs(step))) < tol:
            break
    return a, b


@dataclass(frozen=True)
class Calibrator:
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    clip: float = 1e-4

    def apply(self, p: npt.ArrayLike) -> Arr:
        raw = np.asarray(p, dtype=np.float64)
        if self.method == "none":
            out = raw
        elif self.method == "platt":
            out = sigmoid(self.params["a"] * logit(raw) + self.params["b"])
        elif self.method == "temperature":
            out = sigmoid(logit(raw) / self.params["T"])
        elif self.method == "isotonic":
            out = np.interp(raw, self.params["x"], self.params["y"])
        else:
            raise ValueError(f"unknown calibration method {self.method}")
        return np.asarray(np.clip(out, self.clip, 1 - self.clip), dtype=np.float64)

    def probability(self, raw: float, calibration_version_id: str) -> CalibratedProbability:
        return CalibratedProbability(float(self.apply([raw])[0]), calibration_version_id)


def fit_method(method: str, p: npt.ArrayLike, y: npt.ArrayLike, cfg: Phase1Config) -> Calibrator:
    pa, ya = np.asarray(p, dtype=np.float64), np.asarray(y, dtype=np.float64)
    clip = cfg.calibration.prob_clip
    if method == "none":
        return Calibrator("none", {}, clip)
    if method == "platt":
        a, b = logistic_fit(logit(pa), ya)
        if np.isnan(a):  # constant scores carry no ranking: the map is the base rate
            a = 0.0
        return Calibrator("platt", {"a": a, "b": b}, clip)
    if method == "temperature":
        z = logit(pa)
        res = minimize_scalar(
            lambda lt: log_loss(ya, sigmoid(z / np.exp(lt))),
            bounds=(np.log(0.05), np.log(20.0)),
            method="bounded",
            options={"xatol": 1e-8},
        )
        return Calibrator("temperature", {"T": float(np.exp(res.x))}, clip)
    if method == "isotonic":
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(pa, ya)
        xs = [float(v) for v in iso.X_thresholds_]
        ys = [float(v) for v in iso.y_thresholds_]
        return Calibrator("isotonic", {"x": xs, "y": ys}, clip)
    raise ValueError(f"unknown calibration method {method}")


def save(c: Calibrator, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"format": FORMAT, "method": c.method, "params": c.params, "clip": c.clip}
    data = json.dumps(payload, sort_keys=True, indent=1).encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def load(path: Path, expected_sha256: str | None = None) -> tuple[Calibrator, str]:
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and sha != expected_sha256:
        raise ValueError(f"{path}: sha256 {sha} != expected {expected_sha256}")
    d = json.loads(data)
    if d.get("format") != FORMAT:
        raise ValueError(f"{path}: unknown calibrator format")
    return Calibrator(d["method"], d["params"], d["clip"]), sha
