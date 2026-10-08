"""M19: full historical validation of gates 1-18 (spec §11) on the walk-forward evidence.

ADR-0011 (owner, option B): the final holdout stays locked while pre-holdout gates fail; every
check here uses pre-holdout sessions only (`HoldoutGuard`, `final_test_access_log` untouched).

One registered `final_validation` run. Evidence is recomputed where cheap and decisive (gate 3
PIT counts and feature replay, gate 7 re-selection of every journaled candidate, gate 17 journal
replay, gate 16 PBO, the test suites behind gates 4 / 7 / 8 / 9 / 17), and read from the
committed runs named in `validation_gates.evidence` otherwise (ids checked).

    uv run python scripts/m19_validation.py [--workers 7]
"""

from __future__ import annotations

import argparse
import os
import random
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m5_build_features as build
from qqq1dte.backtesting.holdout import HoldoutGuard
from qqq1dte.backtesting.oos import TARGETS as ALL_TARGETS
from qqq1dte.backtesting.oos import block_rows, code_commit, dataset_id, load_data
from qqq1dte.backtesting.registry import complete_run, fail_run, n_trials, register_run
from qqq1dte.backtesting.session_data import session_inputs
from qqq1dte.backtesting.splits import Fold, walk_forward_folds
from qqq1dte.core.calendar import TradingCalendar
from qqq1dte.core.config import load_config
from qqq1dte.core.timeutil import to_et
from qqq1dte.execution_sim.engine import selection_detail_at
from qqq1dte.features.engine import compute_session
from qqq1dte.journal.replay import replay
from qqq1dte.models.baseline import fit_baseline
from qqq1dte.models.design import KEYS, fit_design, transform
from qqq1dte.models.gbm import fit_gbm, grid_points
from qqq1dte.models.logistic import LogisticModel, fit_logistic
from qqq1dte.validation.phase1_gates import (
    FAIL,
    NOT_EVALUABLE,
    PASS,
    GateResult,
    gate6,
    gate10,
    gate11,
    gate13,
    gate14,
    gate15,
    gate16,
    gate_from_checks,
    pbo_cscv,
)

ROOT = Path(__file__).resolve().parents[1]
END = date(2026, 10, 2)
REPORT = ROOT / "reports" / "validation" / "m19_gates.md"
CFG = load_config()
EV = CFG.validation_gates.evidence
DECISION_TARGETS = ("C_call", "C_put")
SUITES = {  # test files behind the suite-based checks
    4: [
        "test_core_pit.py",
        "test_features_pit.py",
        "test_forward_reader.py",
        "test_splits.py",
        "test_design.py",
        "test_regimes.py",
        "test_baseline.py",
        "test_gbm.py",
    ],
    7: ["test_selection.py", "test_backtest_engine.py"],
    8: ["test_fills_accounting.py", "test_backtest_engine.py", "test_cursor.py"],
    9: ["test_reporting_gate9.py"],
    17: ["test_journal_replay.py", "test_logistic.py", "test_gbm.py"],
}


def metrics(engine: Engine, run_id: str) -> dict[str, Any]:
    with engine.connect() as c:
        row = c.execute(
            text("SELECT status, metrics FROM validation_runs WHERE run_id = :r"), {"r": run_id}
        ).one()
    if row[0] != "COMPLETED":
        raise RuntimeError(f"evidence run {run_id} is {row[0]}")
    return dict(row[1])


# -- test suites ------------------------------------------------------------------------------
def run_tests(junit: Path) -> dict[str, dict[str, int]]:
    env = {**os.environ, "REQUIRE_DB": "1"}
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", f"--junitxml={junit}"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
    )
    per_file: dict[str, dict[str, int]] = defaultdict(lambda: {"passed": 0, "failed": 0})
    for tc in ET.parse(junit).getroot().iter("testcase"):
        f = tc.get("classname", "").split(".")[-1] + ".py"
        bad = any(ch.tag in ("failure", "error") for ch in tc)
        per_file[f]["failed" if bad else "passed"] += 1
    return dict(per_file)


