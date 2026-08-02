"""Phase 10 integration tests (plan.md §18 item 10).

Run against the live Postgres (Docker) + real vault on this machine. Requires
the stack to be up (`docker compose up -d postgres redis`) — these are
integration tests by design, not mocks. `lancedb` tests use a temp index.
"""

from __future__ import annotations

# asyncio_mode = auto in pytest.ini: async `def test_` functions are detected
# automatically; sync tests stay sync. No global mark needed.


# ── Relationship OS ─────────────────────────────────────────────────────
async def test_relationship_stats_shape():
    from backend.modules.relationship.logic import relationship_get_stats

    stats = await relationship_get_stats()
    assert "total_contacts" in stats
    assert isinstance(stats["total_contacts"], int)
    assert stats["total_contacts"] >= 0
    assert "top_contacts" in stats
    assert isinstance(stats["top_contacts"], list)


async def test_relationship_search_known_person():
    from backend.modules.relationship.logic import relationship_search

    res = await relationship_search("Chloe", limit=5)
    assert isinstance(res.get("results"), list)
    names = [p["name"] for p in res.get("results", [])]
    assert any("Chloe" in n for n in names)


# ── Journal ─────────────────────────────────────────────────────────────
async def test_journal_streak_shape():
    from backend.modules.journal.logic import get_mood_streak

    res = await get_mood_streak()
    assert res["ok"] is True
    assert isinstance(res["streak"], int)


async def test_journal_complete_day_roundtrip():
    from datetime import date

    from backend.modules.journal.logic import complete_day

    d = date.today()
    res = await complete_day(d.isoformat(), complete=True)
    assert res["ok"] is True
    assert res["complete"] is True
    assert res["date"] == d.isoformat()

    res2 = await complete_day(d.isoformat(), complete=False)
    assert res2["ok"] is True
    assert res2["complete"] is False


async def test_journal_deadline_placeholder_job():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from backend.automation.jobs.journal_deadline import journal_questionnaire_deadline

    # The job writes a placeholder for *today* IST if no row exists yet, then
    # publishes the completion event (complete=False). Today's row is a real one,
    # so it should return ok and never raise.
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    res = await journal_questionnaire_deadline()
    assert res["ok"] is True
    assert res["date"] == today.isoformat()
    assert "placeholder" in res


# ── Graph write adapter (plan §10) ──────────────────────────────────────
async def test_graph_subscriber_person_upsert():
    from backend.modules.graph.write_adapter import graph_subscriber
    from backend.modules.graph.logic import nodes

    # Subscriber returns None by contract; a real person id from the DB should
    # produce a graph node (deterministic md5 id).
    await graph_subscriber("PersonUpdated", {
        "person_id": "b266dac8-af78-4767-ac7d-95122141531c",
        "name": "Chloe Martin",
    })
    res = await nodes(entity_type="person", limit=10)
    assert res.get("count", 0) >= 1


# ── LanceDB (plan §13) ──────────────────────────────────────────────────
async def test_lancedb_index_and_search(tmp_path):
    from backend.db import lancedb_client

    vault = tmp_path / "vault"
    (vault / "daily").mkdir(parents=True)
    (vault / "daily" / "2026-08-02.md").write_text(
        "Focused deep work on the graph adapter and its node upsert today."
    )
    (vault / "books.md").write_text("The Pragmatic Programmer — apply what you learn.")

    old = lancedb_client.LANCEDB_PATH
    lancedb_client.LANCEDB_PATH = str(tmp_path / "index")
    try:
        idx = lancedb_client.index_vault(str(vault))
        assert idx["ok"] is True
        assert idx["indexed"] == 2

        hits = lancedb_client.search("graph adapter", top_k=2, vault_root=str(vault))
        assert len(hits) >= 1
        assert hits[0]["file_path"].endswith("2026-08-02.md")
    finally:
        lancedb_client.LANCEDB_PATH = old


# ── Scheduler registration ──────────────────────────────────────────────
def test_scheduler_registers_all_jobs():
    from backend.automation.scheduler import JOB_SCHEDULE, _register_all

    expected = {
        "fetch_equity", "compute_factors", "fetch_macro", "update_universe",
        "paper_trade_eod", "knowledge_architect_pass", "graph_analytics_pass",
        "crm_followups_sweep", "rss_process", "index_vault_semantic",
        "journal_questionnaire_deadline", "vault_backup_publish",
        "hermes_mirror", "notification_sweep_morning", "notification_sweep_evening",
    }
    assert set(JOB_SCHEDULE) >= expected
    _register_all()


# ── Finance feature store ────────────────────────────────────────────────
async def test_finance_compute_factors_from_synthetic_prices():
    """compute_factors persists to the DuckDB feature store (tmp DB, offline)."""
    import os
    from datetime import date

    import pandas as pd

    from backend.db import feature_store
    from backend.db.duckdb_client import client

    old_path = client.db_path
    tmp_db = "/tmp/vesper-feature-store-test.duckdb"
    if os.path.exists(tmp_db):
        os.unlink(tmp_db)
    client.db_path = tmp_db
    try:
        dates = pd.bdate_range("2024-01-01", periods=210)
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                "Date": d.date(),
                "Symbol": "TEST.NS",
                "Open": 100.0, "High": 101.0, "Low": 99.0,
                "Close": 100.0 + i, "Volume": 1000,
            })
        feature_store.write_equity(pd.DataFrame(rows))
        feature_store.ensure_schema()

        closes = feature_store.equity_closes("TEST.NS")
        assert closes.shape[1] == 1  # one symbol, wide pivot

        from backend.automation.jobs.finance import compute_factors
        res = await compute_factors()
        assert res["ok"] is True
        assert res.get("rows", 0) > 0

        fac = feature_store.client.df(
            "SELECT Symbol, ret_1d, momentum_6m, vol_20d FROM factor_features LIMIT 1"
        )
        assert not fac.empty
        assert fac.iloc[0]["Symbol"] == "TEST.NS"
        assert fac.iloc[0]["vol_20d"] is not None
    finally:
        client.db_path = old_path
        if os.path.exists(tmp_db):
            os.unlink(tmp_db)


async def test_finance_update_universe_refreshes_membership():
    from backend.db import feature_store

    res = feature_store.upsert_membership(["AAA.NS", "BBB.NS"], index_name="Nifty 500")
    assert res == 2
    symbols = feature_store.universe_symbols()
    assert isinstance(symbols, list)
    assert all(s.endswith(".NS") for s in symbols)


# ── Notification triage (anti-nagging; no delivery in tests) ────────────
async def test_notification_triage_runs(monkeypatch):
    from backend.notification import triage

    # Stub delivery so tests never send to Telegram.
    async def _noop(_m):  # noqa: ANN001
        return None

    monkeypatch.setattr("backend.notification.send_telegram", _noop)
    messages = await triage()
    assert isinstance(messages, list)


# ── API endpoints (TestClient) ──────────────────────────────────────────
def test_api_endpoints():
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    for path in [
        "/api/relationship/stats",
        "/api/journal/streak",
        "/api/study/readiness",
        "/api/calendar/birthdays",
        "/api/hobbies",
        "/api/graph/nodes",
        "/api/graph/analytics",
        "/api/finance/portfolio",
    ]:
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} -> {resp.status_code}: {resp.text}"


# ── Event catalog ───────────────────────────────────────────────────────
def test_event_catalog_has_new_events():
    from backend.events.catalog import DAILY_JOURNAL_COMPLETED, all_events

    assert DAILY_JOURNAL_COMPLETED in all_events()
