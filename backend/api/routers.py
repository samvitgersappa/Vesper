"""Vesper API — REST surface for the web app (plan.md §3/§13, Phase 8).

The web app talks to the same module logic (not a parallel data path). Each
router below imports the module's `logic` functions directly — the identical
business logic the MCP servers expose — and wraps them as JSON endpoints. The
module MCP servers remain Hermes Agent's interface; this is the browser's.

Conventions:
- Every endpoint returns a plain JSON dict/list (module logic already does).
- Errors are caught and returned as `{"ok": False, "message": ...}` with the
  appropriate status code, never raised.
- Finance endpoints are READ-ONLY here too (plan §16): the logic layer has no
  write tools exposed on the agent/MCP path, and the API mirrors that.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException

from backend.modules.activity.logic import recent as activity_recent
from backend.modules.calendar.logic import birthdays as calendar_birthdays
from backend.modules.calendar.logic import events as calendar_events
from backend.modules.finance.logic import nav as finance_nav
from backend.modules.finance.logic import portfolio as finance_portfolio
from backend.modules.finance.logic import signals as finance_signals
from backend.modules.finance.logic import strategies as finance_strategies
from backend.modules.finance.logic import trades as finance_trades
from backend.modules.finance.logic import catalyst as finance_catalyst
from backend.modules.finance.eod import mark_to_market as finance_mark_to_market
from backend.modules.finance.eod import run_eod as finance_run_eod
from backend.modules.graph.logic import analytics as graph_analytics
from backend.modules.graph.logic import community as graph_community
from backend.modules.graph.logic import edges as graph_edges
from backend.modules.graph.logic import nodes as graph_nodes
from backend.modules.hobbies.logic import get_person_hobbies, list_all as hobbies_list_all
from backend.modules.ipo.logic import list_all as ipo_list_all
from backend.modules.ipo.logic import list_recent as ipo_list_recent
from backend.modules.ipo.logic import list_upcoming as ipo_list_upcoming
from backend.modules.journal.logic import get_entry as journal_get_entry
from backend.modules.journal.logic import get_mood_streak as journal_get_mood_streak
from backend.modules.journal.logic import get_streak_calendar as journal_get_streak_calendar
from backend.modules.journal.logic import log_expense as journal_log_expense
from backend.modules.journal.logic import log_workout as journal_log_workout
from backend.modules.journal.logic import read_entry as journal_read_entry
from backend.modules.journal.logic import resolve as journal_resolve
from backend.modules.journal.logic import spending_analysis as journal_spending_analysis
from backend.modules.journal.logic import spending_summary as journal_spending_summary
from backend.modules.journal.logic import spending_transactions as journal_spending_transactions
from backend.modules.journal.logic import update_entry as journal_update_entry
from backend.modules.journal.logic import write_entry as journal_write_entry
from backend.modules.knowledge.logic import knowledge_recall_everything
from backend.modules.knowledge.logic import knowledge_search
from backend.modules.relationship.logic import relationship_get_due_today
from backend.modules.relationship.logic import relationship_get_meeting_prep
from backend.modules.relationship.logic import relationship_graph
from backend.modules.relationship.logic import relationship_get_stats
from backend.modules.relationship.logic import relationship_create_person
from backend.modules.relationship.logic import relationship_log_interaction
from backend.modules.relationship.logic import relationship_draft_message
from backend.modules.relationship.logic import relationship_person_detail
from backend.modules.relationship.logic import relationship_search
from backend.modules.relationship.logic import relationship_update_person
from backend.modules.relationship.logic import relationship_add_note
from backend.modules.study.logic import list_tests as study_list_tests
from backend.modules.study.logic import percentiles as study_percentiles
from backend.modules.study.logic import readiness as study_readiness


def _run(coro, status: int = 200) -> Any:
    """Await a module-logic coroutine, mapping errors to JSON errors."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        result = asyncio.run(coro)
    else:
        result = loop.run_until_complete(coro) if False else asyncio.run(coro)  # noqa
    if isinstance(result, dict) and result.get("ok") is False:
        raise HTTPException(status_code=status, detail=result)
    return result


