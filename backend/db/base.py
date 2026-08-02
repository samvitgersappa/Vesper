"""Shared SQLAlchemy declarative base + helpers for all Postgres schemas.

All Vesper schemas live in one Postgres database but are namespaced per plan.md
§13 via the `__table_args__ = {"schema": ...}` on each model class, so a single
Base/metadata can be created/migrated by Alembic in one pass.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    """Offset-naive UTC now — PostgreSQL TIMESTAMP WITHOUT TIME ZONE compat."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_uuid() -> str:
    return str(uuid.uuid4())
