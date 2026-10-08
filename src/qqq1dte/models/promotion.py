"""Model promotion (spec Phase 1P; M17). A new model never replaces the production model
automatically:

- `evaluate_gates` maps the Phase 1P gates to the spec §11 numbers (owner M17 Q1); a gate whose
  evidence is missing is NOT_EVALUABLE and counts as not passed;
- `promote` is the only code path that sets PRODUCTION: it needs every gate PASS and an explicit
  named approver, and writes the PROMOTED record, retires the current model and switches the
  candidate in one transaction. The database refuses PRODUCTION without that record in the same
  transaction (migration 0003);
- `record_keep_current` records a KEEP_CURRENT decision (failing or declined candidate).
Both records are append-only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, text

from qqq1dte.core.config import Phase1Config

PASS, FAIL, NOT_EVALUABLE = "PASS", "FAIL", "NOT_EVALUABLE"
GATES = (
    "oos_performance",
    "no_degradation",
    "calibration",
    "regimes",
    "after_costs",
    "sample_size",
    "leakage",
    "walk_forward_stability",
)
Gates = dict[str, dict[str, Any]]


@dataclass(frozen=True)
class Evidence:
    """Out-of-sample evidence for one model (pooled walk-forward test blocks)."""

    bss_vs_m0: float | None  # gate 6
    bss_vs_m0_ci: tuple[float, float] | None
    folds_better_share: float | None
    bss_vs_current_ci: tuple[float, float] | None  # candidate vs the current production model
    gate12_pass: bool | None
    ece: float | None
    gate13_pass: bool | None
    mean_net: float | None  # gate 10 (moderate fills, net of costs)
    mean_net_ci: tuple[float, float] | None
    folds_positive_share: float | None
    conservative_mean_net: float | None  # gate 11
    n_trades: int
    n_sessions: int
    canary_pass: bool | None  # gate 4


def _g(status: str, detail: str) -> dict[str, Any]:
    return {"status": status, "detail": detail}


def _flag(v: bool | None, what: str) -> dict[str, Any]:
    if v is None:
        return _g(NOT_EVALUABLE, f"{what}: no evidence")
    return _g(PASS if v else FAIL, f"{what}: {'pass' if v else 'fail'}")


def evaluate_gates(ev: Evidence, current: Evidence | None, cfg: Phase1Config) -> Gates:
    pc = cfg.promotion
    out: Gates = {}
    # better out-of-sample performance (gate 6; and vs the current model when one exists)
    if ev.bss_vs_m0_ci is None:
        out["oos_performance"] = _g(NOT_EVALUABLE, "no Brier skill vs Model 0")
    elif ev.bss_vs_m0_ci[0] <= 0:
        out["oos_performance"] = _g(FAIL, f"BSS vs Model 0 CI {ev.bss_vs_m0_ci} not above 0")
    elif current is not None and ev.bss_vs_current_ci is None:
        out["oos_performance"] = _g(NOT_EVALUABLE, "no Brier skill vs the current model")
    elif current is not None and ev.bss_vs_current_ci is not None and ev.bss_vs_current_ci[0] <= 0:
        out["oos_performance"] = _g(FAIL, f"BSS vs current CI {ev.bss_vs_current_ci} not above 0")
    else:
        out["oos_performance"] = _g(PASS, f"BSS vs Model 0 CI {ev.bss_vs_m0_ci}")
    # no unacceptable degradation vs the current model
    if current is None:
        out["no_degradation"] = _g(PASS, "no current production model")
    elif None in (ev.ece, current.ece, ev.mean_net, current.mean_net):
        out["no_degradation"] = _g(NOT_EVALUABLE, "ECE or expectancy missing")
    else:
        assert ev.ece is not None and current.ece is not None
        assert ev.mean_net is not None and current.mean_net is not None
        worse_cal = ev.ece > current.ece + pc.max_ece_increase
        worse_net = ev.mean_net < current.mean_net
        out["no_degradation"] = _g(
            FAIL if (worse_cal or worse_net) else PASS,
            f"ECE {ev.ece:.4f} vs {current.ece:.4f}; mean net {ev.mean_net:+.2f} vs "
            f"{current.mean_net:+.2f}",
        )
    out["calibration"] = _flag(ev.gate12_pass, "gate 12")
    out["regimes"] = _flag(ev.gate13_pass, "gate 13")
    # positive after costs (gates 10, 11)
    if ev.mean_net_ci is None or ev.conservative_mean_net is None:
        out["after_costs"] = _g(NOT_EVALUABLE, "no traded expectancy")
    else:
        ok = ev.mean_net_ci[0] > 0 and ev.conservative_mean_net > 0
        out["after_costs"] = _g(
            PASS if ok else FAIL,
            f"mean net CI {ev.mean_net_ci}; conservative {ev.conservative_mean_net:+.2f}",
        )
    ok_n = ev.n_trades >= pc.min_trades and ev.n_sessions >= pc.min_sessions
    out["sample_size"] = _g(
        PASS if ok_n else FAIL, f"{ev.n_trades} trades, {ev.n_sessions} sessions"
    )
    out["leakage"] = _flag(ev.canary_pass, "gate 4 canary")
    # stable across walk-forward periods (fold shares of gates 6 and 10)
    if ev.folds_better_share is None or ev.folds_positive_share is None:
        out["walk_forward_stability"] = _g(NOT_EVALUABLE, "fold shares missing")
    else:
        ok = (
            ev.folds_better_share >= pc.min_folds_better_share
            and ev.folds_positive_share >= pc.min_folds_positive_share
        )
        out["walk_forward_stability"] = _g(
            PASS if ok else FAIL,
            f"better than Model 0 in {ev.folds_better_share:.0%} of folds; positive in "
            f"{ev.folds_positive_share:.0%}",
        )
    return out


def eligible(gates: Gates) -> bool:
    return set(gates) == set(GATES) and all(g["status"] == PASS for g in gates.values())


def _approver(approved_by: str) -> str:
    if not approved_by or not approved_by.strip():
        raise ValueError("a named human approver is required")
    return approved_by.strip()


def _record(
    c: Any, decision: str, candidate: str, current: str | None, gates: Gates, approved_by: str
) -> None:
    c.execute(
        text("""
            INSERT INTO model_promotions (from_model_id, to_model_id, gate_results, decision,
              approved_by)
            VALUES (:f, :t, CAST(:g AS JSONB), :d, :a)"""),
        {"f": current, "t": candidate, "g": json.dumps(gates), "d": decision, "a": approved_by},
    )


def record_keep_current(
    engine: Engine, candidate: str, current: str | None, gates: Gates, *, approved_by: str
) -> None:
    """Record that the candidate is not promoted (the current model, if any, stays)."""
    who = _approver(approved_by)
    with engine.begin() as c:
        _record(c, "KEEP_CURRENT", candidate, current, gates, who)


def promote(
    engine: Engine, candidate: str, current: str | None, gates: Gates, *, approved_by: str
) -> None:
    """The only path to PRODUCTION: every gate PASS and a named approver, one transaction."""
    who = _approver(approved_by)
    if not eligible(gates):
        failed = [k for k, g in gates.items() if g["status"] != PASS]
        raise ValueError(f"promotion refused: gate(s) not passed: {failed}")
    with engine.begin() as c:
        _record(c, "PROMOTED", candidate, current, gates, who)
        if current is not None:
            c.execute(
                text("UPDATE model_versions SET status = 'RETIRED' WHERE model_version_id = :m"),
                {"m": current},
            )
        c.execute(
            text("UPDATE model_versions SET status = 'PRODUCTION' WHERE model_version_id = :m"),
            {"m": candidate},
        )


def main(argv: list[str] | None = None, engine: Engine | None = None) -> int:
    """Manual promotion by a named human, from the gate results stored by a promotion review run:

        uv run python -m qqq1dte.models.promotion --review-run <run_id> --target C_call \
            --approved-by "<name>"
    """
    import argparse  # noqa: PLC0415
    import os  # noqa: PLC0415

    from sqlalchemy import create_engine  # noqa: PLC0415

    ap = argparse.ArgumentParser(description="promote a reviewed candidate (human only)")
    ap.add_argument("--review-run", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--approved-by", required=True)
    args = ap.parse_args(argv)
    eng = engine or create_engine(os.environ["DATABASE_URL"])
    with eng.connect() as c:
        m = c.execute(
            text(
                "SELECT metrics FROM validation_runs WHERE run_id = :r "
                "AND run_kind = 'promotion_review' AND status = 'COMPLETED'"
            ),
            {"r": args.review_run},
        ).scalar_one()
    t = m["targets"][args.target]
    promote(eng, t["candidate"], t["current"], t["gates"], approved_by=args.approved_by)
    print(f"{t['candidate']} promoted to PRODUCTION for {args.target} by {args.approved_by}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
