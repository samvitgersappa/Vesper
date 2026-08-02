"""hobbies module MCP server.

Exposes read/write over the `persons.hobbies` JSON column (plan.md §8/§13):
`hobbies.list_all`, `hobbies.get`, `hobbies.add`, `hobbies.remove`,
`hobbies.set`. Tool names are the short forms (hermes registers them as
`mcp__hobbies__<tool>`). Business logic lives in logic/.
"""

import asyncio

from fastmcp import FastMCP

from backend.modules.db import dispose
from backend.modules.hobbies.logic import (
    add_hobby as _add_hobby,
    get_person_hobbies as _get_person_hobbies,
    list_all as _list_all,
    remove_hobby as _remove_hobby,
    set_hobbies as _set_hobbies,
)

mcp = FastMCP("vesper-hobbies")


@mcp.tool()
async def list_all() -> dict:
    """Every hobby across active contacts + a count of people sharing it."""
    return await _list_all()


@mcp.tool()
async def get(person_id: str) -> dict:
    """Return one contact's hobbies list."""
    return await _get_person_hobbies(person_id)


@mcp.tool()
async def add(person_id: str, hobby: str) -> dict:
    """Add a hobby to a contact (no-op if already present)."""
    return await _add_hobby(person_id, hobby)


@mcp.tool()
async def remove(person_id: str, hobby: str) -> dict:
    """Remove a hobby from a contact (case-insensitive)."""
    return await _remove_hobby(person_id, hobby)


@mcp.tool()
async def set(person_id: str, hobbies: list[str]) -> dict:
    """Replace a contact's entire hobbies list."""
    return await _set_hobbies(person_id, hobbies)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    try:
        main()
    finally:
        asyncio.run(dispose())
