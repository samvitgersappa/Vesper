"""Catalyst Swing Trader — risk & execution engine (Part E).

Runs at 18:50 (risk) and 19:00 (paper trade) IST. All state lives in the
existing paper-trading tables (trader_id="catalyst_swing") plus
`catalyst_positions` for swing-exit bookkeeping.

Exits (checked first): ATR stop, trailing stop, rank deterioration, 10-day
time exit, negative-catalyst exit.
Entries (after exits): positive-catalyst candidates from the funnel, subject
to position limits (5–8 concurrent, 1–3 entries/day) and the cost gate
(estimated cost <= target / 3, targeting target-to-cost 3–4x).

The worker is the only writer to the finance schema (plan §16).
"""

import logging
import math
import uuid
from typing import Any, Optional

import pandas as pd
from sqlalchemy import text

from backend.db import feature_store
from backend.modules.db import session_factory
from backend.modules.finance.catalyst import (
    COST_TARGET_MIN_MULTIPLE,
    MAX_CONCURRENT_POSITIONS,
    MAX_ENTRIES_PER_DAY,
    MAX_HOLD_DAYS,
    MIN_CONCURRENT_POSITIONS,
    TRADER_ID,
    WATCHLIST_SIZE,
)
from backend.modules.finance.catalyst._util import ist_today, record_run

logger = logging.getLogger("vesper.finance.catalyst.trader")

STARTING_CAPITAL = 1_000_000.0  # ₹10L paper capital for the catalyst swing trader
_SLIPPAGE_BPS = 8
_ATR_PERIOD = 14
_STOP_MULT = 1.5  # ATR stop: entry - 1.5 * ATR
_TRAIL_MULT = 2.5  # trailing stop: peak - 2.5 * ATR
_TARGET_MULT = 2.0  # target: entry + 2.0 * ATR


def _today() -> str:
    return ist_today()


def _q(v: float | None) -> float | None:
    if v is None or math.isnan(v):
        return None
    return round(float(v), 2)


# ── Account / prices / ATR ───────────────────────────────────────────────
async def ensure_account() -> None:
    """Create the catalyst_swing paper account if it doesn't exist (idempotent)."""
    async with session_factory()() as db:
        row = (await db.execute(
            text("SELECT trader_id FROM finance.paper_account WHERE trader_id = :t"),
            {"t": TRADER_ID},
        )).first()
        if row is None:
            await db.execute(
                text(
                    "INSERT INTO finance.paper_account "
                    "(trader_id, available_cash, settled_cash, blocked_cash) "
                    "VALUES (:t, :c, :c, 0)"
                ),
                {"t": TRADER_ID, "c": STARTING_CAPITAL},
            )
            await db.commit()


def _price_map() -> dict[str, float]:
    try:
        closes = feature_store.equity_closes()
    except Exception:  # pragma: no cover - defensive
        return {}
    if closes.empty:
        return {}
    latest = closes.iloc[-1]
    return {str(s): round(float(v), 4) for s, v in latest.items() if pd.notna(v) and float(v) > 0}


async def _mark_to_market(db, prices: dict[str, float]) -> int:
    """Refresh catalyst holdings before exits and NAV calculations."""
    updated = 0
    rows = (await db.execute(
        text("SELECT ticker, last_price FROM finance.paper_holdings WHERE trader_id = :t"),
        {"t": TRADER_ID},
    )).all()
    for row in rows:
        price = prices.get(row.ticker)
        if price is not None and (row.last_price is None or float(row.last_price) != price):
            await db.execute(
                text("UPDATE finance.paper_holdings SET last_price = :p WHERE trader_id = :t AND ticker = :s"),
                {"p": _q(price), "t": TRADER_ID, "s": row.ticker},
            )
            updated += 1
    return updated


def _atr(symbol: str, period: int = _ATR_PERIOD) -> Optional[float]:
    """14-day ATR from equity_daily OHLC (feature store)."""
    try:
        df = feature_store.client.df(
            "SELECT Date, High, Low, Close FROM equity_daily WHERE Symbol = $s ORDER BY Date",
            {"s": symbol},
        )
    except Exception:  # pragma: no cover - defensive
        return None
    if df is None or len(df) < period + 1:
        return None
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    val = tr.iloc[-period:].mean()
    return round(float(val), 4) if pd.notna(val) else None


