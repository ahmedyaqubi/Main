# Milestones

Status: TODO | IN PROGRESS | DONE. Each milestone is DONE only when every criterion has evidence.
Global criteria for every milestone: `uv run pytest`, `uv run ruff check .`, `uv run mypy src` pass
in CI; tests for numerical code were written first; this file is updated with evidence.
Test IDs refer to `docs/TEST_PLAN.md`; gate numbers refer to `PHASE_1_SPEC.md` §11.

> **PHASE 1 CLOSED (owner, 2026-10-08).** No validated, calibrated, cost-adjusted edge was found:
> M19 FAIL; M19R no edge; M19S KILL; M19T KILL.
> - Registered trials on the development window: 39. The final holdout was never opened (ADR-0011).
> - Synthesis and recommendation: `reports/research/phase1_synthesis.md`.
> - M20–M22 are not started and stay blocked. Forward data collection (ADR-0013 D8) is not set up.
> - Any further research needs a new project ADR (see the synthesis report §6).

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

## M8 — Logistic regression (Model 1) — DONE (2026-10-07; CI green on 4f9b459: https://github.com/ahmedyaqubi/Main/actions/runs/37597027525)
Depends on: M7 (DONE)
Owner decisions (2026-10-07): Q1 scikit-learn fit, JSON artifact scored with numpy; Q2 missing → training mean + `missing_<feature>` indicator, fills reported; Q3 all 28 f2 features, day_of_week one-hot, no interactions, z clipped ±5; Q4 C grid {0.001, 0.01, 0.1, 1, 10} chosen by calibration-block log loss, fit on train only, no refit; Q5 every grid point is a registered trial; Q6 primary reference = conditional Model 0, also unconditional; Q7 70 CANDIDATE `model_versions` rows; Q8 `qqq1dte.models` added to the no-labels import contract. Parameters in `configs/phase1.yaml` → `models.logistic`.
Acceptance:
- [x] Standardisation fit on train only (T-LEAK-11); regularisation chosen on the validation/calibration block, never on test — `src/qqq1dte/models/design.py` (`wide_features`, `fit_design`, `transform`), `src/qqq1dte/models/logistic.py` (`select_c` takes only train and calibration arrays); `tests/test_design.py::test_fit_design_statistics_equal_training_statistics_exactly`, `test_test_data_changes_nothing`, fill/indicator/clip tests; `tests/test_logistic.py::test_select_c_minimises_calibration_log_loss_and_sees_no_test_rows`, known-coefficient recovery, numpy = scikit-learn scores (1e-12)
- [x] Brier skill vs Model 0 per fold with CI; coefficients reported per fold (stability) — `scripts/m8_logistic.py` → `reports/models/logistic_m1.md` (pooled and per-fold BSS vs conditional and unconditional Model 0 with 2,000-rep session-bootstrap CIs, fold win counts, chosen C, fill rates, standardised coefficients per fold with sign consistency)
- [x] Serialization round-trip (T-REP-01) — `tests/test_logistic.py::test_t_rep_01_save_load_roundtrip` (bit-identical scores, same sha256), `test_load_rejects_tampered_artifact`; all 70 run artifacts reloaded against their recorded `artifact_sha256`
Evidence / results (run `walk_forward-ae9e9d38408f` + 5 `hyperparam_search` runs from code 4f9b459, all COMPLETED; n_trials on the test window = 7; 70 CANDIDATE models in `model_versions` for that run, artifacts `data/models/m1/<run_id>/`; pooled OOS 440 sessions, n_effective ≈ 1,320; scores uncalibrated):
- Move-size targets: Model 1 beats conditional Model 0 clearly. BSS B_up 0.25% +0.114 [+0.094, +0.134] (6/7 folds), B_dn 0.25% +0.089 [+0.067, +0.113] (6/7), B_up 0.50% +0.122 [+0.076, +0.168] (7/7), B_dn 0.50% +0.090 [+0.057, +0.124] (6/7). Main terms, stable in sign across all 7 folds: rv_30m, straddle_move (+), minutes_since_open (−), macro_event_today (+). This is volatility forecasting, not direction.
- Direction targets: no skill. A_up −0.005 [−0.017, +0.006], A_dn +0.004 [−0.007, +0.016], C_call −0.003 [−0.012, +0.006], C_put +0.006 [−0.002, +0.015] (vs unconditional +0.009 [+0.001, +0.018], marginal), D_put −0.003 [−0.009, +0.004]; D_call is worse than Model 0: −0.009 [−0.019, −0.000].
- C chosen: 0.001 (the smallest grid value) in 42/70 fold-targets, mostly the direction targets, i.e. the selector prefers a near-constant model there.
Notes / open issues:
1. Grid boundary: C = 0.001 is the lower edge of the grid for 42/70 fits. A smaller C would move further toward the base rate; extending the grid is a new pre-declared config (more trials), not done here.
2. Several missing indicators are identical columns (e.g. ret_since_prev_close / dist_prev_high / dist_prev_low / overnight_gap are missing together), so L2 splits their weight; harmless for scores, but read their individual coefficients as a group.
3. B-label skill is consistent with volatility clustering and with shorter effective windows late in the session; it says nothing about option P&L. The trading-relevant C targets show no reliable skill over Model 0 at this stage.
4. Test-first: design, logistic and model-registry tests were run red before implementation.
5. A first run (`walk_forward-8a78b189a6b8`, uncommitted code on e21d3af) gave identical numbers; it and its 70 model rows stay recorded. Same config hashes, so n_trials is unchanged.

## M9 — Gradient-boosted model (Model 2) — DONE (2026-10-07; CI green on 0be7adf: https://github.com/ahmedyaqubi/Main/actions/runs/37601566656)
Depends on: M8 (DONE)
Owner decisions (2026-10-07): Q1 grid num_leaves {7, 31} × min_data_in_leaf {500, 2000}, fixed lr 0.03 / feature & bagging fraction 0.8 / λ2 1.0, early stopping 100 rounds (max 2,000) on calibration log loss; Q2 deterministic LightGBM, text artifact + sha256; Q3 raw features, native missing handling; Q4 Model 1 = saved artifacts of `walk_forward-ae9e9d38408f`; Q5 gain-share stability (Spearman, top-10 counts); Q6 canary = selected grid point refit on row-permuted train/calibration labels (statistic superseded by ADR-0008, see below); Q7 lightgbm added. Parameters in `configs/phase1.yaml` → `models.gbm`.
Acceptance:
- [x] LightGBM with a small, pre-declared hyperparameter grid; every grid point logged as a trial — `src/qqq1dte/models/gbm.py` (`grid_points`, `fit_gbm`, `select_params`, `save`/`load`, `gain_importance`, `canary_permutation`); `tests/test_gbm.py` (planted signal learned and ranked first, noise AUC ≈ 0.5, selection on calibration only, deterministic refit, T-REP-01 bit-identical round trip + tamper rejection); 4 `hyperparam_search` runs + `walk_forward-8adbdf4112a5` + canary run, from code 0be7adf, all COMPLETED; n_trials on the test window = 14; 70 CANDIDATE `model_versions` for that run (`data/models/m2/<run_id>/`)
- [x] Brier skill vs Model 0 and Model 1 per fold with CI; feature-importance stability across folds — `scripts/m9_gbm.py` → `reports/models/gbm_m2.md`; `metrics.auc` (`tests/test_metrics_bootstrap.py::test_auc_hand_computed_and_ties`); shared helpers `src/qqq1dte/backtesting/oos.py`
- [x] Shuffled-label canary gives AUC ≈ 0.5 (T-LEAK-13) — per **ADR-0008** (mean over 20 permutations of the mean per-fold OOS AUC, ± 0.02): **PASS for all 10 targets**, statistic 0.4957–0.5059 (permutation SD 0.007–0.021), `reports/models/gbm_m2.md` § Gate-4 canary; `models.gbm.canary_statistic` + test. The first canary (single permutation, pooled scores; `canary-541beb1db5f4`) failed for 3 B targets below 0.5 and stays recorded (note 1).
Evidence / results (pooled OOS, 440 sessions, n_effective ≈ 1,320; uncalibrated scores):
- B targets: Model 2 beats conditional Model 0 (BSS +0.070 to +0.139, all CI lower bounds > 0, 6–7/7 folds) but is not better than Model 1: vs M1 B_up 0.25% +0.013 [−0.001, +0.026], B_up 0.50% +0.020 [−0.016, +0.054], B_dn 0.25% −0.018 [−0.031, −0.006], B_dn 0.50% −0.021 [−0.044, −0.002].
- Direction targets vs conditional Model 0: A_up −0.004, A_dn +0.001, C_call +0.007 [−0.001, +0.014] (5/7 folds), C_put +0.005 [−0.002, +0.012], D_call +0.007 [−0.003, +0.017], D_put −0.001; no CI excludes 0. AUC 0.51–0.57.
- Importance stability: mean pairwise Spearman 0.84–0.93 for A_up, B, C targets; 0.66–0.70 for A_dn, D_call, D_put. B targets dominated by rv_30m, straddle_move, vix_prev_close (top 10 in 7/7 folds).
Notes / open issues:
1. Canary diagnosis. The failures are BELOW 0.5, which leakage cannot produce (leakage pushes AUC up). The mean of per-fold canary AUCs is 0.484–0.510 for every target. Two causes: (a) pooling scores across folds — each canary model predicts roughly its own training base rate, and B base rates mean-revert between training and test blocks, so pooled AUC falls below 0.5; (b) one permutation is a noisy draw: when features strongly predict the target (B), any random function of the features has a wide AUC spread (per-fold SD 0.07 for B_up 0.50%). The owner accepted ADR-0008 (option A) and the canary was rerun under it; the failed run stays recorded.
2. Test-first: gbm and auc tests were run red before implementation.
4. **ADR-0008 (owner, 2026-10-07, option A):** canary statistic = mean over 20 permutations of the mean per-fold OOS AUC, tolerance ± 0.02 unchanged; implemented in `models.gbm.canary_statistic` (`tests/test_gbm.py::test_canary_statistic_averages_fold_aucs_over_permutations`, run red first). Rerun done (PASS, above).
3. Runs `walk_forward-2a8b55bd1356` and its grid runs (code 507bb6f + uncommitted M9 code) gave the same model results as the rerun from 0be7adf (`walk_forward-8adbdf4112a5`); grid and OOS config hashes are identical, so the rerun added only the new canary config to n_trials (13 → 14).

