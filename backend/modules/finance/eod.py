"""Finance EOD paper-trading engine (plan.md §7, Phase 7 port).

Implements the daily end-of-day routine the Automation table lists:
for each of the 5 live paper traders (`alpha_tilt`, `arjun_etf`,
`lowdd_multi_asset`, `momentum_surge`, `alpha_generators`) compute a *target
portfolio* from the shared feature store, compare to current holdings, and
execute the resulting orders against cash — recording trades, updating
holdings, and appending NAV history. This is the writer side of the Finance
module (plan §16); the module logic/MCP/API layer stays read-only.

Design:
- `strategies` — deterministic, factor-driven target generation (no LLM).
  Stock strategies rank the Nifty universe by the persisted factor features;
  ETF strategies rotate a fixed ETF basket by trailing momentum.
- `run_eod` — orchestration: build the price map, generate targets, diff to
  orders, execute sells-first then buys (respecting cash), persist everything
  in one transaction, and emit TradeExecuted / PortfolioNAVUpdated.
- `mark_to_market` — refresh `paper_holdings.last_price` from live quotes
  (feature store for the stock universe, yfinance for ETFs) so the web app
  shows real-time-ish holdings.

Every write degrades honestly: a missing price for a symbol skips that order;
an empty price map aborts with `degraded` (never fabricates fills).
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from backend.db import feature_store
from backend.modules.db import session_factory
from backend.events.catalog import PORTFOLIO_NAV_UPDATED, TRADE_EXECUTED
from backend.modules.common import publish

logger = logging.getLogger("vesper.finance.eod")

# Slippage applied to fills: stocks 8 bps, ETFs 3 bps (Quiver used bps slippage).
_SLIPPAGE_BPS = {"stock": 8, "etf": 3}
# Position sizing guards.
_MAX_TRADES_PER_RUN = 80
_MIN_ORDER_VALUE = 500.0

# Fixed ETF basket for the rotation / multi-asset strategies (liquid NSE ETFs).
ETF_BASKET = [
    "NIFTYBEES.NS",
    "JUNIORBEES.NS",
    "BANKBEES.NS",
    "MOM100.NS",
    "GOLDBEES.NS",
    "LIQUIDBEES.NS",
    "PHARMABEES.NS",
    "MAFANG.NS",
]


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _q(v: float | None) -> float | None:
    if v is None or math.isnan(v):
        return None
    return round(float(v), 2)


# ── Price map ──────────────────────────────────────────────────────────────
def _stock_closes() -> pd.DataFrame:
    """Latest close per symbol from the feature store (wide pivot)."""
    try:
        return feature_store.equity_closes()
    except Exception:  # pragma: no cover - defensive
        return pd.DataFrame()


def _etf_quotes() -> dict[str, float]:
    """Latest ETF closes from yfinance (best-effort; missing ETFs are skipped)."""
    import yfinance as yf  # noqa: PLC0415 - lazy, only needed for live quotes

    out: dict[str, float] = {}
    try:
        df = yf.download(ETF_BASKET, period="5d", progress=False, auto_adjust=True, group_by="ticker")
    except Exception as exc:  # pragma: no cover - provider flake
        logger.warning("etf quotes unavailable: %s", exc)
        return out
    if df is None or df.empty:
        return out
    for sym in ETF_BASKET:
        try:
            sub = df[sym]["Close"].dropna()
            if not sub.empty:
                out[sym] = round(float(sub.iloc[-1]), 4)
        except Exception:  # pragma: no cover - a bad ticker is skipped
            continue
    return out


def build_price_map() -> dict[str, float]:
    """Universe-wide price map: feature-store closes for stocks, yfinance for ETFs."""
    prices: dict[str, float] = {}
    closes = _stock_closes()
    if not closes.empty:
        latest = closes.iloc[-1]
        for sym in latest.index:
            v = latest[sym]
            if pd.notna(v) and float(v) > 0:
                prices[str(sym)] = round(float(v), 4)
    prices.update(_etf_quotes())
    return prices


# ── Factor access ──────────────────────────────────────────────────────────
def _latest_factors() -> pd.DataFrame:
    """Most-recent factor row per symbol from factor_features."""
    try:
        df = feature_store.client.df(
            "SELECT * FROM factor_features "
            "WHERE Date = (SELECT MAX(Date) FROM factor_features)"
        )
    except Exception:  # pragma: no cover - defensive
        return pd.DataFrame()
    return df


def _factor_rank(series: pd.Series) -> pd.Series:
    """0..1 cross-sectional rank (higher = better), NaN-safe."""
    return series.rank(pct=True)


# ── Target generation (deterministic, factor-driven) ──────────────────────
def _stock_targets(
    strategy_id: str,
    factors: pd.DataFrame,
    prices: dict[str, float],
    top_n: int,
    score_fn: Any,
) -> dict[str, float]:
    """Rank the universe by `score_fn(factors)` and return top-N equal-weight targets."""
    if factors.empty or not prices:
        return {}
    f = factors.copy()
    f["_score"] = score_fn(f)
    f = f.dropna(subset=["_score"]).sort_values("_score", ascending=False)
    picks = f.head(top_n)
    picks = picks[picks["Symbol"].isin(prices)]
    if picks.empty:
        return {}
    w = 1.0 / len(picks)
    return {s: w for s in picks["Symbol"].tolist()}


def generate_targets(strategy_id: str, prices: dict[str, float]) -> dict[str, float]:
    """Target weights (symbol -> fraction of equity) for one strategy.

    Deterministic factor rules (no LLM):
    - momentum_surge      top-15 by 6-month momentum
    - alpha_generators    top-20 by momentum + 20d return blend
    - alpha_tilt          top-15 by a multifactor tilt (momentum + MA ratio - vol)
    - arjun_etf           ETF rotation: hold the top-2 ETFs by 20d momentum (Kelly-ish)
    - lowdd_multi_asset   low-drawdown: gold + liquid + lowest-vol equity ETFs
    """
    sid = strategy_id or ""
    if sid in {"momentum_surge", "alpha_generators", "alpha_tilt"}:
        factors = _latest_factors()
        if sid == "momentum_surge":
            return _stock_targets(sid, factors, prices, 15, lambda f: _factor_rank(f["momentum_6m"]))
        if sid == "alpha_generators":
            return _stock_targets(
                sid, factors, prices, 20,
                lambda f: 0.6 * _factor_rank(f["momentum_6m"]) + 0.4 * _factor_rank(f["ret_20d"]),
            )
        # alpha_tilt: momentum + trend (MA ratio) - volatility, top 15.
        return _stock_targets(
            sid, factors, prices, 15,
            lambda f: 0.5 * _factor_rank(f["momentum_6m"])
            + 0.3 * _factor_rank(f["ma_ratio_20_200"])
            - 0.2 * _factor_rank(f["vol_20d"]),
        )

    if sid == "arjun_etf":
        import yfinance as yf  # noqa: PLC0415 - lazy

        try:
            hist = yf.download(ETF_BASKET, period="3mo", progress=False, auto_adjust=True, group_by="ticker")
        except Exception:  # pragma: no cover - provider flake
            hist = None
        if hist is None or hist.empty:
            return {}
        mom: dict[str, float] = {}
        for sym in ETF_BASKET:
            try:
                closes = hist[sym]["Close"].dropna()
                if len(closes) >= 20:
                    mom[sym] = float(closes.iloc[-1]) / float(closes.iloc[-20]) - 1.0
            except Exception:  # pragma: no cover
                continue
        ranked = sorted(((s, m) for s, m in mom.items() if s in prices), key=lambda x: x[1], reverse=True)
        top2 = [s for s, _ in ranked[:2]]
        if not top2:
            return {}
        w = 1.0 / len(top2)
        return {s: w for s in top2}

    if sid == "lowdd_multi_asset":
        # Low-drawdown sleeve: gold + liquid + lowest-vol equity ETFs.
        sleeve = [s for s in ["GOLDBEES.NS", "LIQUIDBEES.NS", "PHARMABEES.NS", "MAFANG.NS"] if s in prices]
        if not sleeve:
            return {}
        w = 1.0 / len(sleeve)
        return {s: w for s in sleeve}

    return {}


# ── Execution ──────────────────────────────────────────────────────────────
def _order_plan(
    targets: dict[str, float],
    holdings: dict[str, int],
    prices: dict[str, float],
    equity: float,
    slippage_bps: int,
) -> list[dict[str, Any]]:
    """Diff target weights to current holdings → sorted orders (sells first).

    Returns list of {symbol, side, qty, price, kind} where kind is stock|etf.
    Only symbols with a known price are considered.
    """
    target_value: dict[str, float] = {}
    for sym, w in targets.items():
        p = prices.get(sym)
        if p and p > 0:
            target_value[sym] = equity * w
    orders: list[dict[str, Any]] = []
    symbols = set(target_value) | set(holdings)
    for sym in symbols:
        p = prices.get(sym)
        if not p or p <= 0:
            continue
        tgt_qty = int(target_value.get(sym, 0.0) / p) if target_value.get(sym, 0.0) >= _MIN_ORDER_VALUE else 0
        cur_qty = holdings.get(sym, 0)
        if tgt_qty > cur_qty:
            orders.append({
                "symbol": sym, "side": "BUY", "qty": tgt_qty - cur_qty,
                "price": p, "kind": "etf" if sym in ETF_BASKET else "stock",
            })
        elif tgt_qty < cur_qty:
            orders.append({
                "symbol": sym, "side": "SELL", "qty": cur_qty - tgt_qty,
                "price": p, "kind": "etf" if sym in ETF_BASKET else "stock",
            })
    # Sells first, then buys (largest value first) — respects cash naturally.
    orders.sort(key=lambda o: (0 if o["side"] == "SELL" else 1, -o["qty"] * o["price"]))
    return orders[: _MAX_TRADES_PER_RUN]


async def run_eod(strategy_ids: list[str] | None = None) -> dict[str, Any]:
    """Run the full EOD routine for the given (or all) paper traders.

    Sells first (realizing cash), then buys within available cash. Updates
    holdings + account cash + NAV history atomically, publishes events.

    The Catalyst Swing Trader (`catalyst_swing`) is intentionally excluded from
    the default run: it trades on its own schedule (catalyst_risk 18:50 /
    catalyst_paper_trade 19:00 IST) with its own exit/entry engine — the EOD
    routine here only manages the 5 classic factor/ETF traders.
    """
    ids = strategy_ids or [
        s["trader_id"] for s in __import__("backend.modules.finance.logic", fromlist=["STRATEGIES"]).STRATEGIES
        if s["trader_id"] != "catalyst_swing"
    ]
    today = _today()
    prices = build_price_map()
    if not prices:
        return {"ok": False, "job": "paper_trade_eod", "degraded": True, "note": "no prices available"}

    from sqlalchemy import text

    summary: dict[str, Any] = {"ok": True, "job": "paper_trade_eod", "date": today, "traders": []}

    for tid in ids:
        target_weights = generate_targets(tid, prices)
        try:
            async with session_factory()() as db:
                acct = (await db.execute(
                    text("SELECT trader_id, available_cash, settled_cash, blocked_cash FROM finance.paper_account WHERE trader_id = :t"),
                    {"t": tid},
                )).first()
                if acct is None:
                    summary["traders"].append({"trader_id": tid, "skipped": "no account"})
                    continue
                cash = float(acct.available_cash or 0)
                held = (await db.execute(
                    text("SELECT ticker, qty, avg_price, last_price FROM finance.paper_holdings WHERE trader_id = :t"),
                    {"t": tid},
                )).all()
                holdings: dict[str, int] = {}
                holdings_cost: dict[str, float] = {}
                holdings_last: dict[str, float] = {}
                holdings_value = 0.0
                for h in held:
                    holdings[h.ticker] = int(h.qty)
                    holdings_cost[h.ticker] = float(h.avg_price or 0)
                    lp = float(h.last_price) if h.last_price else prices.get(h.ticker, 0.0)
                    holdings_last[h.ticker] = lp
                    holdings_value += int(h.qty) * (prices.get(h.ticker, lp) or 0)

                equity = cash + holdings_value
                # No target weights (data gap) → just mark-to-market NAV and skip orders.
                orders = _order_plan(target_weights, holdings, prices, equity, _SLIPPAGE_BPS["stock"]) if target_weights else []

                executed: list[dict[str, Any]] = []
                realized_pnl_total = 0.0
                for o in orders:
                    p = prices.get(o["symbol"])
                    if not p:
                        continue
                    fill = p * (1 + _SLIPPAGE_BPS[o["kind"]] / 10000.0) if o["side"] == "BUY" else p * (1 - _SLIPPAGE_BPS[o["kind"]] / 10000.0)
                    cost = fill * o["qty"]
                    if o["side"] == "SELL":
                        rp = (fill - holdings_cost.get(o["symbol"], fill)) * o["qty"]
                        realized_pnl_total += rp
                        cash += cost
                        holdings[o["symbol"]] -= o["qty"]
                        if holdings[o["symbol"]] <= 0:
                            holdings.pop(o["symbol"])
                            holdings_cost.pop(o["symbol"], None)
                    else:
                        if cost > cash:
                            # Scale down to cash if affordable.
                            affordable = int(cash // fill)
                            if affordable <= 0:
                                continue
                            o["qty"] = affordable
                            cost = fill * o["qty"]
                        cash -= cost
                        prev = holdings_cost.get(o["symbol"], 0.0)
                        new_qty = holdings.get(o["symbol"], 0) + o["qty"]
                        holdings[o["symbol"]] = new_qty
                        holdings_cost[o["symbol"]] = (prev * (new_qty - o["qty"]) + cost) / new_qty
                    holdings_last[o["symbol"]] = fill
                    trade_id = str(uuid.uuid4())
                    await db.execute(
                        text(
                            "INSERT INTO finance.paper_trades "
                            "(trade_id, trader_id, trade_date, symbol, side, quantity, signal_price, fill_price, "
                            "slippage_bps, cost_total, reason, realized_pnl, order_status) "
                            "VALUES (:tid, :trader, :d, :sym, :side, :qty, :sig, :fill, :slip, :cost, :reason, :pnl, 'EXECUTED')"
                        ),
                        {
                            "tid": trade_id, "trader": tid, "d": today, "sym": o["symbol"],
                            "side": o["side"], "qty": int(o["qty"]), "sig": _q(p),
                            "fill": _q(fill), "slip": _SLIPPAGE_BPS[o["kind"]],
                            "cost": _q(cost), "reason": f"{target_weights.get(o['symbol'], 0.0):.1%} target",
                            "pnl": _q(rp) if o["side"] == "SELL" else 0.0,
                        },
                    )
                    executed.append({"symbol": o["symbol"], "side": o["side"], "qty": int(o["qty"]), "fill_price": _q(fill)})
                    publish(TRADE_EXECUTED, {"trader_id": tid, "trade_id": trade_id, "symbol": o["symbol"], "side": o["side"], "qty": int(o["qty"])})

                # Persist holdings (rewrite the trader's rows).
                await db.execute(text("DELETE FROM finance.paper_holdings WHERE trader_id = :t"), {"t": tid})
                for sym, qty in holdings.items():
                    if qty <= 0:
                        continue
                    await db.execute(
                        text(
                            "INSERT INTO finance.paper_holdings "
                            "(trader_id, ticker, qty, avg_price, last_price, buy_date) "
                            "VALUES (:t, :s, :qty, :avg, :last, :d)"
                        ),
                        {"t": tid, "s": sym, "qty": int(qty), "avg": _q(holdings_cost.get(sym, 0.0)), "last": _q(prices.get(sym, holdings_last.get(sym))), "d": today},
                    )

                await db.execute(
                    text("UPDATE finance.paper_account SET available_cash = :c WHERE trader_id = :t"),
                    {"c": _q(cash), "t": tid},
                )

                # NAV history (mark-to-market) with day-over-day PnL.
                final_value = sum(qty * (prices.get(sym, holdings_last.get(sym, 0)) or 0) for sym, qty in holdings.items())
                total_equity = cash + final_value
                # Compute day-over-day PnL from the previous row.
                prev = (await db.execute(
                    text("SELECT total_equity FROM finance.paper_nav_history WHERE trader_id = :t AND date < :d ORDER BY date DESC LIMIT 1"),
                    {"t": tid, "d": today},
                )).scalar()
                day_pnl = None
                if prev is not None and prev > 0:
                    day_pnl = ((total_equity / prev) - 1) * 100
                await db.execute(
                    text(
                        "INSERT INTO finance.paper_nav_history "
                        "(trader_id, date, total_equity, cash, holdings_value, n_positions, day_pnl_pct) "
                        "VALUES (:t, :d, :eq, :c, :hv, :n, :dp) "
                        "ON CONFLICT (trader_id, date) DO UPDATE SET "
                        "total_equity = EXCLUDED.total_equity, cash = EXCLUDED.cash, "
                        "holdings_value = EXCLUDED.holdings_value, n_positions = EXCLUDED.n_positions, "
                        "day_pnl_pct = EXCLUDED.day_pnl_pct"
                    ),
                    {"t": tid, "d": today, "eq": _q(total_equity), "c": _q(cash), "hv": _q(final_value), "n": len(holdings), "dp": day_pnl},
                )
                await db.commit()
                publish(PORTFOLIO_NAV_UPDATED, {"trader_id": tid, "date": today, "equity": _q(total_equity)})

                summary["traders"].append({
                    "trader_id": tid,
                    "trades": len(executed),
                    "realized_pnl": _q(realized_pnl_total),
                    "total_equity": _q(total_equity),
                    "n_positions": len(holdings),
                })
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("run_eod(%s) failed: %s", tid, exc)
            summary["traders"].append({"trader_id": tid, "error": str(exc)})

    n_trades = sum(t.get("trades", 0) for t in summary["traders"])
    summary["trades"] = n_trades
    return summary


async def mark_to_market(strategy_ids: list[str] | None = None) -> dict[str, Any]:
    """Refresh last_price on holdings from the current price map (no orders)."""
    prices = build_price_map()
    updated = 0
    try:
        from sqlalchemy import text

        async with session_factory()() as db:
            rows = (await db.execute(
                text("SELECT trader_id, ticker, last_price FROM finance.paper_holdings")
            )).all()
            for r in rows:
                p = prices.get(r.ticker)
                if p and (r.last_price is None or abs(float(r.last_price) - p) > 1e-9):
                    await db.execute(
                        text("UPDATE finance.paper_holdings SET last_price = :p WHERE trader_id = :t AND ticker = :s"),
                        {"p": _q(p), "t": r.trader_id, "s": r.ticker},
                    )
                    updated += 1
            await db.commit()
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "updated": updated}
