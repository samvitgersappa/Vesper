"""Catalyst Swing Trader — per-stock news capture (Part E).

Fetches the latest news headlines for the screen's top funnel candidates from
yfinance and persists them to `finance.catalyst_news` (date, symbol, title,
source, url, published_at, summary). The `catalyst_llm` stage reads this table
so its catalyst verdicts are grounded in actual recent news instead of factor
scores alone, and the API/frontend surfaces the same stored news per stock.

Degrades honestly: a failed/unavailable news fetch records a `degraded` run and
persists nothing — it never fabricates a headline.
"""

import logging
from typing import Any, Optional

from sqlalchemy import text

from backend.modules.db import session_factory
from backend.modules.finance.catalyst import SCREEN_TOP_N
from backend.modules.finance.catalyst._util import ist_today, record_run

logger = logging.getLogger("vesper.finance.catalyst.news")

_NEWS_PER_SYMBOL = 6


def _yf():
    """Import yfinance lazily (only needed for live news fetches)."""
    import yfinance as yf

    return yf


def _normalise(item: dict) -> Optional[dict]:
    """Map a yfinance `get_news` item to our slim news shape."""
    content = item.get("content") if isinstance(item, dict) else None
    if not isinstance(content, dict):
        return None
    title = str(content.get("title") or "").strip()
    if not title:
        return None
    provider = content.get("provider") or {}
    source = ""
    if isinstance(provider, dict):
        source = str(provider.get("displayName") or "").strip()
    url = ""
    c_url = content.get("canonicalUrl") or {}
    if isinstance(c_url, dict):
        url = str(c_url.get("url") or "").strip()
    published = str(content.get("pubDate") or "").strip()
    return {
        "title": title[:500],
        "source": source[:200],
        "url": url[:500],
        "published_at": published[:40],
        "summary": str(content.get("summary") or "")[:1000],
    }


def fetch_symbol_news(symbol: str, count: int = _NEWS_PER_SYMBOL) -> list[dict]:
    """Latest yfinance headlines for `symbol`. Returns [] on any failure."""
    try:
        yf = _yf()
        raw = yf.Ticker(symbol).get_news(count=count)
    except Exception as exc:  # noqa: BLE001 - news is best-effort
        logger.info("news fetch failed for %s: %s", symbol, exc)
        return []
    items = [_normalise(i) for i in raw] if isinstance(raw, list) else []
    return [i for i in items if i]


async def _persist_news(date: str, symbol: str, items: list[dict]) -> int:
    if not items:
        return 0
    written = 0
    async with session_factory()() as db:
        await db.execute(text("DELETE FROM finance.catalyst_news WHERE date = :d AND symbol = :s"), {"d": date, "s": symbol})
        for i in items:
            await db.execute(
                text(
                    "INSERT INTO finance.catalyst_news "
                    "(date, symbol, title, source, url, published_at, summary) "
                    "VALUES (:d, :s, :t, :src, :u, :p, :sum)"
                ),
                {
                    "d": date, "s": symbol, "t": i["title"], "src": i["source"],
                    "u": i["url"], "p": i["published_at"], "sum": i["summary"],
                },
            )
            written += 1
        await db.commit()
    return written


async def run_news(date: str | None = None, limit: int = SCREEN_TOP_N) -> dict[str, Any]:
    """18:30 IST — fetch + persist news for the screen's top funnel candidates."""
    from backend.modules.finance.catalyst.scores import funnel_for_llm

    d = date or ist_today()
    candidates = await funnel_for_llm(d, limit=limit)
    if not candidates:
        await record_run("catalyst_news", "degraded", "no funnel candidates — run catalyst_screen first")
        return {"ok": True, "job": "catalyst_news", "degraded": True, "note": "no candidates"}

    total = 0
    with_news = 0
    for c in candidates:
        items = fetch_symbol_news(c["symbol"])
        n = await _persist_news(d, c["symbol"], items)
        total += n
        if n:
            with_news += 1

    if total == 0:
        await record_run("catalyst_news", "degraded", "yfinance news unavailable for funnel")
        return {"ok": True, "job": "catalyst_news", "degraded": True, "note": "no news available"}
    await record_run("catalyst_news", "ok", f"{with_news}/{len(candidates)} symbols with news ({total} headlines)", rows=total)
    return {"ok": True, "job": "catalyst_news", "date": d, "symbols_with_news": with_news, "headlines": total}


async def news_for_symbol(date: str, symbol: str, limit: int = 5) -> list[dict]:
    """Stored news for a symbol/date, newest first (SELECT-only)."""
    async with session_factory()() as db:
        rows = (await db.execute(
            text(
                "SELECT date, symbol, title, source, url, published_at, summary "
                "FROM finance.catalyst_news WHERE date = :d AND symbol = :s "
                "ORDER BY published_at DESC LIMIT :n"
            ),
            {"d": date, "s": symbol, "n": int(limit)},
        )).all()
    return [dict(r._mapping) for r in rows]