## M10 — Chronological walk-forward — DONE (built within M7, 2026-10-07; CI green on 763497a)
Depends on: M5, M6 (DONE)
Acceptance:
- [x] Expanding-window splitter with calibration block, test block, 1-session embargo (§8); T-WF-01…04 pass — `src/qqq1dte/backtesting/splits.py` (`walk_forward_folds`; only whole 3-month test blocks, M7 Q1; refuses any session past the holdout boundary); `tests/test_splits.py` (fold layout: 7 folds, fold 1 train 2023-03-28→2024-03-27 (251 sessions), embargo 2024-03-28, calib 2024-04-01→05-24, test 2024-05-28→08-27 (64); T-WF-01 chronological/disjoint/expanding; T-WF-02 embargo = next session; holdout rejected; T-WF-04 no shuffle/seed parameter and no "random"/"shuffle" in the source). Month arithmetic `core.calendar.add_months` (tested in `test_core_time.py`)
- [x] Final holdout locked and access-logged (T-WF-03) — `src/qqq1dte/backtesting/holdout.py` (`HoldoutGuard`): holdout sessions need a run registered with `touches_final_holdout`, a justification and a database; each access is written to `final_test_access_log`; any access after the first needs an ADR reference. `tests/test_registry_holdout.py::test_wf_03_*`, `test_guard_without_database_refuses_any_holdout_access`. Holdout = sessions after `TradingCalendar.final_holdout_start(2026-10-02)` = 2026-04-02
- [x] Run registry: every run creates a `validation_runs` row before evaluation; `n_trials` computable per data window — `src/qqq1dte/backtesting/registry.py` (`register_run` → REGISTERED, `complete_run`, `fail_run`, `n_trials` = distinct config hashes overlapping a window, any status); `tests/test_registry_holdout.py::test_run_is_registered_before_evaluation_then_completed`, `test_failed_run_still_counts_as_a_trial`
- [x] Session-block bootstrap utility with a test on a known-variance synthetic series — `src/qqq1dte/backtesting/bootstrap.py` (`session_bootstrap_ci`, multinomial session weights); `tests/test_metrics_bootstrap.py::test_session_bootstrap_respects_within_session_dependence` (half-width ≈ 1.96σ/√n_sessions within 15%, > 3× the naive row-level width), `test_session_bootstrap_is_reproducible`

## M11 — Realistic options backtester — DONE (2026-10-07; CI green on 54825e8: https://github.com/ahmedyaqubi/Main/actions/runs/37605349237)
Depends on: M6, M10 (DONE)
Owner decisions (2026-10-07): Q1 before M13 the engine runs on real data only with a mechanical diagnostic signal (CALL / PUT at every timestamp, separately), used for reconciliation with the C labels and as an unconditional-entry baseline, not a strategy; Q2 conservative fill + §4.8 costs behind a fill-model interface (moderate/optimistic in M12); Q3 clock steps through signals (T_e = T + 5 s) and 1-minute quote snapshots; exits on the bid up to min(T_e + 90 min, forced flat); Q4 journal writer tested on the test DB, the real-data diagnostic writes Parquet + a `validation_runs` row only; Q5 only filled entries count toward max entries; UNFILLED = fill-time hard/age failure; M6 path rules for unresolved data.
Acceptance:
- [x] Event-driven loop with monotonic clock and quote cursor (T-BT-05) — `src/qqq1dte/execution_sim/engine.py` (`run_session`), `execution_sim/cursor.py` (`QuoteCursor` on the shared `SimClock`); `tests/test_cursor.py` (never returns a quote later than the clock, cannot move backward, shared-clock check, one symbol in time order)
- [x] Frozen selection rule at `T_e` (T-SEL-01…05); candidates written to `trade_candidates` — engine uses `execution_sim.selection` at T_e, a `Candidate` per selection (gates, failures, quote); `src/qqq1dte/journal/writer.py` (`write_backtest`, one transaction); `tests/test_journal_writer.py` (written and read back; DB PIT trigger rejects a quote after T_e; one trade per candidate × fill model; append-only); `tests/test_backtest_engine.py::test_illiquid_selection_is_no_trade_with_a_candidate_and_no_entry_used`, `test_put_side_selects_highest_strike_at_or_below_spot`; T-SEL suite unchanged and passing
- [x] Target/stop on the bid, forced flat, one position, max entries/day (T-BT-02…04) — `tests/test_backtest_engine.py::test_bt_02_one_position_at_a_time`, `test_bt_03_max_entries_per_day`, `test_bt_04_forced_flat_at_1550_and_never_expired`, `test_mid_reaching_target_does_not_trigger`, `test_time_exit_at_entry_plus_max_holding`, unresolved-gap / no-bid / rejected-record tests
- [x] Per-trade MFE, MAE, P&L, R, holding time, exit reason, unfilled count recorded — `Trade` (entry/exit fills and quotes, target/stop, MFE/MAE, gross/commissions/fees/spread cost/net, R, holding seconds, flags); UNFILLED counted in decisions and trades
- [x] Accounting test with hand-computed trades (T-BT-01) — `src/qqq1dte/execution_sim/accounting.py`, `fills.py`; `tests/test_fills_accounting.py::test_bt_01_pnl_accounting` (5 trades: net, costs, R, spread cost, time-exit class), tick rounding against the trader, conservative fill
Evidence / results (`scripts/m11_diagnostic.py` → `reports/backtest/m11_diagnostic.md`, run `diagnostic-69efc08f5c09` from code 54825e8 (supersedes `diagnostic-09621c5bebe5`, uncommitted code, identical results), 756 pre-holdout research sessions, outputs `data/backtest/m11_diagnostic/<run_id>/`):
- Reconciliation with the independently written C labels: **4,535 / 4,535 trades match** on contract, outcome, entry, exit price, net P&L and trigger exit time (0 mismatches).
- Decisions: 2,268 CALL / 2,267 PUT entries (3 per session); NO_TRADE mostly MAX_ENTRIES_PER_DAY, SELECTED_CONTRACT_ILLIQUID 56 / 63; UNFILLED 0 (selection and fill see the same quote at T_e, as expected); UNRESOLVED_DATA 3 / 4.
- Unconditional-entry baseline (conservative fill, net, per contract; NOT a strategy): mean net CALL −$4.45 [−7.50, −1.19], PUT −$5.77 [−9.05, −2.53]; mean R −0.10 / −0.11; WIN 32% / 33%, LOSS 54% / 58%; median hold 25 / 21 min; mean spread cost $2.30 / $2.51.
Notes / open issues:
1. Time exits happen at T_e + 90 min (spec §2: entry + max holding) while C labels end at T + 90 min (§3). With 1-minute quotes both use the same quote; a missing T+90 snapshot could in principle flip a NO_EXIT_QUOTE decision (5 s more age). None occurred.
2. Entries are taken at the first three timestamps the gates allow, so the baseline concentrates early in the session (from 09:45). It is a reference for later comparisons, not an estimate of any model's performance.
3. Test-first: cursor, fills/accounting, engine and writer tests were all run red before implementation.

## M12 — Costs, slippage, latency — DONE (2026-10-07; CI green on 52c68a0: https://github.com/ahmedyaqubi/Main/actions/runs/37608678539)
Depends on: M11 (DONE)
Owner decisions (2026-10-07): Q1 moderate = mid ± α·half-spread, optimistic = mid, all rounded against the trader, triggers on the bid, missing bid sells at 0 in every model; Q2 each fill model is a full re-simulation (target/stop from its own entry fill); Q3 latency moves selection, spot and entry to T_e = T + latency; latency slippage = entry fill at T_e − same fill on T's quote; Q4 mechanical diagnostic signal, grid α {0, .25, .5, .75, 1} × latency {0, 5, 60} s × costs ×{1, 1.5} + three named models, pre-holdout; Q5 one `sensitivity` run for the whole pre-declared grid; Q6 gate 9 by a `NetPnl` type; Q7 cost multiplier scales commission + fees only. Grid in `configs/phase1.yaml` → `sensitivity`.
Acceptance:
- [x] Three fill models (T-FILL-01…03); commissions + fees per §4.8 — `src/qqq1dte/execution_sim/fills.py` (`Conservative`, `Moderate`, `Optimistic`, `scaled_costs`); `tests/test_fills_accounting.py::test_fill_01_three_models` (1.10 / 1.08 / 1.05), `test_fill_02_every_model_rounds_against_the_trader`, `test_missing_bid_sells_at_zero_in_every_model`, `test_cost_multiplier_scales_commission_and_fees_only`; `tests/test_backtest_engine.py::test_fill_03_optimistic_does_not_trigger_on_the_mid`, `test_each_model_sets_target_and_stop_from_its_own_entry_fill`, `test_latency_60s_selects_and_fills_on_the_later_snapshot`, `test_latency_0_and_5_use_the_same_minute_snapshot`
- [x] Sensitivity report: expectancy vs α ∈ {0, 0.25, 0.5, 0.75, 1}, latency ∈ {0, 5, 60} s, costs ×{1, 1.5} — `scripts/m12_sensitivity.py` → `reports/backtest/m12_sensitivity.md`, run `sensitivity-1097416fc6c0` from code 52c68a0 (supersedes `sensitivity-f6b5dad8437b`, uncommitted code, identical results; 756 pre-holdout sessions; trades in `data/backtest/m12_sensitivity/<run_id>/`)
- [x] Every P&L figure in reports is net of costs (enforced by type) — gate 9 — `NetPnl` (`execution_sim/accounting.py`, only constructible from gross + costs), `src/qqq1dte/backtesting/reporting.py` (`net_from_frame` rebuilds net from gross/cost columns and checks the stored net; `summarize_net` accepts only `NetPnl`); `tests/test_reporting_gate9.py` (arithmetic, inconsistent/missing cost columns rejected, runtime TypeError for floats, type hints, **mypy rejects a float P&L passed to the report helper**); M11 and M12 reports both use the helpers
Evidence / results (mechanical baseline, NOT a strategy; mean net $ per trade per contract, 95% session-bootstrap CI):
- Three models at latency 5 s, costs ×1: CALL conservative −4.45 [−7.50, −1.19], moderate −4.19 [−7.20, −0.94], optimistic −2.39 [−5.41, +0.77]; PUT −5.77 [−9.05, −2.53], −5.06 [−8.38, −1.76], −3.09 [−6.48, +0.16]. Mean spread cost per round trip $2.30–2.51 (conservative) vs $0.42 (optimistic).
- Grid: mean net < 0 in all 66 side × configuration cells; none has a CI above 0. Costs ×1.5 subtract $0.70 per trade; 60 s latency changes the mean by between +$0.02 and −$1.35 vs 5 s.
- Latency 0 s and 5 s give identical results (1-minute quote snapshots, as flagged in spec §6). At 60 s the mean latency slippage is slightly favourable (−$0.6 to −$1.4 per trade), yet net results worsen, because entry timing and selection change.
- α = 1 reproduces the conservative model and α = 0 the optimistic model exactly (consistency check).
Notes / open issues:
1. Fill probability is assumed to be 1 whenever the gates pass (spec §6); the grid does not model non-fills or queue position.
2. Test-first: fill, gate-9 and latency tests were run red first; `test_fill_03_*` and `test_each_model_sets_target_and_stop_from_its_own_entry_fill` passed on first run because the M11 engine already took a fill model (they are regression tests here). One expected median in `test_reporting_gate9.py` was wrong in the first draft and was corrected.
3. Shared per-session input loader `backtesting/session_data.py` (used by M12; M11 keeps its own loader).
4. The M11 report was regenerated from 52c68a0 (run `diagnostic-f52a8c29246a`, identical results) because its P&L now goes through the gate-9 helpers.

