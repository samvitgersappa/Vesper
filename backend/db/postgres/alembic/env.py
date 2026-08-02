"""Alembic environment — Vesper Postgres schemas.

Uses DATABASE_URL from the environment (or a local default). Every Vesper schema
model is imported so autogenerate sees all tables.
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make `backend` importable (env.py lives at backend/db/postgres/alembic/,
# so vesper root is 4 levels up).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from backend.db.base import Base
from backend.db.postgres.schemas import all_models  # noqa: F401  (registers models)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata: ALL Vesper tables across every schema.
target_metadata = Base.metadata

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://vesper:change-me@localhost:5432/vesper",
)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (async engine)."""
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    connectable = create_async_engine(DATABASE_URL)

    def do_run_migrations(connection):
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()

    async def run_async_migrations():
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
        await connectable.dispose()

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
