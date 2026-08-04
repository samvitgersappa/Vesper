"""Universal graph write adapter (plan.md §10).

Every domain table gets a thin adapter that registers/updates its rows as graph
nodes on write, driven by the event bus (PersonUpdated / InteractionLogged /
KnowledgeIndexed). This is what populates `graph.graph_nodes`/`graph_edges` —
the graph module's MCP server reads them; the nightly analytics job computes
communities/centrality over them.

Subscriber contract: `graph_subscriber(event, payload)` is called by the worker's
event-bus subscription thread (backend/automation/scheduler.py). Each handler is
best-effort: an upstream module write already committed; this adapter is a
downstream projection and must never raise across the loop.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from backend.modules.db import session_factory
from backend.db.postgres.schemas.graph.models import GraphNode, GraphEdge
from backend.db.postgres.schemas.relationship.models import Person, Interaction

logger = logging.getLogger("vesper.graph.adapter")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _node_id(entity_type: str, ref_id: str) -> str:
    """Deterministic graph node id from (entity_type, domain ref_id)."""
    import hashlib

    return hashlib.md5(f"{entity_type}:{ref_id}".encode()).hexdigest()


async def _upsert_node(
    db,
    entity_type: str,
    ref_id: str,
    label: str,
    node_metadata: dict,
) -> GraphNode:
    node = (await db.execute(
        select(GraphNode).where(GraphNode.id == _node_id(entity_type, ref_id))
    )).scalar_one_or_none()
    if node is None:
        node = GraphNode(
            id=_node_id(entity_type, ref_id),
            entity_type=entity_type,
            ref_table=entity_type,
            ref_id=ref_id,
            label=label,
            node_metadata=node_metadata,
        )
        db.add(node)
    else:
        node.label = label
        node.node_metadata = node_metadata
        node.updated_at = _now()
    return node


async def _upsert_edge(db, source: GraphNode, target: GraphNode, edge_type: str, weight: float = 1.0) -> None:
    edge = (await db.execute(
        select(GraphEdge).where(
            GraphEdge.source_id == source.id,
            GraphEdge.target_id == target.id,
            GraphEdge.edge_type == edge_type,
        )
    )).scalar_one_or_none()
    if edge is None:
        db.add(GraphEdge(
            source_id=source.id,
            target_id=target.id,
            edge_type=edge_type,
            weight=weight,
        ))
    else:
        edge.weight = weight


async def _on_person(person_id: str) -> None:
    """PersonUpdated — upsert a person node + its introduced_by edge."""
    try:
        async with session_factory()() as db:
            person = (await db.execute(
                select(Person).where(Person.id == person_id)
            )).scalar_one_or_none()
            if person is None:
                return
            node = await _upsert_node(
                db,
                "person",
                person.id,
                person.name or person.nickname or "person",
                {
                    "category": person.category if hasattr(person.category, "value") else person.category,
                    "health_score": person.health_score,
                    "company": person.company,
                    "occupation": person.occupation,
                },
            )
            if person.introduced_by_id:
                intro = (await db.execute(
                    select(Person).where(Person.id == person.introduced_by_id)
                )).scalar_one_or_none()
                if intro is not None:
                    intro_node = await _upsert_node(
                        db, "person", intro.id, intro.name or "person", {}
                    )
                    await _upsert_edge(intro_node, node, "introduced_by", weight=1.0)
            await db.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning("graph person adapter failed: %s", exc)


async def _on_interaction(interaction_id: str) -> None:
    """InteractionLogged — edge from person to a shared 'interaction' node."""
    try:
        async with session_factory()() as db:
            interaction = (await db.execute(
                select(Interaction).where(Interaction.id == interaction_id)
            )).scalar_one_or_none()
            if interaction is None:
                return
            person = (await db.execute(
                select(Person).where(Person.id == interaction.person_id)
            )).scalar_one_or_none()
            if person is None:
                return
            person_node = await _upsert_node(
                db, "person", person.id, person.name or "person", {}
            )
            event_node = await _upsert_node(
                db,
                "interaction",
                interaction.id,
                f"interaction {interaction.event_date.date().isoformat() if interaction.event_date else ''}".strip(),
                {"type": interaction.type if hasattr(interaction.type, "value") else interaction.type,
                 "summary": interaction.summary},
            )
            await _upsert_edge(db, person_node, event_node, "participated", weight=1.0)
            await db.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning("graph interaction adapter failed: %s", exc)


def _vault_rel(path: str) -> str:
    """Vault-relative path for a note (falls back to the raw path)."""
    try:
        from backend.modules.knowledge.logic import vault_root
        return str(Path(path).relative_to(vault_root()))
    except Exception:
        return str(path)


async def _on_knowledge(payload: dict) -> None:
    """KnowledgeIndexed — upsert a note node (label from file path)."""
    try:
        path = payload.get("file_path") or payload.get("path") or ""
        if not path:
            return
        rel = _vault_rel(path)
        async with session_factory()() as db:
            node = await _upsert_node(
                db,
                "note",
                rel,
                str(Path(rel).stem),
                {"vault_path": rel},
            )
            await db.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning("graph knowledge adapter failed: %s", exc)

    # Reactive garden refresh: after any note write, rebuild the Quartz garden
    # (debounced) so new notes appear promptly instead of only at the nightly
    # vault_backup_publish job. Cheap no-op when QUARTZ_TRIGGER_URL is unset.
    _schedule_garden_rebuild()


# ── Reactive Quartz garden rebuild (debounced) ────────────────────────────
_QUARTZ_LOCK = threading.Lock()
_QUARTZ_PENDING = False
_QUARTZ_SCHEDULED_AT = 0.0
_QUARTZ_DEBOUNCE_SECONDS = 30.0


def _schedule_garden_rebuild() -> None:
    """Schedule a debounced POST /rebuild to the Quartz trigger server."""
    global _QUARTZ_PENDING, _QUARTZ_SCHEDULED_AT
    trigger = os.environ.get("QUARTZ_TRIGGER_URL", "").strip()
    if not trigger:
        return
    with _QUARTZ_LOCK:
        _QUARTZ_PENDING = True
        _QUARTZ_SCHEDULED_AT = time.monotonic()
    threading.Thread(target=_quartz_rebuild_worker, args=(trigger,), daemon=True).start()


def _quartz_rebuild_worker(trigger: str) -> None:
    """Wait out the debounce window, then fire one rebuild if still pending."""
    global _QUARTZ_PENDING, _QUARTZ_SCHEDULED_AT
    # Debounce: wait up to the window; if another note landed meanwhile, keep
    # waiting so burst captures coalesce into a single rebuild.
    while True:
        with _QUARTZ_LOCK:
            elapsed = time.monotonic() - _QUARTZ_SCHEDULED_AT
        if elapsed >= _QUARTZ_DEBOUNCE_SECONDS:
            break
        time.sleep(2.0)
    with _QUARTZ_LOCK:
        if not _QUARTZ_PENDING:
            return
        _QUARTZ_PENDING = False
    try:
        req = urllib.request.Request(
            trigger, data=b"{}", method="POST", headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read() or b"{}")
        if body.get("ok"):
            logger.info("quartz garden rebuilt (reactive, %.0fs)", body.get("durationMs", 0))
        else:
            logger.warning("quartz garden rebuild failed: %s", body.get("output", "")[-300:])
    except Exception as exc:  # pragma: no cover - never let this break writes
        logger.warning("quartz garden rebuild trigger failed: %s", exc)


async def graph_subscriber(event: str, payload: dict) -> None:
    """Event-bus subscriber entrypoint (plan §10 / §6)."""
    try:
        if event == "PersonUpdated":
            pid = payload.get("person_id") or payload.get("id")
            if pid:
                await _on_person(pid)
        elif event == "InteractionLogged":
            iid = payload.get("interaction_id") or payload.get("id")
            if iid:
                await _on_interaction(iid)
        elif event == "KnowledgeIndexed":
            await _on_knowledge(payload)
    except Exception as exc:  # pragma: no cover
        logger.warning("graph_subscriber(%s) failed: %s", event, exc)
