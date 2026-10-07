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

## M5 — Point-in-time feature engine — DONE (2026-10-07; CI green on 4cbc36b: https://github.com/ahmedyaqubi/Main/actions/runs/37564128242)
Depends on: M4 (DONE)
Deliverables: docs/FEATURES.md, ADR-0004 (+ amendment 1), src/qqq1dte/features/, configs/reference/macro_calendar.csv, scripts/m5_*.py, reports/features/
Acceptance:
- [x] 20–30 features, each documented (definition, formula, source, availability, missing behaviour, rationale, leakage risk) — `docs/FEATURES.md`: 28 features, feature_version **f2**
- [x] Features only consume `AsOfReader`; import-linter contract enforced in CI (T-LEAK-10) — feature functions (`features/defs.py`) take an `AsOfReader` + `Ctx` only; contract "Point-in-time code never imports labels" (features, regimes, execution_sim, core) in `pyproject.toml`, CI step `lint-imports`, `test_leak_10_import_contract_kept`. Mutation check: a planted features→labels import breaks the contract
- [x] T-LEAK-03…09 pass, including the future-perturbation property test over ≥ 1,000 random T — `tests/test_features_pit.py`: T-LEAK-05 runs 1,000 hypothesis examples (random T, every row with available_at > T scaled by one of {−3, 0, 0.5, 7}), plus T-LEAK-03/04/06/07/08/09 and the macro calendar checks
- [x] Unit test with exact expected value for every feature on a synthetic series — `tests/test_features_values.py` (all 28, hand-computed; missing-reason test; quote-based cross-market tests)
- [x] Gate 3 check script: 100% of stored rows satisfy `available_at <= T`; 20-timestamp replay matches — `scripts/m5_gate3.py` → `reports/features/gate3.md`: **PASS**, 0 violations in 1,572,480 rows; 20 random timestamps recomputed from inputs holding the *full* history (data after T included) are identical
Evidence / results:
- Snapshots: 882 sessions × 64 timestamps × 28 features = 1,572,480 rows (`data/features/f2/`, catalogued as dataset `71259fcf…`; f1 `cf00f91b…` superseded). Summary and missing-value reasons: `reports/features/summary.md`.
- Data added (ADR-0004): 9 cross-market symbols (bars $1.84, unused after amendment 1; NBBO $1.33), Cboe VIX daily history (free), macro calendar (119 events, BLS/Fed sources). M5 spend: **$3.17**.
- Cross-market NBBO quality (`reports/features/summary.md`): SPY, AMD, AVGO, TSM, IEF, SOXX ≥ 98% valid RTH quotes in all but 0–2 sessions; UUP below 98% in 360 sessions and SHY in 273 (worst 83% / 78%), because Databento omits some quiet minutes for them (median 385–388 records/day). Affected timestamps are missing (~0.9%). NVDA 2024-05-28: vendor gap (2 records), NVDA features missing that day.
Open issues:
1. **Resolved (owner, 2026-10-07):** cross-market instruments are *optional feature inputs*: their gaps become nulls, and they are not gate-1 "required instruments". Gate 1 is scored on QQQ + QQQ options (M4).
2. UUP/SHY mids are unchanged in 84% / 93% of minutes (one-tick spreads on slow ETFs): many exact-zero returns. Real microstructure, not staleness. Their information value is for M8/M9 to judge.
3. Early-window nulls: ATR needs 15 prior sessions and relative volume 10. The data starts 2023-03-28, so the first sessions have nulls. M8 needs train-only imputation or row exclusion (no silent fill).
4. Holiday macro releases (Good Friday NFP 2023-04-07, 2026-04-03) never fire `macro_event_today`. Documented in FEATURES.md.
5. T-LEAK-05 takes ~100 s (1,000 examples) and is part of every CI run.

