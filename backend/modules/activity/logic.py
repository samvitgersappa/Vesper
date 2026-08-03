"""Activity feed — a live, honest mirror of what Vesper actually writes.

The web app's other pages show *state* (current contacts, NAV, spending
buckets). This module answers "what has the system been DOING": recent Hermes
agent tool calls, knowledge captures, automation runs, and the latest writes
across every domain table. It reads the same Postgres rows the pages render,
so the feed can only ever show real activity — never fabricated entries.

Schema: reads `hermes`, `relationship`, `journal`, `finance`, `graph`,
`study` tables read-only.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from backend.modules.db import session_factory

logger = logging.getLogger("vesper.modules.activity")

_DOMAINS = {
    "hermes": "#5b8cff",
    "knowledge": "#b980f7",
    "automation": "#f6c445",
    "relationships": "#ff7a8a",
    "journal": "#f6c445",
    "finance": "#3ddc97",
    "graph": "#b980f7",
    "study": "#5b8cff",
}

_QUERIES: list[dict[str, str]] = [
    {
        "kind": "hermes_tool",
        "domain": "hermes",
        "ts": "ts",
        "detail": "tool_name",
        "label": "(server_name)",
        "ok_col": "is_error",
        "sql": (
            "SELECT ts, tool_name, server_name, is_error FROM hermes.hermes_tool_calls "
            "ORDER BY ts DESC LIMIT 60"
        ),
    },
    {
        "kind": "capture",
        "domain": "knowledge",
        "ts": "ts",
        "detail": "utterance",
        "label": "(stored_in)",
        "sql": (
            "SELECT ts, utterance, stored_in FROM hermes.capture_routing_log "
            "ORDER BY ts DESC LIMIT 60"
        ),
    },
    {
        "kind": "automation",
        "domain": "automation",
        "ts": "last_run_at",
        "detail": "job_name",
        "sql": (
            "SELECT last_run_at, job_name FROM relationship.cron_runs "
            "ORDER BY last_run_at DESC LIMIT 40"
        ),
    },
    {
        "kind": "diary",
        "domain": "journal",
        "ts": "created_at",
        "detail": "mood",
        "label": "(date)",
        "sql": (
            "SELECT created_at, mood, entry_date FROM journal.diary_entries "
            "ORDER BY created_at DESC LIMIT 40"
        ),
    },
    {
        "kind": "spending",
        "domain": "journal",
        "ts": "created_at",
        "detail": "category",
        "label": "(amount)",
        "sql": (
            "SELECT created_at, category, amount FROM journal.spending "
            "ORDER BY created_at DESC LIMIT 40"
        ),
    },
    {
        "kind": "workout",
        "domain": "journal",
        "ts": "created_at",
        "detail": "workout_type",
        "label": "(minutes)",
        "sql": (
            "SELECT created_at, workout_type, minutes FROM journal.workouts "
            "ORDER BY created_at DESC LIMIT 40"
        ),
    },
    {
        "kind": "person",
        "domain": "relationships",
        "ts": "updated_at",
        "detail": "name",
        "sql": (
            "SELECT updated_at, name FROM relationship.persons "
            "ORDER BY updated_at DESC LIMIT 40"
        ),
    },
    {
        "kind": "interaction",
        "domain": "relationships",
        "ts": "interaction_date",
        "detail": "person_name",
        "label": "(type)",
        "sql": (
            "SELECT i.interaction_date, p.name AS person_name, i.interaction_type AS type "
            "FROM relationship.interactions i "
            "LEFT JOIN relationship.persons p ON p.person_id = i.person_id "
            "ORDER BY i.interaction_date DESC LIMIT 40"
        ),
    },
    {
        "kind": "trade",
        "domain": "finance",
        "ts": "trade_date",
        "detail": "symbol",
        "label": "(side qty)",
        "ok_col": "order_status",
        "sql": (
            "SELECT trade_date, symbol, side || ' ' || quantity AS side_qty, order_status "
            "FROM finance.paper_trades "
            "ORDER BY trade_date DESC LIMIT 40"
        ),
    },
    {
        "kind": "nav",
        "domain": "finance",
        "ts": "date",
        "detail": "trader_id",
        "label": "(equity)",
        "sql": (
            "SELECT date, trader_id, total_equity FROM finance.paper_nav_history "
            "ORDER BY date DESC LIMIT 40"
        ),
    },
    {
        "kind": "graph",
        "domain": "graph",
        "ts": "created_at",
        "detail": "label",
        "label": "(type)",
        "sql": (
            "SELECT created_at, label, entity_type FROM graph.graph_nodes "
            "ORDER BY created_at DESC LIMIT 40"
        ),
    },
    {
        "kind": "test",
        "domain": "study",
        "ts": "created_at",
        "detail": "name",
        "sql": (
            "SELECT created_at, name FROM study.tests "
            "ORDER BY created_at DESC LIMIT 40"
        ),
    },
]


def _iso(dt) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(dt)


def _summarize(row: tuple, q: dict) -> dict:
    label = str(row[2]) if len(row) > 2 else ""
    ok = None
    ok_col = q.get("ok_col")
    if ok_col:
        val = str(row[3]) if len(row) > 3 else ""
        if q["kind"] == "hermes_tool":
            ok = val.lower() not in ("1", "true", "t")
        elif q["kind"] == "trade":
            ok = val == "FILLED"
    return {
        "ts": _iso(row[0]),
        "kind": q["kind"],
        "domain": q["domain"],
        "detail": str(row[1] if len(row) > 1 else ""),
        "label": label.strip(),
        "ok": ok,
    }


async def recent(limit: int = 80) -> dict:
    """Return the most recent writes across the system, newest first."""
    items: list[dict] = []
    async with session_factory()() as s:
        for q in _QUERIES:
            try:
                rows = (await s.execute(text(q["sql"]))).all()
            except Exception as exc:  # table missing / not provisioned yet
                logger.debug("activity skip %s: %s", q["kind"], exc)
                continue
            items.extend(_summarize(tuple(row), q) for row in rows)
    items.sort(key=lambda i: i["ts"] or "", reverse=True)
    return {
        "ok": True,
        "count": len(items),
        "limit": limit,
        "domains": _DOMAINS,
        "items": items[:limit],
    }
