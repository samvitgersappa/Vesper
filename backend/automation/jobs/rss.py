"""RSS processing job (plan.md §12).

Weekly fetch of configured RSS feeds (ProjectVesper's RSS fetcher pattern).
Every item is routed through `knowledge.capture` so it lands in the right store
and leaves an audit trail. Feed URLs come from `RSS_FEEDS` (comma-separated) in
the environment, falling back to a sane default set; an unconfigured/empty set
makes the job a successful no-op.
"""

from __future__ import annotations

import logging
import os

import feedparser

logger = logging.getLogger("vesper.automation.rss")


def _feeds() -> list[str]:
    raw = os.environ.get("RSS_FEEDS", "").strip()
    if raw:
        return [u.strip() for u in raw.split(",") if u.strip()]
    return []


async def rss_process() -> dict:
    feeds = _feeds()
    if not feeds:
        logger.info("rss_process: no RSS_FEEDS configured — no-op")
        return {"ok": True, "items": 0, "note": "no feeds configured"}
    captured = 0
    for url in feeds:
        try:
            parsed = feedparser.parse(url)
        except Exception as exc:  # pragma: no cover - resilient per-feed
            logger.warning("rss parse %s failed: %s", url, exc)
            continue
        for entry in parsed.entries[:10]:
            try:
                from backend.modules.knowledge.logic import knowledge_capture
                title = getattr(entry, "title", "") or ""
                summary = getattr(entry, "summary", "") or ""
                text_ = f"{title}. {summary}".strip()
                if text_:
                    await knowledge_capture(f"from RSS: {text_}", {})
                    captured += 1
            except Exception as exc:  # pragma: no cover
                logger.warning("rss capture failed: %s", exc)
    logger.info("rss_process: %d item(s) captured from %d feed(s)", captured, len(feeds))
    return {"ok": True, "items": captured, "feeds": len(feeds)}
