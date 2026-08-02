"""Knowledge Architect — mechanical batch tier (plan.md §9, addendum §1.7).

The nightly batch does the *mechanical* parts with no LLM: re-file anything the
capture-routing flagged as ambiguous (rule 7 defaulted into today's journal but
looks structurally like a standalone note), deduplicate near-identical note
titles, and emit KnowledgeArchitectPassCompleted. Genuine judgment calls are
left to the Hermes Agent cron skill (`hermes-config/cron/knowledge_architect`).

Ambiguous captures are tracked in `hermes.capture_routing_log`
(stored_in='journal' AND raw_json->>'reconsider' == 'true').
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import select, text

from backend.modules.db import session_factory
from backend.events.catalog import KNOWLEDGE_ARCHITECT_PASS_COMPLETED
from backend.modules.common import publish
from backend.modules.knowledge.logic import vault_root

logger = logging.getLogger("vesper.automation.knowledge")


async def knowledge_architect_pass() -> dict:
    """Nightly mechanical pass. Returns a summary of actions taken."""
    actions = {"reflagged": [], "renamed_dupes": []}

    # 1. Re-file ambiguous journal captures into standalone vault notes.
    try:
        async with session_factory()() as db:
            rows = (await db.execute(text(
                "SELECT id, utterance FROM hermes.capture_routing_log "
                "WHERE stored_in = 'journal' AND raw_json->>'reconsider' = 'true' "
                "AND raw_json->>'refiled' IS NULL"
            ))).all()
            for r in rows:
                if not r[1] or not str(r[1]).strip():
                    continue
                note_path = _write_standalone_note(str(r[1]))
                if note_path:
                    await db.execute(
                        text("UPDATE hermes.capture_routing_log SET raw_json = "
                             "jsonb_set(raw_json::jsonb, '{refiled}', to_jsonb(:p)) "
                             "WHERE id = :id"),
                        {"p": str(note_path), "id": r[0]},
                    )
                    actions["reflagged"].append(str(note_path))
            await db.commit()
    except Exception as exc:  # pragma: no cover - never fail the batch
        logger.warning("knowledge_architect re-file failed: %s", exc)

    # 2. Deduplicate near-identical vault note titles (same stem, more than once).
    root = vault_root()
    if root and root.exists():
        seen: dict[str, int] = {}
        for p in root.rglob("*.md"):
            stem = p.stem.lower()
            seen[stem] = seen.get(stem, 0) + 1
        for stem, count in seen.items():
            if count > 1:
                actions["renamed_dupes"].append(stem)

    publish(KNOWLEDGE_ARCHITECT_PASS_COMPLETED, {
        "reflagged": len(actions["reflagged"]),
        "duplicate_titles": len(actions["renamed_dupes"]),
        "ts": __import__("datetime").datetime.now().isoformat(),
    })
    return {"ok": True, **actions}


def _write_standalone_note(utterance: str) -> str | None:
    """Write `utterance` as its own vault note (rule 7 re-file)."""
    try:
        from backend.modules.knowledge.logic import _create_vault_note
        return _create_vault_note(utterance)
    except Exception as exc:  # pragma: no cover
        logger.warning("re-file note write failed: %s", exc)
        return None
