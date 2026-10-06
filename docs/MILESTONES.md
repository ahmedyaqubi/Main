# Milestones

Status: TODO | IN PROGRESS | DONE. Each milestone is DONE only when every criterion has evidence.
Global criteria for every milestone: `uv run pytest`, `uv run ruff check .`, `uv run mypy src` pass
in CI; tests for numerical code were written first; this file is updated with evidence.
Test IDs refer to `docs/TEST_PLAN.md`; gate numbers refer to `PHASE_1_SPEC.md` §11.

## M1 — Specification & architecture — DONE (2026-10-05)
Depends on: none
Deliverables: docs/PHASE_1_SPEC.md, docs/ARCHITECTURE.md, docs/SCHEMA.md, docs/TEST_PLAN.md, docs/decisions/0001-*.md
Acceptance:
- [x] Every item in MASTER_PROMPT Phase 1A defined with a concrete value or a config key + default — PHASE_1_SPEC §1–§6, configs/phase1.yaml; T-CFG-01
- [x] "1DTE", holding period (intraday vs overnight), and option-selection rule frozen — spec §1.2, §2, §5; PHASE_1_SPEC v1.0 FROZEN, ADR-0001 ACCEPTED 2026-10-05
- [x] Every Phase 1V gate has a numeric threshold — §11 (accepted, OD-5)
- [x] Open decisions section lists anything still needing my input — §12 (OD-1…OD-12, all resolved in ADR-0001)
- [x] Repo skeleton, pyproject.toml, CI (pytest/ruff/mypy) passing on empty package — GitHub Actions CI green on e53cfa1: https://github.com/ahmedyaqubi/Main/actions/runs/37287440694

## M2 — Data requirements & provider evaluation — DONE (2026-10-05; see open issue 1)
Depends on: M1 (DONE)
Deliverables: docs/DATA_REQUIREMENTS.md (matrix), docs/decisions/0002-options-data-provider.md (ACCEPTED: Databento), docs/decisions/0003-history-start-2023-03-28.md (ACCEPTED)
Acceptance:
- [x] Matrix: every instrument × field × granularity × source × history start × point-in-time notes — DATA_REQUIREMENTS §1 (substitutions DXY→DX futures, 2Y/10Y→ZT/ZN futures, intraday VIX→VX futures, breadth dropped; feature ADR-0004 needed before M5)
- [x] QQQ expiration calendar history documented — DATA_REQUIREMENTS §2 (exchange notices) + listing lead time from data: Mon–Thu expirations first listed 10 sessions ahead in Mar 2025 (`reports/m2/sample_week.md` C5)
- [x] IBKR vs historical-provider split documented; candidate providers compared on coverage, granularity (NBBO vs trades), cost, licensing — DATA_REQUIREMENTS §3, ADR-0002 (free `metadata.get_cost` estimate: ≈ $34 Databento vs ≈ $280 ThetaData sprint)
- [x] Sample pull from the chosen provider validated end-to-end for one week — `scripts/m2_fetch_sample.py` (cost-capped), `scripts/m2_sample_check.py`, report `reports/m2/sample_week.md`; check logic tested in `tests/test_m2_checks.py` (17 tests incl. hypothesis equivalence test). Week 2025-03-10→14 for 1-min options NBBO, definitions, OI, QQQ bars/BBO; tick-level (`cmbp-1`) all 5 days: full strike band on 03-10, D+1 ATM ± 5 on 03-11→14 (see open issue 1)
- [x] Vendor bar timestamp convention, OI publication timing, and quote granularity documented — bars labelled at **start** (C2); `cbbo-1m` stamped at interval **end**, 0/42,900 contract-minutes over 5 sessions leak the next minute (C3); OI arrives 06:30:00–06:30:02 ET, none after the open (C7); 1-min NBBO for every contract-minute in RTH
- [x] Intraday source for 2Y/10Y yields and DXY identified — ZT/ZN (`GLBX.MDP3`) and DX (`IFUS.IMPACT`) futures via Databento
Sample results (all in `reports/m2/sample_week.md`): C1 UTC timestamps, DST correct (13:30 UTC open); C2 390/390 RTH bars every session; C4 1DTE expiry present every session; C6 0 crossed/zero/missing quotes in ATM ± 5, median spread $0.02–0.03, 98.4–99.8% pass §4.9 gates; C8 100% identical (42,900 contract-minutes).
Open issues:
1. **Tick sample scope (owner decision, option A).** `cmbp-1` for 2025-03-10 covers the full strike band (424 contracts, 6.45 GB compressed). For 2025-03-11→14 it covers only the 22 D+1 ATM ± 5 contracts that C3/C8 compare (`--tick-atm-only`, $2.12), because a full-band pull ran at ~0.5 MB/s and was stopped twice. Two interrupted full-band 03-11 requests may have been billed: check usage in the Databento portal. See "Later" for the full pull.
2. **Storage planning for M3:** full-history tick NBBO is infeasible locally (~6.5 GB/day); the research store uses `cbbo-1m` (~4 MB/day compressed).
3. Symbol resolution returned nothing for 2023-12-28 during cost estimation, while the full chain is available that day. Investigate in M4 DQ.
4. NQ/ES roll rule (Databento `c.0` semantics) still to verify before using futures features.
5. Databento licence terms for stored historical data not yet reviewed (before M3).
6. Python on this machine needs certifi's CA bundle (Windows store has an expired chain certificate); scripts set `SSL_CERT_FILE`.
7. Runtime deps added in M2: tzdata, python-dotenv, certifi, databento, exchange-calendars, numpy; dev: pandas-stubs.

