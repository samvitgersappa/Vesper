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

import logging
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