## M6 — Label generation — DONE (2026-10-07; CI green on a4ce025: https://github.com/ahmedyaqubi/Main/actions/runs/37578959788)
Depends on: M4 (DONE)
Owner decisions (2026-10-07): Q1 adjusted and standard strikes treated alike in §5; Q2 no contract or a failed §4.9 gate → C = INVALID (excluded from training); Q3 path gaps: missing bid = 0, rejected records skipped and flagged, > 5 min without a usable quote or no fresh exit quote → UNRESOLVED_DATA; Q4 1-minute path resolution accepted (intra-minute touches unseen).
Acceptance:
- [x] Labels A/B/C/D (both sides, all configured variants) per spec §3; T-LBL-01…07 pass — `src/qqq1dte/labels/` (underlying.py, option.py, common.py); `tests/test_labels_underlying.py` (T-LBL-01/02/04/05/06/07 + risk-label and window-boundary tests), `tests/test_labels_option.py` (T-LBL-03 target/stop on the bid, time-exit classes, breakeven, no-bid-as-zero, path gaps, unresolved, illiquid → INVALID, entry at T_e only, invariance to data after T_end, schema regression)
- [x] C labels use the frozen selection rule (§5); its pure function is implemented here and reused by M11 — `src/qqq1dte/execution_sim/selection.py` (`select_contract`, `choose_contract`, `liquidity_failures`); `tests/test_selection.py` (T-SEL-01…05 incl. a 300-example property test, every §4.9 gate)
- [x] Class balance, ambiguous-bar rate, INVALID rate, and UNRESOLVED rate reported per label and per year — `reports/labels/summary.md` (**final holdout excluded**; 80,640 rows after 2026-04-02 locked)
- [x] D-label stop default (0.15%) checked against the empirical option bracket; any change needs an ADR — `reports/labels/d_stop_check.md` (pre-holdout only): the option −20% stop ↔ median QQQ move −0.20% / +0.18%; +30% target ↔ +0.31% / −0.30%. **ADR-0007 (owner, 2026-10-07):** D stop 0.19%, D target 0.30% (own `labels.risk.target` key), labels → **L2**. Tests `test_risk_defaults_are_adr_0007`, `test_risk_target_is_independent_of_magnitude_threshold`
Evidence / results:
- **L2** (current): 882 sessions × 64 timestamps × 10 label ids/variants = 561,600 rows (`data/labels/L2/`, catalogue `0aeb046d…`); C trade details (entry/exit/MFE/MAE/net P&L) in `data/labels/L2_option/`. L1 (`9b35b8aa…`) superseded by ADR-0007.
- Pre-holdout: C_call WIN 25.3% / C_put WIN 27.9% of resolved (LOSS ≈ 47–51%); INVALID ≈ 0.5% (mostly SPREAD_TOO_WIDE); UNRESOLVED_DATA 0.05%. A/B/D INVALID 1.27%, all from the 52 missing QQQ bars (one missing bar invalidates every window containing it). D (L2) UNRESOLVED 26–28% (17% under L1's tighter bracket); stop-first share of resolved 65.6% calls / 62.7% puts.
- New shared helper `TradingCalendar.final_holdout_start` (tested). M10 must use it.
Notes / open issues:
1. Transparency: before the holdout filter was added, full-history label stats (incl. the holdout) were printed once during development. No definition was chosen from them; the pre-holdout figures are essentially identical.
2. Selection tests (T-SEL) were written together with `selection.py` rather than strictly red-first. They all pass and cover every rule; labels and the holdout helper were done red-first.
3. Path resolution is 1 minute (Q4). The M2 tick week could quantify missed intra-minute touches later ("Later").

## M7 — Baseline model (Model 0) — DONE (2026-10-07; CI green on 763497a: https://github.com/ahmedyaqubi/Main/actions/runs/37584917299)
Depends on: M5, M6 (DONE); M10 splitter built within M7 (see M10)
Owner decisions (2026-10-07): Q1 only whole 3-month test blocks (7 folds, tests 2024-05-28 → 2026-02-27); Q2 vol regime = VIX terciles of `vix_prev_close`, cut points from training sessions only; Q3 time-of-day buckets 09:45 / 11:00 / 13:00 ET; Q4 conditional rates shrunk towards the base rate, (k + n0·p0)/(n + n0), n0 = 50; Q5 D evaluated on resolved predictions only; Q6 splitter, holdout lock, registry and bootstrap built here and M10 marked from them. Parameters in `configs/phase1.yaml` → `models`.
Acceptance:
- [x] Unconditional rate and conditional rate (by time-of-day bucket and vol regime, fit on train only) per target — `src/qqq1dte/models/baseline.py` (`fit_baseline`, `BaselineModel`, `tod_bucket`); `tests/test_baseline.py` (exact rates and VIX cuts on synthetic data, New York wall-clock buckets across DST, null VIX → base rate, unresolved targets excluded, cut points use one value per training session and ignore test data)
- [x] OOS Brier, log loss, ECE per fold, with session-bootstrap CIs (gate 5) — `src/qqq1dte/models/metrics.py` (`tests/test_metrics_bootstrap.py`: hand-computed Brier / log loss / ECE, weights = repeated rows), `scripts/m7_baseline.py` → `reports/models/baseline_m0.md` (7 folds × 10 targets × {unconditional, conditional}, plus pooled OOS, each with 2,000-rep session-bootstrap 95% CIs, n_predictions, n_sessions, n_effective)
- [x] Results logged in `validation_runs` with config hash — run `walk_forward-843056faa13a` (code 763497a; supersedes `walk_forward-c6c69dae663a`, same config, uncommitted code, identical numbers), COMPLETED, config hash `b8439c2a…`, dataset = features f2 (`71259fcf…`), labels L2 (`0aeb046d…`) in `config_json`, window 2023-03-28 → 2026-02-27, `touches_final_holdout` = false, 70 fold×target metric blocks; `n_trials` on this window = 1. `final_test_access_log` empty
Evidence / results (pooled OOS, 440 test sessions, n_effective ≈ 1,320; these are base rates, not a model):
- Magnitude targets carry regime information: Brier skill of conditional over unconditional is B_up 0.25% +4.1% [+2.7, +5.5], B_dn 0.25% +3.1% [+2.0, +4.1], B_up 0.50% +5.3% [+3.6, +6.8], B_dn 0.50% +3.7% [+2.5, +4.7].
- Direction targets do not: A_up +0.1% [−0.4, +0.6], A_dn −0.2% [−0.5, +0.2], C_call +0.4% [−0.1, +0.9], C_put +0.3% [−0.1, +0.7], D_call −0.2% [−0.8, +0.4], D_put −0.2% [−0.5, +0.2] (all CIs include 0).
- Test-block base rates drift from training (e.g. B_up 0.25%: fold-1 training rate 0.41, pooled test rate 0.37; pooled unconditional ECE 0.09), so later models must be compared to Model 0 fold by fold, not to a fixed rate.
- D: unresolved predictions excluded (Q5) range from 9% (fold 4) to 45% (fold 5) per fold, 32% / 30% pooled for D_call / D_put; resolved hit rates 0.67 / 0.62. D results are conditional on resolution, which itself depends on volatility.
Notes / open issues:
1. A first run (`walk_forward-c6c69dae663a`) used the uncommitted M7 code on ba2ae24; it was rerun from 763497a (`walk_forward-843056faa13a`) with identical numbers (seeded bootstrap). Both rows stay in `validation_runs`; same config hash, so n_trials = 1.
2. ECE is a biased, non-negative statistic; its percentile bootstrap CI can sit above the point estimate (e.g. C_put pooled 0.0149 [0.0133, 0.0390]). Treat ECE CIs as indicative; gate 5 decisions should lean on Brier / log loss CIs.
3. Test-first: metrics, bootstrap, splitter and registry/holdout tests were run red before implementation; `tests/test_baseline.py` was written before `baseline.py` but not run red separately.
4. The calibration block is unused by Model 0 (no calibration step); M8+ uses it.

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

## M10 — Chronological walk-forward — DONE (built within M7, 2026-10-07; CI green on 763497a)
Depends on: M5, M6 (DONE)
Acceptance:
- [x] Expanding-window splitter with calibration block, test block, 1-session embargo (§8); T-WF-01…04 pass — `src/qqq1dte/backtesting/splits.py` (`walk_forward_folds`; only whole 3-month test blocks, M7 Q1; refuses any session past the holdout boundary); `tests/test_splits.py` (fold layout: 7 folds, fold 1 train 2023-03-28→2024-03-27 (251 sessions), embargo 2024-03-28, calib 2024-04-01→05-24, test 2024-05-28→08-27 (64); T-WF-01 chronological/disjoint/expanding; T-WF-02 embargo = next session; holdout rejected; T-WF-04 no shuffle/seed parameter and no "random"/"shuffle" in the source). Month arithmetic `core.calendar.add_months` (tested in `test_core_time.py`)
- [x] Final holdout locked and access-logged (T-WF-03) — `src/qqq1dte/backtesting/holdout.py` (`HoldoutGuard`): holdout sessions need a run registered with `touches_final_holdout`, a justification and a database; each access is written to `final_test_access_log`; any access after the first needs an ADR reference. `tests/test_registry_holdout.py::test_wf_03_*`, `test_guard_without_database_refuses_any_holdout_access`. Holdout = sessions after `TradingCalendar.final_holdout_start(2026-10-02)` = 2026-04-02
- [x] Run registry: every run creates a `validation_runs` row before evaluation; `n_trials` computable per data window — `src/qqq1dte/backtesting/registry.py` (`register_run` → REGISTERED, `complete_run`, `fail_run`, `n_trials` = distinct config hashes overlapping a window, any status); `tests/test_registry_holdout.py::test_run_is_registered_before_evaluation_then_completed`, `test_failed_run_still_counts_as_a_trial`
- [x] Session-block bootstrap utility with a test on a known-variance synthetic series — `src/qqq1dte/backtesting/bootstrap.py` (`session_bootstrap_ci`, multinomial session weights); `tests/test_metrics_bootstrap.py::test_session_bootstrap_respects_within_session_dependence` (half-width ≈ 1.96σ/√n_sessions within 15%, > 3× the naive row-level width), `test_session_bootstrap_is_reproducible`

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
