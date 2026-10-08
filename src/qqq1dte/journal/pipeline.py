"""The decision pipeline shared by the M15 analysis and the M16 journal: calibrated probabilities
from features only, regime cells, and per-session decisions (spec §4.1 with ADR-0010) passed
through the event engine.

For each test-block prediction timestamp T:
- P(C_call WIN), P(C_put WIN) from `decision.model_family` (saved artifacts) and its M13
  calibrators, the raw scores, and their calibration-block tail support (ADR-0010);
- per side, the frozen selection and §4.9 gates at T_e and the moderate entry fill;
- `decide`, then CALL / PUT decisions through the engine (one position, max entries per day).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from sqlalchemy import Engine, text

from qqq1dte.backtesting.artifacts import calibrators, model_scorers
from qqq1dte.backtesting.splits import Fold
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import Phase1Config
from qqq1dte.core.pit import AsOfReader
from qqq1dte.execution_sim.decision import CalibratedProbability, DecisionOutcome, SideInput, decide
from qqq1dte.execution_sim.engine import (
    Candidate,
    SessionResult,
    Signal,
    run_session,
    selection_detail_at,
)
from qqq1dte.execution_sim.fills import Moderate
from qqq1dte.execution_sim.selection import NoTrade, Selected
from qqq1dte.features.engine import FEATURE_NAMES
from qqq1dte.models.design import wide_features

DT = pl.Datetime("us", "UTC")
SIDES = (("C", "call", "C_call"), ("P", "put", "C_put"))


def decision_run_config(cfg: Phase1Config) -> dict[str, Any]:
    """The registered configuration of a decision run (M15 and the M16 journal share it)."""
    fam = cfg.decision.model_family
    return {
        "model": "decision_engine",
        "decision": cfg.decision.model_dump(mode="json"),
        "fills": cfg.fills.model_dump(mode="json"),
        "trade": cfg.trade.model_dump(mode="json"),
        "costs": cfg.costs.model_dump(mode="json"),
        "calibration_run": cfg.regimes.calibration_runs[fam],
        "model_run": cfg.calibration.reference_runs[fam],
        "regime_version": cfg.regimes.version,
    }


def _wide(root: Path, cfg: Phase1Config, sessions: Sequence[date]) -> pl.DataFrame:
    fdir = root / "data" / "features" / cfg.features.version
    return pl.concat(
        [
            wide_features(pl.read_parquet(fdir / f"session={d}.parquet"), FEATURE_NAMES)
            for d in sessions
        ]
    )


def max_feature_available_at(root: Path, cfg: Phase1Config, d: date) -> pl.DataFrame:
    """Latest `available_at` among the snapshot's feature rows, per prediction timestamp."""
    snap = pl.read_parquet(
        root / "data" / "features" / cfg.features.version / f"session={d}.parquet"
    )
    return snap.group_by("prediction_ts").agg(max_feature_available_at=pl.col("available_at").max())


def probabilities(engine: Engine, root: Path, cfg: Phase1Config, folds: list[Fold]) -> pl.DataFrame:
    """Per test-block timestamp: model / calibration ids, raw score, calibrated P(WIN) and the
    ADR-0010 support for C_call and C_put. Features only, never conditioned on labels."""
    fam = cfg.decision.model_family
    scorers = model_scorers(engine, root, fam, cfg.calibration.reference_runs[fam])
    cals = calibrators(engine, root, cfg.regimes.calibration_runs[fam])
    parts = []
    for f in folds:
        wide, calib_wide = _wide(root, cfg, f.test), _wide(root, cfg, f.calib)
        cols: dict[str, Any] = {"fold": pl.lit(f.index)}
        for _, key, tgt in SIDES:
            mid, scorer = scorers[(f.index, tgt)]
            cid, calib = cals[mid]
            raw = scorer(wide)
            calib_raw = np.sort(scorer(calib_wide))  # the block the calibrator was fit on
            cols[f"p_{key}"] = pl.Series(calib.apply(raw))
            cols[f"raw_{key}"] = pl.Series(raw)
            cols[f"support_{key}"] = pl.Series(
                calib_raw.size - np.searchsorted(calib_raw, raw, side="left")
            ).cast(pl.Int64)
            cols[f"ver_{key}"] = pl.lit(cid)
            cols[f"mid_{key}"] = pl.lit(mid)
        parts.append(wide.select("session_date", "prediction_ts").with_columns(**cols))
    return pl.concat(parts).with_columns(pl.col("prediction_ts").cast(DT))


