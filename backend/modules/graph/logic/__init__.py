"""Universal Intelligence Graph module business logic (plan.md §10).

Reimplements ProjectVesper's network-science operations (Louvain community
detection, betweenness centrality, connected components) over the UNIVERSAL
graph — `graph.graph_nodes` / `graph.graph_edges` / `graph.graph_snapshots` —
for ANY `entity_type`, not just persons (unlike relationship.graph, which is
the person-only network).

This module is READ-ONLY: it never commits. The network math is factored into
pure, DB-free helpers (`compute_analytics` / `detect_communities`) so the
nightly Graph Analytics job and tests can run them over synthetic data.

Tool output shapes:
- `nodes(...)    -> {"nodes": [{id, entity_type, label, community_id, betweenness_score}]}`
- `edges(...)    -> {"edges": [{source_id, source_label, target_id, target_label, edge_type, weight}]}`
- `analytics(...) -> {"nodes, edges, density, connected_components, largest_component_size, top_degree, top_betweenness, communities}"}`
- `community(...) -> {"communities": [{id, members: [{id, label}]}]}`
- `snapshot(...) -> {"as_of, nodes_count, edges_count, payload"}`
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, or_

import networkx as nx

try:  # python-louvain
    import community.community_louvain as community_louvain
except ImportError:  # pragma: no cover - degrades to connected components
    community_louvain = None

import dateutil.parser

from backend.db.postgres.schemas.graph.models import (
    GraphNode, GraphEdge, GraphSnapshot,
)
from backend.modules.db import session_factory

logger = logging.getLogger("vesper.graph")

MAX_LIMIT = 10000


def _now() -> datetime:
    """Offset-naive UTC now (Postgres TIMESTAMP WITHOUT TIME ZONE compat)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_datetime(s: str) -> Optional[datetime]:
    """Parse an ISO-ish datetime string to timezone-naive UTC (defensive)."""
    if not s or not s.strip():
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass
    try:
        return dateutil.parser.parse(s.strip()).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


# ─── Serializers ────────────────────────────────────────────────────

def _node_dict(n: GraphNode) -> dict[str, Any]:
    return {
        "id": n.id,
        "entity_type": n.entity_type,
        "label": n.label,
        "community_id": n.community_id,
        "betweenness_score": round(n.betweenness_score, 4) if n.betweenness_score is not None else None,
    }


def _edge_dict(e: GraphEdge) -> dict[str, Any]:
    return {
        "id": e.id,
        "source_id": e.source_id,
        "target_id": e.target_id,
        "edge_type": e.edge_type,
        "weight": float(e.weight) if e.weight is not None else 1.0,
    }


# ─── Pure network-science helpers (DB-free, testable) ───────────────

def _build_graph(nodes: list[dict], edges: list[dict]) -> nx.Graph:
    """networkx Graph from plain node/edge dicts (induced subgraph).

    Edges whose endpoints are not both present in `nodes` (or that are
    self-loops) are dropped, so an entity_type-filtered node set naturally
    yields the induced subgraph on that type.
    """
    G = nx.Graph()
    ids = {str(n["id"]) for n in nodes}
    for n in nodes:
        G.add_node(str(n["id"]), label=n.get("label"), entity_type=n.get("entity_type"))
    for e in edges:
        src, tgt = str(e["source_id"]), str(e["target_id"])
        if src in ids and tgt in ids and src != tgt:
            G.add_edge(src, tgt, weight=float(e.get("weight") or 1.0))
    return G