## M3 — Ingestion & storage — DONE (2026-10-06)
Depends on: M2 (DONE, provider chosen), M1 (DONE); schema v1.0 approved 2026-10-05 (`docs/SCHEMA.md`)
Acceptance:
- [x] `core/` calendar, clock, config loader, `AsOfReader` implemented; T-TIME-01…08, T-LEAK-01/02, T-CFG-01/02 pass — `src/qqq1dte/core/`, `tests/test_core_time.py`, `tests/test_core_pit.py`, `tests/test_skeleton.py`
- [x] Alembic migrations create every Postgres table in SCHEMA (as approved); upgrade → downgrade → upgrade works on an empty DB in CI (service container) — `migrations/versions/0001_initial_schema.py`; `tests/test_db_schema.py` 13/13 pass on local PostgreSQL 16.15 with `REQUIRE_DB=1` (2026-10-06), including `test_upgrade_downgrade_upgrade` and every constraint/trigger test; main `qqq1dte` DB at revision `0001`. CI green with Postgres service container and `REQUIRE_DB=1` on df84181: https://github.com/ahmedyaqubi/Main/actions/runs/37437683279
- [x] Raw Parquet writers store vendor data unchanged, with `source`, `raw_file_id`, `ingested_at`; re-ingesting the same file is idempotent (same `dataset_id`) — `src/qqq1dte/ingestion/databento_raw.py`, `tests/test_ingestion_raw.py` (7 tests on synthetic DBN files)
- [x] `dataset_versions` row written for every dataset; content hash reproducible — `src/qqq1dte/ingestion/catalog.py`; `test_record_dataset_is_idempotent`, `test_record_dataset_same_id_different_content_raises`; 5 sample datasets registered in local `qqq1dte`, a second registration wrote 0 rows, and the dataset_ids equal those computed in the earlier no-DB run (`reports/m3/ingest_sample.md`)
- [x] The one-week sample from M2 ingested end to end for QQQ underlying + QQQ options — `scripts/m3_ingest_sample.py`, `reports/m3/ingest_sample.md` (40 files → 40 Parquet files, 5 datasets; second pass changed nothing)
- [x] No vendor code path can place orders (T-SAFE-01); market data never tracked in git (T-SAFE-02, new)
Notes:
- Schema implementation choices (trigger-based append-only journal, `trade_candidates.latency_s`) documented in `docs/SCHEMA.md` §B notes.
- New deps: polars, pyarrow, sqlalchemy, alembic, psycopg[binary], pydantic.
- Local setup: PostgreSQL 16 service, role `qqq1dte` (no superuser, no CREATEDB), databases `qqq1dte` and `qqq1dte_test`; URLs in `.env` only.
- `alembic.ini` sets `path_separator = os` (the repo path contains a space).
- Incident: the first M3 push (e8c2000) failed before any job ran because `ci.yml` had an unquoted `: ` in a step name (invalid YAML). Fixed in df84181; T-CI-01 now parses every workflow file in the local test suite.

