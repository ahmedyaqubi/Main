"""Shared fixtures. Database tests need TEST_DATABASE_URL (in .env locally; set by CI)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _alembic(url: str, action: str) -> None:
    from alembic import command  # noqa: PLC0415 (only for DB tests)
    from alembic.config import Config  # noqa: PLC0415

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["url"] = url
    if action == "upgrade":
        command.upgrade(cfg, "head")
    else:
        command.downgrade(cfg, "base")


@pytest.fixture(scope="session")
def test_db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        if os.environ.get("REQUIRE_DB") == "1":  # CI: a missing database is a failure
            pytest.fail("REQUIRE_DB=1 but TEST_DATABASE_URL is not set")
        pytest.skip("TEST_DATABASE_URL not set: PostgreSQL tests skipped (they run in CI)")
    return url


@pytest.fixture
def migrated_engine(test_db_url: str) -> Iterator[Engine]:
    """A freshly migrated, empty schema for each test."""
    _alembic(test_db_url, "downgrade")
    _alembic(test_db_url, "upgrade")
    engine = create_engine(test_db_url)
    try:
        yield engine
    finally:
        engine.dispose()


def alembic_cycle(url: str, action: str) -> None:
    _alembic(url, action)


def table_names(engine: Engine) -> set[str]:
    with engine.connect() as c:
        rows = c.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
        )
        return {r[0] for r in rows}
