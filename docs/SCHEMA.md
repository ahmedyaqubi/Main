# Database / Dataset Schema

**Status: v1.0, approved by the owner 2026-10-05 (M3).** Implemented by the Alembic migrations in
`migrations/`. Changes after this point need an ADR.

Conventions: every timestamp is `TIMESTAMPTZ` stored in UTC. `*_ts` is an event time and
`available_at` is when the information became knowable. `ingested_at` is wall-clock load time.
Every row carries provenance (`source`, `dataset_id` or `run_id`). Journal tables are
**append-only**: a DB role without UPDATE/DELETE rights does the writing.

## A. Parquet datasets (large), with Postgres catalogue

Every dataset version is immutable and catalogued in `dataset_versions`.

### 1–2. Raw layer: raw_market_data / raw_options_data (v1.0, Databento)
The raw layer stores vendor data **unchanged**, in two forms:

1. **Original files**: `data/raw/files/<raw_file_id>.dbn.zst`, byte-identical to the
   download, where `raw_file_id` = SHA-256 of the file bytes. Never modified or deleted.
2. **Decoded Parquet**: `data/raw/parquet/<vendor_dataset>/<schema>/date=<YYYY-MM-DD>/<raw_file_id>.parquet`,
   one file per original file. Every DBN record field is kept as delivered:
   - timestamps (`ts_recv`, `ts_event`, …) as **uint64 ns since epoch, UTC**, the vendor's type (no conversion);
   - prices (`price`, `bid_px_00`, `open`, …) as **int64 fixed-point, 1e-9 units**, with the
     vendor's undefined sentinel (`INT64_MAX`) kept, not turned into null;
   - all other fields with the decoder's native types (single-character fields such as
     `side`/`action` as 1-char strings; the DBN framing field `length` is not stored);
   - `symbol` (vendor raw symbol mapped by the decoder) added for readability.

   Plus provenance columns: `source` (`databento`), `vendor_dataset` (e.g. `OPRA.PILLAR`),
   `schema` (e.g. `cbbo-1m`), `raw_file_id`, `ingested_at` (UTC wall clock).

`raw_market_data` = equity/futures datasets (`EQUS.MINI`, `GLBX.MDP3`, …).
`raw_options_data` = `OPRA.PILLAR` schemas. Columns differ by schema, so each
(vendor_dataset, schema) pair is its own Parquet dataset. The partition `date` is the UTC date
of the file's requested start (DBN metadata).

Conventions learned in M2 (applied in the cleaned layer, M4, not here): `ohlcv-*` bars are
stamped at bar **start** (`available_at = ts_event + interval`); `cbbo-*`/`bbo-*` `ts_recv` is
the interval **end** (`available_at = ts_recv`); OI arrives in `statistics` (stat_type 9) at
~06:30 ET. Databento supplies no IV/Greeks; those are computed in-house (OD-7).

**`dataset_id`** = SHA-256 of canonical JSON `{kind, vendor_dataset, schema, raw_file_ids
(sorted), raw_format_version}`. It does **not** include `ingested_at` or the code commit
(recorded separately in `dataset_versions`), so re-ingesting identical files yields the same
`dataset_id` and writes no duplicate rows.

### 3. cleaned_market_data (Parquet)
raw columns + `available_at`, `session_date` (ET), `is_rth`, `is_early_close`, `dq_status`
(`OK`/`FLAGGED`), `dataset_id`. Rejected rows are **not present** here. Their reasons live in
`data_quality_events`.

### 4. cleaned_options_data (Parquet)
raw columns + `available_at`, `session_date`, `mid`, `spread`, `spread_pct`, `is_1dte` (per
spec §1.2 at that session), `dq_status`, `dataset_id`.

### 5. feature_snapshots (Parquet, catalogued in Postgres)
| column | type | note |
|---|---|---|
| snapshot_id | uuid | |
| prediction_ts | timestamp[UTC] | T |
| feature_name | str | long format; a wide view is materialised per feature_version |
| value | float64 | nullable; nulls are explicit with `missing_reason` |
| missing_reason | str | nullable |
| available_at | timestamp[UTC] | **must be ≤ prediction_ts** (writer asserts) |
| feature_version | str | |
| dataset_id | str | |

