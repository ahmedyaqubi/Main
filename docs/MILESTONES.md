# Milestones

Status: TODO | IN PROGRESS | DONE. Each milestone is DONE only when every criterion has evidence.
Global criteria for every milestone: `uv run pytest`, `uv run ruff check .`, `uv run mypy src` pass
in CI; tests for numerical code were written first; this file is updated with evidence.
Test IDs refer to `docs/TEST_PLAN.md`; gate numbers refer to `PHASE_1_SPEC.md` §11.

## M1 — Specification & architecture — IN PROGRESS (spec frozen; only the CI-on-GitHub criterion remains)
Depends on: none
Deliverables: docs/PHASE_1_SPEC.md, docs/ARCHITECTURE.md, docs/SCHEMA_DRAFT.md, docs/TEST_PLAN.md, docs/decisions/0001-*.md
Acceptance:
- [x] Every item in MASTER_PROMPT Phase 1A defined with a concrete value or a config key + default — PHASE_1_SPEC §1–§6, configs/phase1.yaml; T-CFG-01
- [x] "1DTE", holding period (intraday vs overnight), and option-selection rule frozen — spec §1.2, §2, §5; PHASE_1_SPEC v1.0 FROZEN, ADR-0001 ACCEPTED 2026-10-05
- [x] Every Phase 1V gate has a numeric threshold — §11 (accepted, OD-5)
- [x] Open decisions section lists anything still needing my input — §12 (OD-1…OD-12, all resolved in ADR-0001)
- [ ] Repo skeleton, pyproject.toml, CI (pytest/ruff/mypy) passing on empty package — skeleton incl. `core/` (OD-11) done; pytest (15), ruff check/format, mypy --strict pass locally; **GitHub Actions run pending: no remote yet**

## M2 — Data requirements & provider evaluation — TODO
Depends on: M1
Deliverables: docs/DATA_REQUIREMENTS.md (matrix), docs/decisions/000X-options-data-provider.md
Acceptance:
- [ ] Matrix: every instrument × field × granularity × source × history start × point-in-time notes
- [ ] QQQ expiration calendar history documented (when daily expirations began). M1 found Tue/Thu from 2022-11-14/16 and Mon/Wed from 2021-04-23/27; confirm against vendor chain data, including how far ahead short-term series are listed now
- [ ] IBKR vs historical-provider split documented; candidate providers compared on coverage, granularity (NBBO vs trades), cost, licensing
- [ ] Sample pull from the chosen provider validated end-to-end for one week
- [ ] Vendor bar timestamp convention (start/end), OI publication timing, and quote granularity documented (these feed `pit.*` and `fills.latency_s`)
- [ ] Intraday source for 2Y/10Y yields and DXY identified, or the feature is dropped with an ADR (daily FRED values are not available intraday)

## M3 — Ingestion & storage — TODO
Depends on: M2 (provider chosen), M1 (schema approved)
Acceptance:
- [ ] `core/` calendar, clock, config loader, `AsOfReader` implemented; T-TIME-01…08, T-LEAK-01/02, T-CFG-01/02 pass
- [ ] Alembic migrations create every Postgres table in SCHEMA_DRAFT (as approved); upgrade → downgrade → upgrade works on an empty DB in CI (service container)
- [ ] Raw Parquet writers store vendor data unchanged, with `source`, `raw_file_id`, `ingested_at`; re-ingesting the same file is idempotent (same `dataset_id`)
- [ ] `dataset_versions` row written for every dataset; content hash reproducible
- [ ] The one-week sample from M2 ingested end to end for QQQ underlying + QQQ options
- [ ] No vendor code path can place orders (T-SAFE-01)

## M4 — Data-quality validation — TODO
Depends on: M3
Acceptance:
- [ ] Every Phase 1D check implemented as a named check with severity; T-DQ-01…09 pass
- [ ] Conservation: raw = cleaned + rejected, for every dataset (T-DQ-08)
- [ ] DQ report (days, bars expected/received, missing %, duplicates, invalid quotes, timestamp errors, coverage by instrument/date, chain coverage) generated for the full ingested history and committed under `reports/dq/`
- [ ] Gates 1–2 evaluated on the full history with numbers; any failure is documented and blocks M5
- [ ] Liquidity gate defaults (§4.9) checked against the empirical spread distribution of ATM 1DTE contracts; changes go through an ADR