## M4 — Data-quality validation — DONE (2026-10-06; CI green on fec9bd4: https://github.com/ahmedyaqubi/Main/actions/runs/37523570060)
Depends on: M3 (DONE)
Deliverables: docs/DATA_QUALITY.md (check catalogue), src/qqq1dte/validation/, scripts/m4_fetch_history.py, scripts/m4_run_dq.py, reports/dq/, ADR-0005, ADR-0006
Acceptance:
- [x] Every Phase 1D check implemented as a named check with severity; T-DQ-01…09 pass — `validation/rules.py` (catalogue, `DQ_RULES_VERSION` 2), `validation/records.py`, `validation/sessions.py`; `tests/test_dq_records.py`, `tests/test_dq_sessions.py` (T-DQ-02 revised per owner decision 2). Not in M4 scope, documented in DATA_QUALITY.md: OI-change checks (OI deferred to M5), "required features available" (M5)
- [x] Conservation: raw = cleaned + rejected, for every dataset (T-DQ-08) — held for all three datasets on the full history (`reports/dq/full_history.md`: 460,268 bars, 621,899 QQQ quotes, 83,470,947 option quotes)
- [x] DQ report generated for the full ingested history — `reports/dq/full_history.md` (datasets, rejections/flags by check, bars expected/received/missing, chain coverage, coverage by month, CRITICAL events, exclusions, catalogue)
- [x] Gates 1–2 evaluated on the full history with numbers — `reports/dq/gates.md`: **gate 1 PASS** (882 research sessions, 0 below 98% bar coverage, worst 99.23%; 879/882 = 99.66% sessions with a valid frozen-rule chain at ≥ 95% of timestamps); **gate 2 PASS** (0 open CRITICAL after ADR-0006; ATM invalid-quote rate 1,919/7,543,994 = 0.025%)
- [x] Liquidity gate defaults (§4.9) checked against the empirical spread distribution — `reports/dq/liquidity_spreads.md`: frozen-rule quotes 112,336; spread median $0.02, p99 $0.04–0.11 by year; 99.58% pass all gates; min-bid and size gates never bind. **No change, so no ADR.**
Findings / decisions (all with tests written first):
- Vendor leaves the OPRA multiplier undefined → ADR-0005 standard-contract evidence (root, strike grid or documented OCC adjustment, symbol/expiry consistency).
- OCC #53847: QQQ strikes reduced by $0.21584 on 2023-12-27 (M2 had wrongly called 2023-12-28 an anomaly). Adjusted strikes are accepted via `dq.strike_adjustments`; 88 supplemental files ($0.16) completed the chain for 46 affected sessions.
- `NO_EVENT_TS` (undefined ts_event on carried-forward interval records) and `ZERO_QUOTE` (0/0 = no market) are flagged, not rejected.
- ADR-0006: 2023-12-27 excluded (`history.excluded_sessions`); 3 sessions with intraday crossed-quote windows kept, CRITICAL closed (`dq.resolved_critical`).
- Catalogue: `config_hash` is provenance, not content, for registered datasets (test added).
Spend: underlying $0.47, options history $12.63, adjusted supplement $0.16, 2023-12-28 diagnostic $0.01 → **$13.27**.
Open issues (carried forward):
1. **M11:** the selection rule must treat a rejected latest record as "no valid quote" (never fall back to an older quote), as chain coverage does (`sessions._latest_records`).
2. **M11 / spec:** when adjusted and standard strikes are both listed for an expiry, spec §5 treats them equally. Whether to prefer standard-grid strikes is an open spec question (ADR-0005 notes).
3. The `MULTIPLIER_UNKNOWN` flag is on every option row, so the report's "flagged" count for options equals all rows. Cosmetic; can be excluded from that count.
4. NQ/ES roll rule and OI (`statistics`) download: before M5 features.

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
- **Full strike-band tick NBBO for the M2 sample week (owner note, 2026-10-05).** Re-pull `cmbp-1` for 2025-03-11→14 over the full band (D+1/D+2 expiries, 424 contracts/day): priced at $11.20, ~75 GB uncompressed / ~25 GB on disk. Run `uv run python scripts/m2_fetch_sample.py --days <day> --download` one day per run (each day can exceed 1 h at slow transfer rates), or use Databento's batch API. Useful if later work (fill modelling in M12, quote-age/latency studies) needs tick data beyond ATM ± 5.
- Overnight-hold variant of 1DTE (if OD-2 = intraday-only), with gap/theta/assignment labels
- Extending Stage 1 history before 2022-11 (OD-1 option b)
- Size/spread-dependent fill-probability model fit on paper data
- Delta-targeted selection rule as a pre-registered alternative experiment (OD-3)
- Breadth features if a reliable point-in-time intraday source exists
