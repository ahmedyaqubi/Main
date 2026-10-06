"""Alembic environment. The URL comes from (in order): config attribute `url` (tests),
`-x url=...`, or DATABASE_URL in the environment / .env. It is never written to disk."""

from __future__ import annotations

import os
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _url() -> str:
    cfg_url = context.config.attributes.get("url")
    x_url = context.get_x_argument(as_dictionary=True).get("url")
    url = cfg_url or x_url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("No database URL: set DATABASE_URL (in .env) or pass -x url=...")
    return str(url)


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Offline (SQL script) migrations are not supported; run against a database.")
run_migrations_online()