# ── Exits ────────────────────────────────────────────────────────────────
async def _open_positions(db) -> list[dict]:
    rows = (await db.execute(
        text("SELECT * FROM finance.catalyst_positions WHERE status = 'open'")
    )).all()
    return [dict(r._mapping) for r in rows]


async def _exit_position(db, pos: dict, reason: str, date: str, prices: dict[str, float]) -> Optional[dict]:
    """Sell the position, realize PnL, close the swing row. Returns trade info."""
    symbol = pos["symbol"]
    price = prices.get(symbol)
    if not price:
        return None
    qty = int(pos["qty"])
    hold_row = (await db.execute(
        text("SELECT avg_price FROM finance.paper_holdings WHERE trader_id = :t AND ticker = :s"),
        {"t": TRADER_ID, "s": symbol},
    )).first()
    avg = float(hold_row.avg_price) if hold_row else float(pos["entry_price"])
    fill = price * (1 - _SLIPPAGE_BPS / 10000.0)
    realized = (fill - avg) * qty

    await db.execute(
        text(
            "INSERT INTO finance.paper_trades "
            "(trade_id, trader_id, trade_date, symbol, side, quantity, signal_price, fill_price, "
            "slippage_bps, cost_total, reason, realized_pnl, order_status) "
            "VALUES (:tid, :t, :d, :s, 'SELL', :q, :sig, :fill, :slip, :cost, :reason, :pnl, 'EXECUTED')"
        ),
        {
            "tid": str(uuid.uuid4()), "t": TRADER_ID, "d": date, "s": symbol, "q": qty,
            "sig": _q(price), "fill": _q(fill), "slip": _SLIPPAGE_BPS,
            "cost": _q(fill * qty), "reason": f"exit: {reason}", "pnl": _q(realized),
        },
    )
    await db.execute(
        text("DELETE FROM finance.paper_holdings WHERE trader_id = :t AND ticker = :s"),
        {"t": TRADER_ID, "s": symbol},
    )
    await db.execute(
        text("UPDATE finance.catalyst_positions SET status='closed', exit_reason=:r, exit_date=:d WHERE id=:id"),
        {"r": reason, "d": date, "id": pos["id"]},
    )
    await db.execute(
        text(
            "UPDATE finance.paper_account SET available_cash = available_cash + :proceeds "
            "WHERE trader_id = :t"
        ),
        {"proceeds": _q(fill * qty), "t": TRADER_ID},
    )
    return {"symbol": symbol, "side": "SELL", "qty": qty, "fill_price": _q(fill), "realized_pnl": _q(realized)}


async def _check_exits(date: str, prices: dict[str, float]) -> tuple[list[dict], list[dict]]:
    """Run all five exit rules. Returns (executed_exits, kept_positions)."""
    today_ranks: dict[str, int] = {}
    today_signals: dict[str, str] = {}
    async with session_factory()() as db:
        rows = (await db.execute(
            text(
                "SELECT symbol, rank FROM finance.catalyst_scores WHERE date = :d AND rank IS NOT NULL"
            ),
            {"d": date},
        )).all()
        today_ranks = {r.symbol: int(r.rank) for r in rows}
        sig_rows = (await db.execute(
            text(
                "SELECT symbol, catalyst_signal FROM finance.catalyst_scores "
                "WHERE date = :d AND catalyst_signal IS NOT NULL"
            ),
            {"d": date},
        )).all()
        today_signals = {r.symbol: r.catalyst_signal for r in sig_rows}

    exits: list[dict] = []
    kept: list[dict] = []
    async with session_factory()() as db:
        positions = await _open_positions(db)
        for pos in positions:
            symbol = pos["symbol"]
            price = prices.get(symbol)
            reason: Optional[str] = None

            if price is not None:
                if pos.get("stop_loss") and price <= float(pos["stop_loss"]):
                    reason = "atr_stop"
                elif pos.get("trailing_stop") and price <= float(pos["trailing_stop"]):
                    reason = "trailing_stop"
                elif pos.get("target") and price >= float(pos["target"]):
                    reason = "target"

            # Rank deterioration: fell out of the top of the funnel.
            if reason is None and symbol in today_ranks and today_ranks[symbol] > WATCHLIST_SIZE * 2:
                reason = "rank_deterioration"

            # Negative catalyst from today's LLM stage.
            if reason is None and today_signals.get(symbol) == "negative":
                reason = "negative_catalyst"

            # Time exit: held >= MAX_HOLD_DAYS.
            if reason is None and pos.get("days_held", 0) >= MAX_HOLD_DAYS:
                reason = "time_exit"

            if reason is not None:
                ex = await _exit_position(db, pos, reason, date, prices)
                if ex:
                    exits.append(ex)
            else:
                kept.append(pos)

        await db.commit()

    return exits, kept


