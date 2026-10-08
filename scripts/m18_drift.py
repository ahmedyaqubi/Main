"""M18: drift monitoring on the journaled research predictions (spec Phase 1Q, gate 18).

Data: the M16 journal run (`monitoring.journal_run`): calibrated C_call / C_put probabilities,
R1 regime cells, the f2 feature snapshot values at each prediction time, and the L2 C labels as
outcomes. Reference = test blocks of `monitoring.reference_folds`.

1. Gate-18 replay (owner M18 Q4): the reference sessions replayed in seeded random orders,
   injections at `replay.inject_at_session`: (a) features shifted by `feature_shift_sd`
   reference SDs -> PAPER_ONLY expected; (b) `win_loss_flip` of WIN outcomes -> LOSS on both
   decision targets -> DISABLED expected. Pass: every replay detects the right alert within
   `max_delay_sessions`, and at most `max_false_alarm_replays` replays escalate before injection.
2. Chronological monitoring (information): the remaining folds' test blocks in time order,
   rolling windows vs the reference, with the latching DriftMonitor.
One `validation_runs` row (run_kind "monitoring").

    uv run python scripts/m18_drift.py
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text

from qqq1dte.backtesting.oos import code_commit, dataset_id
from qqq1dte.backtesting.registry import complete_run, fail_run, register_run
from qqq1dte.backtesting.splits import walk_forward_folds
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.features.engine import FEATURE_NAMES
from qqq1dte.monitoring.drift import DriftMonitor, assess_window, build_reference, replay_detection

ROOT = Path(__file__).resolve().parents[1]
END = date(2026, 10, 2)
REPORT = ROOT / "reports" / "monitoring" / "m18_drift.md"
CFG = load_config()
DT = pl.Datetime("ns", "UTC")
FEATS = [f for f in FEATURE_NAMES if f != "day_of_week"]  # calendar position, not a distribution


def frame(engine: Engine, sessions: list[date]) -> pl.DataFrame:
    """One row per journaled prediction: features, p_/y_ per decision target, regime cell."""
    with engine.connect() as c:
        rows = c.execute(
            text("""
            SELECT p.prediction_ts, p.regime->>'cell', s.target, s.calibrated_prob
            FROM predictions p JOIN prediction_scores s USING (prediction_id)
            WHERE p.run_id = :r"""),
            {"r": CFG.monitoring.journal_run},
        ).all()
    pr = pl.DataFrame(
        rows,
        schema={
            "prediction_ts": pl.Datetime("us", "UTC"),
            "cell": pl.String,
            "target": pl.String,
            "p": pl.Float64,
        },
        orient="row",
    )
    pr = pr.with_columns(pl.col("prediction_ts").dt.cast_time_unit("ns")).pivot(
        on="target", index=["prediction_ts", "cell"], values="p"
    )
    pr = pr.rename({"C_call": "p_C_call", "C_put": "p_C_put"})
    fdir = ROOT / "data" / "features" / CFG.features.version
    ldir = ROOT / "data" / "labels" / CFG.labels.version
    feats = pl.concat(
        [
            pl.read_parquet(fdir / f"session={d}.parquet")
            .filter(pl.col("feature_name").is_in(FEATS))
            .pivot(on="feature_name", index=["session_date", "prediction_ts"], values="value")
            for d in sessions
        ],
        how="diagonal_relaxed",
    )
    labs = (
        pl.concat(
            [
                pl.read_parquet(ldir / f"session={d}.parquet")
                .filter(pl.col("label_id").is_in(["C_call", "C_put"]))
                .select("prediction_ts", "label_id", pl.col("value").cast(pl.Float64))
                for d in sessions
            ]
        )
        .pivot(on="label_id", index="prediction_ts", values="value")
        .rename({"C_call": "y_C_call", "C_put": "y_C_put"})
    )
    return (
        feats.join(pr, on="prediction_ts", how="inner")
        .join(labs, on="prediction_ts", how="left")
        .sort("prediction_ts")
    )


def chronological(ref_frame: pl.DataFrame, live: pl.DataFrame) -> dict[str, Any]:
    m = CFG.monitoring
    ref = build_reference(ref_frame, FEATS, CFG)
    days = live["session_date"].unique().sort().to_list()
    by_day = {d: g for (d,), g in live.group_by("session_date")}
    cells = {d: g["cell"][0] for d, g in by_day.items()}
    mon = DriftMonitor()
    timeline = []
    for i in range(m.window_sessions - 1, len(days)):
        win_days = days[i - m.window_sessions + 1 : i + 1]
        rdays = days[max(0, i - m.regime_window_sessions + 1) : i + 1]
        a = assess_window(
            pl.concat([by_day[d] for d in win_days]),
            ref,
            CFG,
            regime_cells=[cells[d] for d in rdays],
        )
        st = mon.update(a, days[i])
        timeline.append(
            {
                "session": days[i],
                "state": st,
                "overall": a.overall,
                **a.levels,
                "max_feature_psi": a.details["features"]["max_psi"],
                "feature": a.details["features"]["feature"],
                "z_combined": a.details["calibration"]["combined"],
            }
        )
    return {"timeline": timeline, "thresholds": ref.thresholds}


def write_report(rep: dict[str, Any], chrono: dict[str, Any], meta: dict[str, Any]) -> None:
    rc, m = CFG.monitoring.replay, CFG.monitoring
    tl = pl.DataFrame(chrono["timeline"])
    lines = [
        "# M18 drift monitoring (spec Phase 1Q, gate 18)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {meta['commit'][:12]}, run "
        f"`{meta['run_id']}`. Predictions: journal run `{m.journal_run}`. Reference: test blocks "
        f"of folds {m.reference_folds} ({meta['n_ref']} sessions). Final holdout not opened.",
        "",
        f"Monitors over the last {m.window_sessions} sessions: feature PSI (max over "
        f"{len(FEATS)} features) and prediction PSI, with thresholds calibrated to no-drift "
        f"noise (owner, M18 option A): WARN above the {m.psi_warn_quantile:.1%} and PAPER_ONLY "
        f"above the {m.psi_paper_only_quantile:.1%} quantile of the monitor's PSI over "
        f"{m.psi_null_draws:,} random {m.window_sessions}-session windows of the reference, each "
        "compared with the reference without its own sessions (reference thresholds: features "
        f"{meta['thr']['features'][0]:.3f} / {meta['thr']['features'][1]:.3f}, predictions "
        f"{meta['thr']['predictions'][0]:.3f} / {meta['thr']['predictions'][1]:.3f}, regimes "
        f"WARN {meta['thr']['regimes'][0]:.3f}); calibration z = mean(observed - predicted) / "
        "reference session-clustered SE, per decision target and combined (any |z| > "
        f"{m.calib_z_warn} WARN; DISABLED only when the combined |z| > {m.calib_z_disable}); "
        f"expectancy (>= {m.min_trades} trades); regime-cell "
        f"PSI over {m.regime_window_sessions} sessions (WARN only). DISABLED latches until a named "
        "human re-enables; `decide` returns NO_TRADE DRIFT_DISABLED while disabled.",
        "",
        "## Gate 18: synthetic drift injection (replay)",
        "",
        f"{rc.n_replays} replays per injection; the reference sessions in seeded random order "
        f"(seed {rc.seed}; stationary by construction), injection from session "
        f"{rc.inject_at_session}. Pass: right alert within {rc.max_delay_sessions} sessions in "
        f"every replay and at most {rc.max_false_alarm_replays} replay(s) escalating "
        "(PAPER_ONLY / DISABLED) before injection.",
        "",
        "| injection | expected alert | detected | delay (sessions) min / median / max "
        "| false-alarm replays | result |",
        "|---|---|---|---|---|---|",
    ]
    for kind, label in (
        ("feature_shift", f"features +{rc.feature_shift_sd:g} SD"),
        ("calibration", f"{rc.win_loss_flip:.0%} of WINs -> LOSS (both sides)"),
    ):
        r = rep[kind]
        d = sorted(x["delay"] for x in r["replays"])
        lines.append(
            f"| {label} | {r['expected']} | {sum(x['detected'] for x in r['replays'])}/"
            f"{len(r['replays'])} | {d[0]} / {d[len(d) // 2]} / {d[-1]} "
            f"| {r['false_alarm_replays']} | {'PASS' if r['pass'] else 'FAIL'} |"
        )
    states = tl.group_by("state").len().sort("len", descending=True)
    first_dis = tl.filter(pl.col("state") == "DISABLED")
    lines += [
        "",
        "Known limit: a calibration degradation on only one decision target moves the combined "
        "gap half as much; such a change reaches WARN (single-target |z| about 2.3 after 10 "
        "sessions for the same 50% flip) rather than DISABLED within 10 sessions.",
        "",
        "## Chronological monitoring (information): remaining folds vs the reference",
        "",
        f"{tl.height} rolling windows ({meta['first']} → {meta['last']}).",
        "",
        "| state (latched) | windows |",
        "|---|---|",
        *[f"| {r['state']} | {r['len']} |" for r in states.to_dicts()],
        "",
        "| monitor | OK | WARN | PAPER_ONLY | DISABLED |",
        "|---|---|---|---|---|",
        *[
            f"| {mon} | "
            + " | ".join(
                str(int((tl[mon] == lv).sum())) for lv in ("OK", "WARN", "PAPER_ONLY", "DISABLED")
            )
            + " |"
            for mon in ("features", "predictions", "calibration", "expectancy", "regimes")
        ],
        "",
        "First DISABLED: " + (f"{first_dis['session'][0]}" if first_dis.height else "never") + ".",
        "",
        "Most frequent max-PSI features in escalated windows: "
        + ", ".join(
            f"{r['feature']} ({r['len']})"
            for r in tl.filter(pl.col("features") != "OK")
            .group_by("feature")
            .len()
            .sort("len", descending=True)
            .head(5)
            .to_dicts()
        )
        + ".",
        "",
        "Expectancy is not evaluable: the current decision configuration (ADR-0010) makes no "
        "trades.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    load_dotenv(ROOT / ".env")
    cal = TradingCalendar(CFG)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set")
        return 2
    engine = create_engine(url)
    hold = cal.final_holdout_start(END)
    folds = walk_forward_folds(cal.research_sessions(CFG.history.option_era_start, hold), hold, CFG)
    ref_days = sorted(
        {d for f in folds if f.index in CFG.monitoring.reference_folds for d in f.test}
    )
    live_days = sorted(
        {d for f in folds if f.index not in CFG.monitoring.reference_folds for d in f.test}
    )
    commit = code_commit(ROOT)
    run_id = register_run(
        engine,
        run_kind="monitoring",
        config={"monitoring": CFG.monitoring.model_dump(mode="json"), "features": FEATS},
        data_window=(ref_days[0], live_days[-1]),
        dataset_id=dataset_id(engine, f"data/features/{CFG.features.version}"),
        code_commit=commit,
        folds=[],
    )
    print(f"registered run {run_id}")
    try:
        ref_frame = frame(engine, ref_days)
        live = frame(engine, live_days)
        rep = replay_detection(ref_frame, FEATS, CFG)
        print({k: v["pass"] for k, v in rep.items()}, flush=True)
        chrono = chronological(ref_frame, live)
    except Exception as e:
        fail_run(engine, run_id, repr(e))
        raise
    states: dict[str, int] = {}
    for t in chrono["timeline"]:
        states[t["state"]] = states.get(t["state"], 0) + 1
    complete_run(
        engine,
        run_id,
        {"replay": rep, "chronological_states": states, "thresholds": chrono["thresholds"]},
    )
    write_report(
        rep,
        chrono,
        {
            "commit": commit,
            "run_id": run_id,
            "n_ref": len(ref_days),
            "first": chrono["timeline"][0]["session"],
            "last": chrono["timeline"][-1]["session"],
            "thr": chrono["thresholds"],
        },
    )
    engine.dispose()
    print(f"completed run {run_id}; report {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
