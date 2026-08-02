"""calendar module MCP server.

Exposes the Calendar module to Hermes Agent (plan.md §5/§8, calendar.skill):
- events(from, to): merged, date-sorted events across birthdays, interactions,
  reminders, life events, and study exam dates.
- birthdays(): contacts with birthdays in the next 30 days.

Business logic lives in logic/ (aggregates event-shaped rows from the
relationship and study schemas; there is no calendar table). The `events` tool's
`from` argument is a Python keyword, so the wrapper uses `from_` and FastMCP's
ArgTransform renames it back to `from` in the exposed input schema. Tool names
are the short names Hermes registers as `mcp__calendar__<tool>`.
"""

import asyncio

from fastmcp import FastMCP
from fastmcp.tools.base import Tool
from fastmcp.tools.tool_transform import ArgTransform

from backend.modules.calendar.logic import birthdays as _birthdays
from backend.modules.calendar.logic import events as _events
from backend.modules.db import dispose

mcp = FastMCP("vesper-calendar")


@mcp.tool()
async def birthdays() -> dict:
    """Contacts with a birthday in the next 30 days, sorted by date."""
    return await _birthdays()


async def _events_impl(from_: str, to: str) -> dict:
    """Merged calendar events between `from` and `to` (ISO or shorthand)."""
    return await _events(from_, to)


mcp.add_tool(
    Tool.from_tool(
        Tool.from_function(_events_impl, name="events"),
        transform_args={"from_": ArgTransform(name="from")},
    )
)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    try:
        main()
    finally:
        asyncio.run(dispose())
