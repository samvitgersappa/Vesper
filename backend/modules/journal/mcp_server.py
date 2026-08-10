"""journal module MCP server.

Exposes the vault-backed Journal OS to Hermes Agent (plan.md §4.1, §8.3):
get/write/update/resolve journal entries, mood streaks, and lightweight
expense/workout logging.

Business logic lives in logic/ (deterministic, no LLM). FastMCP keeps each
decorated function's name as the tool name, so these thin wrappers carry the
exact short tool names the Hermes journal.skill contract expects; the
implementations are imported under aliases so wrapper and impl don't collide.
"""

import asyncio

from fastmcp import FastMCP

from backend.modules.db import dispose
from backend.modules.journal.logic import (
    complete_day as _complete_day,
    delete_expense as _delete_expense,
    delete_workout as _delete_workout,
    enrich_entry as _enrich_entry,
    get_entry as _get_entry,
    get_mood_streak as _get_mood_streak,
    log_expense as _log_expense,
    log_workout as _log_workout,
    read_entry as _read_entry,
    resolve as _resolve,
    spending_analysis as _spending_analysis,
    spending_summary as _spending_summary,
    spending_transactions as _spending_transactions,
    update_entry as _update_entry,
    write_entry as _write_entry,
)

mcp = FastMCP("vesper-journal")


@mcp.tool()
async def get_entry(date: str = "") -> dict:
    """Read today's (or `date`'s) journal entry: vault note + diary metadata."""
    return await _get_entry(date)


@mcp.tool()
async def read_entry(date: str = "") -> dict:
    """Read just the vault note content for `date` (no DB metadata)."""
    return await _read_entry(date)


@mcp.tool()
async def write_entry(
    text: str,
    mood: str = "",
    date: str = "",
    source: str = "",
    category: str = "GENERAL",
    tags: list = None,
) -> dict:
    """Append today's vault journal note and upsert the diary metadata row."""
    return await _write_entry(text, mood, date, source, category, tags)


@mcp.tool()
async def update_entry(date: str, new_content: str) -> dict:
    """Rewrite the vault journal note for `date` and refresh its word count."""
    return await _update_entry(date, new_content)


@mcp.tool()
async def resolve(date: str = "") -> dict:
    """Forget/scratch: remove the journal entry (vault note + metadata) for `date`."""
    return await _resolve(date)


@mcp.tool()
async def log_expense(amount: float, category: str = "", date: str = "", raw_text: str = "") -> dict:
    """Log a spending row against the fixed taxonomy (default 'Other')."""
    return await _log_expense(amount, category, date, raw_text)


@mcp.tool()
async def log_workout(activity: str = "workout", muscle_groups: list = None, date: str = "", raw_text: str = "") -> dict:
    """Log a workout row (activity + muscle_groups[])."""
    return await _log_workout(activity, muscle_groups, date, raw_text)


@mcp.tool()
async def delete_expense(spending_id: str) -> dict:
    """Remove a specific spending row by id (self-correction for accidental logs)."""
    return await _delete_expense(spending_id)


@mcp.tool()
async def spending_transactions(limit: int = 50) -> dict:
    """List recent expenses, newest first, with date, category, amount, and id."""
    return await _spending_transactions(limit)


@mcp.tool()
async def spending_summary(period: str = "week") -> dict:
    """Summarize expenses by day for week, month, or year."""
    return await _spending_summary(period)


@mcp.tool()
async def spending_analysis() -> dict:
    """Return category totals, trends, and spending habits from logged expenses."""
    return await _spending_analysis()


@mcp.tool()
async def delete_workout(workout_id: str) -> dict:
    """Remove a specific workout row by id (self-correction for accidental logs)."""
    return await _delete_workout(workout_id)


@mcp.tool()
async def get_mood_streak() -> dict:
    """Consecutive days with a diary entry+mood from today backwards."""
    return await _get_mood_streak()


@mcp.tool()
async def complete_day(date: str = "", complete: bool = True) -> dict:
    """Mark today's journal complete (Daily Journal Questionnaire finishing, §12.1)."""
    return await _complete_day(date, complete)


@mcp.tool()
async def enrich_entry(date: str = "") -> dict:
    """Graph-optimise a journal note: rich frontmatter, prev/next nav, Connected block."""
    return await _enrich_entry(date)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    try:
        main()
    finally:
        asyncio.run(dispose())
