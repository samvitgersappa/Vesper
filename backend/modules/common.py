"""Shared helpers for module MCP servers.

Centralizes the DB session factory, event-bus publishing, and plain-dict
serialization so every module's logic/ has one consistent way to talk to
Postgres (Phase 2 schemas) and the Redis event bus (plan.md §6).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from backend.modules.db import session_factory, dispose

logger = logging.getLogger("vesper.modules")

# Event bus is imported lazily to keep module logic importable even when Redis
# is unreachable (a module MCP server must still boot standalone).
_BUS = None


def get_bus():
    global _BUS
    if _BUS is None:
        from backend.events.bus import bus
        _BUS = bus
    return _BUS


def publish(event: str, payload: dict) -> None:
    """Publish an event to the Redis bus, best-effort (never raises).

    Modules publish at the points the source code did (plan.md §6 catalog).
    If Redis is down the write is logged and dropped — the DB write already
    happened and is the system of record.
    """
    try:
        get_bus().publish(event, payload)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("event publish %s failed: %s", event, exc)


def open_session():
    """Open an async SQLAlchemy session for module logic.

    Usage: `async with open_session() as db:` — yields an AsyncSession bound to
    the module-scoped engine. (async_sessionmaker is not itself an async CM;
    call it once to get an AsyncSession, which is.)
    """
    return session_factory()()


__all__ = ["dispose", "get_bus", "publish", "session_factory", "open_session", "logger"]
