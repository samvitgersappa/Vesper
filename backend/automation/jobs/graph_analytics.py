"""Graph analytics data job (plan.md §12, §10).

Nightly network-science pass over the universal graph: Louvain communities,
betweenness centrality, and structural-hole metrics for every node. Writes the
computed values back onto `graph_nodes` and snapshots the graph state for the
Graph OS Replay scrubber (`graph_snapshots`).

Runs over whatever nodes/edges exist; an empty graph is a successful no-op.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, text

from backend.modules.db import session_factory
from backend.db.postgres.schemas.graph.models import GraphNode, GraphSnapshot
from backend.modules.graph.logic import compute_analytics, detect_communities, _fetch_graph

logger = logging.getLogger("vesper.automation.graph")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def graph_analytics_pass() -> dict:
    """Recompute communities + centrality, persist node scores + a snapshot."""
    try:
        graph = await _fetch_graph()
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        if not nodes:
            logger.info("graph_analytics: no nodes — no-op")
            return {"ok": True, "nodes": 0, "edges": 0}

        analytics = compute_analytics(nodes, edges)
        communities = detect_communities(nodes, edges)

        by_id = {c["id"]: c for c in communities.get("communities", [])}
        centrality = analytics.get("betweenness", {})

        async with session_factory()() as db:
            for n in nodes:
                node = (await db.execute(
                    select(GraphNode).where(GraphNode.id == n["id"])
                )).scalar_one_or_none()
                if node is None:
                    continue
                node.community_id = (by_id.get(n["id"]) or {}).get("community")
                node.betweenness_score = centrality.get(n["id"])
            # Snapshot for Replay (plan §10).
            payload = {
                "nodes": [
                    {
                        "id": n["id"],
                        "label": n.get("label"),
                        "entity_type": n.get("entity_type"),
                        "community_id": (by_id.get(n["id"]) or {}).get("community"),
                    }
                    for n in nodes
                ],
                "edges": [
                    {"source_id": e.get("source_id"), "target_id": e.get("target_id"),
                     "edge_type": e.get("edge_type"), "weight": e.get("weight", 1.0)}
                    for e in edges
                ],
            }
            db.add(GraphSnapshot(as_of=_now(), payload=payload))
            await db.commit()

        return {
            "ok": True,
            "nodes": len(nodes),
            "edges": len(edges),
            "communities": len(by_id),
        }
    except Exception as exc:
        logger.error("graph_analytics_pass failed: %s", exc)
        return {"ok": False, "error": str(exc)}
