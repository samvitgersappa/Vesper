"""Shared async SQLAlchemy session factory for module MCP servers.

Module business logic reads/writes the Postgres schemas from Phase 2 via this
session factory, never a direct engine. Each MCP server process creates its own
engine (cheap, one connection) and closes it on shutdown.
"""

import os

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# Hermes Agent connects to module MCP servers as separate processes; the module
# servers reach Postgres directly (Docker network / localhost). Search_path is
# set to `public`; every table is referenced with its explicit schema.
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://vesper:change-me@localhost:5432/vesper",
)

# Under pytest, connections can't be pooled across event loops (pytest-asyncio
# creates/disposes loops between executions while production runs one loop per
# process). NullPool makes each acquire a fresh connection bound to the current
# loop, which is correct for the test harness.
TESTING = os.environ.get("VESPER_TESTING") == "1"


def create_session_factory(url: str = DATABASE_URL):
    """Create an async sessionmaker bound to `url`."""
    engine = create_async_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=300,
        poolclass=NullPool if TESTING else None,
    )
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# Module-scoped default session factory (one per MCP server process).
_engine, _session_factory = create_session_factory()


def session_factory():
    """Return the module-scoped async_sessionmaker."""
    return _session_factory


async def dispose() -> None:
    """Dispose the module-scoped engine (called on MCP server shutdown)."""
    await _engine.dispose()
