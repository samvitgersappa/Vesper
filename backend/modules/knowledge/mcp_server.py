"""Knowledge module MCP server.

Exposes Knowledge OS tools to Hermes Agent (plan.md §4.1/§9, ADDENDUM §1):
- knowledge_capture (universal capture routing)
- knowledge_search, knowledge_note_content (vault reads)
- knowledge_recall_everything (unified recall fan-out)
- knowledge_update_note, knowledge_delete_note (correction/forgetting)
- knowledge_link_entity (person/entity reference)

Tool names are exactly `knowledge_*` because Hermes skills call them by those
names. FastMCP keeps the decorated function's name as the tool name (verified
via list_tools()). Business logic lives in logic/ (deterministic heuristics,
no LLM).
"""

import asyncio

from fastmcp import FastMCP

from backend.modules.db import dispose
from backend.modules.knowledge.logic import (
    knowledge_capture as capture_impl,
    knowledge_delete_note as delete_note_impl,
    knowledge_link_entity as link_entity_impl,
    knowledge_note_content as note_content_impl,
    knowledge_recall_everything as recall_everything_impl,
    knowledge_search as search_impl,
    knowledge_update_note as update_note_impl,
)

mcp = FastMCP("vesper-knowledge")


@mcp.tool()
async def search(query: str, top_k: int = 5) -> dict:
    """Full-text search across the vault markdown files. No DB needed."""
    return await search_impl(query, top_k)


@mcp.tool()
async def note_content(path: str) -> dict:
    """Return the full content of a vault note by path (relative or absolute)."""
    return await note_content_impl(path)


@mcp.tool()
async def capture(utterance: str, conversation_context: dict = None) -> dict:
    """Universal capture-routing decision point (plan.md §4.1, rules 1-8).

    Routes an arbitrary "remember this" utterance to reminder/expense/workout/
    journal/vault_note/image_note and always mirrors the decision to
    hermes.capture_routing_log.
    """
    return await capture_impl(utterance, conversation_context or {})


@mcp.tool()
async def recall_everything(query: str) -> dict:
    """Fan-out recall across the vault, capture log, and journal entries."""
    return await recall_everything_impl(query)


@mcp.tool()
async def update_note(path: str, new_content: str) -> dict:
    """Overwrite a vault note atomically (temp file + rename)."""
    return await update_note_impl(path, new_content)


@mcp.tool()
async def delete_note(path: str) -> dict:
    """Delete a vault note (refuses paths outside the vault root)."""
    return await delete_note_impl(path)


@mcp.tool()
async def link_entity(entity_name: str, note_path: str = None) -> dict:
    """Record a person/entity reference (persona_only). Does not require existence."""
    return await link_entity_impl(entity_name, note_path)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    try:
        main()
    finally:
        asyncio.run(dispose())
