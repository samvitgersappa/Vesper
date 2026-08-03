"""Catalyst Swing Trader — Layer 1/2/3 multiplicative scoring (Part E).

Market → Sector → Stock multiplicative funnel (work order). Each layer is a
0..1 score (neutral 0.5); the composite is the product, so any weak layer
suppresses a candidate (a strong stock in a weak market does not enter).

- Layer 1 (market): FII/DII net, Nifty PCR, breadth (A/D, % > 50DMA), VIX.
- Layer 2 (sector): sector index 20D return / 50DMA / momentum.
- Layer 3 (stock): cross-sectional factor rank (momentum + trend + 20D ret).

`screen()` persists `catalyst_scores` and logs the watchlist funnel to
`catalyst_candidates` (market|sector|stock stages). All reads only.
"""

import logging
from typing import Any, Optional

import pandas as pd
from sqlalchemy import text

from backend.db import feature_store
from backend.modules.db import session_factory
from backend.modules.finance.catalyst import SCREEN_TOP_N
from backend.modules.finance.catalyst._util import record_run, sector_for_symbol

logger = logging.getLogger("vesper.finance.catalyst.scores")


# ── Layer 1 — market ─────────────────────────────────────────────────────
async def _market_layer() -> float:
    """Market-wide score 0..1 from FII/DII, PCR, breadth and VIX."""
    async with session_factory()() as db:
        sent = (await db.execute(text(
            "SELECT actor, net FROM finance.market_sentiment_daily "
            "WHERE date = (SELECT MAX(date) FROM finance.market_sentiment_daily)"
        ))).all()
        pcr_row = (await db.execute(text(
            "SELECT pcr FROM finance.index_options_sentiment "
            "WHERE index_name = 'NIFTY' "
            "AND date = (SELECT MAX(date) FROM finance.index_options_sentiment)"
        ))).first()
        breadth = (await db.execute(text(
            "SELECT advance, decline, pct_above_50dma FROM finance.market_breadth_daily "
            "WHERE date = (SELECT MAX(date) FROM finance.market_breadth_daily)"
        ))).first()

    # FII net: positive flow → bullish. Normalize in rupees crores via tanh.
    fii_net = next((float(r.net) for r in sent if r.actor == "FII" and r.net is not None), None)
    fii_score = 0.5
    if fii_net is not None:
        import math

        fii_score = 0.5 + 0.5 * math.tanh(fii_net / 5_000.0)

    # PCR: low PCR (few puts) → bullish; high PCR (crowded puts) → bearish.
    pcr_score = 0.5
    if pcr_row and pcr_row.pcr is not None:
        pcr = float(pcr_row.pcr)
        pcr_score = max(0.0, min(1.0, 1.0 - (pcr - 0.7) / 0.6)) if pcr >= 0.7 else 1.0

    # Breadth: blend A/D ratio and % above 50DMA (both 0..1).
    breadth_score = 0.5
    if breadth and breadth.pct_above_50dma is not None:
        ad_ratio = 0.5
        if (breadth.decline or 0) + (breadth.advance or 0) > 0:
            ad_ratio = (breadth.advance or 0) / ((breadth.advance or 0) + (breadth.decline or 0))
        p50 = float(breadth.pct_above_50dma) / 100.0
        breadth_score = 0.5 * ad_ratio + 0.5 * p50

    # VIX: low → risk-on, high → risk-off. From the macro feature store.
    vix_score = 0.5
    try:
        vix = feature_store.client.df(
            "SELECT Close FROM macro_series WHERE Series = 'india_vix' ORDER BY Date DESC LIMIT 1"
        )
        if not vix.empty and pd.notna(vix.iloc[0]["Close"]):
            v = float(vix.iloc[0]["Close"])
            vix_score = max(0.0, min(1.0, 1.0 - (v - 14.0) / 12.0)) if v >= 14.0 else 1.0
    except Exception:  # pragma: no cover - missing VIX degrades to neutral
        vix_score = 0.5

    return round(0.3 * fii_score + 0.25 * pcr_score + 0.25 * breadth_score + 0.2 * vix_score, 4)


# ── Layer 2 — sector ─────────────────────────────────────────────────────
async def _sector_layer(date: str) -> dict[str, float]:
    """Latest sector scores by sector name for the given date."""
    async with session_factory()() as db:
        rows = (await db.execute(
            text("SELECT sector, score FROM finance.sector_scores_daily WHERE date = :d"),
            {"d": date},
        )).all()
    return {r.sector: float(r.score) for r in rows if r.score is not None}


