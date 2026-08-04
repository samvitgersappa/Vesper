"""Hermes Agent log mirror (plan.md §13).

Hermes Agent's own SQLite (`~/.hermes/state.db`) is the source of truth; this
job mirrors tool-call and LLM-usage records into the `hermes` Postgres schema so
cross-module SQL reporting never queries Hermes Agent's store directly.

Runs on a short interval (configurable via HERMES_MIRROR_INTERVAL, default 5m).
Idempotent: it tracks the last mirrored row id per table in the state DB's own
`state_meta` key-value store, so re-runs only insert new rows.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone

from sqlalchemy import text

from backend.modules.db import session_factory
from backend.db.postgres.schemas.hermes.models import HermesToolCall, HermesLLMUsage

logger = logging.getLogger("vesper.automation.mirror")

STATE_DB = os.environ.get("HERMES_STATE_DB", "~/.hermes/state.db")
_LAST = "mirror_last_message_id"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _src_conn():
    import os as _os
    path = _os.path.expanduser(STATE_DB)
    if not _os.path.exists(path):
        return None
    return sqlite3.connect(path)


def _last_mirrored_id() -> int:
    try:
        conn = _src_conn()
        if conn is None:
            return 0
        row = conn.execute(
            "SELECT value FROM state_meta WHERE key = ?", (_LAST,)
        ).fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception as exc:  # pragma: no cover
        logger.warning("read last mirrored id failed: %s", exc)
        return 0


def _set_last_mirrored_id(value: int) -> None:
    try:
        conn = _src_conn()
        if conn is None:
            return
        conn.execute(
            "INSERT OR REPLACE INTO state_meta (key, value) VALUES (?, ?)",
            (_LAST, str(value)),
        )
        conn.commit()
        conn.close()
    except Exception as exc:  # pragma: no cover
        logger.warning("write last mirrored id failed: %s", exc)


async def _mirror_tool_calls(since_id: int) -> int:
    """Mirror `messages` rows that are tool calls (role='assistant' with tool_calls)."""
    conn = _src_conn()
    if conn is None:
        return 0
    try:
        rows = conn.execute(
            "SELECT id, session_id, tool_name, tool_calls, content, timestamp, token_count "
            "FROM messages WHERE id > ? AND (tool_name IS NOT NULL OR tool_calls IS NOT NULL) "
            "ORDER BY id LIMIT 500",
            (since_id,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return 0

    async with session_factory()() as db:
        for r in rows:
            tool_name = r[2] or ""
            try:
                import json as _json
                inputs = _json.loads(r[3]) if r[3] else {}
            except Exception:
                inputs = {}
            server = tool_name.split("__")[1] if tool_name.startswith("mcp__") else tool_name
            row = HermesToolCall(
                session_id=r[1],
                tool_name=tool_name,
                server_name=server,
                inputs_json=inputs or {},
                outputs_json={"content": (r[4] or "")[:4000]},
                ts=_now(),
            )
            db.add(row)
        await db.commit()
    return len(rows)


async def _mirror_usage() -> int:
    """Mirror session_model_usage → HermesLLMUsage (last 500, idempotent by session)."""
    conn = _src_conn()
    if conn is None:
        return 0
    try:
        rows = conn.execute(
            "SELECT session_id, model, billing_provider, input_tokens, output_tokens, "
            "cache_read_tokens, cache_write_tokens, estimated_cost_usd, api_call_count, last_seen "
            "FROM session_model_usage ORDER BY last_seen DESC LIMIT 500"
        ).fetchall()
    finally:
        conn.close()

    inserted = 0
    async with session_factory()() as db:
        for r in rows:
            exists = (await db.execute(
                text("SELECT 1 FROM hermes.hermes_llm_usage WHERE session_id = :s AND model = :m"),
                {"s": r[0], "m": r[1]},
            )).scalar()
            if exists:
                continue
            db.add(HermesLLMUsage(
                session_id=r[0],
                model=r[1],
                provider=r[2],
                prompt_tokens=r[3] or 0,
                completion_tokens=r[4] or 0,
                total_tokens=(r[3] or 0) + (r[4] or 0),
                cost_usd=r[7],
                duration_ms=None,
                ts=_now(),
            ))
            inserted += 1
        await db.commit()
    return inserted


async def hermes_mirror() -> dict:
    """Run one mirror pass. Returns counts mirrored this pass."""
    since = _last_mirrored_id()
    tool_rows = await _mirror_tool_calls(since)
    usage_rows = await _mirror_usage()
    if tool_rows:
        _set_last_mirrored_id(since + tool_rows)
    return {"ok": True, "tool_calls_mirrored": tool_rows, "usage_rows_mirrored": usage_rows}