def _node_communities(
    nodes: list[dict], edges: list[dict], entity_type: str = ""
) -> dict[str, str]:
    """Map node_id -> community_id string.

    Persons use Louvain (python-louvain) to mirror the relationship module;
    every other entity type (and empty/no-library cases) falls back to
    connected-component clustering.
    """
    G = _build_graph(nodes, edges)
    if G.number_of_nodes() == 0:
        return {}
    if entity_type == "person" and community_louvain is not None:
        try:
            partition = community_louvain.best_partition(G, weight="weight")
            return {str(n): f"community-{c}" for n, c in partition.items()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("louvain failed, falling back to components: %s", exc)
    return {
        str(n): f"component-{i}"
        for i, comp in enumerate(nx.connected_components(G))
        for n in comp
    }


def compute_analytics(
    nodes: list[dict], edges: list[dict], entity_type: str = ""
) -> dict[str, Any]:
    """Pure network-science analytics over in-memory node/edge dicts. No DB.

    Builds a networkx Graph, then computes node/edge count, density, connected
    components, largest component size, top-5 degree centrality, top-5
    betweenness centrality, and communities (Louvain for persons, connected
    components otherwise). Empty graphs return zeros/empty — never raises.
    """
    G = _build_graph(nodes, edges)
    n_nodes = G.number_of_nodes()
    n_edges = G.number_of_edges()

    if n_nodes == 0:
        return {
            "entity_type": entity_type or "all",
            "nodes": 0,
            "edges": 0,
            "density": 0.0,
            "connected_components": 0,
            "largest_component_size": 0,
            "top_degree": [],
            "top_betweenness": [],
            "communities": [],
        }

    labels = {str(n): G.nodes[n].get("label") for n in G.nodes}
    density = nx.density(G)
    components = list(nx.connected_components(G))
    n_components = len(components)
    largest = max((len(c) for c in components), default=0)

    degree = nx.degree_centrality(G)
    top_degree = [
        {"id": str(n), "label": labels.get(str(n)), "score": round(float(s), 4)}
        for n, s in sorted(degree.items(), key=lambda kv: -kv[1])[:5]
    ]

    betweenness: dict = {}
    if n_nodes >= 2:
        try:
            betweenness = nx.betweenness_centrality(G, weight="weight")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("betweenness centrality failed: %s", exc)
    top_betweenness = [
        {"id": str(n), "label": labels.get(str(n)), "score": round(float(s), 4)}
        for n, s in sorted(betweenness.items(), key=lambda kv: -kv[1])[:5]
    ]

    comm_map = _node_communities(nodes, edges, entity_type)
    grouped: dict[str, list[str]] = {}
    for nid, cid in comm_map.items():
        grouped.setdefault(cid, []).append(nid)
    communities = [
        {"id": cid, "member_count": len(members)}
        for cid, members in sorted(grouped.items(), key=lambda kv: -len(kv[1]))
    ]

    return {
        "entity_type": entity_type or "all",
        "nodes": n_nodes,
        "edges": n_edges,
        "density": round(float(density), 4),
        "connected_components": n_components,
        "largest_component_size": largest,
        "top_degree": top_degree,
        "top_betweenness": top_betweenness,
        "communities": communities,
    }


def detect_communities(
    nodes: list[dict], edges: list[dict], entity_type: str = ""
) -> list[dict]:
    """Pure community detection over in-memory node/edge dicts. No DB.

    Returns [{"id": community_id, "members": [{"id", "label"}]}] sorted by
    member count descending. Persons use Louvain; other entity types use
    connected components.
    """
    comm_map = _node_communities(nodes, edges, entity_type)
    labels = {str(n["id"]): n.get("label") for n in nodes}
    grouped: dict[str, list[dict]] = {}
    for nid in comm_map:
        grouped.setdefault(comm_map[nid], []).append(
            {"id": nid, "label": labels.get(nid)}
        )
    return [
        {"id": cid, "members": members}
        for cid, members in sorted(grouped.items(), key=lambda kv: -len(kv[1]))
    ]


# ─── DB reads (read-only, never commit) ─────────────────────────────

async def _fetch_graph(entity_type: str = ""):
    """Fetch (nodes, edges) from the universal graph tables.

    Edges are limited to those touching the filtered node set; the pure helpers
    further reduce to the induced subgraph when a filter is active.
    """
    et = (entity_type or "").strip()
    async with session_factory()() as db:
        node_stmt = select(GraphNode)
        if et:
            node_stmt = node_stmt.where(GraphNode.entity_type == et)
        node_res = await db.execute(node_stmt.order_by(GraphNode.created_at.asc()))
        nodes = node_res.scalars().all()

        edges = []
        if nodes:
            ids = {n.id for n in nodes}
            edge_stmt = select(GraphEdge).where(
                or_(GraphEdge.source_id.in_(ids), GraphEdge.target_id.in_(ids))
            ).order_by(GraphEdge.created_at.asc())
            edge_res = await db.execute(edge_stmt)
            edges = edge_res.scalars().all()
    return nodes, edges


# ─── Public tools (async, exactly `nodes/edges/analytics/community/snapshot`) ───

async def nodes(entity_type: str = "", limit: int = 500) -> dict[str, Any]:
    """List universal graph nodes, optionally filtered by entity_type."""
    et = (entity_type or "").strip()
    k = max(1, min(int(limit), MAX_LIMIT))
    async with session_factory()() as db:
        stmt = select(GraphNode)
        if et:
            stmt = stmt.where(GraphNode.entity_type == et)
        res = await db.execute(stmt.order_by(GraphNode.created_at.asc()).limit(k))
        rows = res.scalars().all()
    node_list = [_node_dict(n) for n in rows]
    return {"entity_type": et or "all", "nodes": node_list, "count": len(node_list)}


async def edges(entity_type: str = "", limit: int = 1000) -> dict[str, Any]:
    """List graph edges with resolved source/target labels (universal graph)."""
    et = (entity_type or "").strip()
    k = max(1, min(int(limit), MAX_LIMIT))
    async with session_factory()() as db:
        node_res = await db.execute(select(GraphNode))
        all_nodes = node_res.scalars().all()
        edge_res = await db.execute(select(GraphEdge).order_by(GraphEdge.created_at.asc()))
        all_edges = edge_res.scalars().all()

    id_to_label = {n.id: n.label for n in all_nodes}
    node_ids = {n.id for n in all_nodes if n.entity_type == et} if et else set()

    edge_list = []
    for e in all_edges:
        if et and (e.source_id not in node_ids or e.target_id not in node_ids):
            continue
        edge_list.append({
            "source_id": e.source_id,
            "source_label": id_to_label.get(e.source_id),
            "target_id": e.target_id,
            "target_label": id_to_label.get(e.target_id),
            "edge_type": e.edge_type,
            "weight": float(e.weight) if e.weight is not None else 1.0,
        })
        if len(edge_list) >= k:
            break
    return {"entity_type": et or "all", "edges": edge_list, "count": len(edge_list)}


async def analytics(entity_type: str = "") -> dict[str, Any]:
    """Network-science analytics over the universal graph (filtered by entity_type)."""
    et = (entity_type or "").strip()
    node_rows, edge_rows = await _fetch_graph(et)
    node_list = [_node_dict(n) for n in node_rows]
    edge_list = [_edge_dict(e) for e in edge_rows]
    return compute_analytics(node_list, edge_list, et)


async def community(entity_type: str = "") -> dict[str, Any]:
    """Louvain communities (persons) or connected components (other types)."""
    et = (entity_type or "").strip()
    node_rows, edge_rows = await _fetch_graph(et)
    node_list = [_node_dict(n) for n in node_rows]
    edge_list = [_edge_dict(e) for e in edge_rows]
    communities = detect_communities(node_list, edge_list, et)
    return {
        "entity_type": et or "all",
        "communities": communities,
        "count": len(communities),
    }


async def snapshot(as_of: str = "") -> dict[str, Any]:
    """Latest GraphSnapshot payload (or the one closest to `as_of`). Read-only."""
    target = _parse_datetime(as_of) if as_of and as_of.strip() else None
    async with session_factory()() as db:
        if target is not None:
            snap_res = await db.execute(
                select(GraphSnapshot).order_by(GraphSnapshot.as_of.asc())
            )
            snaps = snap_res.scalars().all()
            snap_row = min(
                snaps,
                key=lambda s: abs((s.as_of - target).total_seconds())
                if s.as_of else float("inf"),
            ) if snaps else None
        else:
            snap_res = await db.execute(
                select(GraphSnapshot).order_by(GraphSnapshot.as_of.desc()).limit(1)
            )
            snap_row = snap_res.scalar_one_or_none()

    if snap_row is None:
        return {"found": False, "as_of": None, "nodes_count": 0, "edges_count": 0, "payload": None}

    payload = snap_row.payload if isinstance(snap_row.payload, dict) else {}
    nodes_list = payload.get("nodes", []) if isinstance(payload, dict) else []
    edges_list = payload.get("edges", []) if isinstance(payload, dict) else []
    nodes_count = len(nodes_list) if isinstance(nodes_list, list) else 0
    edges_count = len(edges_list) if isinstance(edges_list, list) else 0

    return {
        "found": True,
        "as_of": snap_row.as_of.isoformat() if snap_row.as_of else None,
        "nodes_count": nodes_count,
        "edges_count": edges_count,
        "payload": payload,
    }
