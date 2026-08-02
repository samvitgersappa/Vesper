"""graph module MCP server.

Exposes the Universal Intelligence Graph (plan.md §10) to Hermes Agent as
`mcp__graph__*` tools: nodes, edges, analytics, community, snapshot. This is
the UNIVERSAL graph over any entity_type — distinct from relationship.graph,
which is the person-only network.

Read-only: never commits. Business logic lives in logic/ (pure network-science
helpers plus read-only queries over graph.graph_nodes / graph.graph_edges /
graph.graph_snapshots). FastMCP keeps each decorated function's name as the
tool name (verified via list_tools()).
"""

import asyncio

from fastmcp import FastMCP

from backend.modules.db import dispose
from backend.modules.graph.logic import (
    analytics as _analytics,
    community as _community,
    edges as _edges,
    nodes as _nodes,
    snapshot as _snapshot,
)

mcp = FastMCP("vesper-graph")


@mcp.tool()
async def nodes(entity_type: str = "", limit: int = 500) -> dict:
    """List universal graph nodes, optionally filtered by entity_type."""
    return await _nodes(entity_type, limit)


@mcp.tool()
async def edges(entity_type: str = "", limit: int = 1000) -> dict:
    """List graph edges with resolved source/target labels."""
    return await _edges(entity_type, limit)


@mcp.tool()
async def analytics(entity_type: str = "") -> dict:
    """Network-science analytics: density, components, degree/betweenness, communities."""
    return await _analytics(entity_type)


@mcp.tool()
async def community(entity_type: str = "") -> dict:
    """Louvain communities (persons) or connected components (other entity types)."""
    return await _community(entity_type)


@mcp.tool()
async def snapshot(as_of: str = "") -> dict:
    """Latest GraphSnapshot payload (or the one closest to as_of). Read-only."""
    return await _snapshot(as_of)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    try:
        main()
    finally:
        asyncio.run(dispose())
