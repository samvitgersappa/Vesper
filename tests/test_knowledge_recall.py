"""Contract tests for the additive unified recall path.

These tests deliberately use a session double: they verify the API/MCP contract
and restart stability without requiring the optional live Postgres container.
"""

from __future__ import annotations

import pytest
import json
import os
import subprocess
import sys


class _EmptyResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, _query):
        return _EmptyResult()

    async def rollback(self):
        return None


class _SessionFactory:
    def __call__(self):
        return _Session()


@pytest.mark.asyncio
async def test_recall_is_deterministic_and_survives_api_worker_hermes_restart(tmp_path, monkeypatch):
    from backend.modules.knowledge import logic
    from backend.modules.knowledge import mcp_server
    from backend.api.routers import api_knowledge_recall

    vault = tmp_path / "vault"
    (vault / "00 Journal" / "2026").mkdir(parents=True)
    (vault / "00 Journal" / "2026" / "2026-08-09.md").write_text(
        "# 2026-08-09\n\nA durable restart fixture about focus."
    )
    monkeypatch.setenv("HERMES_VAULT_PATH", str(vault))
    monkeypatch.delenv("TENCENTDB_AGENT_MEMORY_DB", raising=False)
    monkeypatch.setattr(logic, "session_factory", lambda: _SessionFactory())
    async def fake_search(_query, top_k=20):
        return {"results": [{"file_path": "00 Journal/2026/2026-08-09.md", "title": "focus", "content_preview": "focus"},
                             {"file_path": "duplicate.md", "title": "duplicate", "content_preview": "focus"}]}

    monkeypatch.setattr(logic, "knowledge_search", fake_search)

    first = await api_knowledge_recall("focus")
    # The browser API, worker logic, and Hermes MCP wrapper all use this same
    # persisted path; compare their stable identity after a simulated restart.
    second = await mcp_server.recall_everything("focus")
    third = await api_knowledge_recall("focus")

    assert first["results"] == second["results"] == third["results"]
    assert len(first["results"]) == 1
    assert first["results"][0]["ref_id"].startswith("vault:")
    assert first["results"][0]["sources"]
    statuses = {row["source"]: row["status"] for row in first["source_status"]}
    assert statuses["hermes-tencentdb"] == "not configured"
    assert all("ref_id" in row for row in first["results"])

    script = (
        "import asyncio, json, sys; "
        "from backend.modules.knowledge.logic import knowledge_recall_everything; "
        "from backend.modules.knowledge.mcp_server import recall_everything; "
        "from backend.api.routers import api_knowledge_recall; "
        "f={'api': api_knowledge_recall, 'worker': knowledge_recall_everything, 'hermes': recall_everything}[sys.argv[1]]; "
        "print(json.dumps(asyncio.run(f('focus')), sort_keys=True))"
    )
    process_env = {**os.environ, "PYTHONPATH": os.getcwd(), "DATABASE_URL": "postgresql+asyncpg://vesper:change-me@127.0.0.1:1/vesper"}
    process_env["HERMES_VAULT_PATH"] = str(vault)
    process_env.pop("TENCENTDB_AGENT_MEMORY_DB", None)
    process_results = []
    for mode in ("api", "worker", "hermes"):
        completed = subprocess.run([sys.executable, "-c", script, mode], env=process_env, capture_output=True, text=True, check=True)
        process_results.append(json.loads(completed.stdout))
    assert process_results[0] == process_results[1] == process_results[2]