# ── Layer 3 — stock ──────────────────────────────────────────────────────
def _stock_layer(factors: pd.DataFrame) -> dict[str, float]:
    """Cross-sectional 0..1 factor rank per symbol."""
    if factors is None or factors.empty:
        return {}
    f = factors.copy()
    for col in ("momentum_6m", "ma_ratio_20_200", "ret_20d"):
        if col not in f.columns:
            f[col] = 0.0
    # Missing factor rows (e.g. recent IPOs with no 200DMA) rank as neutral
    # 0.5 instead of poisoning the whole composite with NaN.
    score = (
        0.4 * f["momentum_6m"].rank(pct=True).fillna(0.5)
        + 0.3 * f["ma_ratio_20_200"].rank(pct=True).fillna(0.5)
        + 0.3 * f["ret_20d"].rank(pct=True).fillna(0.5)
    )
    return {
        str(sym): round(float(v), 4)
        for sym, v in zip(f["Symbol"].tolist(), score.tolist())
        if pd.notna(v)
    }


# ── Screen ───────────────────────────────────────────────────────────────
async def screen(date: str | None = None) -> dict[str, Any]:
    """Run Layer 1/2/3 scoring and persist catalyst_scores + funnel log.

    Returns the ranked composite list for the LLM stage to consume.
    """
    from backend.modules.finance.catalyst._util import ist_today

    d = date or ist_today()

    factors = _latest_factors()
    if factors is None or factors.empty:
        await record_run("catalyst_screen", "degraded", "no factor features — run compute_factors first")
        return {"ok": True, "job": "catalyst_screen", "degraded": True, "note": "no factors"}

    market_score = await _market_layer()
    sector_scores = await _sector_layer(d)
    stock_scores = _stock_layer(factors)

    symbols = [str(s) for s in factors["Symbol"].tolist()]
    scored = []
    for sym in symbols:
        stock = stock_scores.get(sym)
        if stock is None:
            continue
        sector = sector_for_symbol(sym)
        sector_score = sector_scores.get(sector, 0.5) if sector else 0.5
        composite = round(market_score * sector_score * stock, 6)
        scored.append({
            "symbol": sym,
            "sector": sector,
            "market_score": market_score,
            "sector_score": sector_score,
            "stock_score": stock,
            "composite_score": composite,
        })

    scored.sort(key=lambda x: x["composite_score"], reverse=True)
    for i, s in enumerate(scored, start=1):
        s["rank"] = i

    await _persist_scores(d, scored)
    await _log_funnel(d, scored)
    await record_run("catalyst_screen", "ok", f"scored {len(scored)} symbols", rows=len(scored))
    return {"ok": True, "job": "catalyst_screen", "date": d, "scored": len(scored), "top": scored[:SCREEN_TOP_N]}


def _latest_factors() -> pd.DataFrame:
    try:
        return feature_store.client.df(
            "SELECT * FROM factor_features WHERE Date = (SELECT MAX(Date) FROM factor_features)"
        )
    except Exception:  # pragma: no cover - defensive
        return pd.DataFrame()


async def _persist_scores(date: str, scored: list[dict]) -> None:
    async with session_factory()() as db:
        await db.execute(text("DELETE FROM finance.catalyst_scores WHERE date = :d"), {"d": date})
        for s in scored:
            await db.execute(
                text(
                    "INSERT INTO finance.catalyst_scores "
                    "(date, symbol, sector, market_score, sector_score, stock_score, composite_score, rank) "
                    "VALUES (:d, :s, :sec_name, :m, :sec, :st, :c, :r)"
                ),
                {
                    "d": date, "s": s["symbol"], "sec_name": s.get("sector"),
                    "m": s["market_score"], "sec": s["sector_score"], "st": s["stock_score"],
                    "c": s["composite_score"], "r": s["rank"],
                },
            )
        await db.commit()


async def funnel_for_llm(date: str, limit: int | None = None) -> list[dict]:
    """Top-N candidates (by composite score) for the LLM catalyst stage."""
    n = limit or SCREEN_TOP_N
    async with session_factory()() as db:
        rows = (await db.execute(
            text(
                "SELECT symbol, sector, market_score, sector_score, stock_score, "
                "composite_score, rank FROM finance.catalyst_scores "
                "WHERE date = :d ORDER BY composite_score DESC LIMIT :n"
            ),
            {"d": date, "n": n},
        )).all()
    return [dict(r._mapping) for r in rows]


async def _log_funnel(date: str, scored: list[dict]) -> None:
    """Log the watchlist funnel stages for audit (market|sector|stock)."""
    import uuid

    async with session_factory()() as db:
        for s in scored:
            if s["rank"] > SCREEN_TOP_N:
                continue
            stage = "market" if s["market_score"] < 0.45 else ("sector" if s["sector_score"] < 0.45 else "stock")
            reason = f"market={s['market_score']} sector={s['sector_score']} stock={s['stock_score']}"
            await db.execute(
                text(
                    "INSERT INTO finance.catalyst_candidates (id, date, symbol, stage, reason, score) "
                    "VALUES (:id, :d, :s, :st, :r, :sc)"
                ),
                {
                    "id": str(uuid.uuid4()), "d": date, "s": s["symbol"],
                    "st": stage, "r": reason, "sc": s["composite_score"],
                },
            )
        await db.commit()
