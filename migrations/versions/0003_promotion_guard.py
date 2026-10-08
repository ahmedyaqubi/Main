"""Promotion guard (M17, spec Phase 1P: no automatic path to production).

- `model_versions.status` may become PRODUCTION only if a `model_promotions` row with
  decision PROMOTED for that model was written earlier in the same transaction
  (created_at = now(), the transaction start time). An INSERT with status PRODUCTION is
  refused for the same reason (no promotion can reference a model that does not exist yet).
- `model_promotions` is append-only (audit trail), like the journal tables.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-08
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UPGRADE = [
    """
    CREATE FUNCTION model_production_requires_promotion() RETURNS trigger AS $$
    BEGIN
      IF NEW.status = 'PRODUCTION'
         AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM 'PRODUCTION') THEN
        IF NOT EXISTS (
          SELECT 1 FROM model_promotions
          WHERE to_model_id = NEW.model_version_id
            AND decision = 'PROMOTED'
            AND created_at = now()
        ) THEN
          RAISE EXCEPTION
            'model % cannot become PRODUCTION without a PROMOTED promotion record '
            'in the same transaction',
            NEW.model_version_id USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER model_versions_production_guard
      BEFORE INSERT OR UPDATE OF status ON model_versions
      FOR EACH ROW EXECUTE FUNCTION model_production_requires_promotion()
    """,
    """
    CREATE TRIGGER model_promotions_append_only
      BEFORE UPDATE OR DELETE ON model_promotions
      FOR EACH ROW EXECUTE FUNCTION journal_append_only()
    """,
    """
    CREATE TRIGGER model_promotions_no_truncate
      BEFORE TRUNCATE ON model_promotions
      FOR EACH STATEMENT EXECUTE FUNCTION journal_append_only()
    """,
]

DOWNGRADE = [
    "DROP TRIGGER model_promotions_no_truncate ON model_promotions",
    "DROP TRIGGER model_promotions_append_only ON model_promotions",
    "DROP TRIGGER model_versions_production_guard ON model_versions",
    "DROP FUNCTION model_production_requires_promotion()",
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)
