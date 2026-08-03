"""ipo module MCP server.

Exposes the curated Indian IPO calendar to Hermes Agent: `list_all`,
`list_upcoming`, `list_recent`. Read-only — no provider, no writes (the NSE IPO
API is unreachable from dev environments, so the calendar is a curated dataset
in logic/).
"""

import asyncio

from fastmcp import FastMCP

from backend.modules.db import dispose
from backend.modules.ipo.logic import (
    list_all as _list_all,
    list_recent as _list_recent,
    list_upcoming as _list_upcoming,
)

mcp = FastMCP("vesper-ipo")


@mcp.tool()
async def list_all() -> dict:
    """The full curated IPO calendar (upcoming + recent/listed)."""
    return await _list_all()


@mcp.tool()
async def list_upcoming() -> dict:
    """IPOs upcoming or currently open for subscription."""
    return await _list_upcoming()


@mcp.tool()
async def list_recent() -> dict:
    """Recently closed or listed IPOs (newest listing first)."""
    return await _list_recent()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    try:
        main()
    finally:
        asyncio.run(dispose())
