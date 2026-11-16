"""Paper journal for ADR-0022 (M32): the evening signals, the owner's fills and events.

- `paper_signals`: one row per evening (data date). `available_at` is when the bar was
  downloaded; it must be after that session's 16:00 New York close and no later than the run
  (hard rule 2). A NO_ACTION row carries 0 shares; BUY and SELL carry a positive count.
- `paper_fills`: at most one per BUY or SELL evening, entered by the owner: FILLED with price,
  quantity, commission and time; MISSED or REJECTED with a reason. Nothing else is stored.
- `paper_events`: data reads (amendment A1 R2), refusals, revisions, loss-limit stops.
- All three are append-only, like the Phase 1 journal.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-15
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TABLES = ("paper_signals", "paper_fills", "paper_events")

UPGRADE = [
    """
    CREATE TABLE paper_signals (
      data_date       DATE PRIMARY KEY,
      next_session    DATE NOT NULL CHECK (next_session > data_date),
      ticker          TEXT NOT NULL,
      run_at          TIMESTAMPTZ NOT NULL,
      available_at    TIMESTAMPTZ NOT NULL,
      close           DOUBLE PRECISION NOT NULL CHECK (close > 0),
      adj_close       DOUBLE PRECISION NOT NULL CHECK (adj_close > 0),
      rsi             DOUBLE PRECISION,
      sma_trend       DOUBLE PRECISION,
      sma_exit        DOUBLE PRECISION,
      entry_signal    BOOLEAN NOT NULL,
      exit_signal     BOOLEAN NOT NULL,
      position_before INTEGER NOT NULL CHECK (position_before >= 0),
      halted          BOOLEAN NOT NULL,
      action          TEXT NOT NULL CHECK (action IN ('BUY','SELL','NO_ACTION')),
      shares          INTEGER NOT NULL,
      instruction     TEXT NOT NULL,
      code_commit     TEXT NOT NULL,
      data_sha256     TEXT NOT NULL,
      config_hash     TEXT NOT NULL,
      CHECK (available_at <= run_at),
      CHECK (available_at >= ((data_date + TIME '16:00') AT TIME ZONE 'America/New_York')),
      CHECK ((action = 'NO_ACTION' AND shares = 0) OR (action <> 'NO_ACTION' AND shares > 0))
    )
    """,
    """
    CREATE TABLE paper_fills (
      data_date    DATE PRIMARY KEY REFERENCES paper_signals,
      status       TEXT NOT NULL CHECK (status IN ('FILLED','MISSED','REJECTED')),
      price        DOUBLE PRECISION,
      quantity     INTEGER,
      commission   DOUBLE PRECISION,
      filled_at    TIMESTAMPTZ,
      reason       TEXT,
      recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (
        (status = 'FILLED' AND price IS NOT NULL AND quantity IS NOT NULL
         AND commission IS NOT NULL AND filled_at IS NOT NULL
         AND price > 0 AND quantity > 0 AND commission >= 0)
        OR (status <> 'FILLED' AND price IS NULL AND quantity IS NULL AND commission IS NULL
            AND filled_at IS NULL AND length(btrim(coalesce(reason, ''))) > 0)
      )
    )
    """,
    """
    CREATE FUNCTION paper_fill_needs_order() RETURNS trigger AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM paper_signals
                     WHERE data_date = NEW.data_date AND action IN ('BUY','SELL')) THEN
        RAISE EXCEPTION 'no BUY or SELL instruction on % to record a fill for', NEW.data_date
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER paper_fills_need_order BEFORE INSERT ON paper_fills
      FOR EACH ROW EXECUTE FUNCTION paper_fill_needs_order()
    """,
    """
    CREATE TABLE paper_events (
      event_id   BIGSERIAL PRIMARY KEY,
      at         TIMESTAMPTZ NOT NULL DEFAULT now(),
      kind       TEXT NOT NULL CHECK (kind IN ('DATA_READ','REFUSED','MISSED_EVENING',
                   'REVISION','REVISION_FLIPS_SIGNAL','LOSS_LIMIT','QTY_DIFFERS','FILL_REFUSED')),
      data_date  DATE,
      detail     JSONB NOT NULL
    )
    """,
    *(
        sql
        for t in TABLES
        for sql in (
            f"""CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON {t}
                FOR EACH ROW EXECUTE FUNCTION journal_append_only()""",
            f"""CREATE TRIGGER {t}_no_truncate BEFORE TRUNCATE ON {t}
                FOR EACH STATEMENT EXECUTE FUNCTION journal_append_only()""",
        )
    ),
]

DOWNGRADE = [
    "DROP TABLE paper_events",
    "DROP TABLE paper_fills",
    "DROP FUNCTION paper_fill_needs_order()",
    "DROP TABLE paper_signals",
]


def upgrade() -> None:
    for sql in UPGRADE:
        op.execute(sql)


def downgrade() -> None:
    for sql in DOWNGRADE:
        op.execute(sql)
