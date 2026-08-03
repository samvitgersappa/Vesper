"""relationship module MCP server.

Exposes the Relationship OS to Hermes Agent (plan.md §8.1, §16, people.skill):
search, person detail, due-today, graph/communities/bridges/introduction
candidates, meeting prep, interactions, stats, and write tools (log
interaction, create/update/archive person, notes, reminders).

Business logic lives in logic/ (ported from ProjectVesper's mcp_server.py and
health service). The logic functions carry the exact required tool names; the
thin wrappers here register them on the FastMCP server (which keeps the
declared function name as the tool name) and are imported under aliases so the
wrapper and the implementation don't collide.
"""

import asyncio

from fastmcp import FastMCP

from backend.modules.db import dispose
from backend.modules.relationship.logic import (
    relationship_add_note as _add_note,
    relationship_add_reminder as _add_reminder,
    relationship_create_person as _create_person,
    relationship_delete_person as _delete_person,
    relationship_draft_message as _draft_message,
    relationship_get_bridge_contacts as _get_bridge_contacts,
    relationship_get_communities as _get_communities,
    relationship_get_due_today as _get_due_today,
    relationship_get_interactions as _get_interactions,
    relationship_get_introduction_candidates as _get_introduction_candidates,
    relationship_get_meeting_prep as _get_meeting_prep,
    relationship_get_recent_activity as _get_recent_activity,
    relationship_get_stats as _get_stats,
    relationship_graph as _graph,
    relationship_log_interaction as _log_interaction,
    relationship_person_detail as _person_detail,
    relationship_search as _search,
    relationship_update_person as _update_person,
)

mcp = FastMCP("vesper-relationship")


@mcp.tool()
async def search(query: str, limit: int = 10) -> dict:
    """Search contacts by name, company, occupation, bio, or city (ILIKE)."""
    return await _search(query, limit)


@mcp.tool()
async def person_detail(person_id: str) -> dict:
    """Full profile for a person: fields, recent interactions, tags, notes, life events, gift ideas."""
    return await _person_detail(person_id)


@mcp.tool()
async def get_due_today() -> dict:
    """Who needs attention: overdue, cold, upcoming birthdays, open follow-ups."""
    return await _get_due_today()


@mcp.tool()
async def graph(limit: int = 200) -> dict:
    """Relationship graph: nodes (people) + edges, with betweenness and communities."""
    return await _graph(limit)


@mcp.tool()
async def get_bridge_contacts(limit: int = 5) -> dict:
    """Top contacts by betweenness centrality — information brokers."""
    return await _get_bridge_contacts(limit)


@mcp.tool()
async def suggested(limit: int = 5) -> dict:
    """Pairs who should know each other but don't, scored by shared interests."""
    return await _get_introduction_candidates(limit)


@mcp.tool()
async def get_communities() -> dict:
    """Louvain community groupings — your social circles."""
    return await _get_communities()


@mcp.tool()
async def get_meeting_prep(person_id: str) -> dict:
    """Full context for meeting someone: profile, last interaction, follow-ups, events, gifts, notes."""
    return await _get_meeting_prep(person_id)


@mcp.tool()
async def get_interactions(person_id: str, limit: int = 10) -> dict:
    """Interaction history for a person, newest first."""
    return await _get_interactions(person_id, limit)


@mcp.tool()
async def get_recent_activity(limit: int = 20) -> dict:
    """Global feed of recent interactions across all contacts."""
    return await _get_recent_activity(limit)


@mcp.tool()
async def get_stats() -> dict:
    """Network dashboard: totals, weekly interactions, cold contacts, health distribution."""
    return await _get_stats()


@mcp.tool()
async def create_interaction(
    person_id: str,
    type: str,
    summary: str,
    date: str = "",
    sentiment: str = "",
    follow_up_needed: bool = False,
    follow_up_note: str = "",
) -> dict:
    """Record an interaction; auto-updates health score and streak."""
    return await _log_interaction(
        person_id, type, summary, date, sentiment, follow_up_needed, follow_up_note
    )


@mcp.tool()
async def create_person(
    name: str,
    company: str = "",
    occupation: str = "",
    category: str = "NETWORK",
    email: str = "",
    phone: str = "",
    notes: str = "",
) -> dict:
    """Add a new contact. Categories: FAMILY, FRIENDS, COLLEAGUES, NETWORK, IMPORTANT, COUSINS, RELATIVES, NEW_CONTACT."""
    return await _create_person(
        name, company, occupation, category, email, phone, notes
    )


@mcp.tool()
async def update_person(person_id: str, field: str, value: str) -> dict:
    """Update one field on a contact; recomputes health when health-relevant."""
    return await _update_person(person_id, field, value)


@mcp.tool()
async def add_note(person_id: str, content: str) -> dict:
    """Append a note to a contact."""
    return await _add_note(person_id, content)


@mcp.tool()
async def add_reminder(
    person_id: str,
    title: str,
    due_at: str,
    reminder_type: str = "custom",
    body: str = "",
) -> dict:
    """Schedule a reminder. due_at: 'tomorrow 9am', 'in 2 hours', 'monday', or ISO."""
    return await _add_reminder(person_id, title, due_at, reminder_type, body)


@mcp.tool()
async def delete_person(person_id: str) -> dict:
    """Soft-delete a contact (is_archived=True)."""
    return await _delete_person(person_id)


@mcp.tool()
async def draft_message(
    person_id: str,
    purpose: str = "reconnect",
    context: str = "",
) -> dict:
    """Draft a message for a contact (reconnect/follow_up/congrats/check_in/custom).

    DRAFT-ONLY — never sends anything. The returned draft requires human
    approval before any real send happens (approvals-style).
    """
    return await _draft_message(person_id, purpose, context)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    try:
        main()
    finally:
        asyncio.run(dispose())
