"""Initial schema v1.0 (docs/SCHEMA.md §B, approved 2026-10-05).

Revision ID: 0001
Revises:
Create Date: 2026-10-05
"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JOURNAL_TABLES = ("predictions", "trade_candidates", "simulated_trades")

UPGRADE = [
    # catalogue / provenance -----------------------------------------------------------
    """
    CREATE TABLE dataset_versions (
      dataset_id        TEXT PRIMARY KEY,
      kind              TEXT NOT NULL,
      parent_ids        TEXT[] NOT NULL DEFAULT '{}',
      source            TEXT NOT NULL,
      coverage_start    DATE NOT NULL,
      coverage_end      DATE NOT NULL,
      row_count         BIGINT NOT NULL,
      storage_uri       TEXT NOT NULL,
      code_commit       TEXT NOT NULL,
      config_hash       TEXT NOT NULL,
      created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (coverage_start <= coverage_end),
      CHECK (row_count >= 0)
    )
    """,
    """
    CREATE TABLE data_quality_events (
      event_id          BIGSERIAL PRIMARY KEY,
      dataset_id        TEXT REFERENCES dataset_versions,
      check_name        TEXT NOT NULL,
      severity          TEXT NOT NULL CHECK (severity IN ('INFO','WARN','CRITICAL')),
      instrument        TEXT,
      contract          TEXT,
      record_ts         TIMESTAMPTZ,
      session_date      DATE,
      action            TEXT NOT NULL CHECK (action IN ('REJECTED','FLAGGED','NONE')),
      reason            TEXT NOT NULL,
      details           JSONB,
      resolved_by_adr   TEXT,
      created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # models ------------------------------------------------------------------------
    """
    CREATE TABLE model_versions (
      model_version_id  TEXT PRIMARY KEY,
      model_family      TEXT NOT NULL,
      target_label      TEXT NOT NULL,
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
      status            TEXT NOT NULL
                          CHECK (status IN ('CANDIDATE','PRODUCTION','RETIRED','REJECTED')),
      created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (train_start <= train_end)
    )
    """,
    """
    CREATE UNIQUE INDEX one_production ON model_versions (target_label)
      WHERE status = 'PRODUCTION'
    """,
    """
    CREATE TABLE model_promotions (
      promotion_id      BIGSERIAL PRIMARY KEY,
      from_model_id     TEXT REFERENCES model_versions,
      to_model_id       TEXT NOT NULL REFERENCES model_versions,
      gate_results      JSONB NOT NULL,
      decision          TEXT NOT NULL CHECK (decision IN ('PROMOTED','KEEP_CURRENT')),
      approved_by       TEXT NOT NULL CHECK (length(trim(approved_by)) > 0),
      created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
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
      brier             DOUBLE PRECISION,
      log_loss          DOUBLE PRECISION,
      ece               DOUBLE PRECISION,
      slope             DOUBLE PRECISION,
      intercept         DOUBLE PRECISION,
      reliability_bins  JSONB NOT NULL,
      artifact_uri      TEXT NOT NULL,
      created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (calib_end < eval_start)
    )
    """,
    # runs / registry ---------------------------------------------------------------
    """
    CREATE TABLE validation_runs (
      run_id            TEXT PRIMARY KEY,
      config_hash       TEXT NOT NULL,
      config_json       JSONB NOT NULL,
      run_kind          TEXT NOT NULL,
      data_window_start DATE NOT NULL,
      data_window_end   DATE NOT NULL,
      touches_final_holdout BOOLEAN NOT NULL DEFAULT false,
      dataset_id        TEXT NOT NULL REFERENCES dataset_versions,
      code_commit       TEXT NOT NULL,
      folds             JSONB NOT NULL,
      metrics           JSONB,
      status            TEXT NOT NULL
                          CHECK (status IN ('REGISTERED','COMPLETED','FAILED','ABORTED')),
      started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
      finished_at       TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE final_test_access_log (
      access_id         BIGSERIAL PRIMARY KEY,
      run_id            TEXT NOT NULL REFERENCES validation_runs,
      justification     TEXT NOT NULL,
      adr_ref           TEXT,
      accessed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE regime_labels (
      ts                TIMESTAMPTZ NOT NULL,
      axis              TEXT NOT NULL,
      value             TEXT NOT NULL,
      available_at      TIMESTAMPTZ NOT NULL,
      thresholds_fit_run TEXT REFERENCES validation_runs,
      regime_version    TEXT NOT NULL,
      PRIMARY KEY (ts, axis, regime_version),
      CHECK (available_at <= ts)
    )
    """,
    # journal (append-only) ----------------------------------------------------------
    """
    CREATE TABLE predictions (
      prediction_id     UUID PRIMARY KEY,
      run_id            TEXT NOT NULL REFERENCES validation_runs,
      prediction_ts     TIMESTAMPTZ NOT NULL,
      mode              TEXT NOT NULL CHECK (mode IN ('BACKTEST','PAPER')),
      underlying_price  DOUBLE PRECISION NOT NULL,
      chain_snapshot_ref TEXT,
      feature_snapshot_ref TEXT NOT NULL,
      feature_version   TEXT NOT NULL,
      max_feature_available_at TIMESTAMPTZ NOT NULL,
      regime            JSONB NOT NULL,
      model_version_id  TEXT NOT NULL REFERENCES model_versions,
      calibration_version_id TEXT REFERENCES calibration_results,
      raw_scores        JSONB NOT NULL,
      calibrated_probs  JSONB,
      support_n         JSONB,
      decision          TEXT NOT NULL
                          CHECK (decision IN ('CALL','PUT','NO_TRADE','BLOCKED_POSITION_OPEN')),
      decision_reasons  TEXT[] NOT NULL,
      expected_value    JSONB,
      config_hash       TEXT NOT NULL,
      code_commit       TEXT NOT NULL,
      created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT features_not_after_prediction CHECK (max_feature_available_at <= prediction_ts),
      CONSTRAINT trade_requires_calibration CHECK (
        decision IN ('NO_TRADE','BLOCKED_POSITION_OPEN') OR calibration_version_id IS NOT NULL)
    )
    """,
    "CREATE INDEX predictions_ts_idx ON predictions (prediction_ts)",
    """
    CREATE TABLE trade_candidates (
      candidate_id      UUID PRIMARY KEY,
      prediction_id     UUID NOT NULL REFERENCES predictions,
      side              TEXT NOT NULL CHECK (side IN ('CALL','PUT')),
      occ_symbol        TEXT,
      expiration        DATE,
      strike            NUMERIC(10,3),
      quote_ts          TIMESTAMPTZ,
      latency_s         INT NOT NULL CHECK (latency_s >= 0),
      bid               DOUBLE PRECISION,
      ask               DOUBLE PRECISION,
      bid_size          INT,
      ask_size          INT,
      computed_iv       DOUBLE PRECISION,
      computed_delta    DOUBLE PRECISION,
      passed_gates      BOOLEAN NOT NULL,
      gate_failures     TEXT[] NOT NULL DEFAULT '{}',
      selection_rule_version TEXT NOT NULL,
      selected          BOOLEAN NOT NULL
    )
    """,
    # Spec §5: selection may only use quotes available at T_e = prediction_ts + latency.
    """
    CREATE FUNCTION trade_candidates_pit_check() RETURNS trigger AS $$
    DECLARE
      t_pred TIMESTAMPTZ;
    BEGIN
      IF NEW.quote_ts IS NULL THEN
        RETURN NEW;
      END IF;
      SELECT prediction_ts INTO t_pred FROM predictions WHERE prediction_id = NEW.prediction_id;
      IF NEW.quote_ts > t_pred + make_interval(secs => NEW.latency_s) THEN
        RAISE EXCEPTION 'look-ahead: candidate quote_ts % is after prediction_ts % + % s',
          NEW.quote_ts, t_pred, NEW.latency_s
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER trade_candidates_pit
      BEFORE INSERT ON trade_candidates
      FOR EACH ROW EXECUTE FUNCTION trade_candidates_pit_check()
    """,
    """
    CREATE TABLE simulated_trades (
      trade_id          UUID PRIMARY KEY,
      candidate_id      UUID NOT NULL REFERENCES trade_candidates,
      fill_model        TEXT NOT NULL
                          CHECK (fill_model IN ('CONSERVATIVE','MODERATE','OPTIMISTIC')),
      entry_ts          TIMESTAMPTZ,
      entry_price       DOUBLE PRECISION,
      exit_ts           TIMESTAMPTZ,
      exit_price        DOUBLE PRECISION,
      target_price      DOUBLE PRECISION,
      stop_price        DOUBLE PRECISION,
      outcome           TEXT NOT NULL CHECK (outcome IN ('WIN','LOSS','BREAKEVEN',
                          'TIME_EXIT_PROFIT','TIME_EXIT_LOSS','EXPIRED','UNFILLED',
                          'UNRESOLVED_DATA')),
      exit_reason       TEXT,
      ambiguous_bar     BOOLEAN NOT NULL DEFAULT false,
      mfe               DOUBLE PRECISION,
      mae               DOUBLE PRECISION,
      gross_pnl         DOUBLE PRECISION,
      commissions       DOUBLE PRECISION,
      fees              DOUBLE PRECISION,
      spread_cost       DOUBLE PRECISION,
      slippage          DOUBLE PRECISION,
      net_pnl           DOUBLE PRECISION,
      r_multiple        DOUBLE PRECISION,
      holding_seconds   INT,
      CHECK (exit_ts IS NULL OR exit_ts > entry_ts),
      UNIQUE (candidate_id, fill_model)
    )
    """,
    # Append-only journal: reject UPDATE/DELETE for every role (spec Phase 1O).
    """
    CREATE FUNCTION journal_append_only() RETURNS trigger AS $$
    BEGIN
      RAISE EXCEPTION 'journal table % is append-only (% rejected)', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
    END;
    $$ LANGUAGE plpgsql
    """,
    *[
        f"""
        CREATE TRIGGER {t}_append_only
          BEFORE UPDATE OR DELETE ON {t}
          FOR EACH ROW EXECUTE FUNCTION journal_append_only()
        """
        for t in JOURNAL_TABLES
    ],
    *[
        f"""
        CREATE TRIGGER {t}_no_truncate
          BEFORE TRUNCATE ON {t}
          FOR EACH STATEMENT EXECUTE FUNCTION journal_append_only()
        """
        for t in JOURNAL_TABLES
    ],
]

DOWNGRADE = [
    "DROP TABLE simulated_trades",
    "DROP TABLE trade_candidates",
    "DROP FUNCTION trade_candidates_pit_check()",
    "DROP TABLE predictions",
    "DROP FUNCTION journal_append_only()",
    "DROP TABLE regime_labels",
    "DROP TABLE final_test_access_log",
    "DROP TABLE validation_runs",
    "DROP TABLE calibration_results",
    "DROP TABLE model_promotions",
    "DROP TABLE model_versions",
    "DROP TABLE data_quality_events",
    "DROP TABLE dataset_versions",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