# ── Entries ──────────────────────────────────────────────────────────────
async def _funnel_candidates(date: str) -> list[dict]:
    """Candidates for entry, sorted by composite score.

    Preferred signal: the LLM stage's `positive` catalysts. When the LLM stage
    produced none (degraded run, no API key, or genuinely no concrete catalyst
    today), fall back to the top factor-composite candidates from the screen so
    the swing trader isn't perpetually flat — entries still pass the cost gate,
    position limits (5–8 concurrent) and the per-day entry cap.
    """
    async with session_factory()() as db:
        rows = (await db.execute(
            text(
                "SELECT symbol, market_score, sector_score, stock_score, composite_score, rank, "
                "catalyst_signal, catalyst_json "
                "FROM finance.catalyst_scores WHERE date = :d AND catalyst_signal = 'positive' "
                "ORDER BY composite_score DESC LIMIT :n"
            ),
            {"d": date, "n": WATCHLIST_SIZE * 2},
        )).all()
        if not rows:
            rows = (await db.execute(
                text(
                    "SELECT symbol, market_score, sector_score, stock_score, composite_score, rank, "
                    "catalyst_signal, catalyst_json "
                    "FROM finance.catalyst_scores WHERE date = :d "
                    "ORDER BY composite_score DESC LIMIT :n"
                ),
                {"d": date, "n": WATCHLIST_SIZE * 2},
            )).all()
    return [dict(r._mapping) for r in rows]


async def _open_count(db, date: str) -> tuple[int, int]:
    n_pos = (await db.execute(
        text("SELECT COUNT(*) FROM finance.catalyst_positions WHERE status = 'open'")
    )).scalar_one()
    n_today = (await db.execute(
        text(
            "SELECT COUNT(*) FROM finance.catalyst_positions "
            "WHERE entry_date = :d"
        ),
        {"d": date},
    )).scalar_one()
    return int(n_pos), int(n_today)


async def _held_symbols(db) -> set[str]:
    rows = (await db.execute(
        text("SELECT ticker FROM finance.paper_holdings WHERE trader_id = :t"),
        {"t": TRADER_ID},
    )).all()
    return {str(row.ticker) for row in rows}


