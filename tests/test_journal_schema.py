"""Migration 0002 (M16): `prediction_scores` journal table and the journal-writer DB role.
PostgreSQL; skipped without TEST_DATABASE_URL (required in CI)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from conftest import alembic_cycle, table_names
from test_db_schema import _parents, _prediction

ROLE = "qqq1dte_journal_writer"
JOURNAL = ("predictions", "prediction_scores", "trade_candidates", "simulated_trades")


def _score(c: Connection, pid: uuid.UUID, target: str = "C_call", cal: str | None = "cal1") -> None:
    c.execute(
        text("""
        INSERT INTO prediction_scores (prediction_id, target, model_version_id,
          calibration_version_id, raw_score, calibrated_prob, support_n, entry_price,
          p_breakeven, margin, expected_value, side_reason)
        VALUES (:pid, :t, 'm1', :cal, 0.31, :p, 450, 1.52, 0.41, -0.1, -9.5,
          'BELOW_BREAKEVEN_MARGIN')"""),
        {"pid": pid, "t": target, "cal": cal, "p": 0.27 if cal else None},
    )


def test_prediction_scores_round_trip_and_keys(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as c:
        _parents(c, calibrated=True)
        pid = _prediction(c)
        _score(c, pid, "C_call")
        _score(c, pid, "C_put")
    with migrated_engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT target, raw_score, calibrated_prob, support_n "
                "FROM prediction_scores ORDER BY target"
            )
        ).all()
    assert [tuple(r) for r in rows] == [("C_call", 0.31, 0.27, 450), ("C_put", 0.31, 0.27, 450)]
    with pytest.raises(IntegrityError), migrated_engine.begin() as c:
        _score(c, pid, "C_call")  # one row per (prediction, target)
    with pytest.raises(IntegrityError), migrated_engine.begin() as c:
        _score(c, uuid.uuid4())  # unknown prediction


def test_calibrated_prob_requires_a_calibration_version(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as c:
        _parents(c, calibrated=True)
        pid = _prediction(c)
    with pytest.raises(IntegrityError), migrated_engine.begin() as c:
        c.execute(
            text("""
            INSERT INTO prediction_scores (prediction_id, target, model_version_id, raw_score,
              calibrated_prob) VALUES (:pid, 'C_call', 'm1', 0.3, 0.3)"""),
            {"pid": pid},
        )


@pytest.mark.parametrize(
    "stmt",
    [
        "UPDATE prediction_scores SET raw_score = 0",
        "DELETE FROM prediction_scores",
        "TRUNCATE prediction_scores",
    ],
)
def test_prediction_scores_append_only(migrated_engine: Engine, stmt: str) -> None:
    with migrated_engine.begin() as c:
        _parents(c, calibrated=True)
        _score(c, _prediction(c))
    with pytest.raises(DBAPIError, match="append-only"), migrated_engine.begin() as c:
        c.execute(text(stmt))


@pytest.mark.parametrize("table", JOURNAL)
@pytest.mark.parametrize("verb", ["UPDATE", "DELETE"])
def test_journal_writer_role_cannot_update_or_delete(
    migrated_engine: Engine, table: str, verb: str
) -> None:
    """M16 'DB role test': privileges alone (before any trigger) refuse UPDATE/DELETE."""
    with migrated_engine.begin() as c:
        _parents(c, calibrated=True)
        _score(c, _prediction(c))
    stmt = {
        "UPDATE": f"UPDATE {table} SET created_at = created_at"
        if table == "predictions"
        else f"UPDATE {table} SET {_any_col(table)} = {_any_col(table)}",
        "DELETE": f"DELETE FROM {table}",
    }[verb]
    with pytest.raises(DBAPIError, match="permission denied"), migrated_engine.begin() as c:
        c.execute(text(f"SET LOCAL ROLE {ROLE}"))
        c.execute(text(stmt))


def _any_col(table: str) -> str:
    return {
        "prediction_scores": "raw_score",
        "trade_candidates": "bid",
        "simulated_trades": "net_pnl",
    }[table]


def test_journal_writer_role_can_insert_and_select(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as c:
        _parents(c, calibrated=True)
    with migrated_engine.begin() as c:
        c.execute(text(f"SET LOCAL ROLE {ROLE}"))
        pid = _prediction(c)
        _score(c, pid)
        n = c.execute(text("SELECT count(*) FROM prediction_scores")).scalar_one()
    assert n == 1


def test_upgrade_downgrade_upgrade_keeps_role_usable(
    test_db_url: str, migrated_engine: Engine
) -> None:
    assert "prediction_scores" in table_names(migrated_engine)
    alembic_cycle(test_db_url, "downgrade")
    assert "prediction_scores" not in table_names(migrated_engine)
    alembic_cycle(test_db_url, "upgrade")
    with migrated_engine.connect() as c:
        grants = c.execute(
            text("""
            SELECT table_name, privilege_type FROM information_schema.role_table_grants
            WHERE grantee = :r AND table_name = 'prediction_scores'"""),
            {"r": ROLE},
        ).all()
    assert {g[1] for g in grants} == {"INSERT", "SELECT"}