## M5 — Point-in-time feature engine — TODO
Depends on: M4
Acceptance:
- [ ] 20–30 features, each documented (definition, formula, source, availability, missing behaviour, rationale, leakage risk) in `docs/FEATURES.md`
- [ ] Features only consume `AsOfReader`; import-linter contract enforced in CI (T-LEAK-10)
- [ ] T-LEAK-03…09 pass, including the future-perturbation property test (T-LEAK-05) over ≥ 1,000 random T
- [ ] Unit test with exact expected value for every feature on a synthetic series
- [ ] Gate 3 check script: 100% of stored rows satisfy `available_at <= T`; 20-timestamp replay matches

## M6 — Label generation — TODO
Depends on: M4 (and the M1 freeze of label definitions)
Acceptance:
- [ ] Labels A/B/C/D (both sides, all configured variants) per spec §3; T-LBL-01…07 pass
- [ ] C labels use the frozen selection rule (§5); its pure function is implemented here and reused by M11
- [ ] Class balance, ambiguous-bar rate, INVALID rate, and UNRESOLVED rate reported per label and per year
- [ ] D-label stop default (0.15%) checked against the empirical option bracket; any change needs an ADR

## M7 — Baseline model (Model 0) — TODO
Depends on: M5, M6, M10 splitter (T-WF-01/02 can be built first within M7 if M10 is not yet done)
Acceptance:
- [ ] Unconditional rate and conditional rate (by time-of-day bucket and vol regime, fit on train only) per target
- [ ] OOS Brier, log loss, ECE per fold, with session-bootstrap CIs (gate 5)
- [ ] Results logged in `validation_runs` with config hash

## M8 — Logistic regression (Model 1) — TODO
Depends on: M7
Acceptance:
- [ ] Standardisation fit on train only (T-LEAK-11); regularisation chosen on the validation/calibration block, never on test
- [ ] Brier skill vs Model 0 per fold with CI; coefficients reported per fold (stability)
- [ ] Serialization round-trip (T-REP-01)

## M9 — Gradient-boosted model (Model 2) — TODO
Depends on: M8
Acceptance:
- [ ] LightGBM with a small, pre-declared hyperparameter grid; every grid point logged as a trial
- [ ] Brier skill vs Model 0 and Model 1 per fold with CI; feature-importance stability across folds
- [ ] Shuffled-label canary gives AUC ≈ 0.5 (T-LEAK-13)

## M10 — Chronological walk-forward — TODO
Depends on: M5, M6
Acceptance:
- [ ] Expanding-window splitter with calibration block, test block, 1-session embargo (§8); T-WF-01…04 pass
- [ ] Final holdout locked and access-logged (T-WF-03)
- [ ] Run registry: every run creates a `validation_runs` row before evaluation; `n_trials` computable per data window
- [ ] Session-block bootstrap utility with a test on a known-variance synthetic series

## M11 — Realistic options backtester — TODO
Depends on: M6, M10
Acceptance:
- [ ] Event-driven loop with monotonic clock and quote cursor (T-BT-05)
- [ ] Frozen selection rule at `T_e` (T-SEL-01…05); candidates written to `trade_candidates`
- [ ] Target/stop on the bid, forced flat, one position, max entries/day (T-BT-02…04)
- [ ] Per-trade MFE, MAE, P&L, R, holding time, exit reason, unfilled count recorded
- [ ] Accounting test with hand-computed trades (T-BT-01)

## M12 — Costs, slippage, latency — TODO
Depends on: M11
Acceptance:
- [ ] Three fill models (T-FILL-01…03); commissions + fees per §4.8
- [ ] Sensitivity report: expectancy vs α ∈ {0, 0.25, 0.5, 0.75, 1}, latency ∈ {0, 5, 60} s, costs ×{1, 1.5}
- [ ] Every P&L figure in reports is net of costs (enforced by type) — gate 9

## M13 — Probability calibration — TODO
Depends on: M8/M9 OOS scores, M10
Acceptance:
- [ ] Platt, isotonic, temperature fitted on calibration blocks only (T-CAL-03); chosen method selected without test data
- [ ] Reliability curves, Brier, log loss, ECE, slope, per-bin n and Wilson CI (T-CAL-01/02)
- [ ] The decision engine refuses CALL/PUT without a calibration version (T-CAL-04)
- [ ] Gate 12 evaluated with numbers