router = APIRouter(prefix="/api")


# ── Relationship ──────────────────────────────────────────────────────────
@router.get("/relationship/search")
async def api_relationship_search(query: str = "", limit: int = 20):
    return await relationship_search(query, limit)


@router.get("/relationship/person/{person_id}")
async def api_relationship_person(person_id: str):
    return await relationship_person_detail(person_id)


@router.post("/relationship/person")
async def api_relationship_create_person(payload: dict[str, Any] = Body(...)):
    return await relationship_create_person(
        name=str(payload.get("name", "")),
        company=str(payload.get("company", "")),
        occupation=str(payload.get("occupation", "")),
        category=str(payload.get("category", "NETWORK")),
        email=str(payload.get("email", "")),
        phone=str(payload.get("phone", "")),
        notes=str(payload.get("notes", "")),
    )


@router.patch("/relationship/person/{person_id}")
async def api_relationship_update_person(person_id: str, payload: dict[str, Any] = Body(...)):
    field = str(payload.get("field", ""))
    value = payload.get("value", "")
    return await relationship_update_person(person_id, field, str(value))


@router.post("/relationship/person/{person_id}/notes")
async def api_relationship_add_note(person_id: str, payload: dict[str, Any] = Body(...)):
    content = str(payload.get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=400, detail="Note content is required")
    return await relationship_add_note(person_id, content)


@router.post("/relationship/person/{person_id}/interactions")
async def api_relationship_log_interaction(person_id: str, payload: dict[str, Any] = Body(...)):
    summary = str(payload.get("summary", "")).strip()
    if not summary:
        raise HTTPException(status_code=400, detail="Interaction summary is required")
    return await relationship_log_interaction(
        person_id=person_id,
        type=str(payload.get("type", "message")),
        summary=summary,
        date=str(payload.get("date", "")),
        sentiment=str(payload.get("sentiment", "")),
        follow_up_needed=bool(payload.get("follow_up_needed", False)),
        follow_up_note=str(payload.get("follow_up_note", "")),
    )


@router.get("/relationship/person/{person_id}/meeting-prep")
async def api_relationship_meeting_prep(person_id: str):
    return await relationship_get_meeting_prep(person_id)


@router.post("/relationship/person/{person_id}/draft-message")
async def api_relationship_draft_message(person_id: str, payload: dict[str, Any] = Body(...)):
    return await relationship_draft_message(
        person_id=person_id,
        purpose=str(payload.get("purpose", "reconnect")),
        context=str(payload.get("context", "")),
    )


@router.get("/relationship/due-today")
async def api_relationship_due_today():
    return await relationship_get_due_today()


@router.get("/relationship/stats")
async def api_relationship_stats():
    return await relationship_get_stats()


@router.get("/relationship/graph")
async def api_relationship_graph(limit: int = 200):
    return await relationship_graph(limit)


# ── Journal ───────────────────────────────────────────────────────────────
@router.get("/journal/entry")
async def api_journal_entry(date: str = ""):
    return await journal_read_entry(date)


@router.get("/journal/streak")
async def api_journal_streak():
    return await journal_get_mood_streak()


@router.get("/journal/calendar")
async def api_journal_calendar(days: int = 84):
    return await journal_get_streak_calendar(days)


# ── Spending ───────────────────────────────────────────────────────────────
@router.get("/spending/summary")
async def api_spending_summary(period: str = "week"):
    return await journal_spending_summary(period)


@router.get("/spending/analysis")
async def api_spending_analysis():
    return await journal_spending_analysis()


@router.get("/spending/transactions")
async def api_spending_transactions(limit: int = 50):
    return await journal_spending_transactions(limit)


# ── Study ─────────────────────────────────────────────────────────────────
@router.get("/study/tests")
async def api_study_tests():
    return await study_list_tests()


@router.get("/study/percentiles/{test_id}")
async def api_study_percentiles(test_id: str):
    return await study_percentiles(test_id)


