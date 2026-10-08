"""Model promotion (spec Phase 1P; M17): gate evaluation on synthetic evidence, the promotion /
KEEP_CURRENT paths, and the guarantees that no automatic path exists (DB trigger, named
approver, single code path). DB tests skipped without TEST_DATABASE_URL (required in CI)."""

from __future__ import annotations

import dataclasses
import inspect
import re
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from qqq1dte.core.config import load_config
from qqq1dte.models import promotion
from qqq1dte.models.promotion import (
    Evidence,
    eligible,
    evaluate_gates,
    promote,
    record_keep_current,
)
from test_db_schema import _parents

CFG = load_config()
ROOT = Path(__file__).resolve().parents[1]

GOOD = Evidence(
    bss_vs_m0=0.02,
    bss_vs_m0_ci=(0.005, 0.035),
    folds_better_share=6 / 7,
    bss_vs_current_ci=None,
    gate12_pass=True,
    ece=0.02,
    gate13_pass=True,
    mean_net=8.0,
    mean_net_ci=(1.0, 15.0),
    folds_positive_share=5 / 7,
    conservative_mean_net=3.0,
    n_trades=450,
    n_sessions=210,
    canary_pass=True,
)


def test_all_good_evidence_passes_every_gate() -> None:
    g = evaluate_gates(GOOD, None, CFG)
    assert set(g) == set(promotion.GATES)
    assert all(v["status"] == "PASS" for v in g.values()), g
    assert eligible(g)


@pytest.mark.parametrize(
    ("change", "gate"),
    [
        ({"bss_vs_m0_ci": (-0.001, 0.03)}, "oos_performance"),
        ({"folds_better_share": 4 / 7}, "walk_forward_stability"),
        ({"gate12_pass": False}, "calibration"),
        ({"gate13_pass": False}, "regimes"),
        ({"mean_net_ci": (-2.0, 9.0)}, "after_costs"),
        ({"conservative_mean_net": -0.5}, "after_costs"),
        ({"folds_positive_share": 3 / 7}, "walk_forward_stability"),
        ({"n_trades": 299}, "sample_size"),
        ({"n_sessions": 149}, "sample_size"),
        ({"canary_pass": False}, "leakage"),
    ],
)
def test_each_threshold_fails_its_gate(change: dict, gate: str) -> None:  # type: ignore[type-arg]
    g = evaluate_gates(dataclasses.replace(GOOD, **change), None, CFG)
    assert g[gate]["status"] == "FAIL" and not eligible(g)


def test_missing_evidence_is_not_evaluable_and_not_eligible() -> None:
    ev = dataclasses.replace(
        GOOD,
        mean_net=None,
        mean_net_ci=None,
        folds_positive_share=None,
        conservative_mean_net=None,
        n_trades=0,
        n_sessions=0,
        gate13_pass=None,
    )
    g = evaluate_gates(ev, None, CFG)
    assert g["after_costs"]["status"] == "NOT_EVALUABLE"
    assert g["regimes"]["status"] == "NOT_EVALUABLE"
    assert g["sample_size"]["status"] == "FAIL" and not eligible(g)


def test_versus_a_current_model() -> None:
    cur = dataclasses.replace(GOOD, ece=0.015, mean_net=7.0)
    better = dataclasses.replace(GOOD, bss_vs_current_ci=(0.001, 0.01))
    assert eligible(evaluate_gates(better, cur, CFG))
    not_better = dataclasses.replace(GOOD, bss_vs_current_ci=(-0.002, 0.01))
    assert evaluate_gates(not_better, cur, CFG)["oos_performance"]["status"] == "FAIL"
    worse_cal = dataclasses.replace(better, ece=0.015 + CFG.promotion.max_ece_increase + 0.001)
    assert evaluate_gates(worse_cal, cur, CFG)["no_degradation"]["status"] == "FAIL"
    worse_net = dataclasses.replace(better, mean_net=6.9)
    assert evaluate_gates(worse_net, cur, CFG)["no_degradation"]["status"] == "FAIL"
    missing = dataclasses.replace(GOOD, bss_vs_current_ci=None)
    assert evaluate_gates(missing, cur, CFG)["oos_performance"]["status"] == "NOT_EVALUABLE"


# -- no automatic path ------------------------------------------------------------------------
def test_promote_requires_an_explicit_named_approver() -> None:
    sig = inspect.signature(promote)
    assert sig.parameters["approved_by"].default is inspect.Parameter.empty
    assert inspect.signature(record_keep_current).parameters["approved_by"].default is (
        inspect.Parameter.empty
    )


def test_only_the_promotion_module_can_set_production() -> None:
    """Static check: no other source or script writes PRODUCTION or calls promote()."""
    hits = []
    for path in [*(ROOT / "src").rglob("*.py"), *(ROOT / "scripts").glob("*.py")]:
        if path.name == "promotion.py":
            continue
        src = path.read_text(encoding="utf-8")
        # writes only: reads such as WHERE status = 'PRODUCTION' are fine
        if re.search(r"SET\s+status\s*=\s*'PRODUCTION'|\bpromote\(", src):
            hits.append(path.name)
    assert hits == []


