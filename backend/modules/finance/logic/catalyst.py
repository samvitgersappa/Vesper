"""Catalyst Swing Trader — READ-ONLY state reads (Part E).

Serves the Finance MCP contract for the catalyst swing strategy. Everything
here is SELECT-only; the worker remains the only writer to the finance schema
(plan §16, coding_prompt Phase 4 rule 5).
"""

from typing import Any, Optional

from sqlalchemy import text

from backend.modules.db import session_factory

_MAX_LIMIT = 200


def _q(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    return round(float(v), 4)


def _clamp(limit: int) -> int:
    return max(1, min(int(limit), _MAX_LIMIT))


async def scores(date: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
    """Latest (or dated) catalyst_scores, best first."""
    limit = _clamp(limit)
    where = ""
    params: dict = {"n": limit}
    if date:
        where = "WHERE date = :d"
        params["d"] = date
    async with session_factory()() as db:
        rows = (await db.execute(
            text(
                f"SELECT date, symbol, sector, market_score, sector_score, stock_score, "
                f"composite_score, rank, catalyst_signal, llm_analyzed "
                f"FROM finance.catalyst_scores {where} "
                f"ORDER BY composite_score DESC LIMIT :n"
            ),
            params,
        )).all()
    return {
        "scores": [
            {
                "date": r.date,
                "symbol": r.symbol,
                "sector": r.sector,
                "market_score": _q(r.market_score),
                "sector_score": _q(r.sector_score),
                "stock_score": _q(r.stock_score),
                "composite_score": _q(r.composite_score),
                "rank": r.rank,
                "catalyst_signal": r.catalyst_signal,
                "llm_analyzed": bool(r.llm_analyzed),
            }
            for r in rows
        ]
    }


async def candidates(date: Optional[str] = None, limit: int = 100) -> dict[str, Any]:
    """Funnel log (catalyst_candidates), newest first."""
    limit = _clamp(limit)
    where = ""
    params: dict = {"n": limit}
    if date:
        where = "WHERE date = :d"
        params["d"] = date
    async with session_factory()() as db:
        rows = (await db.execute(
            text(
                f"SELECT date, symbol, stage, reason, score, status "
                f"FROM finance.catalyst_candidates {where} "
                f"ORDER BY date DESC, score DESC LIMIT :n"
            ),
            params,
        )).all()
    return {
        "candidates": [
            {
                "date": r.date,
                "symbol": r.symbol,
                "stage": r.stage,
                "reason": r.reason,
                "score": _q(r.score),
                "status": r.status,
            }
            for r in rows
        ]
    }


async def positions() -> dict[str, Any]:
    """Open catalyst swing positions with entry/target/stop bookkeeping."""
    async with session_factory()() as db:
        rows = (await db.execute(
            text(
                "SELECT p.id, p.symbol, p.entry_date, p.entry_price, p.qty, p.atr, "
                "p.stop_loss, p.trailing_stop, p.target, p.days_held, p.exit_reason, "
                "h.last_price, h.avg_price "
                "FROM finance.catalyst_positions p "
                "LEFT JOIN finance.paper_holdings h ON h.trader_id = 'catalyst_swing' AND h.ticker = p.symbol "
                "WHERE p.status = 'open' ORDER BY p.entry_date DESC"
            ),
        )).all()
    return {
        "positions": [
            {
                "symbol": r.symbol,
                "entry_date": r.entry_date,
                "entry_price": _q(r.entry_price),
                "qty": r.qty,
                "atr": _q(r.atr),
                "stop_loss": _q(r.stop_loss),
                "trailing_stop": _q(r.trailing_stop),
                "target": _q(r.target),
                "days_held": r.days_held,
                "last_price": _q(r.last_price),
                "avg_price": _q(r.avg_price),
            }
            for r in rows
        ]
    }


async def usage(limit: int = 30) -> dict[str, Any]:
    """Daily LLM-call budget usage + recent audit trail for the catalyst stage."""
    async with session_factory()() as db:
        usage_rows = (await db.execute(
            text(
                "SELECT date, calls_used FROM finance.catalyst_llm_usage ORDER BY date DESC LIMIT 14"
            ),
        )).all()
        call_rows = (await db.execute(
            text(
                "SELECT ts, date, symbol, model, ok FROM finance.catalyst_llm_calls "
                "ORDER BY ts DESC LIMIT :n"
            ),
            {"n": _clamp(limit)},
        )).all()
    return {
        "budget": [
            {"date": r.date, "calls_used": r.calls_used}
            for r in usage_rows
        ],
        "recent_calls": [
            {"ts": str(r.ts), "date": r.date, "symbol": r.symbol, "model": r.model, "ok": bool(r.ok)}
            for r in call_rows
        ],
    }


async def cost_gate(date: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
    """Recent cost-gate estimates (expected slippage vs target PnL)."""
    limit = _clamp(limit)
    where = ""
    params: dict = {"n": limit}
    if date:
        where = "WHERE date = :d"
        params["d"] = date
    async with session_factory()() as db:
        rows = (await db.execute(
            text(
                f"SELECT date, symbol, notional, expected_slippage_bps, estimated_cost, "
                f"target_pnl, cost_target_ratio, gate_passed "
                f"FROM finance.catalyst_cost_estimates {where} "
                f"ORDER BY date DESC LIMIT :n"
            ),
            params,
        )).all()
    return {
        "estimates": [
            {
                "date": r.date,
                "symbol": r.symbol,
                "notional": _q(r.notional),
                "expected_slippage_bps": r.expected_slippage_bps,
                "estimated_cost": _q(r.estimated_cost),
                "target_pnl": _q(r.target_pnl),
                "cost_target_ratio": _q(r.cost_target_ratio),
                "gate_passed": bool(r.gate_passed),
            }
            for r in rows
        ]
    }
