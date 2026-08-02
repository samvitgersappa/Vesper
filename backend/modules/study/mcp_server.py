"""study module MCP server.

Exposes Study OS tools to Hermes Agent (plan.md §17, hermes-config/skills/study.skill):
- study.list_tests, study.mock_tests, study.percentiles (read)
- study.create_test, study.add_mock_test (write — study data, no approval gate)

Business logic lives in logic/ (ported from ProjectVesper's tests router).
"""

import asyncio

from fastmcp import FastMCP

from backend.modules.db import dispose
from backend.modules.study.logic import (
    add_mock_test,
    create_test,
    delete_mock_test,
    delete_test,
    list_mock_tests,
    list_tests,
    percentiles,
    readiness,
)

mcp = FastMCP("vesper-study")


@mcp.tool()
async def list_tests() -> dict:
    """List all exams (tests) with mock-test counts, newest first."""
    return {"tests": await list_tests()}


@mcp.tool()
async def mock_tests(test_id: str) -> dict:
    """List mock tests for an exam (test_id)."""
    return {"test_id": test_id, "mock_tests": await list_mock_tests(test_id)}


@mcp.tool()
async def percentiles(test_id: str) -> dict:
    """Percentile rank of each mock test's total_score within its exam."""
    return await percentiles(test_id)


@mcp.tool()
async def readiness(test_id: str) -> dict:
    """Exam-readiness summary: latest percentile, trend, days to target date."""
    return await readiness(test_id)


@mcp.tool()
async def create_test(name: str, target_date: str = "") -> dict:
    """Create an exam. target_date ISO (YYYY-MM-DD) or empty."""
    return await create_test(name, target_date)


@mcp.tool()
async def add_mock_test(
    test_id: str, total_score: float, subject_scores: dict = None, date: str = ""
) -> dict:
    """Record a mock test score for an exam. subject_scores is {subject: score}."""
    return await add_mock_test(test_id, total_score, subject_scores or {}, date)


@mcp.tool()
async def delete_mock_test(mock_id: str) -> dict:
    """Delete a mock test by id."""
    return {"deleted": await delete_mock_test(mock_id)}


@mcp.tool()
async def delete_test(test_id: str) -> dict:
    """Delete an exam and its mock tests."""
    return {"deleted": await delete_test(test_id)}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    try:
        main()
    finally:
        asyncio.run(dispose())
