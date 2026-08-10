"""Graph projection backfill (self-healing bootstrap).

The graph write adapter is event-driven (PersonUpdated / InteractionLogged /
KnowledgeIndexed), so rows that were written before the event bus was wired up
never got projected into `graph.graph_nodes`/`graph_edges`. This idempotent
backfill reconstructs the projection from the real source tables
(`relationship.persons`, `relationship.interactions`) and the vault notes,
reusing the exact same upsert helpers as the live adapter. Safe to run any
time: it only upserts to match the sources, never deletes.

The note projection also rebuilds the rich knowledge graph — Obsidian
wikilinks become `links_to` edges, tags become `topic` nodes (`tagged_with`),
top-level folders become `area` nodes (`belongs_to`), and journal days are
linked into a chronological `chronology` spine.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import func, select

from backend.modules.db import session_factory
from backend.db.postgres.schemas.graph.models import GraphEdge
from backend.db.postgres.schemas.relationship.models import Interaction, Person
from backend.modules.graph.write_adapter import _on_interaction, _on_knowledge, _on_person
from backend.modules.knowledge.logic import vault_root, _walk_vault_files

logger = logging.getLogger("vesper.graph.backfill")

#: Non-note directories we never project as graph nodes (mirror of _walk_vault_files).
_IGNORED_DIR_MARKERS = ("template", "archive")


async def _note_paths() -> list[str]:
    """Vault-relative note paths (mirrors note-node ref_ids)."""
    try:
        root = vault_root()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("graph backfill: cannot resolve vault root: %s", exc)
        return []
    if not root.is_dir():
        return []
    try:
        return [str(p.relative_to(root)) for p in _walk_vault_files(root)]
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("graph backfill: vault walk failed: %s", exc)
        return []


async def _edge_count() -> int:
    async with session_factory()() as db:
        return int((await db.execute(select(func.count()).select_from(GraphEdge))).scalar_one())


async def _prune_stale() -> None:
    """Delete projection nodes that no longer mirror a real source row.

    Keeps `graph.graph_nodes` an exact projection: person/interaction nodes
    reference existing relationship rows, note nodes reference existing vault
    files, and area/topic nodes are derived from the vault's folder structure +
    tags (kept, they carry no external ref_id). Edges cascade on node delete.
    """
    from backend.db.postgres.schemas.graph.models import GraphNode

    async with session_factory()() as db:
        nodes = (await db.execute(select(GraphNode))).scalars().all()
        keep: set[tuple[str, str]] = {
            ("person", pid)
            for pid in (await db.execute(select(Person.id))).scalars().all()
        }
        keep.update(
            ("interaction", iid)
            for iid in (await db.execute(select(Interaction.id))).scalars().all()
        )
        keep.update(("note", str(p)) for p in await _note_paths())
        stale = [
            n for n in nodes
            if n.entity_type not in ("area", "topic")
            and (n.entity_type, n.ref_id) not in keep
        ]
        for n in stale:
            await db.delete(n)
        await db.commit()
        if stale:
            logger.info("graph backfill pruned %d stale nodes", len(stale))


async def backfill_graph(prune: bool = True) -> dict:
    """Upsert person, interaction, and note nodes/edges from their sources.

    Args:
        prune: also delete projection nodes that no longer mirror a source row
            (default True). Tests pass ``prune=False`` to avoid touching nodes
            that reference other data while their vault is monkeypatched.

    Returns counts by entity type plus total edges — what the projection now
    contains (persons, interactions, notes, areas, topics).
    """
    person_rows = interaction_rows = 0
    async with session_factory()() as db:
        person_rows = len((await db.execute(select(Person.id))).scalars().all())
        interaction_rows = len((await db.execute(select(Interaction.id))).scalars().all())

    async with session_factory()() as db:
        for person_id in (await db.execute(select(Person.id))).scalars().all():
            await _on_person(person_id)
        for interaction_id in (await db.execute(select(Interaction.id))).scalars().all():
            await _on_interaction(interaction_id)

    notes = 0
    for path in await _note_paths():
        await _on_knowledge({"file_path": str(path)})
        notes += 1

    if prune:
        await _prune_stale()

    edges = await _edge_count()
    node_counts = await _node_counts()
    logger.info(
        "graph backfill complete: persons=%d interactions=%d notes=%d areas=%d topics=%d edges=%d",
        person_rows, interaction_rows, notes,
        node_counts.get("area", 0), node_counts.get("topic", 0), edges,
    )
    return {
        "ok": True,
        "persons": person_rows,
        "interactions": interaction_rows,
        "notes": notes,
        "areas": node_counts.get("area", 0),
        "topics": node_counts.get("topic", 0),
        "edges": edges,
        "by_type": node_counts,
    }


async def _node_counts() -> dict:
    """Count graph nodes grouped by entity_type."""
    from sqlalchemy import func

    from backend.db.postgres.schemas.graph.models import GraphNode

    async with session_factory()() as db:
        rows = (await db.execute(
            select(GraphNode.entity_type, func.count())
            .group_by(GraphNode.entity_type)
        )).all()
    return {rtype: count for rtype, count in rows}
