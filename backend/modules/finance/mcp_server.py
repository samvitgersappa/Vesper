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
from backend.modules.finance.logic import catalyst as _catalyst

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


@mcp.tool()
async def catalyst_scores(date: str = "", limit: int = 50) -> dict:
    """Catalyst swing-trader scores (Layer 1/2/3 + composite), best first. Read-only."""
    return await _catalyst.scores(date or None, limit)


@mcp.tool()
async def catalyst_candidates(date: str = "", limit: int = 100) -> dict:
    """Catalyst swing-trader watchlist funnel log. Read-only."""
    return await _catalyst.candidates(date or None, limit)


@mcp.tool()
async def catalyst_positions() -> dict:
    """Open catalyst swing positions with stop/target bookkeeping. Read-only."""
    return await _catalyst.positions()


@mcp.tool()
async def catalyst_usage(limit: int = 30) -> dict:
    """Catalyst LLM daily budget usage + recent audit trail. Read-only."""
    return await _catalyst.usage(limit)


@mcp.tool()
async def catalyst_cost_gate(date: str = "", limit: int = 50) -> dict:
    """Recent catalyst cost-gate estimates (slippage vs target PnL). Read-only."""
    return await _catalyst.cost_gate(date or None, limit)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    try:
        main()
    finally:
        asyncio.run(dispose())