Labels (Parquet, not one of the 13 required tables but needed): `prediction_ts, label_id
(A_up…D_put), variant, value, outcome_class, t_end, ambiguous_bar, label_version, dataset_id`.

## B. PostgreSQL tables

```sql
-- catalogue / provenance -------------------------------------------------------
CREATE TABLE dataset_versions (
  dataset_id        TEXT PRIMARY KEY,           -- content hash
  kind              TEXT NOT NULL,              -- raw_market | raw_options | cleaned_* | features | labels
  parent_ids        TEXT[] NOT NULL DEFAULT '{}',
  source            TEXT NOT NULL,
  coverage_start    DATE NOT NULL,
  coverage_end      DATE NOT NULL,
  row_count         BIGINT NOT NULL,
  storage_uri       TEXT NOT NULL,
  code_commit       TEXT NOT NULL,
  config_hash       TEXT NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 13. data_quality_events ------------------------------------------------------
CREATE TABLE data_quality_events (
  event_id          BIGSERIAL PRIMARY KEY,
  dataset_id        TEXT REFERENCES dataset_versions,
  check_name        TEXT NOT NULL,               -- e.g. BID_GT_ASK, DUP_RECORD, MISSING_BAR
  severity          TEXT NOT NULL CHECK (severity IN ('INFO','WARN','CRITICAL')),
  instrument        TEXT,
  contract          TEXT,                        -- OCC symbol when relevant
  record_ts         TIMESTAMPTZ,
  session_date      DATE,
  action            TEXT NOT NULL CHECK (action IN ('REJECTED','FLAGGED','NONE')),
  reason            TEXT NOT NULL,
  details           JSONB,
  resolved_by_adr   TEXT,                        -- set only by an explicit acceptance
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 9. model_versions ------------------------------------------------------------
CREATE TABLE model_versions (
  model_version_id  TEXT PRIMARY KEY,
  model_family      TEXT NOT NULL,               -- baseline | logreg | lgbm
  target_label      TEXT NOT NULL,               -- e.g. C_call
  train_start       DATE NOT NULL,
  train_end         DATE NOT NULL,
  dataset_id        TEXT NOT NULL REFERENCES dataset_versions,
  feature_version   TEXT NOT NULL,
  label_version     TEXT NOT NULL,
  hyperparameters   JSONB NOT NULL,
  artifact_uri      TEXT NOT NULL,
  artifact_sha256   TEXT NOT NULL,
  code_commit       TEXT NOT NULL,
  config_hash       TEXT NOT NULL,
  status            TEXT NOT NULL CHECK (status IN ('CANDIDATE','PRODUCTION','RETIRED','REJECTED')),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- at most one PRODUCTION per target_label; status changes only via model_promotions
CREATE UNIQUE INDEX one_production ON model_versions(target_label) WHERE status = 'PRODUCTION';

CREATE TABLE model_promotions (
  promotion_id      BIGSERIAL PRIMARY KEY,
  from_model_id     TEXT REFERENCES model_versions,
  to_model_id       TEXT NOT NULL REFERENCES model_versions,
  gate_results      JSONB NOT NULL,
  decision          TEXT NOT NULL CHECK (decision IN ('PROMOTED','KEEP_CURRENT')),
  approved_by       TEXT NOT NULL,               -- a human, never automatic
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 10. calibration_results -------------------------------------------------------
CREATE TABLE calibration_results (
  calibration_version_id TEXT PRIMARY KEY,
  model_version_id  TEXT NOT NULL REFERENCES model_versions,
  method            TEXT NOT NULL CHECK (method IN ('platt','isotonic','temperature','none')),
  calib_start       DATE NOT NULL,
  calib_end         DATE NOT NULL,
  eval_start        DATE NOT NULL,
  eval_end          DATE NOT NULL,
  n_calib           INT NOT NULL,
  n_eval            INT NOT NULL,
  brier             DOUBLE PRECISION, log_loss DOUBLE PRECISION, ece DOUBLE PRECISION,
  slope             DOUBLE PRECISION, intercept DOUBLE PRECISION,
  reliability_bins  JSONB NOT NULL,              -- [{lo,hi,n,mean_pred,obs_rate,wilson_lo,wilson_hi}]
  artifact_uri      TEXT NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (calib_end < eval_start)
);

-- 11. validation_runs (also the multiple-testing registry) ----------------------
CREATE TABLE validation_runs (
  run_id            TEXT PRIMARY KEY,
  config_hash       TEXT NOT NULL,
  config_json       JSONB NOT NULL,
  run_kind          TEXT NOT NULL,               -- walk_forward | backtest | calibration | paper
  data_window_start DATE NOT NULL,
  data_window_end   DATE NOT NULL,
  touches_final_holdout BOOLEAN NOT NULL DEFAULT false,
  dataset_id        TEXT NOT NULL REFERENCES dataset_versions,
  code_commit       TEXT NOT NULL,
  folds             JSONB NOT NULL,              -- [{train,calib,test,embargo}]
  metrics           JSONB,                       -- filled at completion; null = crashed/aborted (still counts as a trial)
  status            TEXT NOT NULL CHECK (status IN ('REGISTERED','COMPLETED','FAILED','ABORTED')),
  started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at       TIMESTAMPTZ
);

CREATE TABLE final_test_access_log (
  access_id         BIGSERIAL PRIMARY KEY,
  run_id            TEXT NOT NULL REFERENCES validation_runs,
  justification     TEXT NOT NULL,
  adr_ref           TEXT,                        -- required for any access after the first
  accessed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 12. regime_labels --------------------------------------------------------------
CREATE TABLE regime_labels (
  ts                TIMESTAMPTZ NOT NULL,        -- prediction_ts (or session for daily regimes)
  axis              TEXT NOT NULL,               -- VOL | TREND | EVENT | STRUCTURE
  value             TEXT NOT NULL,
  available_at      TIMESTAMPTZ NOT NULL,
  thresholds_fit_run TEXT REFERENCES validation_runs, -- which fold fitted the cut points
  regime_version    TEXT NOT NULL,
  PRIMARY KEY (ts, axis, regime_version),
  CHECK (available_at <= ts)
);

-- 6. predictions (journal, append-only) -----------------------------------------
CREATE TABLE predictions (
  prediction_id     UUID PRIMARY KEY,
  run_id            TEXT NOT NULL REFERENCES validation_runs,
  prediction_ts     TIMESTAMPTZ NOT NULL,
  mode              TEXT NOT NULL CHECK (mode IN ('BACKTEST','PAPER')),
  underlying_price  DOUBLE PRECISION NOT NULL,
  chain_snapshot_ref TEXT,                       -- dataset_id + snapshot ts
  feature_snapshot_ref TEXT NOT NULL,
  feature_version   TEXT NOT NULL,
  max_feature_available_at TIMESTAMPTZ NOT NULL,
  regime            JSONB NOT NULL,
  model_version_id  TEXT NOT NULL REFERENCES model_versions,
  calibration_version_id TEXT REFERENCES calibration_results,  -- null ⇒ uncalibrated ⇒ decision must be NO_TRADE
  raw_scores        JSONB NOT NULL,              -- {"C_call": 0.61, ...} — named *score*, not probability
  calibrated_probs  JSONB,
  support_n         JSONB,                       -- comparable historical n per output + CI
  decision          TEXT NOT NULL CHECK (decision IN ('CALL','PUT','NO_TRADE','BLOCKED_POSITION_OPEN')),
  decision_reasons  TEXT[] NOT NULL,
  expected_value    JSONB,                       -- per side, per fill model
  config_hash       TEXT NOT NULL,
  code_commit       TEXT NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (max_feature_available_at <= prediction_ts),
  CHECK (decision = 'NO_TRADE' OR decision = 'BLOCKED_POSITION_OPEN' OR calibration_version_id IS NOT NULL)
);
CREATE INDEX ON predictions (prediction_ts);

-- 7. trade_candidates --------------------------------------------------------------
CREATE TABLE trade_candidates (
  candidate_id      UUID PRIMARY KEY,
  prediction_id     UUID NOT NULL REFERENCES predictions,
  side              TEXT NOT NULL CHECK (side IN ('CALL','PUT')),
  occ_symbol        TEXT,                        -- null if no contract resolvable
  expiration        DATE, strike NUMERIC(10,3),
  quote_ts          TIMESTAMPTZ,
  bid DOUBLE PRECISION, ask DOUBLE PRECISION, bid_size INT, ask_size INT,
  computed_iv DOUBLE PRECISION, computed_delta DOUBLE PRECISION,
  passed_gates      BOOLEAN NOT NULL,
  gate_failures     TEXT[] NOT NULL DEFAULT '{}',
  selection_rule_version TEXT NOT NULL,
  selected          BOOLEAN NOT NULL
  -- PIT rule quote_ts <= prediction_ts + latency spans tables: enforced by trigger, see note
);

-- 8. simulated_trades -------------------------------------------------------------
CREATE TABLE simulated_trades (
  trade_id          UUID PRIMARY KEY,
  candidate_id      UUID NOT NULL REFERENCES trade_candidates,
  fill_model        TEXT NOT NULL CHECK (fill_model IN ('CONSERVATIVE','MODERATE','OPTIMISTIC')),
  entry_ts          TIMESTAMPTZ, entry_price DOUBLE PRECISION,
  exit_ts           TIMESTAMPTZ, exit_price DOUBLE PRECISION,
  target_price DOUBLE PRECISION, stop_price DOUBLE PRECISION,
  outcome           TEXT NOT NULL CHECK (outcome IN ('WIN','LOSS','BREAKEVEN','TIME_EXIT_PROFIT',
                         'TIME_EXIT_LOSS','EXPIRED','UNFILLED','UNRESOLVED_DATA')),
  exit_reason       TEXT,
  ambiguous_bar     BOOLEAN NOT NULL DEFAULT false,
  mfe DOUBLE PRECISION, mae DOUBLE PRECISION,
  gross_pnl DOUBLE PRECISION, commissions DOUBLE PRECISION, fees DOUBLE PRECISION,
  spread_cost DOUBLE PRECISION, slippage DOUBLE PRECISION, net_pnl DOUBLE PRECISION,
  r_multiple DOUBLE PRECISION, holding_seconds INT,
  CHECK (exit_ts IS NULL OR exit_ts > entry_ts),
  UNIQUE (candidate_id, fill_model)
);
```

**Implementation notes (migration `0001`, M3):**
- `trade_candidates` has `latency_s INT NOT NULL`. A `BEFORE INSERT` trigger rejects any candidate
  whose `quote_ts` is later than its prediction's `prediction_ts + latency_s` (spec §5 point-in-time
  rule, which spans two tables, so a CHECK can't express it).
- Append-only journal: triggers on `predictions`, `trade_candidates`, `simulated_trades` reject every
  UPDATE, DELETE and TRUNCATE, for every role including the owner. This replaces the draft's
  "writer role without UPDATE/DELETE rights": creating roles needs `CREATEROLE`, which the
  project user does not have, and triggers also bind the owner.
- Named constraints `features_not_after_prediction` and `trade_requires_calibration` on `predictions`;
  extra sanity CHECKs on date ranges (`coverage_start <= coverage_end`, `train_start <= train_end`)
  and a non-empty `approved_by` for promotions.

## C. Schema decisions (resolved 2026-10-05)
- `predictions`: **one row per timestamp** with JSONB scores per target, so there is exactly one decision per timestamp.
- `feature_snapshots`: **long canonical** Parquet plus a wide materialised table per `feature_version`.
- Partitioning `predictions` by month is deferred to M20 (paper mode).