## M13 — Probability calibration — DONE (2026-10-07; CI green on 8b47af4: https://github.com/ahmedyaqubi/Main/actions/runs/37613563163) — gate 12 (ADR-0009) would PASS for 1 of 20 model/targets (Model 2 B_up 0.25%), FAIL for all others incl. every C target
Depends on: M8, M9 OOS models (DONE), M10 (DONE)
Owner decisions (2026-10-07): Q1 calibrate Model 1 and Model 2 (saved artifacts, no refit) for all 10 targets; Q2 fit on each fold's calibration block, evaluate on its test block, disclose that M8/M9 already used the calibration block for selection; Q3 candidates none / temperature / Platt / isotonic chosen by log loss on a chronological inner split of the calibration block, then refit on the whole block; Q4 gate 12 per spec §11 on pooled test blocks (would-pass/fail; verdict at M19); Q5 `CalibratedProbability` type + `decide()` guard; Q6 `calibration_results` rows + one `calibration` run per family. Parameters in `configs/phase1.yaml` → `calibration`.
Acceptance:
- [x] Platt, isotonic, temperature fitted on calibration blocks only (T-CAL-03); chosen method selected without test data — `src/qqq1dte/calibration/methods.py`, `fit.py` (`fit_calibration` refuses rows overlapping the training period or the test block; inner chronological split); `tests/test_calibration.py` (known Platt / temperature parameters recovered, isotonic monotone, clipping, save/load round trip per method, `test_cal_03_refuses_rows_overlapping_training_or_test`, `test_method_chosen_on_inner_chronological_split_then_refit`)
- [x] Reliability curves, Brier, log loss, ECE, slope, per-bin n and Wilson CI (T-CAL-01/02) — `src/qqq1dte/calibration/metrics.py` (`calibration_slope`, `wilson_ci`, `reliability`, `gate12`); `test_cal_01_ece_known`, `test_cal_02_perfectly_calibrated_synthetic`, `test_wilson_ci_hand_computed`, slope/robustness tests; `reports/models/calibration_m13.md` (pooled and per-fold metrics, a reliability table per model × target)
- [x] The decision engine refuses CALL/PUT without a calibration version (T-CAL-04) — `src/qqq1dte/execution_sim/decision.py` (`decide` → NO_TRADE UNCALIBRATED; with a version still NO_TRADE DECISION_RULE_PENDING until M15; `CalibratedProbability` only from a calibrator with a version id); `test_cal_04_uncalibrated_forces_no_trade`, `test_mypy_rejects_a_raw_score_as_probability`; the DB constraint `trade_requires_calibration` (M3) also holds
- [x] Gate 12 evaluated with numbers — `reports/models/calibration_m13.md`; runs `calibration-799352d4eabb` (Model 1) and `calibration-06a056389e36` (Model 2) from code 8b47af4 (supersede `calibration-7d1242da955e` / `calibration-383503512f20`, uncommitted code, identical results), all COMPLETED, 140 `calibration_results` rows (sha256 in `artifact_uri`), calibrator JSON in `data/calibration/<run_id>/`
Evidence / results (pooled test blocks, 440 sessions; would-pass/fail only):
- **Gate 12 (ADR-0009 bin rule; runs `calibration-4deeb5149539` / `calibration-e19b6c392dd0`, code be973f4, CI green https://github.com/ahmedyaqubi/Main/actions/runs/37642944327) would PASS only for Model 2 B_up 0.25%** (ECE 0.012, slope 0.999, 0 / 10 bins fail; 5 at the old unadjusted 95%) — a move-size target, not a decision target. All 19 others would FAIL. Under the original every-bin-at-95% rule all 20 failed (2–9 of 10 bins outside the Wilson CI); slope is outside [0.8, 1.2] in 14 of 20 (mostly direction targets, calibrated slope −0.03 to 0.74: the scores carry little information, so any spread is over-confident).
- Closest: Model 2 B targets — B_up 0.25% ECE 0.012, slope 0.999; B_up 0.50% ECE 0.007, slope 1.068; B_dn 0.50% ECE 0.010, slope 0.963 — failing only the bin rule (5 / 3 / 2 bins of 10).
- Decision targets: C_call M1 ECE 0.029, slope 0.49; M2 ECE 0.022, slope 0.35; C_put M1 ECE 0.017, slope 0.74; M2 ECE 0.016, slope 0.86 (bins 3–5 of 10 failed).
- Calibration rarely improves held-out Brier and sometimes worsens it (e.g. Model 1 B_up 0.25%: slope 1.03 raw → 0.52 calibrated, Brier 0.199 → 0.202). "none" is chosen in 26 / 70 fold-targets for M1 and 38 / 70 for M2: with 2-month calibration blocks and drift between blocks, re-mapping often does not transfer to the next 3 months.
Notes / open issues:
1. **Owner decision needed — gate-12 bin rule.** As written (every bin with n ≥ 200 inside its own 95% Wilson CI), a perfectly calibrated model with 10 bins fails about 40% of the time (1 − 0.95^10; `test_gate12_bin_rule_false_fail_rate_is_documented`). The observed failures (2–9 bins) are far beyond that chance level, so the conclusion above does not depend on it, but the rule needs an ADR before M19. **ADR-0009 ACCEPTED (owner, 2026-10-07, option A), implemented in be973f4:** per-bin Bonferroni level 1 − 0.05/k (simulated family-wise false-fail ≈ 4.5% vs 37–40% now). Disclosed there: under it 1 of 20 would pass (Model 2 B_up 0.25%, not a decision target); every C target still fails.
2. Calibration blocks were also used for M8/M9 selection (Q2); test-block evaluation is unaffected.
3. Robustness fixes found on real data: a constant prediction has no slope (NaN → the slope check fails), Platt on constant scores maps to the base rate, run metrics store NaN as null, and the logistic fit uses damped Newton (undamped Newton diverged on an isotonic-calibrated case kept as fixture `tests/fixtures/m13_gbm_f1_ccall_calibrated.npz`, 4,039 predictions and labels, no vendor data).
4. Test-first: methods, metrics, fit, store and guard tests were run red first; two synthetic convergence tests passed immediately (kept as regression tests); the real-data fixture test reproduced the failure and was red first.

## M14 — Regime analysis — DONE (2026-10-07; CI green on 67ad763: https://github.com/ahmedyaqubi/Main/actions/runs/37678700294)
Depends on: M13 (DONE)
Owner decisions (2026-10-07): Q1 R1 per §9 with fold-fit thresholds, EXTREME merged into HIGH (only counted), trend UNKNOWN with a reason when history is missing; Q2 labels stored for test-block sessions only; Q3 per-regime calibration (Models 1 and 2, M13 calibrators) and mechanical-baseline expectancy (conservative, moderate) with LOW_SUPPORT flags; Q4 pre-declared OD-9 test (stratified TREND − CHOP within volatility × event for C_call / C_put WIN rate and conservative baseline net CALL / PUT; keep the axis if any 95% CI excludes 0). Also accepted and implemented in this session: **ADR-0009** (gate-12 bin rule, M13). Parameters in `configs/phase1.yaml` → `regimes`.
Acceptance:
- [x] Regime labels per §9 with fold-fit thresholds (T-LEAK-12); stored in `regime_labels` — `src/qqq1dte/regimes/engine.py` (`session_state` via AsOfReader, `efficiency_ratio`, `fit_thresholds`, `assign`), `regimes/store.py`; `tests/test_regimes.py::test_leak_12_thresholds_fit_on_training_states_only`, `test_session_state_uses_only_information_known_at_t`, `test_missing_history_is_unknown_with_a_reason`, `test_macro_event_only_once_available`, `test_assignment_buckets`, `test_efficiency_ratio_hand_computed`; `tests/test_regime_store.py` (DB: written/read back, `available_at <= ts` enforced). Run `regime-a1fc599d0e3b` (uncommitted code) wrote 83,832 labels (27,944 test-block timestamps × 3 axes, version R1); the rerun from 67ad763, `regime-bffd14dd0c5a`, reproduced all 83,832 exactly (0 inserted, 0 conflicts) and regenerated the report with identical results
- [x] Per-regime calibration and expectancy with n, sessions, CI; LOW_SUPPORT flags applied — `src/qqq1dte/regimes/analysis.py` (`summarize`, `stratified_difference`; tests with known answers); `scripts/m14_regimes.py` → `reports/regimes/regimes_r1.md` (thresholds per fold, sessions per cell per fold, calibration by bucket for 10 targets × 2 models and by full cell for C targets, baseline expectancy by bucket and cell, both net of costs via the gate-9 helpers)
- [x] Decision on collapsing the trend axis (OD-9) documented via ADR if changed — **not changed**: the pre-declared test keeps the trend axis (12 cells). TREND − CHOP baseline net CALL +$12.97 [+3.28, +22.94], PUT −$12.72 [−22.80, −2.74]; C_call WIN +0.028 [−0.006, +0.061], C_put WIN −0.027 [−0.065, +0.014]. No ADR needed.
Evidence / results (test blocks 2024-05-28 → 2026-02-27, 440 sessions):
- Cells: 11 of 12 observed (LOW/CHOP/MACRO never occurs); 6 cells are LOW_SUPPORT pooled (5–15 sessions). LOW volatility appears almost only in fold 1: test-period VIX sat above the training terciles (cuts 13.6–14.6 / 15.7–17.5), so cell membership shifts strongly between folds.
- Baseline (NOT a strategy): **no regime bucket or cell has a mean-net CI above 0** (28 bucket rows, 44 cell rows, conservative and moderate). CALL side worst in CHOP (−$10.40 [−16.15, −4.81]) and MACRO (−$17.31 [−31.00, −3.64]); PUT side worst in TREND (−$13.09) and HIGH/LOW volatility.
- Calibrated probabilities by bucket (Model 2, C targets): observed − predicted within ±0.04 in every bucket; ECE 0.016–0.052 (higher in the smaller buckets).
Notes / open issues:
1. The efficiency ratio has no direction. The TREND/CHOP separation (CALL better, PUT worse in TREND) most likely reflects that trending stretches in 2024–2026 were mainly up-trends. A direction-aware trend axis would be a new regime version and a new ADR ("Later").
2. Many buckets and cells are compared; single CIs that exclude 0 are not corrected for multiplicity and are descriptive only.
3. 21 training sessions per fold have UNKNOWN trend (bar history starts 2023-03-28; 21 prior closes needed); they are excluded from the ER median, counted, and not filled.
4. Shared loaders `backtesting/artifacts.py` (model scorers, calibrators by run) now used by M13 and M14.
6. `write_regime_labels` is idempotent: an identical (ts, axis, version) label is kept with its original `thresholds_fit_run`; a different value is an error (`tests/test_regime_store.py::test_rewrite_is_idempotent_and_conflicts_are_errors`).
5. Test-first: engine, analysis and store tests were run red first.

## M15 — NO_TRADE logic — DONE (2026-10-07; CI green on c4e1bdd: https://github.com/ahmedyaqubi/Main/actions/runs/37703371065)
Depends on: M12, M13, M14 (DONE)
Owner decisions (2026-10-07): Q1 binary-conservative EV (P(WIN) calibrated; every non-WIN = full −20% stop; moderate entry fill; p_breakeven = (0.2·E·100 + costs) / (0.5·E·100)); Q2 `decision.model_family = gbm_m2` with its M13 calibrators, no extra gate-12 refusal rule; Q3 per-side reasons, higher EV wins, exact tie → NO_TRADE SIDE_TIE, positions via the engine (BLOCKED_POSITION_OPEN distinct); Q4 gate-13 mechanism `decision.blocked_regime_cells` (empty); Q5 gate-14 counterfactual = higher-EV side simulated anyway, one independent moderate trade per NO_TRADE timestamp, test blocks only.
Acceptance:
- [x] Decision engine per spec §4.1 with reason codes; BLOCKED_POSITION_OPEN distinct from NO_TRADE — `src/qqq1dte/execution_sim/decision.py` (`breakeven_probability`, `expected_value`, `SideInput`, `decide`), `execution_sim/engine.py::selection_at`; `tests/test_decision.py` (hand-computed breakeven/EV, strict margin, EV-based side choice and SIDE_TIE, selection reasons, REGIME_BLOCKED, T-CAL-04, mypy rejects a raw score), `tests/test_backtest_engine.py::test_selection_at_matches_the_engine_and_respects_t_e`; engine BLOCKED_POSITION_OPEN unchanged (T-BT-02)
- [x] Counterfactual analysis of NO_TRADE timestamps (gate 14) with session-bootstrap CI — `scripts/m15_decisions.py` → `reports/decisions/m15_no_trade.md`, run `decision-747dec735c50` from code c4e1bdd (supersedes `decision-8a196b570c04`, uncommitted code, identical results): 27,650 counterfactual trades at NO_TRADE timestamps, mean net −$2.96 [−5.32, −0.70]; traded − counterfactual +$14.95 [−11.52, +42.94] → **gate 14 would FAIL** (CI includes 0)
- [x] NO_TRADE rate reported overall, by regime, and by reason — same report: NO_TRADE 99.47% of 27,944 test-block timestamps; by R1 cell; reasons BELOW_BREAKEVEN_MARGIN (≈ 27.6k per side), SELECTED_CONTRACT_ILLIQUID (147 CALL / 153 PUT)
Evidence / results (test blocks 2024-05-28 → 2026-02-27; not a claim of profitability):
- Calibrated P(WIN) median 0.257 (CALL) / 0.280 (PUT) vs p_breakeven ≈ 0.41: median margin −0.155 / −0.132.
- Rule decisions: 175 CALL, 2 PUT (27 sessions, folds 1, 5, 6). Engine: 46 entered (45 CALL, 1 PUT), 103 BLOCKED_POSITION_OPEN, 28 NO_TRADE (MAX_ENTRIES_PER_DAY).
- 46 trades: 18 WIN / 23 LOSS / 5 time-exit profit; mean net +$12.0, median −$5.9 — far below the gate-15 minimum (300 trades, 150 sessions) and statistically indistinguishable from 0.
Notes / open issues:
1. **Correction (2026-10-07):** an earlier version of this note said most CALL decisions came from isotonic step values. Traced per decision, they come from fold 1 (isotonic, 47 decisions / 12 trades), fold 5 (temperature, 40 / 12) and fold 6 (no calibration, raw score, 88 / 22). The common factor is support: every CALL decision's raw score lies in the extreme upper tail of its fold's calibration block (0–79 calibration rows score as high or higher; median 5–50). **ADR-0010 ACCEPTED (owner, 2026-10-07, option A), implemented in 770893b (CI green https://github.com/ahmedyaqubi/Main/actions/runs/37704387480):** a side needs ≥ 200 calibration-block rows with a raw score at or above its own (gate-12 bin size); `tests/test_decision.py::test_adr_0010_minimum_calibration_support`. Rerun `decision-7cd0dc2805d1` (new configuration): **NO_TRADE at 100% of 27,944 test-block timestamps, 0 trades**; reasons BELOW_BREAKEVEN_MARGIN (25,459 CALL / 24,644 PUT), INSUFFICIENT_CALIBRATION_SUPPORT (2,338 / 3,147), SELECTED_CONTRACT_ILLIQUID (147 / 153). Gates 13 and 14 not evaluable (0 trades); NO_TRADE counterfactual mean net −$2.97 [−5.37, −0.71] over 27,827 simulated trades. The pre-ADR runs (`decision-8a196b570c04`, `decision-747dec735c50`, 46 trades) stay recorded.
2. Gate 13 not evaluable (no regime cell reaches 100 trades). Gate 15 (sample size) clearly not met.
3. The M13 decision guard tests moved to `tests/test_decision.py` with the new interface (per-side calibration versions; `CalibratedProbability` carries its own version).
4. Test-first: decision and selection_at tests were run red first.

## M16 — Prediction/trade journal — DONE (2026-10-08; code 1348fb8 CI green: https://github.com/ahmedyaqubi/Main/actions/runs/37716079120)
Depends on: M15 (DONE)
Owner decisions (2026-10-07/08): Q1 per-target versions in a new append-only `prediction_scores` table (predictions' single version columns = CALL side); Q2 a non-owner role `qqq1dte_journal_writer` with INSERT/SELECT only (owner granted CREATEROLE to `qqq1dte` locally; CI's user is superuser); Q3 journal every test-block prediction of the current decision configuration (BACKTEST mode), counterfactuals stay in Parquet; Q4 `journal.replay` re-derives everything from stored references, seeded sample of 200.
Acceptance:
- [x] Every Phase 1O field persisted; journal tables append-only (DB role test: UPDATE/DELETE fail) — `migrations/versions/0002_prediction_scores_journal_role.py`; `src/qqq1dte/journal/writer.py` (`write_prediction`, one transaction); `tests/test_journal_schema.py` (`test_journal_writer_role_cannot_update_or_delete` × 4 tables × UPDATE/DELETE → permission denied; role can INSERT/SELECT; `prediction_scores` append-only and keys; upgrade/downgrade keeps grants); field-coverage table in `reports/journal/m16_journal.md` (all 25 Phase 1O fields mapped; target/stop/MFE/MAE/outcome/P&L/costs live on `simulated_trades` and are empty here because there are 0 trades)
- [x] `journal.replay(prediction_id)` reproduces stored scores and decision (T-REP-02) — `src/qqq1dte/journal/replay.py`; `tests/test_journal_replay.py` (synthetic prediction reproduced; a 1e-6 tampered score detected); run `journal-4a7a186908c7`: **200 / 200 sampled predictions reproduced, 3,400 checks, 0 failures**
Evidence / results: run `journal-4a7a186908c7` (code 1348fb8, decision config hash `1eb97f25…`, the M15 ADR-0010 configuration): 27,944 predictions, 55,888 `prediction_scores`, 55,888 `trade_candidates` (the chosen contract per side, with gate results), 0 `simulated_trades`; all decisions NO_TRADE; 0 underlying prices older than 60 s.
Notes / open issues:
1. The M15 decision logic moved to `src/qqq1dte/journal/pipeline.py` (shared by M15 and M16); the M15 report was reproduced identically after the move (run `decision-8a5f9559f8c4`, uncommitted code on 6ff5463; same configuration hash, so n_trials unchanged).
2. Roles are cluster-wide: migration 0002 creates the role if missing (needs CREATEROLE, fails loudly otherwise) and never drops it on downgrade (only revokes its privileges in that database).
3. Feature values are journaled by reference to the immutable f2 snapshot row (dataset `71259fcf…`), not copied; replay reads that row.
4. Test-first: schema, writer and replay tests were written before the code; the first replay-test run failed on a fixture without PUT quotes (test data, fixed).

## M17 — Model versioning & promotion — DONE (2026-10-08; CI green on cc297f8: https://github.com/ahmedyaqubi/Main/actions/runs/37720505643)
Depends on: M16 (DONE)
Owner decisions (2026-10-08): Q1 Phase 1P gates mapped to spec §11 numbers (`configs/phase1.yaml` → `promotion`), NOT_EVALUABLE counts as not passed; Q2 DB-enforced human-only path (migration 0003) + single code path `promote`; Q3 approver recorded as **Ahmed**; Q4 review the decision family's latest-fold candidates (gbm_m2 fold 7, C_call / C_put) from stored evidence runs, expected KEEP_CURRENT.
Acceptance:
- [x] `model_versions` + `model_promotions`; at most one PRODUCTION per target (DB constraint test) — unique index `one_production` (M3) tested through a promotion record (`tests/test_db_schema.py::test_one_production_model_per_target`); migration 0003 makes `model_promotions` append-only (`tests/test_promotion.py::test_promotion_records_are_append_only`)
- [x] Promotion requires all Phase 1P gates and a named human approver; there is no automatic path (test) — `src/qqq1dte/models/promotion.py` (`evaluate_gates`, `eligible`, `promote`, manual CLI `python -m qqq1dte.models.promotion --review-run … --target … --approved-by …`); migration 0003 trigger refuses PRODUCTION without a PROMOTED record in the same transaction; tests: `test_direct_status_change_to_production_is_refused`, `test_promote_refuses_failing_gates_and_blank_approver`, `test_promote_requires_an_explicit_named_approver`, `test_only_the_promotion_module_can_set_production` (static), `test_manual_promotion_command_uses_stored_gate_results`, per-gate threshold tests
- [x] Failing candidate → KEEP_CURRENT recorded — `record_keep_current`; `test_failing_candidate_records_keep_current`; run `promotion_review-d7ae9c089efa` (code cc297f8, reviewer Ahmed): **KEEP_CURRENT for C_call and C_put**, gate results stored in `model_promotions` and `reports/models/promotion_m17.md`
Evidence / results (candidates `m2-walk_forward-8adbdf4112a5-f7-C_call` / `-C_put`; no production model exists):
- PASS: leakage (canary 0.4997 / 0.4984), no degradation (no current model).
- FAIL: out-of-sample performance (BSS vs Model 0 +0.0066 [−0.0008, +0.0138] / +0.0046 [−0.0020, +0.0116]; CIs include 0), calibration (gate 12), sample size (0 trades under ADR-0010).
- NOT_EVALUABLE: regimes (gate 13), after costs (gates 10/11), walk-forward stability (needs fold-level traded expectancy; Model 0 fold share alone is 5/7).
Notes / open issues:
1. Comparison against an existing production model needs that model's stored evidence; the review script stops with an error in that case (none exists today). To be built when a first promotion happens.
2. `conservative_mean_net` (gate 11) is not available from decision runs, which simulate the moderate fill; with 0 trades it is moot. A future review with trades should rerun the traded decisions under the conservative fill.
3. Test-first: promotion and migration tests were run red first; the static check initially flagged a read-only `WHERE status = 'PRODUCTION'` and was narrowed to writes.

## M18 — Drift monitoring — DONE (2026-10-08; CI green on b2e4aa8: https://github.com/ahmedyaqubi/Main/actions/runs/37723191996)
Depends on: M16 (DONE)
Owner decisions (2026-10-08): Q1 monitors (feature / prediction PSI, calibration z, expectancy, regime frequency) on 10-session windows vs a research reference; Q2 overall = most severe, DISABLED latches until a named human re-enables; Q3 DISABLED → `decide` NO_TRADE DRIFT_DISABLED, PAPER_ONLY flagged (no live mode in Phase 1), WARN logged; Q4 gate-18 replay (reference sessions in seeded random order, 20 replays, injections at session 30: features +1 SD → PAPER_ONLY, 50% of WINs → LOSS → DISABLED; pass = right alert ≤ 10 sessions in every replay, ≤ 1 replay escalating before injection); Q5 alerts in run metrics / report (DB table at M20). **Option A (owner, after the first real-data run):** PSI thresholds calibrated to no-drift noise instead of fixed 0.10 / 0.25. Parameters in `configs/phase1.yaml` → `monitoring`.
Acceptance:
- [x] PSI on features and predictions, rolling calibration/ECE, rolling expectancy, regime frequency — `src/qqq1dte/monitoring/drift.py` (`psi`, `psi_categorical`, `build_reference` with leave-window-out null calibration, `assess_window`, `DriftMonitor`); `tests/test_drift.py` (hand-computed PSI and categorical PSI, reference gap SD, thresholds = null quantiles and reproducible, stationary windows rarely escalate, each injection raises its alert, expectancy levels with the gate-9 helpers, regime frequency only WARNs, combined-only DISABLED)
- [x] Synthetic drift injection detected within 10 sessions (gate 18); alert states: OK / WARN / PAPER_ONLY / DISABLED — synthetic replay test (`test_gate_18_replay_on_synthetic_stationary_data`) and real-data replay `scripts/m18_drift.py` → `reports/monitoring/m18_drift.md`, run `monitoring-10b177d1695e` from code b2e4aa8 (identical to `monitoring-6455ec4d4e17`): **feature shift 20/20 PAPER_ONLY, delay 5 / 10 / 10 (min / median / max), 1 false-alarm replay — PASS; calibration degradation 20/20 DISABLED, delay 4 / 8 / 10, 0 false-alarm replays — PASS**
- [x] A degraded model cannot keep emitting CALL/PUT (test) — `decide(..., drift_state=)`: DISABLED → NO_TRADE DRIFT_DISABLED before any other check; `test_degraded_model_cannot_emit_call_or_put`; `DriftMonitor` latches DISABLED until `reenable(approved_by)` with a non-blank name (`test_disabled_latches_until_a_named_human_reenables`)
Evidence / results:
- Reference thresholds (folds 1–4 test blocks, 256 sessions; 5,000 leave-window-out draws): max feature PSI WARN 4.94 / PAPER_ONLY 5.11; max prediction PSI 1.19 / 1.97; regime-cell PSI WARN 2.39. No-drift 10-session windows have feature PSI ≈ 3 (median): many features are constant within a session.
- Chronological monitoring of folds 5–7 (181 windows, information only): latched state WARN 92 / PAPER_ONLY 85 / OK 4; never DISABLED. PAPER_ONLY is driven by `vix_prev_close` (105 escalated windows): the VIX level in mid-2025 – early 2026 sits outside the 2024 – early 2025 reference; regime frequency WARN in 169 windows for the same reason. Calibration WARN in 14 windows, never DISABLED. Expectancy not evaluable (0 trades under ADR-0010).
Notes / open issues (disclosed: the monitor design was refined after real-data runs failed gate 18):
1. Run `monitoring-fbaf389a5600` (fixed PSI 0.10 / 0.25 as first approved): every replay escalated before injection (no-drift feature PSI ≈ 3) and the calibration injection was missed because `flip_wins` turned unresolved (null) outcomes into NaN — a bug, fixed with `test_flip_wins_keeps_unresolved_outcomes_null`. → Owner chose option A (null-calibrated thresholds).
2. Run `monitoring-18591d2806a1` (option A, 1,000 draws, any calibration z > 3 → DISABLED): features PASS; calibration detected 20/20 but 3 replays false-alarmed (three z-scores at 3σ across ~20 windows; 0.8% per window). Changed: DISABLED only from the combined decision-target z (per-target > 3 → WARN, consistent with the documented one-sided limit) and 5,000 null draws (stable 99.9% quantile). Run `monitoring-6455ec4d4e17` passes both.
3. Known limits: a calibration degradation on one decision target only reaches WARN within 10 sessions; feature-shift detection sits at the 10-session limit (median and max delay 10) for a +1 SD shift — smaller shifts would take longer.
4. The three development runs used uncommitted code on 12e79be; the rerun from b2e4aa8 (`monitoring-10b177d1695e`) reproduced the final results exactly.
5. Test-first: drift tests were run red first; one synthetic test case was mis-specified (combined gap not balanced) and corrected.

## M19 — Full historical validation — DONE: verdict **FAIL** (2026-10-08; CI green on 287846e: https://github.com/ahmedyaqubi/Main/actions/runs/37726181006)
Depends on: M7–M18 (DONE)
Owner decisions (2026-10-08): **ADR-0011 (option B)** — the final holdout stays locked while pre-holdout gates fail (opening it could not change a FAIL verdict and would spend it); Q2 gate 16: DSR needs trade returns (not evaluable), PBO (CSCV, 16 blocks) over the 9 model-selection configurations; Q3 decisive evidence recomputed in the run (gate 3, gate 7 all journal candidates, gate 16 PBO, gate 17 replay, test suites), the rest read from committed runs by id (`configs/phase1.yaml` → `validation_gates.evidence`).
Acceptance:
- [x] Single registered run over the full walk-forward; final holdout opened exactly once (logged) — **amended by ADR-0011**: one registered `final_validation` run over the walk-forward evidence; the holdout was **not opened** (`HoldoutGuard` on pre-holdout sessions; `final_test_access_log` 0 rows). It is reserved for the first configuration that passes every pre-holdout gate.
- [x] Gates 1–18 evaluated with numbers, CIs, sample sizes, `n_trials`, DSR, PBO in `reports/validation/` — `reports/validation/m19_gates.md`, run `final_validation-b060967f6104` (code 287846e); `src/qqq1dte/validation/phase1_gates.py` (gate evaluators, `pbo_cscv`, `deflated_sharpe_probability`), `tests/test_validation_gates.py` (thresholds, PBO noise ≈ 0.5 / dominant = 0 / hand case, DSR formula and monotonicity); n_trials on the test window = 28
- [x] Explicit PASS/FAIL per gate; FAIL on any gate stops progression to M20 unless the owner records an ADR accepting the limitation — **PASS: 1, 2, 3, 4, 5, 7, 8, 9, 17, 18. FAIL: 6, 12, 15, 16. NOT_EVALUABLE (counted as not passed): 10, 11, 13, 14.** Progression to M20 is blocked.
- [x] No claim of profitability; report states evidence and uncertainty only — stated in the report
Evidence / results (walk-forward test blocks 2024-05-28 → 2026-02-27, decision configuration gbm_m2 + ADR-0010):
- Gate 3: 1,346,688 pre-holdout feature rows, 0 PIT violations; 20/20 random timestamps recomputed identically. Gate 7: all 55,888 journaled candidates re-selected exactly. Gate 17: 200/200 journal predictions replayed (fresh seed), 373/373 tests pass in-run.
- Gate 6 FAIL: BSS vs Model 0 C_call +0.0066 [−0.0008, +0.0138], C_put +0.0046 [−0.0020, +0.0116]; 5/7 folds each (< 70%).
- Gate 12 FAIL: C_call ECE 0.0216, slope 0.348, 4/10 bins outside; C_put ECE 0.0155, slope 0.857, 1/10 bins outside.
- Gate 15 FAIL: 0 trades (ADR-0010). Gates 10, 11, 13, 14: not evaluable without trades.
- Gate 16 FAIL: PBO C_call 0.062, **C_put 0.410** (> 0.20); DSR not evaluable (no trade returns).
- Gate 18 PASS (M18 replay); gate 4 PASS (canary 0.4957–0.5059, import contract kept, T-LEAK tests).
Notes / open issues:
1. First run `final_validation-1910724fb43c` (uncommitted code on a983dad) reported gates 2 and 4 FAIL for reasons in the checks, not the project: gate 2 counted CRITICAL events of two superseded cleaned-options dataset versions (the current version's 4 events are all ADR-resolved, as M4 reported) — fixed to count current versions only; gate 4's `test_leak_10_import_contract_kept` crashed decoding `lint-imports` output under `PYTHONIOENCODING=utf-8` on Windows (contract kept, exit 0) — fixed with explicit UTF-8 decoding. All other numbers identical in the rerun.
2. An earlier draft of the gate module overwrote M4's `validation/gates.py`; it was restored from git before any commit, and the new module lives in `validation/phase1_gates.py`.
3. What M19 says: on 3+ years of 1-minute QQQ and OPRA data, the pre-declared models do not show a reliable, calibrated, cost-adjusted edge for the C option targets; the decision engine (with ADR-0010) correctly refuses to trade. Better features or models would be needed; the holdout remains available to test them.

## M19R — Research iteration 1: move-size (B) and direction — CLOSED 2026-10-08: no validated edge (stage 1 CI green on 5ed682e: https://github.com/ahmedyaqubi/Main/actions/runs/37731145335)
Depends on: M19 (verdict FAIL; holdout locked by ADR-0011)
Owner decisions (2026-10-08): diagnostics first, then the owner picks Stage-2 experiments; Stage-2 trial budget ≤ 6 new configurations declared before any run; no data purchases (data on disk only); holdout untouched.
Acceptance:
- [x] D1 implied-move benchmark: Model 2 B-target Brier vs a benchmark using only the option-implied move at T (logistic on log(m / implied σ), log(window minutes), log(minutes to expiry), fit on train), fold by fold with session-bootstrap CIs (test blocks: evaluation of the existing configuration) — `src/qqq1dte/models/implied.py` (`implied_inputs`, `ImpliedBenchmark`), tests in `tests/test_research_diagnostics.py`; result below
- [x] D2 lift: observed C_call / C_put (and A_up / A_dn) outcome rates by Model 2 score quantile (deciles, top 2%, top 1%) with Wilson CIs vs the breakeven probability (test blocks) — `src/qqq1dte/models/lift.py`; result below
- [x] D3 feature-group ablation for direction targets (A_up, A_dn, C_call, C_put): Brier change when each pre-declared feature group is dropped, scored on **calibration blocks** (fit on train) so the test blocks are not used to choose features — groups pre-declared in `configs/phase1.yaml` → `research.feature_groups`; result below
- [x] Stage-2 experiments declared (≤ 6 configurations) before any run — **declared 2026-10-08 (owner, option a): E1 f3 direction features + Model 2 (C_call, C_put); E2 E1 + D1 implied inputs + Model 2; E3 E1 + Model 1; E4 E1 + Model 2, C_put only (4 of 6)**; any configuration re-evaluated on gates 6 and 12 on the walk-forward; the holdout stays locked
- [x] All runs registered (counted in n_trials); reports in `reports/research/`
Stage-1 results (run `diagnostic-28e2588a772d` from code 5ed682e, identical to the uncommitted `diagnostic-5ef116763afd`; `reports/research/m19r_diagnostics.md`):
- **D1: the B skill is almost entirely what the option price already implies.** Implied-move benchmark vs Model 0: +0.085 to +0.137 BSS; Model 2 vs the implied benchmark: B_up 0.25% +0.0195 [+0.0015, +0.0352] (4/7 folds), B_up 0.50% +0.003 [−0.027, +0.032], B_dn 0.25% −0.014 [−0.028, +0.000], B_dn 0.50% −0.018 [−0.039, +0.001]. A volatility edge beyond implied is at most small (B_up 0.25% only).
- **D2: direction is far from tradable.** Observed C_call win rate: top decile 0.298, top 2% 0.300, top 1% 0.288 vs median breakeven 0.412 (base 0.241). C_put: top decile 0.350, top 2% 0.371 [0.331, 0.411], top 1% 0.374 [0.319, 0.432] — the closest to breakeven, still below it. A_up / A_dn top deciles 0.465 / 0.429 vs bases 0.449 / 0.391.
- **D3 (calibration blocks): small but real direction information** in price path (A_up ΔBrier +0.0030 [+0.0009, +0.0052]; A_dn +0.0022), momentum and cross-asset groups for A targets; for C_call: calendar (+0.0012), options flow, volume; for C_put: no group's CI excludes 0.
Stage-2 results (`reports/research/m19r_experiments.md`; runs E1 `experiment-d878fa4dade5`, E2 `experiment-204b18b73d79`, E3 `experiment-77f47aa007f9`, E4 `experiment-e4ace04b0c76`, uncommitted code on 2d2d5eb; f3 extras dataset `0884f8b3…`, `src/qqq1dte/features/defs_f3.py`, tests `tests/test_features_f3.py`):
- **Scope change (rule 9):** OPRA open interest is on disk for only 5 sessions (the M2 sample week), so the declared OI features were dropped; f3 = f2 + 8 extras (ATM call/put mid momentum 5 / 15 min, put/call imbalance change 15 min, call/put quote-size imbalance, QQQ NBBO size imbalance).
- **E1 C_call passes gate 6**: BSS vs Model 0 +0.0091 [+0.0032, +0.0154], 5/7 folds (f2: +0.0066 [−0.0008, +0.0138]). Gate 12 fails on the bin rule only (ECE 0.0137, slope 0.818, 2/10 bins). Lift is far from tradable: top 10% / 2% / 1% observed 0.297 / 0.315 / 0.255 vs breakeven 0.412.
- E1 C_put: +0.0060 [−0.0011, +0.0134] (gate 6 FAIL); gate 12 FAIL; top 1% 0.360.
- E2 (with implied inputs): C_call +0.0041 [−0.0035, +0.0124]; C_put +0.0076 [−0.0002, +0.0157]; C_put top 2% / 1% **0.403 [0.363, 0.444] / 0.421 [0.364, 0.480]** — the first buckets whose CI includes the breakeven, but gate 6 and gate 12 (slope 0.307) fail.
- E3 (logistic): C_call −0.0034, C_put +0.0061 [−0.0020, +0.0148] (6/7 folds); both gate 6 FAIL.
- **E4 was redundant**: models are already per target, so "C_put only" is exactly E1's C_put model (identical numbers). It still counts as a trial — a declaration error, disclosed.
- Multiple testing: 7 experiment × target results were examined; one gate-6 pass among them is weak evidence on its own (no correction applied), and no configuration passes gates 6 and 12 together or reaches breakeven in its top bucket with a lower CI above 0.412.
- **Stage-2b declared 2026-10-08 before any run (owner option b; the last 2 of 6 trials):** E5 = E2's C_put model (f3 + implied inputs, Model 2) with a tail trade rule — trade when the raw test score ≥ the fold's calibration-block score quantile 0.98 (threshold from scores only, no outcomes); E6 = the same at quantile 0.99. Evaluated on test blocks as independent trades with the C_put label outcome (conservative fill): trades, sessions, win rate with Wilson CI vs breakeven 0.412, mean net $ with session-bootstrap CI (gate-9 helpers). Research test only: it bypasses the §4.1 calibrated rule, so a positive result needs a spec ADR before any decision use.
- **Stage-2b results (runs experiment-a4a5672324a1 = E5, experiment-64105fcb6609 = E6; report `reports/research/m19r_tail_rule.md`):** the underlying model is E2's C_put model, re-fit identically, so the score metrics repeat E2. E5 (q 0.98): 1,201 trades over 135 sessions. Win rate 0.381 [0.354, 0.409], so the whole CI is below breakeven 0.412. Mean net +$0.57 [−7.25, +8.43], median −$35.40. E6 (q 0.99): 828 trades over 95 sessions. Win rate 0.396 [0.363, 0.430], which includes breakeven. Mean net +$2.27 [−7.71, +11.99], median −$35.40. Neither shows evidence of a cost-adjusted edge: both mean-net CIs include 0. Disclosures:
  - the Wilson CIs treat trades as independent, but there are about 9 tail trades per session with overlapping labels, so the true win-rate uncertainty is wider (the mean-net CI uses the session-block bootstrap);
  - these are trials 5–6 of 6, and the registry now counts more than 35 trials, so any marginal positive would also face DSR deflation.
  The 6-trial Stage-2 budget is used up.
- **Closed 2026-10-08 (owner):** no configuration passes gates 6 and 12; the tail rules show no cost-adjusted edge. The closing report is `reports/research/m19r_closing.md`. Descriptive statistics of the trade definition (pre-holdout, no model) come from `scripts/m19r_label_stats.py`: unconditional win rate 25–28% vs breakeven about 0.41; mean net −$5.05 to −$5.27 per trade; median entry spread $0.02 (0.82% of premium). M19 stays FAIL, M20 stays blocked, and the holdout stays locked. Open follow-ups (new data, a trade-definition ADR, a different strategy class) are under "Later"; none has been started.

## M19S — Phase 1b trade-definition study (ADR-0012) — CLOSED 2026-10-08: kill rule fired at Step 1 (code ea64d76, CI green: https://github.com/ahmedyaqubi/Main/actions/runs/37746323813)
Depends on: M19R (closed); ADR-0012 ACCEPTED 2026-10-08 (n_trials 35 at acceptance; budget ≤ 7 new trials, cap 42)
Step 1 acceptance (model-free screen + Â; 1 screen run + 2 counted refits):
- [x] Study label engine for T0–T5. Covers option bracket, time exit, QQQ bracket and the 2-strikes-ITM selection, all point-in-time.
  - `labels/option.py` (`ExitRule`; the Phase 1 rule is the default and unchanged);
  - `execution_sim/selection.py` (`strike_offset`, `NO_OFFSET_STRIKE`);
  - `labels/underlying.py` (`underlying_move`, `und_bracket`);
  - `labels/common.py` (horizon parameter);
  - tests in `tests/test_study1b_labels.py`.
  - The smoke run (7 sessions, uncommitted code, not registered) reproduces the stored L2 option labels exactly for T0, and the stored A_up / A_dn exactly from ret_90 (`scripts/m19s_build_labels.py --verify-t0`). The full build runs from committed code.
- [x] Screen logic: `backtesting/screen.py`. Covers a*, Â, coverage, the shared paired bootstrap, guards, the advance rule and the live-like policy / drawdown. Tests in `tests/test_study1b_screen.py`, with exact synthetic answers and the bootstrap identical to `session_bootstrap_ci`.
- Note: the edge-margin sensitivity (D2) needs calibrated direction probabilities, so it is reported in Step 2, not Step 1 (rule 6).
- [x] A labels at h = 45 and 150; Model 2 refits at those horizons with the frozen M9 grid point per fold. Registered and counted: `refit-ea7b11495e8a` (h = 45), `refit-2a1e8c58a334` (h = 150). Test AUCs are 0.48–0.59, and several folds kept only 1–8 trees.
- [x] Full label build from ea64d76: 577,152 study trades over 756 pre-holdout sessions, registered. The T0 and A checks match exactly on 76 sessions.
- [x] Screen per ADR-0012 D2: run `screen-667eb0490979`, report `reports/research/m19s_step1.md`. n_trials went 35 → 38 (cap 42).
- [x] **Decision: the kill rule fires. No definition qualifies, so the long-premium direction line is closed.**
  - Every cell has a negative Δ point estimate.
    - The best is T1a at 20% coverage: Δ −0.013, LB −0.049 (a* 0.570 vs Â 0.557).
    - At 100% coverage, Δ ranges from −0.050 (T1a, T1b) to −0.107 (T2).
    - Every 5% cell is also barred by the 150-session floor (71–127 sessions).
  - Â never exceeds 0.557 at any horizon or coverage. The cheapest definitions need a* of about 0.57–0.58, and T0 / T2 need 0.61–0.65.
  - Model-free per side (c = 100%): put a* is 0.50–0.53 against a down-move base rate of 0.47. Call a* is 0.58–0.64 against an up-move base rate of 0.53.
  - The deadband sensitivity (3 / 5 / 10 bp) changes no ranking.
  - Every definition's mean net per trade is negative at every coverage: −$1.47 to −$16.15.
Step 2 is not run (kill rule), and the holdout stays locked. The remaining options per ADR-0012 Consequences are new data, a defined-risk-structure ADR, or a different strategy class. Each needs an owner decision.

## M19T — Phase 1c defined-risk short premium (ADR-0013, ACCEPTED) — DONE: KILL, FAMILY CLOSED
Depends on: M19S (closed). ADR-0013 is drafted from the owner's 10-point review; n_trials 38 at drafting.
Step 0 (data; no trial):
- [x] Data gap identified. M4 fetched only contracts expiring at D+1 / D+2 (`scripts/m4_fetch_history.py`), so expiry-day (0DTE) quotes are not on disk. Both tenors (S1–S6) need them.
- [x] Price quote: `scripts/m19t_price_gap.py` (price only) → `reports/research/m19t_price_quote.md`
- [x] Owner approval 2026-10-08: everything, with a $20 cap. Downloaded with `scripts/m19t_fetch.py`; the exact total was **$10.18**. Raw files are in `data/raw/databento/m19t/`.
  - **X:** QQQ daily bars 2020–2023, $0.0013.
  - **A:** expiry-day contracts for the development period, 757 sessions, $5.08.
  - **H:** holdout-period storage, 126 sessions, $1.21. Locked.
  - **E:** the 2020–2023 extension, 628 sessions with listed contracts, $3.89.
    - 186 sessions had no listed contracts expiring on D or D+1. Those are not trading days for this family, and they are logged, not filled.
    - **Expirations, inferred from listings:** Fridays only from 2020-01 to about 2021-04, then Mon/Wed/Fri until 2022-11-13, then daily. ADR-0013 D2 era reporting is updated to 3 eras (reporting only).
    - Databento flagged 3 extension days as degraded (2021-07-07, 2021-10-26, 2022-09-19). They are to be checked during cleaning.
  - **F:** forward collection, approved at about $0.64 a month. Its script is still to be written.
- [x] Data converted and cleaned (2026-10-08). Built by `scripts/m19t_build_data.py`, with parameters in `configs/m19t_step0.yaml`.
  - **Separate raw store** `data/raw/m19t/`, cleaned into `data/clean/m19t/`. Earlier scripts read every definition file in the M4 store, so sharing it would have changed the M5–M19S inputs.
  - Cleaning uses the M4 functions unchanged (`build_definitions`, `clean_option_quotes`, DQ rules v2).
  - Every rejected record is stored with its reasons. A per-session log is in `dq_log.parquet`.
  - Raw = cleaned + rejected is asserted for all 1,511 session files, holdout included. The holdout is stored and cleaned only; nothing is reported on it.
  - The QQQ daily bars are ingested but not cleaned (download band only).
- [x] Coverage verified: `scripts/m19t_coverage.py` → `reports/research/m19t_data_coverage.md`.
  - The report covers development sessions only; its loader refuses holdout sessions.
  - It uses entry-time quotes and quote availability only. **No P&L or outcome was computed, and no trial was registered (n_trials 38).**
  - Tests first: `tests/test_spread_coverage.py` (9 tests) covers `validation/spread_coverage.py` (credit-fraction pick, grid holes, longest quote gap).
  - **Sessions.** 0DTE: 1,163 development sessions, 813 of them from 2023. 1DTE: 1,166, of which 814 from 2023. The D4 guards (≥ 300 total, ≥ 150 from 2023) are met.
  - **Eras, from the listings:** Friday-only until 2021-05-04, Mon/Wed/Fri from 2021-05-05, Tue/Thu (daily) from 2022-11-17.
  - **Cleaning.** Development rejection rate is 0.00–0.06% per year (8,112 records, all `BID_GT_ASK`; 18 of them are also `NONPOSITIVE_PRICE`).
  - **Credit rule (D1.a).** It is resolvable without spot. AT_BAND_EDGE is 0% in every cell, with ≥ 9 stored strikes beyond the long leg at p5. NO_QUALIFYING is 0.03–3.6%.
  - **Expiry-day exit.** 0DTE picked legs: 100% have a usable 15:50 ask. 1DTE: 99.2–99.7%. Path gaps over 5 min occur in 0–2.4% of picks.
  - **Degraded days.** 2021-07-07, 2021-10-26 and 2022-09-19 show full minute coverage, no gaps, no rejections and the same contract counts as their neighbours.
    - The median spread on 07-07 and 09-19 is the highest in each 11-session window ($0.37 vs $0.14–0.31; $0.15 vs $0.03–0.15). Owner decision pending (see ADR-0013, Step-0 results).
  - **Gaps found (no new download made):**
    - **2023-12-28 has no 0DTE data.** Its contracts carry OCC-adjusted strikes (#53847), and only whole-dollar symbols were requested.
    - **Adjusted 1DTE exit legs are not stored** for 324 picked entries in 11 sessions, 2023-12 to 2024-02.
    - **$1 grid holes** lie within 3 strikes of the pair in 13–14% of Mon/Wed/Fri-era picks. Elsewhere it is 0.5–2.7%.
- [x] Rerun from committed code 3d134c9 (2026-10-08). Results are identical: the report body is unchanged and only its header moved to 3d134c9. The earlier run on uncommitted code (header 6bb890b) is superseded.
  - 7 datasets registered in `dataset_versions`: 5 raw folders plus cleaned 0dte and ext, all new rows.
  - CI green on 3d134c9: https://github.com/ahmedyaqubi/Main/actions/runs/37829299298
- [x] **ADR-0013 ACCEPTED (owner, 2026-10-08)**, with resolutions R1–R5. The disclosure says they were chosen after seeing coverage numbers, never outcomes.
  - **R1:** §4.9 gates act after selection, with no fallback. The min-bid gate applies to the short leg only.
  - **R2:** a pair whose long strike is not listed is ineligible. Adjusted strikes count like standard ones.
  - **R3:** OCC #53847 supplement.
    - Downloaded with `scripts/m19t_fetch_adjusted.py`: **$0.0804** (owner cap $20), 52 files for 26 expiry sessions, 2023-12-28 → 2026-01-16. 2 requests had no listed symbols.
    - After the rebuild, **2023-12-28 has 0DTE data**. 0DTE sessions: 1,164, of which 814 from 2023.
    - **All 324 adjusted 1DTE exit legs are now stored.** Daily-era 1DTE exit usable: 99.75–100%.
    - The rebuild groups a session's main and adjusted files before cleaning.
  - **R4:** the degraded days are kept, flagged `VENDOR_DEGRADED` (`configs/m19t_step0.yaml`), with a descriptive with/without row.
  - **R5:** `configs/reference/qqq_ex_dividends.csv`, built by `scripts/m19t_ex_dividends.py` with `core/dividends.py` and `tests/test_dividends.py` (4 tests).
    - All 27 regular ex-dates for 2020 → 2026-09 in the Nasdaq history equal the trust's N-30B-2 rule (first business day after the third Friday of Mar/Jun/Sep/Dec).
    - The special dividend (ex-date 2023-12-27) was declared on 2023-12-26.
    - Spend for M19T so far: $10.18 + $0.08 = **$10.26**.
  - **Incident:** the rebuild that tested the supplement ran on uncommitted code. Blanking `DATABASE_URL` in PowerShell deleted the variable, so `.env` supplied it again.
    - 3 `dataset_versions` rows were written with `code_commit` `4e42f43…-dirty`: raw 0dte cbbo `15d2aa19`, raw 0dte definition `9d23cd54`, cleaned 0dte `2d647210`.
    - Owner approved deleting them (2026-10-08). The 3 rows were deleted after confirming that nothing referenced them. They are re-registered by the rerun from the commit below.
- [x] Step 0 rerun from committed code 9619908: the report body is identical. All M19T `dataset_versions` rows carry clean commits. CI green on 9619908: https://github.com/ahmedyaqubi/Main/actions/runs/37845683116
- [x] Step 1 plan approved (2026-10-08). **Owner decision: a condor is both sides or NO_TRADE (`CONDOR_SIDE_MISSING`).**
- [x] Step 1 code, tests first:
  - **Config:** `study_1c` in `configs/phase1.yaml` (cells S1–S6, D3 levels, D4 guards, eras, R4 days, R5 file, budget).
  - **Engine:** `execution_sim/spreads.py` (the frozen D1.a rule, moved from `validation/spread_coverage.py`).
    - `labels/spread.py` covers: open (R1 gates after selection, no fallback, min-bid on short legs only; R2), close (D1.c), costs per leg, max risk, `ex_div_span` (D1.d) and `quote_at`.
    - `selection.liquidity_failures(check_min_bid=...)`: the default keeps Phase 1 unchanged.
  - **Screen:** `backtesting/premium_screen.py` (D3/D4).
  - **Scripts:** `scripts/m19t_build_labels.py`, which registers only from committed code and the full range, and `scripts/m19t_step1.py`.
    - The screen script registers before computing.
    - Its `--dry-run-labels` mode was checked on synthetic random-P&L labels only. No real outcome was read before the registered run.
  - **Tests:** `tests/test_spread_labels.py` (18), `tests/test_premium_screen.py` (8).
  - **Leakage review**, both findings fixed (tests first):
    - `AT_BAND_EDGE` picks are now NO_TRADE: the stored strike band was chosen with the session's full-day range.
    - `quote_at` breaks a duplicate-timestamp tie deterministically, toward the rejected copy.
- [x] **Fix after the first label-build attempt on 369b48b** (it crashed; nothing was registered).
  - Ext sessions 2021-02-09 and 2021-02-10 have definitions but **zero quote records** (vendor gap; `dq_log` n_raw = 0).
  - Their entries are now `UNRESOLVED_DATA` (`ENTRY_DATA_MISSING` / `EXIT_DATA_MISSING`): logged, never filled.
  - The Step-0 coverage report had counted those cells as NO_QUALIFYING.
- [x] **Step 1 run from committed code 8b86c35 (2026-10-08): family outcome KILL. Every cell is KILL. Per ADR-0013 D3, the defined-risk short-premium family is CLOSED.**
  - **Labels:** `scripts/m19t_build_labels.py --register`, registered as label dataset `data/labels/study1c`. 11,640 entry rows per 0DTE cell, 21,964 per 1DTE cell.
  - **Screen:** registered run `screen_1c-9c607f3c96e7` (n_trials 38 → 39) → `reports/research/m19t_step1_screen.md`. It was not rerun, because a rerun would be a second trial.
  - **Results:** mean net per session at the conservative fill [95% CI], and the two-sided 95% upper bound at the mid fill (KILL needs < 0):

    | cell | sessions | mean net (cons) [95% CI] | mid upper bound |
    |---|---|---|---|
    | S1 | 1,155 | −$14.30 [−17.48, −11.19] | −0.55 |
    | S2 | 1,153 | −$24.98 [−29.15, −21.03] | −0.74 |
    | S3 | 1,153 | −$26.35 [−29.52, −22.95] | −3.84 |
    | S4 | 1,143 | −$19.92 [−24.26, −15.90] | −1.21 |
    | S5 | 1,142 | −$33.65 [−39.01, −28.60] | −1.23 |
    | S6 | 1,115 | −$36.29 [−41.11, −31.68] | −5.38 |

    - No cell is barred by a guard, and none is era-driven. All 3 eras are negative at the conservative fill in every cell.
    - The R4 with/without-degraded-days rows are unchanged to within $0.06.
  - **Descriptive reading (not a further test):** in every cell the realized loss share is well above the break-even loss share on the same trades.
    - For example, S1 has a loss share of 0.329 against a break-even of 0.186, and S4 0.291 against 0.135.
    - The losses are large relative to the credits, so the premium collected did not cover the tail.
    - Even at the mid fill the mean is negative in every cell after the $2.80–$5.60 round-trip costs.
  - **Verification:**
    - 18 sampled OK trades (3 per cell) were recomputed by hand from the cleaned quotes, independently of `labels.spread`: 0 mismatches.
    - The holdout was not read (`HoldoutGuard`; the loader refuses those sessions).
  - CI green on 369b48b (https://github.com/ahmedyaqubi/Main/actions/runs/37850595475) and on 8b86c35 (https://github.com/ahmedyaqubi/Main/actions/runs/37850845520).
  - **Family ledger (ADR-0013 D6):** budget 2 trials (screen plus one re-screen). Spent 1. Remaining: 0. A KILL forbids the re-screen, and the family is closed.
    - Holdout access: none. Data spend: $10.26.
    - n_trials on the shared window is now **39**. That raises the bar for any later family.

## M23 — Phase 2: SPX longer-dated defined-risk premium (ADR-0014, ACCEPTED) — STEP 0 IN PROGRESS
Depends on: Phase 1 closed (`reports/research/phase1_synthesis.md`). ADR-0014 accepted 2026-10-08 with R1–R9. Budget: 1 screen + at most 1 re-screen. n_trials is reported next to Phase 1's 39.
Step 0 (data; no trial):
- [x] **Coverage and price checks (2026-10-08/09), all free unless stated:**
  - **Databento OPRA.PILLAR:** SPX, SPXW and XSP are covered from 2013-04-01 (definitions and cbbo-1m).
  - **Cboe daily SPX history (R6):** free, closes only, 1975 → present. The download band uses the previous close, not a same-day range.
  - **Listing universe:** from free symbology resolution: 1,050,018 SPX/SPXW contracts and 569,158 SPY contracts.
  - **Price quotes (`scripts/m23_price_gap.py`, 1-in-19 weekday-balanced sample):** SPX full scope ≈ $10.54 (`reports/research/m23_price_quote.md`); SPY ≈ $5.90 (`m23_price_quote_spy.md`).
    - Corrected during the session: a 1-in-20 sample was weekday-biased, and the holdout boundary was first printed with Phase 1's 6 months instead of 12.
  - **SPX vs SPY comparison sample:** $0.0659, owner approved (`scripts/m23_compare_sample.py`, `reports/research/m23_spx_vs_spy.md`). **Owner chose SPX (R1 confirmed).**
- [ ] Cboe SPX index-option fee (R3) fetched with its source
- [ ] Owner approves the exact quote (cap $50, R8); then download, clean (M4 rules extended to SPX roots), and write a coverage report with the minimum detectable effect per cell (R5)
- [ ] Owner supplies the broker SPX commission (R3)

## M20 — Live market data in PAPER mode — NOT STARTED (Phase 1 closed; blocked by M19 FAIL)
Depends on: M19 PASS (or owner ADR)
Acceptance:
- [ ] Live feed adapter implements the `AsOfReader` interface; market-data permissions only. **No order API anywhere** (T-SAFE-01)
- [ ] The full 12-step loop (Phase 1T) runs at every scheduled timestamp; DQ failures produce NO_TRADE with a reason
- [ ] Live-vs-replay check: one recorded live day replayed offline reproduces the decisions

## M21 — Live paper validation — NOT STARTED (Phase 1 closed; blocked by M19 FAIL)
Depends on: M20
Acceptance:
- [ ] Gates 19–20: ≥ 60 sessions and ≥ 100 paper trades; ECE ≤ 0.05; slippage vs model; PSI ≤ 0.2
- [ ] Weekly paper report with sample sizes and CIs; drift status
- [ ] Moderate-fill α re-estimated from paper quotes; any change via ADR (does not retroactively alter M19 results)

## M22 — Dashboard — NOT STARTED (Phase 1 closed; blocked by M19 FAIL)
Depends on: M21 (engine stable)
Acceptance:
- [ ] Read-only view over the journal/monitoring; shows every Phase 1U field, including sample size, CI, and NO_TRADE reason
- [ ] Never displays a raw score labelled as probability (test on rendering layer)
- [ ] No controls that place or route orders

## Later (out-of-scope ideas parked here)
- **SPY 0DTE/1DTE short premium (owner question, 2026-10-09): parked.**
  - Why: M19T lost even at the mid fill after commissions. SPY's tighter spreads can't beat the mid, and commissions and credits match QQQ's.
  - No untouched SPY daily-expiry history exists: daily expirations only began in late 2022, inside the window already used.
  - Revisit only if M23 finds a premium at longer tenors. Then: one pre-registered trial on forward data.
- **Full strike-band tick NBBO for the M2 sample week (owner note, 2026-10-05).** Re-pull `cmbp-1` for 2025-03-11→14 over the full band (D+1/D+2 expiries, 424 contracts/day): priced at $11.20, ~75 GB uncompressed / ~25 GB on disk. Run `uv run python scripts/m2_fetch_sample.py --days <day> --download` one day per run (each day can exceed 1 h at slow transfer rates), or use Databento's batch API. Useful if later work (fill modelling in M12, quote-age/latency studies) needs tick data beyond ATM ± 5.
- Overnight-hold variant of 1DTE (if OD-2 = intraday-only), with gap/theta/assignment labels
- Extending Stage 1 history before 2022-11 (OD-1 option b)
- Size/spread-dependent fill-probability model fit on paper data
- Delta-targeted selection rule as a pre-registered alternative experiment (OD-3)
- Breadth features if a reliable point-in-time intraday source exists
- Direction-aware trend regime axis (e.g. sign of the 20-session move × efficiency ratio); EXTREME volatility bucket once it has ≥ 30 training sessions (M14)
- Post-M19R follow-ups (see `reports/research/m19r_closing.md` §5; each needs owner approval):
  - a new data source (historical OI, volume and trade prints), after verifying coverage and cost;
  - a trade-definition ADR declaring a small set of definitions and a trial budget before any run;
  - a different strategy class (for example, premium selling), as a separate project
