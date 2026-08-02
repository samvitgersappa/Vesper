"""CRM follow-up sweep (plan.md §12, addendum §1 rule 1).

Scheduled sweep over `relationship.reminders`: any reminder whose due date is
today or earlier (and not yet completed) is dispatched to the Notification
engine as a ReminderDue event. ProjectVesper's existing reminder cron logic,
ported onto the shared session factory.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, text

from backend.modules.db import session_factory
from backend.events.catalog import REMINDER_DUE
from backend.modules.common import publish
from backend.db.postgres.schemas.relationship.models import Reminder

logger = logging.getLogger("vesper.automation.crm")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def crm_followups_sweep() -> dict:
    """Dispatch due reminders to the notification surface."""
    due: list[dict] = []
    try:
        async with session_factory()() as db:
            now = _now()
            rows = (await db.execute(
                select(Reminder)
                .where(Reminder.remind_at <= now)
                .where(Reminder.completed_at.is_(None))
                .order_by(Reminder.remind_at.asc())
            )).scalars().all()
            for r in rows:
                due.append({
                    "reminder_id": r.id,
                    "person_id": r.person_id,
                    "message": r.message or "Follow up",
                    "due": r.remind_at.isoformat() if r.remind_at else None,
                })
            for d in due:
                publish(REMINDER_DUE, d)
            await db.commit()
        logger.info("crm_followups_sweep: %d due reminder(s)", len(due))
        return {"ok": True, "due": due}
    except Exception as exc:
        logger.error("crm_followups_sweep failed: %s", exc)
        return {"ok": False, "error": str(exc)}
