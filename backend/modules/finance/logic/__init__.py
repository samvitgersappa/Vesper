"""Finance module business logic — READ-ONLY portfolio & paper-trading reads.

Implements the Finance MCP contract (portfolio.skill): `portfolio`, `trades`,
`signals`, plus a read-only `nav` helper. Every function here is SELECT-only —
the Finance MCP server is read-only (plan.md §16, coding_prompt Phase 4 rule 5);
the worker/scheduler remains the only writer to the `finance` schema.

The `strategy` argument maps to `trader_id` in the paper-trading tables: pass a
trader id to scope reads to one trader, or leave it empty to read all traders.
No DB writes happen here; all sessions are read-only `await db.execute(...)`.
"""

from typing import Any, Optional

from sqlalchemy import select

from backend.db.postgres.schemas.finance.models import (
    PaperAccount,
    PaperHolding,
    PaperNavHistory,
    PaperTrade,
)
from backend.modules.db import session_factory

_MAX_LIMIT = 500


def _q(v: Optional[float]) -> Optional[float]:
    """Round a number to 2dp for stable, deterministic output (None-safe)."""
    if v is None:
        return None
    return round(float(v), 2)


def _clamp_limit(limit: int) -> int:
    return max(1, min(int(limit), _MAX_LIMIT))


async def portfolio(strategy: str = "") -> dict[str, Any]:
    """Account summary + holdings for one trader (or all traders if empty).

    For each trader: available/settled/blocked cash, the holding list with
    market_value computed in Python (qty * last_price, only when last_price is
    present), total equity and day PnL % from the latest PaperNavHistory row.
    """
    async with session_factory()() as db:
        acc_stmt = select(PaperAccount)
        hol_stmt = select(PaperHolding)
        nav_stmt = select(PaperNavHistory)
        if strategy:
            acc_stmt = acc_stmt.where(PaperAccount.trader_id == strategy)
            hol_stmt = hol_stmt.where(PaperHolding.trader_id == strategy)
            nav_stmt = nav_stmt.where(PaperNavHistory.trader_id == strategy)
        accounts = (await db.execute(acc_stmt)).scalars().all()
        holdings = (await db.execute(hol_stmt)).scalars().all()
        nav_rows = (await db.execute(nav_stmt)).scalars().all()

    holdings_by_trader: dict[str, list[PaperHolding]] = {}
    for h in holdings:
        holdings_by_trader.setdefault(h.trader_id, []).append(h)

    latest_nav: dict[str, PaperNavHistory] = {}
    for n in nav_rows:
        cur = latest_nav.get(n.trader_id)
        if cur is None or n.date > cur.date:
            latest_nav[n.trader_id] = n

    traders = []
    for acc in accounts:
        hs = holdings_by_trader.get(acc.trader_id, [])
        holding_list = []
        holdings_value = 0.0
        for h in hs:
            market_value = round(h.qty * h.last_price, 2) if h.last_price is not None else None
            if market_value is not None:
                holdings_value += market_value
            holding_list.append(
                {
                    "ticker": h.ticker,
                    "qty": h.qty,
                    "avg_price": _q(h.avg_price),
                    "last_price": _q(h.last_price),
                    "market_value": market_value,
                }
            )
        nav = latest_nav.get(acc.trader_id)
        total_equity = _q(nav.total_equity) if nav else _q(acc.available_cash + holdings_value)
        traders.append(
            {
                "trader_id": acc.trader_id,
                "cash": {
                    "available": _q(acc.available_cash),
                    "settled": _q(acc.settled_cash),
                    "blocked": _q(acc.blocked_cash),
                },
                "holdings": holding_list,
                "holdings_value": round(holdings_value, 2),
                "total_equity": total_equity,
                "day_pnl_pct": _q(nav.day_pnl_pct) if nav else None,
                "nav_date": nav.date if nav else None,
            }
        )

    return {"traders": traders}


async def trades(strategy: str = "", limit: int = 20) -> dict[str, Any]:
    """Recent executed trades (order_status == 'EXECUTED'), newest first."""
    limit = _clamp_limit(limit)
    stmt = (
        select(PaperTrade)
        .where(PaperTrade.order_status == "EXECUTED")
        .order_by(PaperTrade.trade_date.desc(), PaperTrade.id.desc())
        .limit(limit)
    )
    if strategy:
        stmt = stmt.where(PaperTrade.trader_id == strategy)
    async with session_factory()() as db:
        rows = (await db.execute(stmt)).scalars().all()
    return {
        "trades": [
            {
                "trader_id": t.trader_id,
                "date": t.trade_date,
                "symbol": t.symbol,
                "side": t.side,
                "qty": t.quantity,
                "signal_price": _q(t.signal_price),
                "fill_price": _q(t.fill_price),
                "realized_pnl": _q(t.realized_pnl),
            }
            for t in rows
        ]
    }


async def signals(strategy: str = "", limit: int = 20) -> dict[str, Any]:
    """Pending/triggered signals interpreted from the paper-trade log.

    status:
    - "pending"   -> order_status != 'EXECUTED'
    - "triggered" -> executed but signal_price set and != fill_price
    - "executed"  -> executed at the signal price (no slippage)
    """
    limit = _clamp_limit(limit)
    stmt = (
        select(PaperTrade)
        .order_by(PaperTrade.trade_date.desc(), PaperTrade.id.desc())
        .limit(limit)
    )
    if strategy:
        stmt = stmt.where(PaperTrade.trader_id == strategy)
    async with session_factory()() as db:
        rows = (await db.execute(stmt)).scalars().all()

    signal_list = []
    for t in rows:
        executed = (t.order_status or "").upper() == "EXECUTED"
        if not executed:
            status = "pending"
        elif (
            t.signal_price is not None
            and t.fill_price is not None
            and abs(t.signal_price - t.fill_price) > 1e-9
        ):
            status = "triggered"
        else:
            status = "executed"
        signal_list.append(
            {
                "trader_id": t.trader_id,
                "symbol": t.symbol,
                "side": t.side,
                "signal_price": _q(t.signal_price),
                "fill_price": _q(t.fill_price),
                "status": status,
                "date": t.trade_date,
            }
        )

    return {"signals": signal_list}


async def nav(strategy: str = "", limit: int = 60) -> dict[str, Any]:
    """Latest NAV series per trader from PaperNavHistory, newest first."""
    limit = _clamp_limit(limit)
    stmt = (
        select(PaperNavHistory)
        .order_by(PaperNavHistory.date.desc())
        .limit(limit)
    )
    if strategy:
        stmt = stmt.where(PaperNavHistory.trader_id == strategy)
    async with session_factory()() as db:
        rows = (await db.execute(stmt)).scalars().all()

    by_trader: dict[str, list[dict[str, Any]]] = {}
    for n in rows:
        by_trader.setdefault(n.trader_id, []).append(
            {
                "date": n.date,
                "total_equity": _q(n.total_equity),
                "cash": _q(n.cash),
                "holdings_value": _q(n.holdings_value),
                "n_positions": n.n_positions,
                "day_pnl_pct": _q(n.day_pnl_pct),
                "cumulative_pnl_pct": _q(n.cumulative_pnl_pct),
            }
        )
    for tid in by_trader:
        by_trader[tid].sort(key=lambda d: d["date"], reverse=True)

    return {"nav": by_trader}
