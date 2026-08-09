"""Regression coverage for vault-backed journal writes."""

from __future__ import annotations


async def test_write_entry_publishes_without_file_abs_failure(tmp_path, monkeypatch):
    from backend.modules.journal import logic

    monkeypatch.setenv("HERMES_VAULT_PATH", str(tmp_path))

    async def fake_metadata(**_kwargs):
        return {"entry_id": "test-entry", "created": True}

    events = []
    monkeypatch.setattr(logic, "_upsert_entry_metadata", fake_metadata)
    monkeypatch.setattr(logic, "publish", lambda *args: events.append(args))

    result = await logic.write_entry("A durable journal write.", date="2099-01-01")

    assert result["ok"] is True
    assert result["entry_id"] == "test-entry"
    assert any(event[0] == logic.KNOWLEDGE_INDEXED for event in events)