def regime_frame(engine: Engine, cfg: Phase1Config) -> pl.DataFrame:
    """Stored R1 regime labels per prediction timestamp, with the joined cell."""
    with engine.connect() as c:
        rows = c.execute(
            text("SELECT ts, axis, value FROM regime_labels WHERE regime_version = :v"),
            {"v": cfg.regimes.version},
        ).all()
    df = pl.DataFrame(rows, schema={"ts": DT, "axis": pl.String, "value": pl.String}, orient="row")
    wide = df.pivot(on="axis", index="ts", values="value")
    return wide.select(
        pl.col("ts").alias("prediction_ts"),
        "volatility",
        "trend",
        "event",
        cell=pl.concat_str(["volatility", "trend", "event"], separator="/"),
    )


@dataclass(frozen=True)
class SideDetail:
    side_input: SideInput
    candidate: Candidate | None  # the chosen contract at T_e (None: no spot / no contract)


@dataclass
class TsDecision:
    prob: dict[str, Any]  # the probabilities() + regime row for this timestamp
    outcome: DecisionOutcome
    sides: tuple[SideDetail, SideDetail]
    underlying_price: float | None
    underlying_quote_ts: datetime | None
    final: str = ""  # decision after the engine: CALL / PUT / NO_TRADE / BLOCKED_POSITION_OPEN
    trades: list[Any] = field(default_factory=list)


def _candidate(
    t: datetime, side: str, sel: Selected | NoTrade, chosen: Any, quote: Any, cfg: Phase1Config
) -> Candidate | None:
    if chosen is None:
        return None
    failures = sel.details if isinstance(sel, NoTrade) else ()
    return Candidate(
        t,
        side,
        chosen.symbol,
        chosen.strike,
        chosen.expiration,
        quote.available_at if quote else None,
        quote.bid if quote else None,
        quote.ask if quote else None,
        quote.bid_sz if quote else None,
        quote.ask_sz if quote else None,
        cfg.fills.latency_s,
        not isinstance(sel, NoTrade),
        tuple(failures),
        not isinstance(sel, NoTrade),
    )


def _underlying(und: pl.DataFrame, t: datetime) -> tuple[float | None, datetime | None]:
    """Latest QQQ NBBO mid at or before T (any age; the quote time is journaled with it)."""
    q = (
        AsOfReader({"u": und}, t)
        .get("u")
        .filter(pl.col("bid").is_not_null() & pl.col("ask").is_not_null() & (pl.col("bid") > 0))
        .sort("available_at")
    )
    if not q.height:
        return None, None
    r = q.row(-1, named=True)
    return float((r["bid"] + r["ask"]) / 2), r["available_at"]


def decide_session(
    d: date, t: dict[str, pl.DataFrame], probs: list[dict[str, Any]], cfg: Phase1Config
) -> tuple[list[TsDecision], SessionResult]:
    cal = TradingCalendar(cfg)
    fill = Moderate(cfg, cfg.fills.moderate_alpha)
    lat = timedelta(seconds=cfg.fills.latency_s)
    out: list[TsDecision] = []
    signals = []
    for pr in sorted(probs, key=lambda r: r["prediction_ts"]):
        ts = pr["prediction_ts"]
        details = []
        for s, key, _ in SIDES:
            p = CalibratedProbability(pr[f"p_{key}"], pr[f"ver_{key}"])
            sel, chosen, quote = selection_detail_at(
                d, s, ts + lat, t["und"], t["chain"], t["records"], cal, cfg
            )
            if isinstance(sel, NoTrade):
                si = SideInput(s, p, sel.reason, None, pr[f"support_{key}"])
            else:
                si = SideInput(s, p, None, fill.buy(sel.quote), pr[f"support_{key}"])
            details.append(SideDetail(si, _candidate(ts, s, sel, chosen, quote, cfg)))
        res = decide(details[0].side_input, details[1].side_input, cfg, regime_cell=pr["cell"])
        price, price_ts = _underlying(t["und"], ts)
        out.append(TsDecision(pr, res, (details[0], details[1]), price, price_ts))
        if res.decision in ("CALL", "PUT"):
            signals.append(Signal(ts, "C" if res.decision == "CALL" else "P"))
    eng = run_session(d, signals, t["und"], t["chain"], t["records"], cal, cfg, fill)
    final = {e.prediction_ts: e for e in eng.decisions}
    trades: dict[datetime, list[Any]] = {}
    for tr in eng.trades:
        trades.setdefault(tr.prediction_ts, []).append(tr)
    for x in out:
        ts = x.prob["prediction_ts"]
        e = final.get(ts)
        x.final = (
            x.outcome.decision
            if e is None
            else (x.outcome.decision if e.decision == "ENTERED" else e.decision)
        )
        x.trades = trades.get(ts, [])
    return out, eng
