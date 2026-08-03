"""Universal graph schema (plan.md §10) — generic nodes/edges.

Generic `graph_nodes` and `graph_edges` tables over which ProjectVesper's graph
algorithms (Louvain, betweenness, structural holes) run for any entity type.
Per-entity adapters arrive in Phase 9.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Text, DateTime, JSON,
    ForeignKey, Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, _now, new_uuid

SCHEMA = "graph"


class GraphNode(Base):
    __tablename__ = "graph_nodes"
    __table_args__ = (
        Index("ix_graph_nodes_entity", "entity_type", "ref_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # The domain row this node mirrors: (ref_table, ref_id).
    ref_table: Mapped[Optional[str]] = mapped_column(Text)
    ref_id: Mapped[Optional[str]] = mapped_column(Text)
    label: Mapped[Optional[str]] = mapped_column(Text)
    node_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, default=dict)

    # Network-science outputs (computed by the graph analytics job, plan §9/§12).
    betweenness_score: Mapped[Optional[float]] = mapped_column(Float)
    community_id: Mapped[Optional[str]] = mapped_column(String(100))
    # Force-graph layout coordinates.
    fx: Mapped[Optional[float]] = mapped_column(Float)
    fy: Mapped[Optional[float]] = mapped_column(Float)
    fz: Mapped[Optional[float]] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class GraphEdge(Base):
    __tablename__ = "graph_edges"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("graph.graph_nodes.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("graph.graph_nodes.id", ondelete="CASCADE"), index=True
    )
    edge_type: Mapped[str] = mapped_column(String(50), nullable=False, default="related")
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    edge_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class GraphSnapshot(Base):
    """Replay support (plan §10 / ProjectVesper Replay): per-snapshot graph state.

    Stores a lightweight snapshot of node/edge weights at a point in time so the
    Graph OS Replay scrubber can restore historical graph states without
    re-running analytics. Populated by the graph analytics data job.
    """
    __tablename__ = "graph_snapshots"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    as_of: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    # JSON: {"nodes": [{id,label,entity_type,community_id,weight}],
    #        "edges": [{source_id,target_id,edge_type,weight}]}
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