def suite_ok(per_file: dict[str, dict[str, int]], files: list[str]) -> bool:
    return all(
        f in per_file and per_file[f]["failed"] == 0 and per_file[f]["passed"] > 0 for f in files
    )


def lint_imports_ok() -> bool:
    return (
        subprocess.run(
            [sys.executable, "-m", "importlinter.cli", "lint"],
            cwd=ROOT,
            check=False,
            capture_output=True,
        ).returncode
        == 0
        or subprocess.run(
            ["lint-imports"], cwd=ROOT, check=False, capture_output=True, shell=False
        ).returncode
        == 0
    )


# -- gate 3 -----------------------------------------------------------------------------------
def gate3_evidence(sessions: list[date], cal: TradingCalendar) -> dict[str, Any]:
    fdir = ROOT / "data" / "features" / CFG.features.version
    counts = (
        pl.scan_parquet([fdir / f"session={d}.parquet" for d in sessions])
        .select(
            rows=pl.len(),
            violations=(
                pl.col("available_at").is_not_null()
                & (pl.col("available_at") > pl.col("prediction_ts"))
            ).sum(),
        )
        .collect()
        .row(0, named=True)
    )
    rng = random.Random(CFG.validation_gates.feature_replay_seed)
    picks = sorted(rng.sample(sessions, CFG.validation_gates.feature_replay_n))
    qqq = build._bars_cols(
        pl.read_parquet(build.CLEAN / "cleaned_market_data" / "ohlcv-1m" / "QQQ.parquet")
    )
    und = pl.read_parquet(build.CLEAN / "cleaned_market_data" / "bbo-1m" / "QQQ.parquet").select(
        "session_date", "ts", "available_at", "bid", "ask"
    )
    cross, _ = build.load_cross(cal, CFG, sessions)
    from qqq1dte.features.inputs import (  # noqa: PLC0415
        chain_table,
        daily_stats,
        macro_table,
        minute_profile,
        option_quotes_table,
        vix_table,
    )
    from qqq1dte.validation.records import build_definitions  # noqa: PLC0415

    raw_defs = pl.concat(
        [
            pl.read_parquet(p)
            for p in (ROOT / "data" / "raw" / "parquet" / "OPRA.PILLAR" / "definition").rglob(
                "*.parquet"
            )
        ],
        how="diagonal_relaxed",
    )
    tables_common = {
        "qqq_bars": qqq,
        "cross_quotes": cross,
        "daily": daily_stats(qqq),
        "profile": minute_profile(qqq, cal),
        "vix": vix_table(ROOT / "data" / "raw" / "cboe" / "VIX_History.csv", CFG),
        "macro": macro_table(ROOT / "configs" / "reference" / "macro_calendar.csv"),
        "und_quotes": und,
        "chain": chain_table(build_definitions(raw_defs, cal), CFG),
    }
    replays = []
    for d in picks:
        t = rng.choice(cal.prediction_timestamps(d))
        opts = option_quotes_table(
            pl.read_parquet(build.CLEAN / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"),
            pl.read_parquet(build.REJECTED / "cleaned_options_data" / "cbbo-1m" / f"{d}.parquet"),
        )
        fresh = compute_session(
            {**tables_common, "options": opts}, d, cal, CFG, timestamps=[t]
        ).sort("feature_name")
        stored = (
            pl.read_parquet(fdir / f"session={d}.parquet")
            .filter(pl.col("prediction_ts") == t)
            .sort("feature_name")
        )
        cols = ["feature_name", "value", "missing_reason", "available_at"]
        replays.append(
            {
                "session": str(d),
                "time_et": f"{to_et(t):%H:%M}",
                "identical": fresh.select(cols).equals(stored.select(cols)),
            }
        )
    return {"rows": counts["rows"], "violations": counts["violations"], "replays": replays}


# -- gate 7 / 17: re-select every journaled candidate -----------------------------------------
def reselect_job(
    args: tuple[date, dict[str, pl.DataFrame], list[dict[str, Any]]],
) -> dict[str, int]:
    d, t, cands = args
    cfg = load_config()
    cal = TradingCalendar(cfg)
    lat = timedelta(seconds=cfg.fills.latency_s)
    ok = bad = 0
    for c in cands:
        side = "C" if c["side"] == "CALL" else "P"
        sel, chosen, quote = selection_detail_at(
            d, side, c["prediction_ts"] + lat, t["und"], t["chain"], t["records"], cal, cfg
        )
        same = (
            chosen is not None
            and chosen.symbol == c["occ_symbol"]
            and quote is not None
            and quote.available_at == c["quote_ts"]
            and quote.bid == c["bid"]
            and quote.ask == c["ask"]
            and (sel.__class__.__name__ == "Selected") == c["passed"]
        )
        ok, bad = ok + same, bad + (not same)
    return {"ok": ok, "bad": bad}


def reselect_all(engine: Engine, cal: TradingCalendar, workers: int) -> dict[str, int]:
    with engine.connect() as c:
        rows = c.execute(
            text("""
            SELECT (p.prediction_ts AT TIME ZONE 'America/New_York')::date, p.prediction_ts,
              t.side, t.occ_symbol, t.quote_ts, t.bid, t.ask, t.passed_gates
            FROM trade_candidates t JOIN predictions p USING (prediction_id)
            WHERE p.run_id = :r"""),
            {"r": EV["journal_run"]},
        ).all()
    by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for d, ts, side, sym, qts, bid, ask, passed in rows:
        by_day[d].append(
            {
                "prediction_ts": ts,
                "side": side,
                "occ_symbol": sym,
                "quote_ts": qts,
                "bid": bid,
                "ask": ask,
                "passed": passed,
            }
        )
    days = sorted(by_day)
    total = {"ok": 0, "bad": 0}
    jobs = ((d, t, by_day[d]) for d, t in session_inputs(ROOT, days, cal, CFG))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(reselect_job, jobs, chunksize=2):
            total["ok"] += r["ok"]
            total["bad"] += r["bad"]
    total["candidates"] = len(rows)
    return total


# -- gate 16: PBO over the model-selection configurations ------------------------------------
def _log_loss_rows(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    q = np.clip(p, 1e-15, 1 - 1e-15)
    return np.asarray(-(y * np.log(q) + (1 - y) * np.log(1 - q)), dtype=np.float64)


def pbo_matrix(folds: list[Fold], target: str) -> pl.DataFrame:
    """Per test session: log-loss improvement over Model 0 (conditional) of each of the 9
    configurations tried (logistic C grid, LightGBM grid), refit per fold on train."""
    lid = target
    used = sorted({d for f in folds for d in (*f.train, *f.calib, *f.test)})
    wide, labels = load_data(ROOT, CFG, used)
    t = labels.filter((pl.col("label_id") == lid) & (pl.col("variant") == ""))
    feats = [c for c in wide.columns if c not in KEYS]
    out = []
    for f in folds:
        tr, ca, te = (block_rows(wide, t, b) for b in (f.train, f.calib, f.test))
        y_tr, y_ca, y_te = (d["y"].cast(pl.Float64).to_numpy() for d in (tr, ca, te))
        m0 = fit_baseline(tr.with_columns(vix=pl.col("vix_prev_close")), CFG.models.baseline)
        p0 = m0.predict(te.with_columns(vix=pl.col("vix_prev_close")))
        cols: dict[str, np.ndarray] = {}
        design = fit_design(tr.drop("y"), CFG.models.logistic.z_clip)
        x_tr, _ = transform(design, tr)
        x_te, _ = transform(design, te)
        for c in CFG.models.logistic.c_grid:
            coef, b = fit_logistic(x_tr, y_tr, c, CFG.models.logistic)
            cols[f"logistic C={c:g}"] = LogisticModel(design, tuple(coef), b, c).score_matrix(x_te)
        xt, xc, xs = (d.select(feats).to_numpy().astype(np.float64) for d in (tr, ca, te))
        for pt in grid_points(CFG.models.gbm):
            g = fit_gbm(xt, y_tr, xc, y_ca, pt, CFG.models.gbm, feats)
            cols[f"gbm leaves={pt['num_leaves']} min_leaf={pt['min_data_in_leaf']}"] = g.predict(xs)
        base = _log_loss_rows(y_te, p0)
        frame = te.select("session_date").with_columns(
            **{k: pl.Series(base - _log_loss_rows(y_te, v)) for k, v in cols.items()}
        )
        out.append(frame.group_by("session_date").mean())
        print(f"PBO {target} fold {f.index}", flush=True)
    return pl.concat(out).sort("session_date")


# -- report -----------------------------------------------------------------------------------
def write_report(gates: list[GateResult], meta: dict[str, Any]) -> None:
    fails = [g for g in gates if g.status != PASS]
    lines = [
        "# M19 full historical validation: gates 1-18 (spec §11)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {meta['commit'][:12]}, run "
        f"`{meta['run_id']}`. Walk-forward evidence (7 folds, test blocks 2024-05-28 → "
        f"2026-02-27). **Final holdout not opened** (ADR-0011; final_test_access_log rows: "
        f"{meta['holdout_accesses']}). n_trials on the test window: **{meta['n_trials']}** "
        "distinct registered configurations.",
        "",
        f"## Verdict: **{'ALL GATES PASS' if not fails else 'FAIL'}** — "
        f"{sum(g.status == PASS for g in gates)} PASS, "
        f"{sum(g.status == FAIL for g in gates)} FAIL, "
        f"{sum(g.status == NOT_EVALUABLE for g in gates)} NOT_EVALUABLE "
        "(counts as not passed).",
        "",
        "Progression to M20 (paper mode) is blocked unless the owner records an ADR accepting the "
        "limitation (M19 criterion 3). This report states evidence and uncertainty only; it makes "
        "no claim of profitability (rule 12).",
        "",
        "| # | gate | status | rule | key numbers |",
        "|---|---|---|---|---|",
    ]
    for g in gates:
        lines.append(
            f"| {g.number} | {g.name} | **{g.status}** | {g.rule} | {meta['summary'][g.number]} |"
        )
    lines += ["", "## Details", ""]
    for g in gates:
        lines += [
            f"### Gate {g.number}: {g.name} — {g.status}",
            "",
            *[
                f"- {k}: {'pass' if v else 'fail' if v is False else 'not evaluable'}"
                for k, v in g.numbers.get("checks", {}).items()
            ],
            *[f"- {line}" for line in meta["notes"].get(g.number, [])],
            "",
        ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:  # noqa: PLR0915 (one evaluation, many gates)
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    cal = TradingCalendar(CFG)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set")
        return 2
    engine = create_engine(url)
    hold = cal.final_holdout_start(END)
    sessions = cal.research_sessions(CFG.history.option_era_start, hold)
    HoldoutGuard(hold, engine).check(sessions)  # pre-holdout only (ADR-0011)
    folds = walk_forward_folds(sessions, hold, CFG)
    window = (folds[0].test[0], folds[-1].test[-1])
    commit = code_commit(ROOT)
    run_id = register_run(
        engine,
        run_kind="final_validation",
        config={
            "validation_gates": CFG.validation_gates.model_dump(mode="json"),
            "adr": ["ADR-0008", "ADR-0009", "ADR-0010", "ADR-0011"],
        },
        data_window=window,
        dataset_id=dataset_id(engine, f"data/features/{CFG.features.version}"),
        code_commit=commit,
        folds=[],
        touches_final_holdout=False,
    )
    print(f"registered run {run_id}")
    summary: dict[int, str] = {}
    notes: dict[int, list[str]] = defaultdict(list)
    gates: list[GateResult] = []
    try:
        junit = ROOT / "data" / "validation" / f"{run_id}_junit.xml"
        junit.parent.mkdir(parents=True, exist_ok=True)
        per_file = run_tests(junit)
        all_ok = all(v["failed"] == 0 for v in per_file.values())
        n_tests = sum(v["passed"] + v["failed"] for v in per_file.values())
        print(f"tests: {n_tests}, all passed: {all_ok}", flush=True)
        # gates 1-2: stored M4 evaluation + live DB check
        g12 = (ROOT / "reports" / "dq" / "gates.md").read_text(encoding="utf-8")
        with engine.connect() as c:
            # current dataset versions only: the latest registration per storage path
            # (superseded versions of the same path keep their own historical events)
            open_crit = c.execute(
                text("""
                SELECT count(*) FROM data_quality_events e
                WHERE e.severity = 'CRITICAL' AND e.resolved_by_adr IS NULL
                  AND e.dataset_id IN (
                    SELECT DISTINCT ON (storage_uri) dataset_id FROM dataset_versions
                    ORDER BY storage_uri, created_at DESC)""")
            ).scalar_one()
        m1 = re.search(r"\| 1 Data coverage \| (PASS|FAIL) \| ([^|]+)\|", g12)
        m2 = re.search(r"\| 2 Data quality \| (PASS|FAIL) \| ([^|]+)\|", g12)
        assert m1 and m2
        gates.append(
            gate_from_checks(
                1,
                "Data coverage",
                "≥ 98% of 1-min bars per session; ≥ 95% "
                "of sessions with a valid chain at ≥ 95% of timestamps",
                {"M4 evaluation": m1.group(1) == "PASS"},
                {},
            )
        )
        summary[1] = m1.group(2).strip()
        gates.append(
            gate_from_checks(
                2,
                "Data quality",
                "0 open CRITICAL DQ events; invalid-quote rate ≤ 2% (ATM ± 5)",
                {
                    "M4 evaluation": m2.group(1) == "PASS",
                    "open CRITICAL events now = 0 (current dataset versions)": open_crit == 0,
                },
                {},
            )
        )
        summary[2] = f"{m2.group(2).strip()}; open CRITICAL now {open_crit}"
        notes[1].append("From M4 (`reports/dq/gates.md`, full downloaded history).")
        # gate 3
        g3 = gate3_evidence(sessions, cal)
        replay_ok = all(r["identical"] for r in g3["replays"])
        gates.append(
            gate_from_checks(
                3,
                "PIT integrity",
                "100% of feature rows available_at ≤ T; 20 random timestamps replay exactly",
                {"no violations": g3["violations"] == 0, "replays identical": replay_ok},
                g3,
            )
        )
        summary[3] = (
            f"{g3['rows']:,} pre-holdout rows, {g3['violations']} violations; "
            f"{sum(r['identical'] for r in g3['replays'])}/{len(g3['replays'])} replays identical"
        )
        print("gate 3 done", flush=True)
        # gate 4
        canary = metrics(engine, EV["canary_run"])
        canary_ok = all(v["pass"] for v in canary.values())
        li = lint_imports_ok()
        gates.append(
            gate_from_checks(
                4,
                "Leakage tests",
                "T-LEAK suite passes; planted-future "
                "canary; shuffled-label AUC 0.50 ± 0.02 (ADR-0008)",
                {
                    "T-LEAK test files pass": suite_ok(per_file, SUITES[4]),
                    "import contract (lint-imports)": li,
                    "shuffled-label canary": canary_ok,
                },
                {},
            )
        )
        summary[4] = (
            f"canary statistic {min(v['statistic'] for v in canary.values()):.4f}-"
            f"{max(v['statistic'] for v in canary.values()):.4f} (10 targets); "
            f"import contract {'kept' if li else 'BROKEN'}"
        )
        # gate 5
        m7 = metrics(engine, EV["baseline_run"])
        folds7 = {r["fold"] for r in m7["per_fold"]}
        gates.append(
            gate_from_checks(
                5,
                "Baseline",
                "Model 0 OOS Brier, log loss, calibration per fold",
                {
                    "all folds reported": folds7 == {f.index for f in folds},
                    "all targets pooled": len(m7["pooled"]) == len(ALL_TARGETS),
                },
                {},
            )
        )
        summary[5] = f"{len(m7['per_fold'])} fold x target rows, {len(m7['pooled'])} pooled targets"
        # gate 6
        m9 = metrics(engine, EV["model_run"])
        per = {
            t: {
                "bss": m9["pooled"][t]["bss_vs_m0c"],
                "ci": m9["pooled"][t]["bss_vs_m0c_ci"],
                "folds_better": m9["pooled"][t]["folds_better"]["m0c"],
                "n_folds": m9["pooled"][t]["n_folds"],
            }
            for t in DECISION_TARGETS
        }
        gates.append(gate6(per, CFG))
        summary[6] = "; ".join(
            f"{t} BSS {e['bss']:+.4f} [{e['ci'][0]:+.4f}, {e['ci'][1]:+.4f}], "
            f"{e['folds_better']}/{e['n_folds']} folds"
            for t, e in per.items()
        )
        notes[6].append(
            "Model family `gbm_m2` (decision.model_family), decision targets C_call / "
            "C_put, reference = conditional Model 0."
        )
        # gate 7 (and part of 17): re-select every journaled candidate
        rs = reselect_all(engine, cal, args.workers)
        gates.append(
            gate_from_checks(
                7,
                "PIT option selection",
                "T-SEL suite passes; 100% of journal selections reproduce",
                {
                    "T-SEL tests pass": suite_ok(per_file, SUITES[7]),
                    "all journal candidates reproduce": rs["bad"] == 0,
                },
                rs,
            )
        )
        summary[7] = f"{rs['ok']:,}/{rs['candidates']:,} journal candidates reproduced"
        print("gate 7 done", flush=True)
        # gates 8, 9
        gates.append(
            gate_from_checks(
                8,
                "Bid/ask execution",
                "T-FILL and T-BT suites pass",
                {"T-FILL / T-BT tests pass": suite_ok(per_file, SUITES[8])},
                {},
            )
        )
        summary[8] = ", ".join(f"{f} {per_file.get(f, {}).get('passed', 0)}" for f in SUITES[8])
        gates.append(
            gate_from_checks(
                9,
                "Costs",
                "every reported P&L net of §4.8 costs (type)",
                {"gate-9 tests pass (incl. mypy check)": suite_ok(per_file, SUITES[9])},
                {},
            )
        )
        summary[9] = "NetPnl type; report helpers accept only NetPnl"
        # gates 10, 11, 13, 14, 15: traded decisions of the decision configuration
        trades = pl.read_parquet(
            ROOT / "data" / "decisions" / EV["decision_run"] / "trades.parquet"
        )
        n_tr = trades.height
        n_sess = trades["session_date"].n_unique() if n_tr else 0
        dm = metrics(engine, EV["decision_run"])
        gates.append(gate10(None, None, CFG))  # 0 trades under ADR-0010: nothing to measure
        summary[10] = f"{n_tr} trades under the decision configuration (ADR-0010)"
        gates.append(gate11(None, None))
        summary[11] = "no trades: conservative expectancy and alpha sign not defined"
        # gate 12
        cal_m = metrics(engine, EV["calibration_run"])["pooled"]
        gates.append(
            gate_from_checks(
                12,
                "Calibration",
                "ECE ≤ 0.03; slope in [0.8, 1.2]; bin rule (ADR-0009)",
                {f"{t} gate 12": bool(cal_m[t]["cal"]["pass"]) for t in DECISION_TARGETS},
                {},
            )
        )
        summary[12] = "; ".join(
            f"{t} ECE {cal_m[t]['cal']['ece']:.4f}, slope "
            f"{cal_m[t]['cal']['slope']:.3f}, bins failed "
            f"{cal_m[t]['cal']['bins_failed']}/{cal_m[t]['cal']['bins_checked']}"
            for t in DECISION_TARGETS
        )
        gates.append(gate13([], n_tr, CFG))
        summary[13] = "no traded regime cells"
        gates.append(gate14(None, n_tr))
        summary[14] = (
            f"0 traded timestamps; NO_TRADE counterfactual {dm.get('counterfactual', 0):,} "
            "trades (M15)"
        )
        gates.append(gate15(n_tr, n_sess, CFG))
        summary[15] = f"{n_tr} trades, {n_sess} sessions"
        # gate 16
        pbo: dict[str, float] = {}
        for tgt in DECISION_TARGETS:
            mat = pbo_matrix(folds, tgt)
            perf = mat.drop("session_date").to_numpy()
            pbo[tgt], _ = pbo_cscv(perf, CFG.validation_gates.pbo_blocks)
            notes[16].append(
                f"{tgt}: PBO {pbo[tgt]:.3f} over {perf.shape[1]} configurations x "
                f"{perf.shape[0]} test sessions (log-loss improvement vs Model 0)"
            )
        nt = n_trials(engine, *window)
        g16 = gate16(max(pbo.values()), None, CFG)
        gates.append(g16)
        summary[16] = (
            f"PBO {', '.join(f'{t} {v:.3f}' for t, v in pbo.items())}; DSR not "
            f"evaluable (no trade returns); n_trials {nt}"
        )
        notes[16].append(
            "DSR needs strategy returns; there are none under the decision "
            "configuration, so the DSR check is NOT_EVALUABLE."
        )
        # gate 17
        with engine.connect() as c:
            ids = [
                r[0]
                for r in c.execute(
                    text(
                        "SELECT prediction_id FROM predictions WHERE run_id "
                        "= :r ORDER BY prediction_id"
                    ),
                    {"r": EV["journal_run"]},
                ).all()
            ]
        sample = random.Random(CFG.validation_gates.journal_replay_seed).sample(
            ids, CFG.validation_gates.journal_replay_sample
        )
        with engine.connect() as c:
            days = sorted(
                {
                    r[0]
                    for r in c.execute(
                        text(
                            "SELECT DISTINCT (prediction_ts AT TIME ZONE 'America/New_York')::date "
                            "FROM "
                            "predictions WHERE prediction_id = ANY(:i)"
                        ),
                        {"i": sample},
                    ).all()
                }
            )
        markets = dict(session_inputs(ROOT, days, cal, CFG))
        rep = [replay(engine, ROOT, CFG, pid, lambda d: markets[d]) for pid in sample]
        rep_ok = sum(r.ok for r in rep)
        gates.append(
            gate_from_checks(
                17,
                "Reproducibility",
                "re-running a logged run reproduces predictions to 1e-9 and identical trades",
                {
                    "journal replay sample reproduced": rep_ok == len(rep),
                    "all journal selections reproduce": rs["bad"] == 0,
                    "serialization / replay tests pass": suite_ok(per_file, SUITES[17]),
                },
                {},
            )
        )
        summary[17] = (
            f"{rep_ok}/{len(rep)} predictions replayed (fresh seed), "
            f"{sum(r.checked for r in rep):,} checks; 0 trades to compare"
        )
        # gate 18
        mon = metrics(engine, EV["monitoring_run"])["replay"]
        gates.append(
            gate_from_checks(
                18,
                "Drift monitoring",
                "synthetic drift raises the right alert within 10 sessions (replay)",
                {k: bool(v["pass"]) for k, v in mon.items()},
                {},
            )
        )
        summary[18] = "; ".join(
            f"{k}: {sum(r['detected'] for r in v['replays'])}/"
            f"{len(v['replays'])} detected, max delay {v['max_delay']}, "
            f"{v['false_alarm_replays']} false-alarm replays"
            for k, v in mon.items()
        )
        gates.sort(key=lambda g: g.number)
        with engine.connect() as c:
            acc = c.execute(text("SELECT count(*) FROM final_test_access_log")).scalar_one()
        out = {
            "gates": [
                {
                    "number": g.number,
                    "name": g.name,
                    "status": g.status,
                    "summary": summary[g.number],
                }
                for g in gates
            ],
            "n_trials": nt,
            "tests": {"n": n_tests, "all_passed": all_ok},
            "pbo": pbo,
            "holdout_accesses": acc,
        }
    except Exception as e:
        fail_run(engine, run_id, repr(e))
        raise
    complete_run(engine, run_id, out)
    write_report(
        gates,
        {
            "commit": commit,
            "run_id": run_id,
            "n_trials": nt,
            "summary": summary,
            "notes": notes,
            "holdout_accesses": acc,
        },
    )
    engine.dispose()
    print(f"completed run {run_id}: " + ", ".join(f"{g.number}:{g.status}" for g in gates))
    return 0


if __name__ == "__main__":
    sys.exit(main())
