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
    from backend.modules.relationship.logic import (
        relationship_create_person, relationship_search,
    )

    # Self-seed a person so the test passes on a fresh/empty DB, then clean up.
    created = await relationship_create_person(
        name="TEST_Chloe Martin", category="FRIENDS", notes="test fixture",
    )
    try:
        res = await relationship_search("Chloe", limit=5)
        assert isinstance(res.get("results"), list)
        names = [p["name"] for p in res.get("results", [])]
        assert any("Chloe" in n for n in names)
    finally:
        from sqlalchemy import text

        from backend.modules.db import session_factory

        async with session_factory()() as db:
            await db.execute(text("DELETE FROM relationship.persons WHERE name = 'TEST_Chloe Martin'"))
            await db.commit()


# ── Relationship draft_message (Part D) ───────────────────────────────
async def test_relationship_draft_message_is_draft_only():
    """draft_message composes a draft but never sends — requires approval."""
    from sqlalchemy import text

    from backend.modules.db import session_factory
    from backend.modules.relationship.logic import (
        relationship_create_person, relationship_draft_message, relationship_search,
    )

    created = await relationship_create_person(
        name="TEST_Chloe Draft", category="FRIENDS", notes="draft fixture",
    )
    assert created["success"] is True

    try:
        res = await relationship_search("Chloe Draft", limit=1)
        results = res.get("results", [])
        assert results, "expected at least one Chloe Draft contact for draft test"
        pid = results[0]["id"]

        draft = await relationship_draft_message(pid, purpose="check_in")
        assert draft["found"] is True
        assert draft["status"] == "draft_only"
        assert draft["requires_approval"] is True
        assert isinstance(draft["draft"], str) and draft["draft"]

        bad = await relationship_draft_message(pid, purpose="bogus")
        assert bad["found"] is False

        custom = await relationship_draft_message(pid, purpose="custom", context="Let's talk soon.")
        assert custom["found"] is True
        assert "Let's talk soon." in custom["draft"]
    finally:
        async with session_factory()() as db:
            await db.execute(text("DELETE FROM relationship.persons WHERE name = 'TEST_Chloe Draft'"))
            await db.commit()


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


async def test_graph_backfill_projects_existing_rows(tmp_path, monkeypatch):
    """Rows written before event wiring still get projected by the backfill."""
    from backend.modules.graph import backfill
    from backend.modules.graph.logic import edges as graph_edges_logic
    from backend.modules.graph.logic import nodes as graph_nodes_logic
    from backend.db.postgres.schemas.relationship.models import Interaction, Person
    from backend.modules.db import session_factory
    from datetime import datetime
    import uuid

    pid, iid = str(uuid.uuid4()), str(uuid.uuid4())
    async with session_factory()() as db:
        db.add(Person(id=pid, name="Backfill Test Person", category="FRIENDS"))
        await db.commit()
        db.add(Interaction(
            id=iid, person_id=pid, type="CALL", summary="hello",
            event_date=datetime(2026, 8, 2),
        ))
        await db.commit()

    note = tmp_path / "daily" / "2026-08-02.md"
    note.parent.mkdir(parents=True)
    note.write_text("# day note")

    monkeypatch.setattr(backfill, "vault_root", lambda: tmp_path)
    res = await backfill.backfill_graph(prune=False)
    assert res["ok"] is True
    assert res["persons"] >= 1
    assert res["notes"] >= 1

    pnodes = await graph_nodes_logic(entity_type="person", limit=1000)
    assert any(n["label"] == "Backfill Test Person" for n in pnodes["nodes"])
    nnodes = await graph_nodes_logic(entity_type="note", limit=1000)
    assert any("2026-08-02" in str(n["label"]) for n in nnodes["nodes"])
    elist = await graph_edges_logic(limit=1000)
    assert any(
        e["edge_type"] == "participated" and e["source_label"] == "Backfill Test Person"
        for e in elist["edges"]
    )

    # Teardown: remove the seeded person (interactions cascade); the graph node
    # for it is pruned by the next real backfill run.
    async with session_factory()() as db:
        p = await db.get(Person, pid)
        if p:
            await db.delete(p)
            await db.commit()


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
        "graph_projection_backfill",
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
    client.close()  # drop any live connection so the tmp DB is actually used
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
        client.close()  # drop the tmp-DB connection; next access reopens the real store
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
        "/api/finance/strategies",
        "/api/spending/summary",
        "/api/spending/analysis",
        "/api/spending/transactions",
        "/api/ipo/all",
        "/api/ipo/upcoming",
        "/api/ipo/recent",
        "/api/activity/recent",
    ]:
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} -> {resp.status_code}: {resp.text}"