def test_direct_status_change_to_production_is_refused(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as c:
        _parents(c)
    with pytest.raises(DBAPIError, match="promotion"), migrated_engine.begin() as c:
        c.execute(
            text("UPDATE model_versions SET status = 'PRODUCTION' WHERE model_version_id = 'm1'")
        )


def test_promote_records_and_switches_in_one_transaction(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as c:
        _parents(c)
    g = evaluate_gates(GOOD, None, CFG)
    promote(migrated_engine, "m1", None, g, approved_by="Ahmed")
    with migrated_engine.connect() as c:
        status = c.execute(
            text("SELECT status FROM model_versions WHERE model_version_id='m1'")
        ).scalar_one()
        rec = c.execute(
            text("SELECT decision, approved_by, from_model_id FROM model_promotions")
        ).one()
    assert status == "PRODUCTION" and tuple(rec) == ("PROMOTED", "Ahmed", None)


def test_promote_refuses_failing_gates_and_blank_approver(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as c:
        _parents(c)
    bad = evaluate_gates(dataclasses.replace(GOOD, n_trades=10), None, CFG)
    with pytest.raises(ValueError, match="gate"):
        promote(migrated_engine, "m1", None, bad, approved_by="Ahmed")
    with pytest.raises(ValueError, match="approver"):
        promote(migrated_engine, "m1", None, evaluate_gates(GOOD, None, CFG), approved_by="  ")
    with migrated_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM model_promotions")).scalar_one() == 0


def test_failing_candidate_records_keep_current(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as c:
        _parents(c)
    bad = evaluate_gates(dataclasses.replace(GOOD, canary_pass=False), None, CFG)
    record_keep_current(migrated_engine, "m1", None, bad, approved_by="Ahmed")
    with migrated_engine.connect() as c:
        rec = c.execute(
            text("SELECT decision, approved_by, gate_results FROM model_promotions")
        ).one()
        status = c.execute(
            text("SELECT status FROM model_versions WHERE model_version_id='m1'")
        ).scalar_one()
    assert rec[0] == "KEEP_CURRENT" and rec[1] == "Ahmed"
    assert rec[2]["leakage"]["status"] == "FAIL" and status == "CANDIDATE"


@pytest.mark.parametrize(
    "stmt",
    [
        "UPDATE model_promotions SET approved_by = 'x'",
        "DELETE FROM model_promotions",
        "TRUNCATE model_promotions",
    ],
)
def test_promotion_records_are_append_only(migrated_engine: Engine, stmt: str) -> None:
    with migrated_engine.begin() as c:
        _parents(c)
    record_keep_current(
        migrated_engine, "m1", None, evaluate_gates(GOOD, None, CFG), approved_by="Ahmed"
    )
    with pytest.raises(DBAPIError, match="append-only"), migrated_engine.begin() as c:
        c.execute(text(stmt))


def test_manual_promotion_command_uses_stored_gate_results(migrated_engine: Engine) -> None:
    """The human path: `python -m qqq1dte.models.promotion` promotes only from a stored review
    run whose gates all passed, with --approved-by required."""
    import json  # noqa: PLC0415

    from qqq1dte.backtesting.registry import complete_run, register_run  # noqa: PLC0415

    with migrated_engine.begin() as c:
        _parents(c)

    def review(gates: dict) -> str:  # type: ignore[type-arg]
        rid = register_run(
            migrated_engine,
            run_kind="promotion_review",
            config={"g": json.dumps(gates)},
            data_window=(__import__("datetime").date(2025, 1, 1),) * 2,
            dataset_id="ds1",
            code_commit="c",
            folds=[],
        )
        complete_run(
            migrated_engine,
            rid,
            {"targets": {"C_call": {"candidate": "m1", "current": None, "gates": gates}}},
        )
        return rid

    bad = review(evaluate_gates(dataclasses.replace(GOOD, n_trades=1), None, CFG))
    with pytest.raises(ValueError, match="gate"):
        promotion.main(
            ["--review-run", bad, "--target", "C_call", "--approved-by", "Ahmed"],
            engine=migrated_engine,
        )
    with pytest.raises(SystemExit):  # --approved-by is mandatory
        promotion.main(["--review-run", bad, "--target", "C_call"], engine=migrated_engine)
    good = review(evaluate_gates(GOOD, None, CFG))
    promotion.main(
        ["--review-run", good, "--target", "C_call", "--approved-by", "Ahmed"],
        engine=migrated_engine,
    )
    with migrated_engine.connect() as c:
        assert (
            c.execute(
                text("SELECT status FROM model_versions WHERE model_version_id='m1'")
            ).scalar_one()
            == "PRODUCTION"
        )
