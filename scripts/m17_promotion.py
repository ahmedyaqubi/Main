"""M17: promotion review of the decision model family's latest-fold candidates (spec Phase 1P).

For C_call and C_put: the candidate is `decision.model_family`'s model from the latest
walk-forward fold (`promotion.candidate_fold`). Evidence is read from stored runs only
(`promotion.evidence`): out-of-sample Brier skill and fold shares (model run), the gate-4 canary,
gate-12 calibration, and traded expectancy / sample / regimes (decision run). Gates are
evaluated (`models.promotion.evaluate_gates`). A candidate that does not pass every gate is
recorded as KEEP_CURRENT with the named reviewer. An eligible candidate is NOT promoted here:
promotion is a separate human action (`python -m qqq1dte.models.promotion`).

    uv run python scripts/m17_promotion.py --approved-by "<name>"
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text

from qqq1dte.backtesting.oos import code_commit, dataset_id
from qqq1dte.backtesting.registry import complete_run, fail_run, register_run
from qqq1dte.backtesting.reporting import net_from_frame, summarize_net
from qqq1dte.core.config import load_config
from qqq1dte.models.promotion import Evidence, eligible, evaluate_gates, record_keep_current

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "models" / "promotion_m17.md"
CFG = load_config()
TARGETS = (("C_call", "C"), ("C_put", "P"))


def _metrics(engine: Engine, run_id: str) -> dict[str, Any]:
    with engine.connect() as c:
        m = c.execute(
            text("SELECT metrics FROM validation_runs WHERE run_id = :r AND status = 'COMPLETED'"),
            {"r": run_id},
        ).scalar_one()
    return dict(m)


def evidence(engine: Engine, target: str, side: str) -> tuple[Evidence, dict[str, Any]]:
    ev = CFG.promotion.evidence
    model = _metrics(engine, ev["model_run"])["pooled"][target]
    canary = _metrics(engine, ev["canary_run"])[target]
    cal = _metrics(engine, ev["calibration_run"])["pooled"][target]["cal"]
    trades = pl.read_parquet(ROOT / "data" / "decisions" / ev["decision_run"] / "trades.parquet")
    t = trades.filter(pl.col("side") == side) if trades.height else trades
    net = None
    if t.height:
        net = summarize_net(net_from_frame(t), t["session_date"].to_list(), CFG)
    e = Evidence(
        bss_vs_m0=model["bss_vs_m0c"],
        bss_vs_m0_ci=tuple(model["bss_vs_m0c_ci"]),
        folds_better_share=model["folds_better"]["m0c"] / model["n_folds"],
        bss_vs_current_ci=None,
        gate12_pass=bool(cal["pass"]),
        ece=cal["ece"],
        # gate 13 and fold-level expectancy need traded cells; with no trades they are missing
        gate13_pass=None,
        mean_net=None if net is None else net.mean,
        mean_net_ci=None if net is None else net.ci,
        folds_positive_share=None,
        conservative_mean_net=None,  # decision trades are simulated at the moderate fill
        n_trades=t.height,
        n_sessions=t["session_date"].n_unique() if t.height else 0,
        canary_pass=bool(canary["pass"]),
    )
    raw = {
        "bss_vs_m0": model["bss_vs_m0c"],
        "bss_vs_m0_ci": model["bss_vs_m0c_ci"],
        "folds_better": f"{model['folds_better']['m0c']}/{model['n_folds']}",
        "gate12_pass": cal["pass"],
        "ece": cal["ece"],
        "slope": cal["slope"],
        "canary_statistic": canary["statistic"],
        "n_trades": t.height,
    }
    return e, raw


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--approved-by", required=True, help="named human reviewer (recorded)")
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set")
        return 2
    engine = create_engine(url)
    fam, fold = CFG.decision.model_family, CFG.promotion.candidate_fold
    prefix = {"gbm_m2": "m2", "logistic_m1": "m1"}[fam]
    model_run = CFG.calibration.reference_runs[fam]
    commit = code_commit(ROOT)
    with engine.connect() as c:
        window = c.execute(
            text(
                "SELECT data_window_start, data_window_end FROM validation_runs WHERE run_id = :r"
            ),
            {"r": model_run},
        ).one()
    run_id = register_run(
        engine,
        run_kind="promotion_review",
        config={
            "promotion": CFG.promotion.model_dump(mode="json"),
            "model_family": fam,
            "model_run": model_run,
        },
        data_window=(window[0], window[1]),
        dataset_id=dataset_id(engine, f"data/features/{CFG.features.version}"),
        code_commit=commit,
        folds=[],
    )
    out: dict[str, Any] = {"targets": {}}
    try:
        for target, side in TARGETS:
            candidate = f"{prefix}-{model_run}-f{fold}-{target}"
            with engine.connect() as c:
                current = c.execute(
                    text(
                        "SELECT model_version_id FROM model_versions WHERE "
                        "target_label = :t AND status = 'PRODUCTION'"
                    ),
                    {"t": target},
                ).scalar_one_or_none()
                c.execute(
                    text("SELECT 1 FROM model_versions WHERE model_version_id = :m"),
                    {"m": candidate},
                ).one()
            ev, raw = evidence(engine, target, side)
            gates = evaluate_gates(ev, None, CFG) if current is None else None
            if gates is None:
                raise RuntimeError(
                    f"{target}: a production model exists ({current}); comparing "
                    "against it needs its stored evidence (not implemented)"
                )
            ok = eligible(gates)
            if not ok:
                record_keep_current(engine, candidate, current, gates, approved_by=args.approved_by)
            out["targets"][target] = {
                "candidate": candidate,
                "current": current,
                "gates": gates,
                "evidence": raw,
                "eligible": ok,
                "recorded": None if ok else "KEEP_CURRENT",
            }
    except Exception as e:
        fail_run(engine, run_id, repr(e))
        raise
    complete_run(engine, run_id, out)
    lines = [
        "# M17 promotion review (spec Phase 1P)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, code {commit[:12]}, run `{run_id}`, "
        f"reviewer **{args.approved_by}**. Candidates: `{fam}` fold {fold} models of "
        f"`{model_run}`. Evidence runs: "
        + ", ".join(f"{k} `{v}`" for k, v in CFG.promotion.evidence.items())
        + ".",
        "",
        "Gates: Phase 1P mapped to spec §11 numbers (M17 Q1). NOT_EVALUABLE counts as not "
        "passed. Promotion is never automatic: an eligible candidate needs a separate human "
        "action (`uv run python -m qqq1dte.models.promotion --review-run <run> --target <t> "
        "--approved-by <name>`), and the database refuses PRODUCTION without a PROMOTED record "
        "(migration 0003).",
    ]
    for target, r in out["targets"].items():
        lines += [
            "",
            f"## {target}",
            "",
            f"Candidate `{r['candidate']}`; current production model: {r['current'] or 'none'}. "
            "Decision recorded: **"
            + (r["recorded"] or "none (eligible: awaiting a human decision)")
            + "**.",
            "",
            "| gate | status | detail |",
            "|---|---|---|",
            *[f"| {k} | {g['status']} | {g['detail']} |" for k, g in r["gates"].items()],
            "",
            "Evidence: " + ", ".join(f"{k} = {v}" for k, v in r["evidence"].items()) + ".",
        ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    engine.dispose()
    print(
        f"completed run {run_id}: "
        + ", ".join(f"{t} {r['recorded'] or 'ELIGIBLE'}" for t, r in out["targets"].items())
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