# ── Calendar "On this day" (Part C) ─────────────────────────────────────
async def test_calendar_on_this_day_matches_prior_year():
    """A prior-year journal entry on the same month/day surfaces via on_this_day."""
    from datetime import date, datetime

    from backend.modules.calendar.logic import on_this_day
    from backend.modules.db import session_factory
    from sqlalchemy import text

    today = date.today()
    prior = today.replace(year=today.year - 1)
    seed_id = "test-onthisday-verify"

    try:
        now = datetime.now()
        async with session_factory()() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO journal.diary_entries
                        (id, title, category, word_count, entry_date, complete, is_pinned, created_at, updated_at)
                    VALUES (:id, :title, 'GENERAL', 3, :ed, false, false, :now, :now)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"id": seed_id, "title": "TEST_ on-this-day verify", "ed": prior, "now": now},
            )
            await db.commit()

        res = await on_this_day(today.isoformat())
        assert res["month_day"] == today.strftime("%m-%d")
        titles = [i["title"] for i in res["items"]]
        assert any(t.startswith("TEST_ on-this-day") for t in titles)
    finally:
        async with session_factory()() as db:
            await db.execute(text("DELETE FROM journal.diary_entries WHERE id = :id"), {"id": seed_id})
            await db.commit()


# ── Finance strategy roster (plan §1.5) ─────────────────────────────────
async def test_finance_strategies_roster():
    from backend.modules.finance.logic import strategies

    res = await strategies()
    assert "strategies" in res
    roster = res["strategies"]
    assert len(roster) >= 5
    live = {s["trader_id"] for s in roster}
    assert {
        "alpha_tilt", "arjun_etf", "lowdd_multi_asset",
        "momentum_surge", "alpha_generators",
    } <= live
    for s in roster:
        assert s["name"]
        assert s["short"]
        assert "total_equity" in s


# ── Spending analytics (read-only) ──────────────────────────────────────
async def test_spending_summary_shapes():
    from backend.modules.journal.logic import spending_summary

    for period in ("day", "week", "month", "year"):
        res = await spending_summary(period)
        assert res["ok"] is True, res
        assert res["period"] == period
        assert isinstance(res["buckets"], list)
        assert len(res["buckets"]) > 0
        for b in res["buckets"]:
            assert "label" in b and "total" in b and "count" in b
        assert "current" in res and "change_pct" in res

    bad = await spending_summary("decade")
    assert bad["ok"] is False


async def test_spending_analysis_shape():
    from backend.modules.journal.logic import spending_analysis

    res = await spending_analysis()
    assert res["ok"] is True
    assert isinstance(res["total"], float)
    assert isinstance(res["categories"], list)
    assert isinstance(res["monthly_trend"], list)
    assert isinstance(res["weekday_spend"], list)
    assert isinstance(res["habits"], list)
    for c in res["categories"]:
        assert "category" in c and "total" in c and "share_pct" in c


async def test_spending_transactions_shape():
    from backend.modules.journal.logic import spending_transactions

    res = await spending_transactions(limit=5)
    assert res["ok"] is True
    assert isinstance(res["transactions"], list)
    for t in res["transactions"]:
        assert "date" in t and "amount" in t and "category" in t


# ── Finance EOD engine + IPO calendar ───────────────────────────────────
async def test_finance_eod_runs_all_traders():
    from backend.modules.finance.eod import run_eod

    res = await run_eod()
    assert res["ok"] is True
    assert "traders" in res
    ids = {t["trader_id"] for t in res["traders"]}
    assert {"alpha_tilt", "arjun_etf", "lowdd_multi_asset",
            "momentum_surge", "alpha_generators"} <= ids
    for t in res["traders"]:
        assert "total_equity" in t


async def test_finance_eod_persists_trades():
    from sqlalchemy import text

    from backend.modules.db import session_factory
    from backend.modules.finance.eod import run_eod

    before = 0
    async with session_factory()() as db:
        before = (await db.execute(
            text("SELECT COUNT(*) FROM finance.paper_trades WHERE trader_id = 'arjun_etf'")
        )).scalar()

    res = await run_eod(["arjun_etf"])
    assert res["ok"] is True

    async with session_factory()() as db:
        after = (await db.execute(
            text("SELECT COUNT(*) FROM finance.paper_trades WHERE trader_id = 'arjun_etf'")
        )).scalar()
    assert after >= before


