"""Postgres schema models — imports every schema so Alembic sees all tables.

Import this module (or call all_models) anywhere you need all Vesper tables
registered on Base.metadata for create_all / autogenerate.
"""

from backend.db.postgres.schemas import (  # noqa: F401
    relationship,
    journal,
    study,
    finance,
    graph,
    hermes,
)


def all_models():
    """Import and return every schema module (registers tables on Base.metadata)."""
    return [relationship, journal, study, finance, graph, hermes]