async def _enter(
    db, date: str, symbol: str, cand: dict, equity: float, cash: float,
) -> Optional[dict]:
    """Open one position: size, ATR stop/target, cost gate, write trades/holdings."""
    closes = feature_store.equity_closes(symbol=symbol)
    if closes.empty:
        return None
    price = float(closes.iloc[-1][symbol]) if symbol in closes.columns else None
    if not price or price <= 0:
        return None
    atr = _atr(symbol)
    if not atr:
        atr = price * 0.02  # fallback: 2% of price when history is too short

    target = price + _TARGET_MULT * atr
    stop = price - _STOP_MULT * atr

    # Cost gate: estimated cost vs target PnL (3–4x).
    notional = equity / MAX_CONCURRENT_POSITIONS
    qty = int(notional / price)
    if qty <= 0:
        return None
    target_pnl = (target - price) * qty
    estimated_cost = notional * (_SLIPPAGE_BPS / 10000.0)
    ratio = target_pnl / estimated_cost if estimated_cost > 0 else 0.0
    gate_passed = ratio >= COST_TARGET_MIN_MULTIPLE
    await _persist_cost_estimate(date, symbol, notional, estimated_cost, target_pnl, ratio, gate_passed)
    if not gate_passed:
        return None

    # Cash check: scale down to affordable qty, skip if nothing affordable.
    cost = price * (1 + _SLIPPAGE_BPS / 10000.0) * qty
    if cost > cash:
        affordable = int(cash // (price * (1 + _SLIPPAGE_BPS / 10000.0)))
        if affordable <= 0:
            return None
        qty = affordable
        cost = price * (1 + _SLIPPAGE_BPS / 10000.0) * qty
        target_pnl = (target - price) * qty

    trade_id = str(uuid.uuid4())
    fill = price * (1 + _SLIPPAGE_BPS / 10000.0)
    await db.execute(
        text(
            "INSERT INTO finance.paper_trades "
            "(trade_id, trader_id, trade_date, symbol, side, quantity, signal_price, fill_price, "
            "slippage_bps, cost_total, reason, order_status) "
            "VALUES (:tid, :t, :d, :s, 'BUY', :q, :sig, :fill, :slip, :cost, :reason, 'EXECUTED')"
        ),
        {
            "tid": trade_id, "t": TRADER_ID, "d": date, "s": symbol, "q": qty,
            "sig": _q(price), "fill": _q(fill), "slip": _SLIPPAGE_BPS,
            "cost": _q(cost), "reason": f"catalyst entry rank={cand.get('rank')}",
        },
    )
    await db.execute(
        text(
            "INSERT INTO finance.paper_holdings "
            "(trader_id, ticker, qty, avg_price, last_price, buy_date) "
            "VALUES (:t, :s, :q, :avg, :last, :d) "
            "ON CONFLICT (trader_id, ticker) DO UPDATE SET "
            "qty = finance.paper_holdings.qty + EXCLUDED.qty, avg_price = :avg"
        ),
        {"t": TRADER_ID, "s": symbol, "q": qty, "avg": _q(fill), "last": _q(price), "d": date},
    )
    await db.execute(
        text(
            "INSERT INTO finance.catalyst_positions "
            "(id, symbol, entry_date, entry_price, qty, atr, stop_loss, trailing_stop, target, days_held, status) "
            "VALUES (:id, :s, :d, :ep, :q, :atr, :stop, :trail, :tgt, 0, 'open')"
        ),
        {
            "id": str(uuid.uuid4()), "s": symbol, "d": date, "ep": _q(price), "q": qty,
            "atr": _q(atr), "stop": _q(stop), "trail": _q(price - _TRAIL_MULT * atr), "tgt": _q(target),
        },
    )
    await db.execute(
        text(
            "UPDATE finance.catalyst_candidates SET stage = 'entered', status = 'entered' "
            "WHERE date = :d AND symbol = :s"
        ),
        {"d": date, "s": symbol},
    )
    return {"symbol": symbol, "side": "BUY", "qty": qty, "fill_price": _q(fill), "target": _q(target)}


async def _persist_cost_estimate(date, symbol, notional, cost, target_pnl, ratio, gate_passed) -> None:
    try:
        async with session_factory()() as db:
            await db.execute(
                text(
                    "INSERT INTO finance.catalyst_cost_estimates "
                    "(date, symbol, notional, expected_slippage_bps, estimated_cost, target_pnl, "
                    "cost_target_ratio, gate_passed) "
                    "VALUES (:d, :s, :n, :b, :c, :tp, :r, :g)"
                ),
                {
                    "d": date, "s": symbol, "n": _q(notional), "b": _SLIPPAGE_BPS,
                    "c": _q(cost), "tp": _q(target_pnl), "r": _q(ratio), "g": gate_passed,
                },
            )
            await db.commit()
    except Exception:  # pragma: no cover - cost log never blocks entry
        pass


# ── Day run ──────────────────────────────────────────────────────────────
async def _snapshot_nav(db, d: str, cash: float, n_pos: int) -> float:
    """Compute total equity and upsert today's NAV row. Returns total equity."""
    held_value = (await db.execute(
        text(
            "SELECT COALESCE(SUM(qty * COALESCE(last_price, 0)), 0) "
            "FROM finance.paper_holdings WHERE trader_id = :t"
        ),
        {"t": TRADER_ID},
    )).scalar_one()
    total_equity = cash + float(held_value or 0)
    # Compute day-over-day PnL from the previous NAV row.
    prev = (await db.execute(
        text("SELECT total_equity FROM finance.paper_nav_history WHERE trader_id = :t AND date < :d ORDER BY date DESC LIMIT 1"),
        {"t": TRADER_ID, "d": d},
    )).scalar()
    day_pnl = None
    if prev is not None and prev > 0:
        day_pnl = ((total_equity / prev) - 1) * 100
    await db.execute(
        text(
            "INSERT INTO finance.paper_nav_history "
            "(trader_id, date, total_equity, cash, holdings_value, n_positions, day_pnl_pct) "
            "VALUES (:t, :d, :e, :c, :h, :n, :dp) "
            "ON CONFLICT (trader_id, date) DO UPDATE SET "
            "total_equity = EXCLUDED.total_equity, cash = EXCLUDED.cash, "
            "holdings_value = EXCLUDED.holdings_value, n_positions = EXCLUDED.n_positions, "
            "day_pnl_pct = EXCLUDED.day_pnl_pct"
        ),
        {
            "t": TRADER_ID, "d": d, "e": _q(total_equity), "c": _q(cash),
            "h": _q(float(held_value or 0)), "n": n_pos, "dp": day_pnl,
        },
    )
    return float(total_equity)


async def run_risk(date: str | None = None) -> dict[str, Any]:
    """18:50 IST — exits-only risk pass: stops, trailing, rank, negative catalyst, time.

    Closes anything broken before the 19:00 entry pass, snapshots NAV, and
    records the run. A warm-up for the trader; also runs standalone.
    """
    d = date or _today()
    await ensure_account()
    prices = _price_map()
    if not prices:
        await record_run("catalyst_risk", "degraded", "no prices available")
        return {"ok": True, "job": "catalyst_risk", "degraded": True, "note": "no prices"}

    async with session_factory()() as db:
        await _mark_to_market(db, prices)
        await db.commit()

    exits, _kept = await _check_exits(d, prices)

    async with session_factory()() as db:
        n_pos, _n_today = await _open_count(db, d)
        acct = (await db.execute(
            text("SELECT available_cash FROM finance.paper_account WHERE trader_id = :t"),
            {"t": TRADER_ID},
        )).first()
        cash = float(acct.available_cash) if acct else 0.0
        total_equity = await _snapshot_nav(db, d, cash, n_pos)
        await db.commit()

    await record_run("catalyst_risk", "ok", f"exits={len(exits)}, positions={n_pos}")
    return {
        "ok": True, "job": "catalyst_risk", "date": d,
        "exits": exits, "n_positions": n_pos, "total_equity": _q(total_equity),
    }


async def run_day(date: str | None = None) -> dict[str, Any]:
    """19:00 IST — exits first, then entries, then NAV. Returns summary."""
    d = date or _today()
    await ensure_account()
    prices = _price_map()
    if not prices:
        await record_run("catalyst_paper_trade", "degraded", "no prices available")
        return {"ok": True, "job": "catalyst_paper_trade", "degraded": True, "note": "no prices"}

    async with session_factory()() as db:
        await _mark_to_market(db, prices)
        await db.commit()

    exits, _kept = await _check_exits(d, prices)

    entered: list[dict] = []
    candidates = await _funnel_candidates(d)
    async with session_factory()() as db:
        n_pos, n_today = await _open_count(db, d)
        held_symbols = await _held_symbols(db)
        acct = (await db.execute(
            text("SELECT available_cash FROM finance.paper_account WHERE trader_id = :t"),
            {"t": TRADER_ID},
        )).first()
        cash = float(acct.available_cash) if acct else 0.0
        held_value = (await db.execute(
            text(
                "SELECT COALESCE(SUM(qty * COALESCE(last_price, 0)), 0) "
                "FROM finance.paper_holdings WHERE trader_id = :t"
            ),
            {"t": TRADER_ID},
        )).scalar_one()
        equity = cash + float(held_value or 0)

        for cand in candidates:
            if n_pos >= MAX_CONCURRENT_POSITIONS or n_today >= MAX_ENTRIES_PER_DAY:
                break
            if cand["symbol"] in held_symbols:
                continue
            if n_pos < MIN_CONCURRENT_POSITIONS or cand["composite_score"] >= 0.12:
                entered_ = await _enter(db, d, cand["symbol"], cand, equity, cash)
                if entered_:
                    entered.append(entered_)
                    cash -= float(entered_["fill_price"]) * int(entered_["qty"])
                    n_pos += 1
                    n_today += 1
                    held_symbols.add(cand["symbol"])

        await db.execute(
            text("UPDATE finance.paper_account SET available_cash = :c WHERE trader_id = :t"),
            {"c": _q(cash), "t": TRADER_ID},
        )
        total_equity = await _snapshot_nav(db, d, cash, n_pos)
        await db.commit()

    await record_run(
        "catalyst_paper_trade", "ok",
        f"exits={len(exits)}, entries={len(entered)}, positions={n_pos}",
        rows=len(entered),
    )
    return {
        "ok": True,
        "job": "catalyst_paper_trade",
        "date": d,
        "exits": exits,
        "entries": entered,
        "n_positions": n_pos,
        "total_equity": _q(total_equity),
    }
