# Architecture — QQQ 1DTE Research & Validation Engine

**Status: v1.0 (M1, accepted 2026-10-05).** Companion to `PHASE_1_SPEC.md`.

## 1. In one paragraph

The system is an evidence pipeline, not a trader. Raw market and options data are ingested
unchanged. They are validated into clean, versioned datasets, with every rejection logged. A
point-in-time reader exposes the data "as of T" to the feature engine. A separate label engine,
the only component allowed to look forward, creates outcome labels. Models (baseline →
logistic → GBM) learn Stage 1, which predicts underlying behaviour, in chronological
walk-forward folds. Their scores are calibrated on held-out blocks. Stage 2 picks one option
mechanically from the chain as it existed at entry time and simulates execution against
bid/ask under three fill models. A decision engine outputs CALL / PUT / NO_TRADE. Every
prediction, decision, and simulated trade is journaled with the dataset, feature, model,
calibration, and code versions, so any result can be replayed exactly. Regimes, drift, and the
Phase 1V gates are evaluated on that journal. Nothing ever sends an order.

## 2. Modules (`src/qqq1dte/`)

| Module | Responsibility | May read | Must never |
|---|---|---|---|
| `core/` | XNYS calendar, session times, 1DTE expiry resolution, UTC↔ET, config loading/hashing, **`AsOfReader`** (PIT gate), `Clock` | config | depend on any other qqq1dte module |
| `ingestion/` | pull vendor data → `raw_*` Parquet, unchanged, with provenance | vendor APIs (historical/market-data only) | transform values; call order APIs |
| `validation/` | QA/QC checks → `cleaned_*` + `data_quality_events`; DQ report | raw | silently fill/drop |
| `features/` | feature functions over an `AsOfView`; writes `feature_snapshots` | `core.AsOfReader` only | import `labels`; read Parquet directly |
| `labels/` | A/B/C/D labels from forward windows | cleaned data via `core.ForwardWindowReader` | be imported by `features`, `models` at inference, `execution_sim` decision path |
| `models/` | Model 0/1/2, training per fold, serialization | feature_snapshots, labels (training only) | see test-period data while fitting |
| `calibration/` | Platt / isotonic / temperature on calibration blocks; reliability metrics | OOS raw scores + labels | fit on training-fold predictions |
| `regimes/` | regime labels at T; per-regime evaluation | AsOfReader; fold-fit thresholds | fit thresholds on test data |
| `execution_sim/` | frozen option-selection rule; fill models; cost model | AsOfReader (chain at `T_e`); quote stream after entry via monotonic cursor | look at quotes ahead of the simulated clock |
| `backtesting/` | event-driven loop, walk-forward orchestration, metrics, run registry | everything above, through their APIs | run without a registered `run_id`; touch the final holdout without logging |
| `journal/` | write predictions / candidates / trades to Postgres; replay | — | update or delete journal rows (append-only) |
| `monitoring/` | drift (PSI, rolling calibration, expectancy), gate evaluation | journal | promote models automatically |

Not in Phase 1 at all: `dashboard/` (M22 only), and any broker order API anywhere in the code.
A CI grep test (T-SAFE-01) fails the build if order-placement identifiers show up (e.g.
`placeOrder`, `submit_order`).

## 3. Data flow

```
vendor ──ingestion──► raw_market_data / raw_options_data (Parquet, immutable, + provenance)
                          │
                     validation ──► data_quality_events (Postgres)
                          ▼
             cleaned_market_data / cleaned_options_data (Parquet, versioned dataset_id)
                 │                                   │
        core.AsOfReader(T)                  core.ForwardWindowReader(T, T_end)
                 │                                   │
             features ──► feature_snapshots      labels ──► labels store (Parquet)
                 │            (available_at ≤ T)            │
                 └────────────┬─────────────────────────────┘
                              ▼
        backtesting.walk_forward (folds, purge/embargo, run registry)
           ├─ models.fit(train)          → model_versions
           ├─ calibration.fit(calib)     → calibration_results
           └─ for each T in test, event loop with Clock:
                regimes.at(T) → models.predict → calibration.apply
                → decision engine (CALL/PUT/NO_TRADE)
                → execution_sim.select(chain @ T_e) → trade_candidates
                → execution_sim.simulate(quote cursor > T_e) → simulated_trades
                → journal (predictions, candidates, trades)
                              ▼
          monitoring / reports / Phase 1V gate evaluation → validation_runs
```

The live paper system (M20) reuses exactly the same path. Only the reader is swapped for a
live feed adapter that implements the same `AsOfReader` interface, and `Clock` is wall time.

## 4. Where point-in-time enforcement lives in code

Rule 2 is enforced by four mechanisms, so it doesn't depend on discipline:

1. **`core.pit.AsOfReader`** is the only object `features/`, `regimes/`, and `execution_sim/`
   receive. It is constructed with a cutoff `T` and every query filters `available_at <= T`.
   A request for a timestamp after `T` raises `LookAheadError`. It does not clip silently.
   The underlying Parquet paths are not exposed.
2. **Stamping and assertion at write time.** `features` returns rows with
   `available_at = max(available_at of all inputs)`. `feature_snapshots` writers assert
   `available_at <= prediction_ts` for every row and refuse the write otherwise. A Postgres
   `CHECK` constraint repeats the check on the stored row (schema draft).
3. **A monotonic simulation clock.** `execution_sim` reads post-entry quotes through a cursor
   tied to `backtesting.Clock`. The cursor can only advance, and it returns quotes with
   timestamp ≤ the current clock. The clock only moves forward.
4. **Import contracts in CI** (`import-linter`, added in M5): `features`, `regimes`, `models`
   (inference path), and `execution_sim.select` may not import `labels`. Only `labels` may
   construct a `ForwardWindowReader`.

Leakage tests (see `TEST_PLAN.md`, T-LEAK-*) attack each of these mechanisms with planted
future data.

## 5. Storage split

- **Parquet** (large, append-only, partitioned by `instrument/date`): raw_*, cleaned_*,
  feature_snapshots (also catalogued in Postgres), labels. Every dataset version is immutable
  and identified by a content hash (`dataset_id`).
- **PostgreSQL**: metadata, catalogue, DQ events, predictions, candidates, trades, models,
  calibrations, runs, regimes, audit logs. See `SCHEMA.md`.

## 6. Versioning tuple (attached to every prediction)

`(dataset_id, feature_version, label_version, model_version_id, calibration_version_id,
config_hash, code_commit)`. Given that tuple, `journal.replay(prediction_id)` must reproduce
the prediction (gate 17).

## 7. Configuration

`configs/phase1.yaml` holds every parameter named in the spec. The loader validates it, and its
canonical-JSON SHA-256 is the `config_hash`. Experiment overrides are separate files and are
hashed the same way. Code never hard-codes trading parameters.