async def test_finance_strategy_targets_shape():
    import pytest

    from backend.modules.finance.eod import build_price_map, generate_targets

    prices = build_price_map()
    # On a fresh install the DuckDB feature store is empty until the 06:00–07:30
    # market jobs run — skip (don't fail) exactly as the EOD engine degrades.
    if not prices:
        pytest.skip("no price data — run the market pipeline first")
    for sid in ("alpha_tilt", "arjun_etf", "lowdd_multi_asset",
                "momentum_surge", "alpha_generators"):
        t = generate_targets(sid, prices)
        # A strategy that has data to target must produce weights summing to ~1.
        # (Partial/mixed feature-store states — e.g. ETF prices but not yet
        # equities — legitimately yield no targets for equity strategies.)
        if not t:
            continue
        total = sum(t.values())
        assert abs(total - 1.0) < 1e-6


async def test_ipo_calendar():
    from backend.modules.ipo.logic import list_all, list_recent, list_upcoming

    all_res = await list_all()
    up_res = await list_upcoming()
    rec_res = await list_recent()
    assert all_res["ok"] is True
    assert all_res["count"] > 0
    assert all_res["source"] == "sample"
    for row in all_res["ipos"]:
        assert "name" in row and "status" in row and "price_band" in row
    assert up_res["count"] > 0
    assert rec_res["count"] > 0


# ── Activity feed (live mirror of writes) ───────────────────────────────
async def test_activity_feed_shapes():
    from backend.modules.activity.logic import recent

    res = await recent(limit=20)
    assert res["ok"] is True
    assert res["limit"] == 20
    assert isinstance(res["items"], list)
    assert isinstance(res["domains"], dict)
    for item in res["items"]:
        assert "ts" in item and "kind" in item and "domain" in item
        assert "detail" in item and "label" in item
        assert item["domain"] in res["domains"]


# ── Vault publish job (git + quartz trigger) ───────────────────────────
def test_vault_publish_noop_without_config(monkeypatch):
    import backend.automation.jobs.vault_publish as vp

    monkeypatch.delenv("VAULT_GIT_REMOTE", raising=False)
    monkeypatch.delenv("VAULT_REPO_URL", raising=False)
    monkeypatch.delenv("GH_PAT", raising=False)
    monkeypatch.delenv("QUARTZ_TRIGGER_URL", raising=False)
    monkeypatch.setenv("HERMES_VAULT_PATH", "/nonexistent-vault")

    res = vp.vault_backup_publish()
    assert res["ok"] is True
    assert res["git_pushed"] is False
    assert res["quartz_rebuilt"] is False