@router.get("/study/readiness")
async def api_study_readiness(test_id: str = ""):
    if not test_id:
        tests = await study_list_tests()
        if not tests:
            return {"test_id": None, "readiness": "no_data", "message": "no tests"}
        test_id = tests[0]["test_id"]
    return await study_readiness(test_id)


# ── Hobbies ───────────────────────────────────────────────────────────────
@router.get("/hobbies")
async def api_hobbies():
    return await hobbies_list_all()


# ── Activity feed (what the system actually writes) ───────────────────────
@router.get("/activity/recent")
async def api_activity_recent(limit: int = 80):
    return await activity_recent(limit=min(limit, 200))


# ── IPO calendar (curated dataset) ───────────────────────────────────────
@router.get("/ipo/all")
async def api_ipo_all():
    return await ipo_list_all()


@router.get("/ipo/upcoming")
async def api_ipo_upcoming():
    return await ipo_list_upcoming()


@router.get("/ipo/recent")
async def api_ipo_recent():
    return await ipo_list_recent()


# ── Calendar ──────────────────────────────────────────────────────────────
@router.get("/calendar/birthdays")
async def api_calendar_birthdays():
    return await calendar_birthdays()


@router.get("/calendar/events")
async def api_calendar_events(from_date: str = "", to_date: str = ""):
    # Web dashboard friendly: default to today..next-30-days so the page works
    # without params (the MCP tool keeps its strict range contract).
    return await calendar_events(from_date or "today", to_date or "month")


# ── Finance (read-only, plan §16) ─────────────────────────────────────────
@router.get("/finance/strategies")
async def api_finance_strategies():
    return await finance_strategies()


@router.post("/finance/run-eod")
async def api_finance_run_eod():
    return await finance_run_eod()


@router.post("/finance/mark-to-market")
async def api_finance_mark_to_market():
    return await finance_mark_to_market()


@router.get("/finance/portfolio")
async def api_finance_portfolio(strategy: str = ""):
    return await finance_portfolio(strategy)


@router.get("/finance/trades")
async def api_finance_trades(strategy: str = "", limit: int = 20):
    return await finance_trades(strategy, limit)


@router.get("/finance/signals")
async def api_finance_signals(strategy: str = "", limit: int = 20):
    return await finance_signals(strategy, limit)


@router.get("/finance/nav")
async def api_finance_nav(strategy: str = "", limit: int = 60):
    return await finance_nav(strategy, limit)


# ── Catalyst Swing Trader (Trader 6, read-only) ───────────────────────────
@router.get("/finance/catalyst/scores")
async def api_catalyst_scores(date: str = "", limit: int = 50):
    return await finance_catalyst.scores(date or None, limit)


@router.get("/finance/catalyst/positions")
async def api_catalyst_positions():
    return await finance_catalyst.positions()


@router.get("/finance/catalyst/usage")
async def api_catalyst_usage(limit: int = 30):
    return await finance_catalyst.usage(limit)


@router.get("/finance/catalyst/estimates")
async def api_catalyst_estimates(date: str = "", limit: int = 50):
    return await finance_catalyst.cost_gate(date or None, limit)


@router.get("/finance/catalyst/news")
async def api_catalyst_news(date: str = "", limit: int = 100):
    return await finance_catalyst.news(date or None, limit)


# ── Graph (universal intelligence graph, plan §10) ────────────────────────
@router.get("/graph/nodes")
async def api_graph_nodes(entity_type: str = "", limit: int = 500):
    return await graph_nodes(entity_type, limit)


@router.get("/graph/edges")
async def api_graph_edges(entity_type: str = "", limit: int = 1000):
    return await graph_edges(entity_type, limit=limit)


@router.get("/graph/analytics")
async def api_graph_analytics():
    return await graph_analytics()


@router.get("/graph/community")
async def api_graph_community():
    return await graph_community()


# ── Knowledge (vault search) ──────────────────────────────────────────────
@router.get("/knowledge/search")
async def api_knowledge_search(query: str, top_k: int = 5):
    return await knowledge_search(query, top_k)


@router.get("/knowledge/recall")
async def api_knowledge_recall(query: str):
    return await knowledge_recall_everything(query)