## M14 — Regime analysis — TODO
Depends on: M13
Acceptance:
- [ ] Regime labels per §9 with fold-fit thresholds (T-LEAK-12); stored in `regime_labels`
- [ ] Per-regime calibration and expectancy with n, sessions, CI; LOW_SUPPORT flags applied
- [ ] Decision on collapsing the trend axis (OD-9) documented via ADR if changed

## M15 — NO_TRADE logic — TODO
Depends on: M12, M13, M14
Acceptance:
- [ ] Decision engine per spec §4.1 with reason codes; BLOCKED_POSITION_OPEN distinct from NO_TRADE
- [ ] Counterfactual analysis of NO_TRADE timestamps (gate 14) with session-bootstrap CI
- [ ] NO_TRADE rate reported overall, by regime, and by reason

## M16 — Prediction/trade journal — TODO
Depends on: M15
Acceptance:
- [ ] Every Phase 1O field persisted; journal tables append-only (DB role test: UPDATE/DELETE fail)
- [ ] `journal.replay(prediction_id)` reproduces stored scores and decision (T-REP-02)

## M17 — Model versioning & promotion — TODO
Depends on: M16
Acceptance:
- [ ] `model_versions` + `model_promotions`; at most one PRODUCTION per target (DB constraint test)
- [ ] Promotion requires all Phase 1P gates and a named human approver; there is no automatic path (test)
- [ ] Failing candidate → KEEP_CURRENT recorded

## M18 — Drift monitoring — TODO
Depends on: M16
Acceptance:
- [ ] PSI on features and predictions, rolling calibration/ECE, rolling expectancy, regime frequency
- [ ] Synthetic drift injection detected within 10 sessions (gate 18); alert states: OK / WARN / PAPER_ONLY / DISABLED
- [ ] A degraded model cannot keep emitting CALL/PUT (test)

## M19 — Full historical validation — TODO
Depends on: M7–M18
Acceptance:
- [ ] Single registered run over the full walk-forward; final holdout opened exactly once (logged)
- [ ] Gates 1–18 evaluated with numbers, CIs, sample sizes, `n_trials`, DSR, PBO in `reports/validation/`
- [ ] Explicit PASS/FAIL per gate; FAIL on any gate stops progression to M20 unless the owner records an ADR accepting the limitation
- [ ] No claim of profitability; report states evidence and uncertainty only

## M20 — Live market data in PAPER mode — TODO
Depends on: M19 PASS (or owner ADR)
Acceptance:
- [ ] Live feed adapter implements the `AsOfReader` interface; market-data permissions only. **No order API anywhere** (T-SAFE-01)
- [ ] The full 12-step loop (Phase 1T) runs at every scheduled timestamp; DQ failures produce NO_TRADE with a reason
- [ ] Live-vs-replay check: one recorded live day replayed offline reproduces the decisions

## M21 — Live paper validation — TODO
Depends on: M20
Acceptance:
- [ ] Gates 19–20: ≥ 60 sessions and ≥ 100 paper trades; ECE ≤ 0.05; slippage vs model; PSI ≤ 0.2
- [ ] Weekly paper report with sample sizes and CIs; drift status
- [ ] Moderate-fill α re-estimated from paper quotes; any change via ADR (does not retroactively alter M19 results)

## M22 — Dashboard — TODO
Depends on: M21 (engine stable)
Acceptance:
- [ ] Read-only view over the journal/monitoring; shows every Phase 1U field, including sample size, CI, and NO_TRADE reason
- [ ] Never displays a raw score labelled as probability (test on rendering layer)
- [ ] No controls that place or route orders

## Later (out-of-scope ideas parked here)
- Overnight-hold variant of 1DTE (if OD-2 = intraday-only), with gap/theta/assignment labels
- Extending Stage 1 history before 2022-11 (OD-1 option b)
- Size/spread-dependent fill-probability model fit on paper data
- Delta-targeted selection rule as a pre-registered alternative experiment (OD-3)
- Breadth features if a reliable point-in-time intraday source exists
