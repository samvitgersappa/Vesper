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

from fastapi import APIRouter, HTTPException

from backend.modules.calendar.logic import birthdays as calendar_birthdays
from backend.modules.calendar.logic import events as calendar_events
from backend.modules.finance.logic import nav as finance_nav
from backend.modules.finance.logic import portfolio as finance_portfolio
from backend.modules.finance.logic import signals as finance_signals
from backend.modules.finance.logic import trades as finance_trades
from backend.modules.graph.logic import analytics as graph_analytics
from backend.modules.graph.logic import community as graph_community
from backend.modules.graph.logic import edges as graph_edges
from backend.modules.graph.logic import nodes as graph_nodes
from backend.modules.hobbies.logic import get_person_hobbies, list_all as hobbies_list_all
from backend.modules.journal.logic import get_entry as journal_get_entry
from backend.modules.journal.logic import get_mood_streak as journal_get_mood_streak
from backend.modules.journal.logic import log_expense as journal_log_expense
from backend.modules.journal.logic import log_workout as journal_log_workout
from backend.modules.journal.logic import read_entry as journal_read_entry
from backend.modules.journal.logic import resolve as journal_resolve
from backend.modules.journal.logic import update_entry as journal_update_entry
from backend.modules.journal.logic import write_entry as journal_write_entry
from backend.modules.knowledge.logic import knowledge_recall_everything
from backend.modules.knowledge.logic import knowledge_search
from backend.modules.relationship.logic import relationship_get_due_today
from backend.modules.relationship.logic import relationship_get_stats
from backend.modules.relationship.logic import relationship_person_detail
from backend.modules.relationship.logic import relationship_search
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


@router.get("/relationship/due-today")
async def api_relationship_due_today():
    return await relationship_get_due_today()


@router.get("/relationship/stats")
async def api_relationship_stats():
    return await relationship_get_stats()


# ── Journal ───────────────────────────────────────────────────────────────
@router.get("/journal/entry")
async def api_journal_entry(date: str = ""):
    return await journal_read_entry(date)


@router.get("/journal/streak")
async def api_journal_streak():
    return await journal_get_mood_streak()


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


# ── Calendar ──────────────────────────────────────────────────────────────
@router.get("/calendar/birthdays")
async def api_calendar_birthdays():
    return await calendar_birthdays()


@router.get("/calendar/events")
async def api_calendar_events(from_date: str = "", to_date: str = ""):
    return await calendar_events(from_date, to_date)


# ── Finance (read-only, plan §16) ─────────────────────────────────────────
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


# ── Graph (universal intelligence graph, plan §10) ────────────────────────
@router.get("/graph/nodes")
async def api_graph_nodes(entity_type: str = "", limit: int = 500):
    return await graph_nodes(entity_type, limit)


@router.get("/graph/edges")
async def api_graph_edges(limit: int = 1000):
    return await graph_edges(limit)


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
