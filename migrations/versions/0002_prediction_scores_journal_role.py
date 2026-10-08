"""Journal additions (M16): per-target prediction scores and the journal-writer role.

- `prediction_scores`: one row per (prediction, target) with its own model and calibration
  versions (a decision uses C_call and C_put, each with its own model and calibrator);
  append-only like the other journal tables. `predictions.model_version_id` /
  `calibration_version_id` hold the CALL-side ids; `prediction_scores` is authoritative.
- role `qqq1dte_journal_writer` (NOLOGIN): INSERT and SELECT on the journal tables only, so
  UPDATE / DELETE are refused by privileges as well as by the append-only triggers. Roles are
  cluster-wide: the role is created if missing (the migrating user needs CREATEROLE; without it
  the migration fails loudly) and is never dropped on downgrade (other databases may use it);
  downgrade revokes its privileges in this database.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ROLE = "qqq1dte_journal_writer"
JOURNAL_TABLES = ("predictions", "prediction_scores", "trade_candidates", "simulated_trades")

UPGRADE = [
    """
    CREATE TABLE prediction_scores (
      prediction_id     UUID NOT NULL REFERENCES predictions,
      target            TEXT NOT NULL,
      model_version_id  TEXT NOT NULL REFERENCES model_versions,
      calibration_version_id TEXT REFERENCES calibration_results,
      raw_score         DOUBLE PRECISION NOT NULL,
      calibrated_prob   DOUBLE PRECISION,
      support_n         INT,
      entry_price       DOUBLE PRECISION,
      p_breakeven       DOUBLE PRECISION,
      margin            DOUBLE PRECISION,
      expected_value    DOUBLE PRECISION,
      side_reason       TEXT,
      PRIMARY KEY (prediction_id, target),
      CONSTRAINT calibrated_prob_requires_calibration CHECK (
        calibrated_prob IS NULL OR calibration_version_id IS NOT NULL)
    )
    """,
    """
    CREATE TRIGGER prediction_scores_append_only
      BEFORE UPDATE OR DELETE ON prediction_scores
      FOR EACH ROW EXECUTE FUNCTION journal_append_only()
    """,
    """
    CREATE TRIGGER prediction_scores_no_truncate
      BEFORE TRUNCATE ON prediction_scores
      FOR EACH STATEMENT EXECUTE FUNCTION journal_append_only()
    """,
    f"""
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') THEN
        CREATE ROLE {ROLE} NOLOGIN;
      END IF;
    END
    $$
    """,
    # the migrating user may SET ROLE to the writer (tests, controlled writers)
    f"GRANT {ROLE} TO CURRENT_USER WITH SET TRUE, INHERIT FALSE",
    f"GRANT USAGE ON SCHEMA public TO {ROLE}",
    *[f"GRANT INSERT, SELECT ON {t} TO {ROLE}" for t in JOURNAL_TABLES],
]

DOWNGRADE = [
    *[f"REVOKE ALL ON {t} FROM {ROLE}" for t in JOURNAL_TABLES],
    f"REVOKE USAGE ON SCHEMA public FROM {ROLE}",
    "DROP TABLE prediction_scores",
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