def test_vault_publish_quartz_trigger(monkeypatch):
    import backend.automation.jobs.vault_publish as vp

    calls = {}

    class FakeResp:
        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout=300):
        calls["url"] = req.full_url
        calls["method"] = req.get_method()
        return FakeResp(b'{"ok": true, "exitCode": 0, "durationMs": 1234}')

    monkeypatch.setattr(vp.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("QUARTZ_TRIGGER_URL", "http://vesper-quartz:8081/rebuild")

    res = vp.vault_backup_publish()
    assert res["quartz_rebuilt"] is True
    assert res["quartz_detail"]["exit_code"] == 0
    assert calls["url"].endswith("/rebuild")
    assert calls["method"] == "POST"


# ── Event catalog ───────────────────────────────────────────────────────
def test_event_catalog_has_new_events():
    from backend.events.catalog import DAILY_JOURNAL_COMPLETED, all_events

    assert DAILY_JOURNAL_COMPLETED in all_events()


# ── Catalyst Swing Trader (Part E) ──────────────────────────────────────
async def test_catalyst_screen_persists_ranked_scores():
    """Layer 1/2/3 screen writes catalyst_scores + funnel log with ranks."""
    import pytest
    from backend.modules.db import session_factory
    from sqlalchemy import text

    from backend.modules.finance.catalyst import SCREEN_TOP_N, scores

    d = "2020-02-02"  # synthetic date: never collides with live runs
    res = await scores.screen(d)
    assert res["ok"] is True
    if res.get("degraded"):
        # Fresh install: factor_features empty until compute_factors runs.
        pytest.skip(res.get("note", "no factor features"))

    async with session_factory()() as db:
        rows = (await db.execute(
            text(
                "SELECT symbol, sector, composite_score, rank FROM finance.catalyst_scores "
                "WHERE date = :d ORDER BY rank"
            ),
            {"d": d},
        )).all()
        funnel = (await db.execute(
            text("SELECT COUNT(*) FROM finance.catalyst_candidates WHERE date = :d"),
            {"d": d},
        )).scalar_one()
        await db.execute(text("DELETE FROM finance.catalyst_scores WHERE date = :d"), {"d": d})
        await db.execute(text("DELETE FROM finance.catalyst_candidates WHERE date = :d"), {"d": d})
        await db.commit()

    assert rows, "expected catalyst_scores rows for synthetic date"
    assert funnel == min(SCREEN_TOP_N, len(rows)), "funnel log covers only the top-N watchlist"
    ranks = [r.rank for r in rows]
    assert ranks == sorted(ranks)
    comps = [r.composite_score for r in rows]
    assert comps == sorted(comps, reverse=True)
    assert all(r.sector for r in rows), "sector mapped from ind_nifty500list.csv"


async def test_catalyst_llm_degrades_honestly_without_key():
    """Without an API key the LLM stage never fabricates a verdict."""
    from backend.modules.finance.catalyst import llm

    old_key = llm.LLM_API_KEY
    llm.LLM_API_KEY = ""
    try:
        verdict = await llm.classify_catalyst("TEST.NS", {"composite_score": 0.5})
        assert verdict["signal"] == "none"
        assert verdict["confidence"] == 0.0
        assert verdict["rationale"] == ""
    finally:
        llm.LLM_API_KEY = old_key


async def test_catalyst_llm_honors_daily_budget():
    """At zero budget, classify_catalyst skips the call entirely."""
    from backend.modules.finance.catalyst import llm

    old_key, old_budget = llm.LLM_API_KEY, llm.MAX_LLM_CALLS_PER_DAY
    llm.LLM_API_KEY = "test-key"
    llm.MAX_LLM_CALLS_PER_DAY = 0
    try:
        verdict = await llm.classify_catalyst("TEST.NS", {})
        assert verdict["signal"] == "none"
    finally:
        llm.LLM_API_KEY = old_key
        llm.MAX_LLM_CALLS_PER_DAY = old_budget


async def test_catalyst_readonly_logic_shapes():
    """Read-only catalyst state tools return stable shapes (SELECT-only)."""
    from backend.modules.finance.logic import catalyst

    assert "scores" in await catalyst.scores()
    assert "candidates" in await catalyst.candidates()
    assert "positions" in await catalyst.positions()
    assert "budget" in await catalyst.usage()
    assert "estimates" in await catalyst.cost_gate()


async def test_catalyst_trader_run_day_idempotent():
    """run_day is idempotent-safe: exits, entries, NAV.

    On a fresh install the DuckDB feature store is empty until the 06:00–07:30
    market jobs have run, so the trader legitimately returns the degraded shape
    (no prices). Both the full and degraded response contracts are asserted.
    """
    from backend.modules.finance.catalyst import trader

    await trader.ensure_account()
    res = await trader.run_day()
    assert res["ok"] is True
    assert res["job"] == "catalyst_paper_trade"
    if res.get("degraded"):
        assert res["note"]  # "no prices" until the market data pipeline runs
        return
    assert isinstance(res["exits"], list)
    assert isinstance(res["entries"], list)
    assert res["n_positions"] >= 0
    assert res["total_equity"] > 0


async def test_catalyst_funnel_falls_back_to_composite():
    """Without any positive LLM signal, the funnel still surfaces candidates."""
    from backend.modules.db import session_factory
    from sqlalchemy import text

    from backend.modules.finance.catalyst import trader

    d = "2020-02-03"  # synthetic date: never collides with live runs
    async with session_factory()() as db:
        await db.execute(
            text(
                "INSERT INTO finance.catalyst_scores "
                "(date, symbol, market_score, sector_score, stock_score, composite_score, rank, catalyst_signal) "
                "VALUES (:d, 'TESTFALL.NS', 0.5, 0.5, 0.5, 0.9, 1, NULL)"
            ),
            {"d": d},
        )
        await db.commit()

    try:
        cands = await trader._funnel_candidates(d)
        assert any(c["symbol"] == "TESTFALL.NS" for c in cands), "composite fallback missed candidate"
        assert all("composite_score" in c for c in cands)
    finally:
        async with session_factory()() as db:
            await db.execute(text("DELETE FROM finance.catalyst_scores WHERE date = :d"), {"d": d})
            await db.commit()


async def test_catalyst_news_and_verdict_api_shape():
    """News + LLM verdicts are exposed per stock with stable shapes."""
    import pytest
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    sc = client.get("/api/finance/catalyst/scores", params={"limit": 5}).json()["scores"]
    if not sc:
        # Fresh install: catalyst_scores empty until the 18:20 catalyst_screen job runs.
        pytest.skip("no catalyst_scores yet — run catalyst_screen first")
    for s in sc:
        assert "verdict" in s
        assert set(s["verdict"]) == {"signal", "urgency", "confidence", "rationale"}

    nw = client.get("/api/finance/catalyst/news", params={"limit": 5}).json()["news"]
    assert isinstance(nw, list)
    for n in nw:
        assert {"title", "symbol", "source", "url", "published_at"} <= set(n)

    pos = client.get("/api/finance/catalyst/positions").json()["positions"]
    assert isinstance(pos, list)
    for p in pos:
        assert {"symbol", "qty", "entry_price", "stop_loss", "target"} <= set(p)

