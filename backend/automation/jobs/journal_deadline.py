"""Daily Journal Questionnaire hard-deadline job (addendum §2.6, plan.md §12.1).

Mechanical, no-LLM: at 23:55 IST ensure a `diary_entries` row exists for today
(placeholder with `complete = false` if the questionnaire never finished) and
publish `DailyJournalCompleted` so Evening Review can still run that night.

The day must never end with literally nothing recorded.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select

from backend.db.postgres.schemas.journal.models import DiaryEntry
from backend.modules.common import publish
from backend.modules.db import session_factory
from backend.events.catalog import DAILY_JOURNAL_COMPLETED

logger = logging.getLogger("vesper.automation.journal_deadline")


def _ist_now() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Kolkata"))


async def journal_questionnaire_deadline() -> dict:
    """23:55 IST: ensure a placeholder diary row exists for today, publish the
    completion event (complete=False) if the questionnaire didn't finish."""
    today = _ist_now().date()
    row_exists = False
    try:
        async with session_factory()() as db:
            start = datetime(today.year, today.month, today.day)
            end = start + timedelta(days=1)
            entry = (await db.execute(
                select(DiaryEntry).where(
                    DiaryEntry.entry_date >= start,
                    DiaryEntry.entry_date < end,
                ).order_by(DiaryEntry.created_at.desc())
            )).scalars().first()
            if entry is not None:
                row_exists = True
                complete = bool(entry.complete)
            else:
                complete = False
                entry = DiaryEntry(
                    title=f"Journal {today.isoformat()}",
                    category="GENERAL",
                    entry_date=start,
                    complete=False,
                )
                db.add(entry)
                await db.commit()
                logger.info("journal deadline: wrote placeholder for %s", today)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("journal deadline failed: %s", exc)
        return {"ok": False, "date": today.isoformat(), "message": str(exc)}

    publish(DAILY_JOURNAL_COMPLETED, {
        "date": today.isoformat(),
        "complete": bool(complete),
        "placeholder": not row_exists,
    })
    return {
        "ok": True,
        "date": today.isoformat(),
        "complete": bool(complete),
        "placeholder": not row_exists,
    }
