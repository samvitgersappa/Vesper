"""One-time data migration (Phase 2): old stores -> new local Postgres.

Reads ProjectVesper (Supabase Postgres or the local personanet.db SQLite copy)
and Quiver's SQLite feature-state store, then writes into the new local Vesper
Postgres (plan.md §13). Column names are matched by name via the SQLAlchemy
metadata; the only intentional divergence is `diary_entries.content` (dropped;
content now lives in the vault per plan §8.3).

ALWAYS run against a copy of production data, never live data.

Usage:
    PROJECTVESPER_SOURCE_URL=postgresql+asyncpg://... \
    QUIVER_SOURCE_SQLITE=/path/to/quiver_state.sqlite \
    VESPER_DATABASE_URL=postgresql+asyncpg://vesper:pass@localhost:5432/vesper \
    .venv/bin/python -m backend.db.migrate_from_sources

Defaults point at the local read-only copies so a dry run is safe.
"""

import asyncio
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, column, inspect, select, table as sa_table
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.db.base import Base
from backend.db.postgres.schemas import all_models  # noqa: F401  (register tables)

# ── Sources / targets (env-overridable) ──────────────────────────────────────
PROJECTVESPER_SOURCE_URL = os.environ.get(
    "PROJECTVESPER_SOURCE_URL",
    "sqlite+aiosqlite:////path/to/source-repository/"
    "ProjectVesper/backend/data/personanet.db",
)
QUIVER_SOURCE_SQLITE = os.environ.get(
    "QUIVER_SOURCE_SQLITE",
    "/path/to/source-repository/Quiver/Quiver/backend/data/"
    "metadata/quiver_state.sqlite",
)
VESPER_DATABASE_URL = os.environ.get(
    "VESPER_DATABASE_URL",
    "postgresql+asyncpg://vesper:change-me@127.0.0.1:5432/vesper",
)

# ProjectVesper tables -> target schema (source table name = target table name).
RELATIONSHIP_TABLES = [
    "clusters", "group_interactions", "tags", "push_subscriptions",
    "persons", "interactions", "relationships", "reminders", "person_tags",
    "notes", "life_events", "gift_ideas", "rss_entries", "health_snapshots",
    "introductions", "person_field_history", "relationship_scores", "cron_runs",
]
JOURNAL_TABLES = ["diary_entries"]
STUDY_TABLES = ["tests", "mock_tests"]

# diary_entries.content is dropped — content lives in the vault file now.
DROPPED_COLUMNS = {"diary_entries": {"content"}}

SCHEMA_BY_TABLE = (
    {t: "relationship" for t in RELATIONSHIP_TABLES}
    | {t: "journal" for t in JOURNAL_TABLES}
    | {t: "study" for t in STUDY_TABLES}
)


def _source_engine() -> AsyncEngine:
    return create_async_engine(PROJECTVESPER_SOURCE_URL)


async def _try_insert(conn, target, row: dict) -> bool:
    """Insert one row inside a savepoint; True if committed, False if it violates a constraint."""
    try:
        async with conn.begin_nested():
            await conn.execute(target.insert().values([row]))
        return True
    except Exception:
        return False


def _quiver_engine() -> AsyncEngine:
    return create_async_engine(
        f"sqlite+aiosqlite:///{Path(QUIVER_SOURCE_SQLITE).resolve()}"
    )


def _target_engine() -> AsyncEngine:
    return create_async_engine(VESPER_DATABASE_URL)


def _coerce(value, col) -> object:
    """Coerce a raw SQLite value to the target Postgres column's Python type."""
    if value is None or isinstance(value, (date, datetime, bool, int, float)):
        return value
    if isinstance(value, str) and value.strip() == "null":
        return None
    if isinstance(col.type, DateTime):
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)
    if isinstance(col.type, JSON):
        if isinstance(value, (dict, list)):
            return value
        return json.loads(value)
    if isinstance(col.type, Boolean):
        return value in (True, "true", "1", 1)
    if isinstance(col.type, Integer):
        return int(value)
    if isinstance(col.type, Float):
        return float(value)
    return value


async def _copy_table(src: AsyncEngine, dst: AsyncEngine, table: str, schema: str) -> int:
    """Copy a table from `src` to `dst`, matching columns by name."""
    target = Base.metadata.tables[f"{schema}.{table}"]
    dropped = DROPPED_COLUMNS.get(table, set())

    async with src.connect() as conn:
        src_cols = {
            c["name"]
            for c in await conn.run_sync(lambda s: inspect(s).get_columns(table))
        }
        sel = None
        src_rows = []
        common = sorted(src_cols & {c.name for c in target.columns} - dropped)
        if common:
            sel = select(*[column(c) for c in common]).select_from(sa_table(table))
            src_rows = (await conn.execute(sel)).fetchall()

    if not common:
        print(f"  !! {schema}.{table}: no common columns; skipped")
        return 0

    target_cols = {c.name: c for c in target.columns}
    values = [
        {c: _coerce(getattr(r, c), target_cols[c]) for c in common}
        for r in src_rows
    ]
    copied = len(values)
    try:
        async with dst.begin() as conn:
            if values:
                await conn.execute(target.insert().values(values))
    except Exception:
        # Fall back to row-by-row in a fresh transaction, skipping rows that
        # violate constraints (e.g. dangling person FKs in the old data).
        copied = 0
        skipped = 0
        async with dst.begin() as conn:
            for row in values:
                if await _try_insert(conn, target, row):
                    copied += 1
                else:
                    skipped += 1
        if skipped:
            print(f"    (skipped {skipped} rows violating constraints)")
    print(f"  {schema}.{table}: copied {copied} rows")
    return copied


async def _copy_quiver_finance(src: AsyncEngine, dst: AsyncEngine) -> int:
    """Copy every Quiver table whose name matches a finance.* target."""
    total = 0
    async with src.connect() as conn:
        sqlite_tables = await conn.run_sync(
            lambda s: [
                r[0]
                for r in s.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
        )
    for t in sorted(sqlite_tables):
        if f"finance.{t}" in Base.metadata.tables:
            total += await _copy_table(src, dst, t, "finance")
    return total


async def main() -> None:
    src = _source_engine()
    quiver = _quiver_engine()
    dst = _target_engine()

    print("Copying ProjectVesper -> Vesper relationship/journal/study...")
    for t in RELATIONSHIP_TABLES + JOURNAL_TABLES + STUDY_TABLES:
        await _copy_table(src, dst, t, SCHEMA_BY_TABLE[t])

    print("Copying Quiver SQLite -> Vesper finance...")
    await _copy_quiver_finance(quiver, dst)

    for e in (src, quiver, dst):
        await e.dispose()
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())
