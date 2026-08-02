"""finance module MCP server.

Exposes the Finance OS to Hermes Agent (plan.md §16, portfolio.skill):
`portfolio`, `trades`, `signals` (the required contract names) plus a read-only
`nav` helper. This server is STRICTLY READ-ONLY — no trade execution, no broker
access, no DB writes (plan.md §16, coding_prompt Phase 4 rule 5). Every tool is
SELECT-only; the worker/scheduler remains the only writer to the finance schema.

Business logic lives in logic/; the thin wrappers here register the tools on
the FastMCP server (which keeps the declared function name as the tool name)
and are imported under aliases so wrapper and implementation don't collide.
"""

import asyncio

from fastmcp import FastMCP

from backend.modules.db import dispose
from backend.modules.finance.logic import (
    nav as _nav,
    portfolio as _portfolio,
    signals as _signals,
    trades as _trades,
)

mcp = FastMCP("vesper-finance")


@mcp.tool()
async def portfolio(strategy: str = "") -> dict:
    """Account summary + holdings for a trader (or all traders if strategy empty). Read-only."""
    return await _portfolio(strategy)


@mcp.tool()
async def trades(strategy: str = "", limit: int = 20) -> dict:
    """Recent executed trades (newest first). Read-only."""
    return await _trades(strategy, limit)


@mcp.tool()
async def signals(strategy: str = "", limit: int = 20) -> dict:
    """Pending/triggered signals from the paper-trade log. Read-only."""
    return await _signals(strategy, limit)


@mcp.tool()
async def nav(strategy: str = "", limit: int = 60) -> dict:
    """Latest NAV series per trader. Read-only."""
    return await _nav(strategy, limit)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    try:
        main()
    finally:
        asyncio.run(dispose())
